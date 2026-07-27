"""QA adversarial del catálogo: ataques que el diseño firmado debe sobrevivir.

Compañero de `test_catalogo_servicio.py`, no sustituto: aquello verifica el
camino feliz y los errores tipados; esto empuja las esquinas — carreras,
reintentos con payload divergente, comodines de LIKE, dobles bajas, EAN con
espacios— y deja cada comportamiento FIJO en un test.

Dos de estos tests documentan comportamientos discutibles a propósito (la
carrera del cupo y el reintento idempotente con datos distintos): el assert
es el comportamiento actual, y la discusión —con la deuda propuesta— vive en
`.superpowers/sdd/qa-adversarial-report.md`. Si alguno de los dos cambia a un
comportamiento más estricto, el test correspondiente se reescribe, no se borra.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.catalogo.schemas import ProductoActualizar, ProductoCrear
from app.modules.catalogo.service import CatalogoService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import NotFoundError, ValidationError
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def limpiar_productos(pg_platform_url: str):
    engine = create_async_engine(pg_platform_url)

    async def _borrar() -> None:
        async with engine.begin() as conn:
            # Los movimientos, los ítems de compra, los ajustes y los ítems de
            # venta referencian productos con FK RESTRICT: si una corrida
            # anterior murió a mitad de otro archivo, hay que borrarlos ANTES
            # que los productos o el DELETE revienta (la suite es re-entrante).
            for tabla in ("movimientos_inventario", "compra_items", "ajustes_inventario", "ventas_items"):
                await conn.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = ANY(:ids)"), {"ids": [T1, T2]})
            await conn.execute(text("DELETE FROM productos WHERE tenant_id = ANY(:ids)"), {"ids": [T1, T2]})
            await conn.execute(
                text(
                    "DELETE FROM outbox_messages WHERE routing_key LIKE 'producto.%' OR routing_key LIKE '%.producto.%'"
                )
            )

    await _borrar()
    try:
        yield
    finally:
        await _borrar()
        await engine.dispose()


@contextlib.asynccontextmanager
async def sesion_de(pg_app_url: str, tenant_id: uuid.UUID):
    """Una sesión de tenant (RLS activa) con el GUC sembrado desde el ContextVar.

    Es el mismo montaje que la fixture `servicio` de `test_catalogo_servicio.py`,
    factorizado: los ataques de esta suite necesitan DOS sesiones del mismo
    negocio a la vez (carreras) o de dos negocios (cross-tenant).
    """
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(tenant_id)
    try:
        async with factory() as s:
            yield s
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def _contar_outbox(pg_platform_url: str, routing_key: str) -> int:
    """El outbox se lee con el rol de plataforma: `vendi_app` solo tiene INSERT."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT count(*) FROM outbox_messages WHERE routing_key = :k"),
                    {"k": routing_key},
                )
            ).scalar_one()
    finally:
        await engine.dispose()


async def _contar_vivos(pg_platform_url: str, tenant_id: uuid.UUID) -> int:
    """Filas vivas del negocio, vistas desde plataforma (sin RLS ni sesión)."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT count(*) FROM productos WHERE tenant_id = :t AND deleted_at IS NULL"),
                    {"t": tenant_id},
                )
            ).scalar_one()
    finally:
        await engine.dispose()


# --- Carreras y límite del tier -----------------------------------------------


async def test_la_carrera_del_cupo_supera_el_limite_aunque_el_check_pase(
    pg_app_url: str, pg_platform_url: str, limpiar_productos
):
    """DOCUMENTA la carrera TOCTOU de `_exigir_cupo` (deuda firmada, no bug nuevo).

    El conteo y el INSERT no son una sola operación (ADR-019: el límite vive en
    la aplicación). El intercalado determinista de la carrera es: A cuenta
    (99 < 100), inserta y NO confirma; B cuenta —en READ COMMITTED la fila de A
    aún es invisible—, también ve 99 y pasa; confirman las dos y el negocio
    queda con 101 productos vivos sobre un límite de 100. El assert fija ese
    desenlace para que nadie lo "descubra" en producción creyendo que el cupo
    era exacto.
    """
    valores = ", ".join(f"('{T1}', 'Semilla {i:03d}', 100)" for i in range(99))
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"INSERT INTO productos (tenant_id, nombre, precio_venta) VALUES {valores}"))
    finally:
        await engine.dispose()

    async with sesion_de(pg_app_url, T1) as s1, sesion_de(pg_app_url, T1) as s2:
        gratis_a = CatalogoService(session=s1, tenant_id=T1, tier="gratis")
        gratis_b = CatalogoService(session=s2, tenant_id=T1, tier="gratis")
        await gratis_a.crear(ProductoCrear(nombre="Alta A", precio_venta=100))  # flush, sin commit
        # B no ve la fila de A: su conteo da 99 y `_exigir_cupo` la deja pasar.
        await gratis_b.crear(ProductoCrear(nombre="Alta B", precio_venta=100))
        await s1.commit()
        await s2.commit()

    assert await _contar_vivos(pg_platform_url, T1) == 101


# --- Idempotencia y reintentos -------------------------------------------------


async def test_el_reintento_idempotente_con_payload_distinto_gana_al_primero_en_silencio(
    pg_app_url: str, pg_platform_url: str, limpiar_productos
):
    """DOCUMENTA la trampa de sync de ADR-017: reenviar el mismo `id` con datos
    DISTINTOS devuelve el producto original, sin 409, sin aviso al cliente y
    sin evento nuevo. El único rastro es un log en el servidor. El cliente que
    corrigió un typo en el reintento cree que su corrección quedó —y no quedó.
    """
    el_id = uuid.uuid4()
    async with sesion_de(pg_app_url, T1) as s:
        servicio = CatalogoService(session=s, tenant_id=T1, tier="pro")
        await servicio.crear(ProductoCrear(id=el_id, nombre="Original", precio_venta=600))
        await s.commit()

        segundo = await servicio.crear(ProductoCrear(id=el_id, nombre="Cambiado", precio_venta=999))

        assert segundo.id == el_id
        assert segundo.nombre == "Original", "el reintento divergente NO pisa los datos"
        assert segundo.precio_venta == 600
        assert (await servicio.obtener(el_id)).nombre == "Original"
    assert await _contar_outbox(pg_platform_url, f"{T1}.producto.creado") == 1, (
        "ni evento nuevo: para cualquier consumidor, el alta divergente nunca existió"
    )


async def test_la_segunda_baja_del_mismo_producto_es_un_404(pg_app_url: str, limpiar_productos):
    """DELETE duplicado (doble clic, reintento de red): la segunda baja no es
    idempotente, es un 404 tipado —el producto ya no existe a efectos de la
    API— y el EAN liberado tampoco resuelve al fantasma."""
    async with sesion_de(pg_app_url, T1) as s:
        servicio = CatalogoService(session=s, tenant_id=T1, tier="pro")
        creado = await servicio.crear(ProductoCrear(nombre="Temporal", precio_venta=100, codigo_barras="770666"))
        await servicio.eliminar(creado.id)

        with pytest.raises(NotFoundError) as exc:
            await servicio.eliminar(creado.id)
        assert exc.value.code == "producto_no_encontrado"

        with pytest.raises(NotFoundError):
            await servicio.buscar_por_codigo("770666")


# --- Búsqueda: comodines y normalización ----------------------------------------


async def test_los_comodines_de_like_son_texto_tambien_el_guion_bajo(pg_app_url: str, limpiar_productos):
    """El `%` ya tenía test; el `_` es el otro comodín de LIKE y el que un
    nombre real («Coca-Cola») convierte en oráculo: si el escape fallara,
    buscar «_cola» devolvería «Coca-Cola» como si fuera patrón."""
    async with sesion_de(pg_app_url, T1) as s:
        servicio = CatalogoService(session=s, tenant_id=T1, tier="pro")
        await servicio.crear(ProductoCrear(nombre="Coca-Cola 400", precio_venta=2500))
        await servicio.crear(ProductoCrear(nombre="Pepsi 400", precio_venta=2400))

        _, total = await servicio.listar(q="_cola")
        assert total == 0, "«_» escapado es texto: no puede hacer de comodín ante «Coca-Cola»"

        await servicio.crear(ProductoCrear(nombre="Coca_Cola zero", precio_venta=2600))
        filas, total = await servicio.listar(q="_cola")
        assert total == 1 and filas[0].nombre == "Coca_Cola zero", "pero sí encuentra el guion bajo literal"

        _, total = await servicio.listar(q="%")
        assert total == 0
        _, total = await servicio.listar(q="\\")
        assert total == 0, "el propio carácter de escape también va escapado"
        _, total = await servicio.listar(q="coca")
        assert total == 2, "y la búsqueda normal sigue funcionando (ilike, sin anclas)"


async def test_buscar_por_codigo_no_recorta_espacios_aunque_el_alta_si(pg_app_url: str, limpiar_productos):
    """DOCUMENTA la asimetría del camino del escáner (ADR-024): el alta
    normaliza el EAN con strip (`_normalizar_ean`), así que en base jamás hay
    espacios; pero `buscar_por_codigo` compara literal y « 770123 » no
    encuentra «770123». Un escáner que mande relleno recibe un 404 de un
    producto que existe."""
    async with sesion_de(pg_app_url, T1) as s:
        servicio = CatalogoService(session=s, tenant_id=T1, tier="pro")
        await servicio.crear(ProductoCrear(nombre="Gaseosa", precio_venta=2500, codigo_barras="  770123  "))

        assert (await servicio.buscar_por_codigo("770123")).nombre == "Gaseosa"
        with pytest.raises(NotFoundError) as exc:
            await servicio.buscar_por_codigo(" 770123 ")
        assert exc.value.code == "producto_no_encontrado"


# --- Eventos outbox --------------------------------------------------------------


async def test_un_patch_con_el_nombre_igual_al_actual_no_emite_evento(
    pg_app_url: str, pg_platform_url: str, limpiar_productos
):
    """La pregunta era «¿evento con `cambios` vacío o ninguno?»: ninguno. Un
    PATCH donde TODOS los campos llegan iguales al estado actual sale por el
    retorno temprano y el outbox no se entera — los consumidores no reciben
    ruido por reintentos del frontend."""
    async with sesion_de(pg_app_url, T1) as s:
        servicio = CatalogoService(session=s, tenant_id=T1, tier="pro")
        creado = await servicio.crear(ProductoCrear(nombre="Sal refisal", precio_venta=1500))
        await s.commit()

        mismo = await servicio.actualizar(creado.id, ProductoActualizar(nombre="Sal refisal"))
        assert mismo.nombre == "Sal refisal"
        await s.commit()

    assert await _contar_outbox(pg_platform_url, f"{T1}.producto.actualizado") == 0


async def test_el_evento_de_baja_lleva_solo_lo_pactado(pg_app_url: str, pg_platform_url: str, limpiar_productos):
    """El payload de `producto.eliminado` es exactamente {producto_id, nombre,
    codigo_barras}: el EAN original viaja porque la fila lo pierde al liberarse
    (decisión 3 del plan), y nada más se cuela —ni precios, ni stock, ni el
    tenant en el `data` (ya va en el sobre del evento)."""
    async with sesion_de(pg_app_url, T1) as s:
        servicio = CatalogoService(session=s, tenant_id=T1, tier="pro")
        creado = await servicio.crear(ProductoCrear(nombre="Panela", precio_venta=4200, codigo_barras="770321"))
        await servicio.eliminar(creado.id)
        el_id = creado.id
        await s.commit()

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            fila = (
                await conn.execute(
                    text("SELECT payload FROM outbox_messages WHERE routing_key = :k"),
                    {"k": f"{T1}.producto.eliminado"},
                )
            ).first()
    finally:
        await engine.dispose()

    assert fila is not None
    assert fila.payload["data"] == {
        "producto_id": str(el_id),
        "nombre": "Panela",
        "codigo_barras": "770321",
    }


# --- Padres y cross-tenant --------------------------------------------------------


async def test_un_padre_dado_de_baja_rechaza_hijas_nuevas(pg_app_url: str, limpiar_productos):
    """`_exigir_padre` mira `deleted_at`, no solo la existencia: una variante
    no puede colgar de un producto dado de baja, aunque la fila siga ahí y la
    FK de Postgres la aceptaría sin rechistar."""
    async with sesion_de(pg_app_url, T1) as s:
        servicio = CatalogoService(session=s, tenant_id=T1, tier="pro")
        padre = await servicio.crear(ProductoCrear(nombre="Arroz base", precio_venta=2500))
        await servicio.eliminar(padre.id)
        await s.commit()

        with pytest.raises(ValidationError) as exc:
            await servicio.crear(ProductoCrear(nombre="Arroz hija 500g", precio_venta=2600, padre_id=padre.id))
        assert exc.value.code == "padre_no_encontrado"


async def test_el_ean_de_otro_tenant_no_choca_ni_se_asoma(pg_app_url: str, limpiar_productos):
    """Adivinar el EAN de otro negocio no da nada: la búsqueda por código no lo
    ve (RLS) y usarlo en un alta propia no choca (el índice único es por
    tenant). Ni fuga ni denegación de servicio por colisión prefabricada."""
    async with sesion_de(pg_app_url, T2) as s2:
        await CatalogoService(session=s2, tenant_id=T2, tier="pro").crear(
            ProductoCrear(nombre="Suyo", precio_venta=100, codigo_barras="770500")
        )
        await s2.commit()

    async with sesion_de(pg_app_url, T1) as s1:
        servicio = CatalogoService(session=s1, tenant_id=T1, tier="pro")
        with pytest.raises(NotFoundError):
            await servicio.buscar_por_codigo("770500")

        propio = await servicio.crear(ProductoCrear(nombre="Mío", precio_venta=100, codigo_barras="770500"))
        assert propio.tenant_id == T1
        assert (await servicio.buscar_por_codigo("770500")).id == propio.id
