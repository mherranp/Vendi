"""`CatalogoService` contra el PostgreSQL real, con el rol `vendi_app`.

`integration` porque la base NO se dobla: la RLS, el índice único parcial del
EAN y la policy de INSERT del outbox solo existen en PostgreSQL. La sesión es
la misma fábrica que usa la API, con el tenant en el ContextVar — el mismo
camino por el que pasarán los handlers.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.catalogo.schemas import ProductoActualizar, ProductoCrear
from app.modules.catalogo.service import CatalogoService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
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


@pytest_asyncio.fixture
async def servicio(pg_app_url: str, limpiar_productos):
    """Servicio del negocio T1 con tier 'pro' (sin límite)."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield CatalogoService(session=s, tenant_id=T1, tier="pro")
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def _contar(session, **filtros) -> int:
    from sqlalchemy import func, select

    from app.modules.catalogo.models import Producto

    consulta = select(func.count()).select_from(Producto)
    for campo, valor in filtros.items():
        consulta = consulta.where(getattr(Producto, campo) == valor)
    return (await session.execute(consulta)).scalar_one()


async def test_crear_y_obtener(servicio):
    creado = await servicio.crear(ProductoCrear(nombre="Arroz 500g", precio_venta=2500, iva_pct=Decimal("5")))
    assert creado.id is not None
    assert creado.tenant_id == T1
    assert creado.stock_actual == Decimal("0")

    obtenido = await servicio.obtener(creado.id)
    assert obtenido.nombre == "Arroz 500g"
    assert obtenido.iva_pct == Decimal("5")


async def test_crear_con_id_de_cliente_es_idempotente(servicio, pg_platform_url):
    """ADR-017: reenviar la misma creación es un no-op porque la fila ya
    existe con la PK que le puso el cliente — no porque nadie recuerde qué se
    procesó."""
    el_id = uuid.uuid4()
    datos = ProductoCrear(id=el_id, nombre="Huevo und", precio_venta=600)
    primero = await servicio.crear(datos)
    await servicio._session.commit()
    segundo = await servicio.crear(datos)

    assert segundo.id == primero.id == el_id
    assert await _contar(servicio._session, nombre="Huevo und") == 1

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            eventos = (
                await conn.execute(
                    text("SELECT count(*) FROM outbox_messages WHERE routing_key = :k"),
                    {"k": f"{T1}.producto.creado"},
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert eventos == 1, "el reintento NO re-emite el evento (ADR-017: una sola vez por operación aceptada)"


async def test_un_id_ya_usado_por_un_producto_dado_de_baja_se_rechaza(servicio):
    datos = ProductoCrear(id=uuid.uuid4(), nombre="Temporal", precio_venta=100)
    creado = await servicio.crear(datos)
    await servicio.eliminar(creado.id)
    with pytest.raises(ConflictError) as exc:
        await servicio.crear(datos)
    assert exc.value.code == "producto_id_duplicado"


async def test_el_ean_duplicado_en_el_mismo_tenant_da_409_tipado(servicio):
    await servicio.crear(ProductoCrear(nombre="A", precio_venta=100, codigo_barras="770123"))
    with pytest.raises(ConflictError) as exc:
        await servicio.crear(ProductoCrear(nombre="B", precio_venta=100, codigo_barras="770123"))
    assert exc.value.code == "codigo_barras_duplicado"
    await servicio._session.rollback()


async def test_buscar_por_codigo(servicio):
    await servicio.crear(ProductoCrear(nombre="Gaseosa 400ml", precio_venta=2500, codigo_barras="770400"))
    encontrado = await servicio.buscar_por_codigo("770400")
    assert encontrado.nombre == "Gaseosa 400ml"
    with pytest.raises(NotFoundError) as exc:
        await servicio.buscar_por_codigo("000000")
    assert exc.value.code == "producto_no_encontrado"


async def test_listar_pagina_filtra_por_nombre_y_categoria(servicio):
    await servicio.crear(ProductoCrear(nombre="Arroz 500g", precio_venta=2500, categoria="Granos"))
    await servicio.crear(ProductoCrear(nombre="Arroz integral", precio_venta=4000, categoria="Granos"))
    await servicio.crear(ProductoCrear(nombre="Detergente", precio_venta=9000, categoria="Aseo"))

    filas, total = await servicio.listar(q="arroz")
    assert total == 2 and [f.nombre for f in filas] == ["Arroz 500g", "Arroz integral"]

    filas, total = await servicio.listar(categoria="Aseo")
    assert total == 1 and filas[0].nombre == "Detergente"

    filas, total = await servicio.listar(skip=1, limit=1)
    assert total == 3 and len(filas) == 1

    # Los comodines de LIKE en la búsqueda son texto, no patrón:
    filas, total = await servicio.listar(q="100%")
    assert total == 0


async def test_actualizar_emite_evento_con_los_cambios(servicio, pg_platform_url):
    creado = await servicio.crear(ProductoCrear(nombre="Leche", precio_venta=3200))
    await servicio._session.commit()

    actualizado = await servicio.actualizar(creado.id, ProductoActualizar(precio_venta=3500))
    assert actualizado.precio_venta == 3500
    await servicio._session.commit()

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            fila = (
                await conn.execute(
                    text("SELECT payload FROM outbox_messages WHERE routing_key = :k"),
                    {"k": f"{T1}.producto.actualizado"},
                )
            ).first()
    finally:
        await engine.dispose()
    assert fila is not None
    assert fila.payload["data"]["cambios"]["precio_venta"] == {"antes": "3200", "despues": "3500"}


async def test_actualizar_sin_cambios_no_emite_evento(servicio, pg_platform_url):
    creado = await servicio.crear(ProductoCrear(nombre="Sal", precio_venta=1500))
    await servicio._session.commit()
    mismo = await servicio.actualizar(creado.id, ProductoActualizar(precio_venta=1500))
    assert mismo.precio_venta == 1500
    await servicio._session.commit()
    assert await _contar_outbox(pg_platform_url, f"{T1}.producto.actualizado") == 0


async def _contar_outbox(pg_platform_url: str, routing_key: str) -> int:
    """El outbox se lee con el rol de PLATAFORMA: `vendi_app` solo tiene
    INSERT sobre `outbox_messages` (migración 0001) y un SELECT con la sesión
    de tenant fallaría con `permission denied`."""
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


async def test_eliminar_es_borrado_logico_libera_el_ean_y_emite_evento(servicio, pg_platform_url):
    creado = await servicio.crear(ProductoCrear(nombre="Panela", precio_venta=4200, codigo_barras="770999"))
    await servicio.eliminar(creado.id)
    await servicio._session.commit()

    with pytest.raises(NotFoundError):
        await servicio.obtener(creado.id)
    _, total = await servicio.listar()
    assert total == 0

    # El EAN quedó libre en el mismo tenant (decisión 3 del plan):
    otro = await servicio.crear(ProductoCrear(nombre="Panela nueva", precio_venta=4300, codigo_barras="770999"))
    assert otro.id != creado.id
    assert await _contar_outbox(pg_platform_url, f"{T1}.producto.eliminado") == 1


async def test_el_limite_del_tier_se_verifica_contra_las_filas_vivas(pg_app_url, limpiar_productos):
    """ADR-010/ADR-019: el límite se verifica en la aplicación contra las
    filas VIVAS del negocio; no es una constraint de base."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            gratis = CatalogoService(session=s, tenant_id=T1, tier="gratis")
            for i in range(100):
                await gratis.crear(ProductoCrear(nombre=f"Producto {i:03d}", precio_venta=100))
            with pytest.raises(PermissionDeniedError) as exc:
                await gratis.crear(ProductoCrear(nombre="El 101", precio_venta=100))
            assert exc.value.code == "limite_de_productos_alcanzado"
            assert exc.value.details == {"tier": "gratis", "limite": 100}
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def test_el_limite_del_tier_light_se_detiene_en_500(pg_app_url, pg_platform_url, limpiar_productos):
    """ADR-010/ADR-019: el límite de `light` (500) se verifica igual que el
    de `gratis`, contra las filas VIVAS del negocio. Las 500 filas se siembran
    en un solo INSERT (500 altas por el servicio harían el test lento sin
    probar nada nuevo); el alta que se prueba es la 501, por el camino real."""
    valores = ", ".join(f"('{T1}', 'Producto {i:03d}', 100)" for i in range(500))
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"INSERT INTO productos (tenant_id, nombre, precio_venta) VALUES {valores}"))
    finally:
        await engine.dispose()

    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            light = CatalogoService(session=s, tenant_id=T1, tier="light")
            with pytest.raises(PermissionDeniedError) as exc:
                await light.crear(ProductoCrear(nombre="El 501", precio_venta=100))
            assert exc.value.code == "limite_de_productos_alcanzado"
            assert exc.value.details == {"tier": "light", "limite": 500}
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def test_actualizar_rechaza_al_producto_como_su_propio_padre(servicio):
    """Un producto no puede colgar de sí mismo: el servicio lo corta antes de
    que la FK lo convierta en un ciclo en el árbol de variantes."""
    creado = await servicio.crear(ProductoCrear(nombre="Base", precio_venta=100))
    with pytest.raises(ValidationError) as exc:
        await servicio.actualizar(creado.id, ProductoActualizar(padre_id=creado.id))
    assert exc.value.code == "padre_es_el_mismo"


async def test_actualizar_a_un_ean_ya_usado_da_409_tipado(servicio):
    """El índice único parcial también vigila el PATCH: mover el EAN de un
    producto al de otro del mismo negocio se traduce al sobre de errores."""
    await servicio.crear(ProductoCrear(nombre="A", precio_venta=100, codigo_barras="770111"))
    otro = await servicio.crear(ProductoCrear(nombre="B", precio_venta=100, codigo_barras="770222"))
    with pytest.raises(ConflictError) as exc:
        await servicio.actualizar(otro.id, ProductoActualizar(codigo_barras="770111"))
    assert exc.value.code == "codigo_barras_duplicado"
    await servicio._session.rollback()


async def test_el_padre_debe_existir_en_el_propio_tenant(pg_app_url, limpiar_productos):
    """Postgres NO aplica RLS al verificar la FK de `padre_id`: sin este
    chequeo, una variante podría colgar del producto de OTRO negocio."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T2)
    try:
        async with factory() as s2:
            ajeno = await CatalogoService(session=s2, tenant_id=T2, tier="pro").crear(
                ProductoCrear(nombre="Base ajena", precio_venta=100)
            )
            await s2.commit()
            id_ajeno = ajeno.id
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()

    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s1:
            servicio_t1 = CatalogoService(session=s1, tenant_id=T1, tier="pro")
            with pytest.raises(ValidationError) as exc:
                await servicio_t1.crear(ProductoCrear(nombre="Hija", precio_venta=100, padre_id=id_ajeno))
            assert exc.value.code == "padre_no_encontrado"
            with pytest.raises(ValidationError):
                await servicio_t1.crear(ProductoCrear(nombre="Hija", precio_venta=100, padre_id=uuid.uuid4()))
            await s1.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def test_actualizar_exige_el_mismo_padre_que_crear(pg_app_url, limpiar_productos):
    """El PATCH pasa por el mismo `_exigir_padre` que el alta: ni un padre de
    OTRO negocio ni uno inexistente pueden entrar por la puerta de atrás."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T2)
    try:
        async with factory() as s2:
            ajeno = await CatalogoService(session=s2, tenant_id=T2, tier="pro").crear(
                ProductoCrear(nombre="Base ajena", precio_venta=100)
            )
            await s2.commit()
            id_ajeno = ajeno.id
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()

    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s1:
            servicio_t1 = CatalogoService(session=s1, tenant_id=T1, tier="pro")
            propio = await servicio_t1.crear(ProductoCrear(nombre="Hija", precio_venta=100))
            with pytest.raises(ValidationError) as exc:
                await servicio_t1.actualizar(propio.id, ProductoActualizar(padre_id=id_ajeno))
            assert exc.value.code == "padre_no_encontrado"
            with pytest.raises(ValidationError):
                await servicio_t1.actualizar(propio.id, ProductoActualizar(padre_id=uuid.uuid4()))
            await s1.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()
