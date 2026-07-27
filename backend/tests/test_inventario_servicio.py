"""`InventarioService` contra el PostgreSQL real, con el rol `vendi_app`.

Misma regla que `test_ventas_servicio.py`: la base no se dobla. Aquí se fijan
los comportamientos firmados del módulo: la compra que mueve stock, costo y
evento en una transacción; el ajuste online cuyo delta se calcula contra el
stock del servidor; la idempotencia por UUID de cliente; la invariante del
libro de ADR-020.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.catalogo.models import Producto
from app.modules.inventario.schemas import AjusteCrear, CompraCrear
from app.modules.inventario.service import InventarioService
from app.modules.inventario.stock import aplicar_movimiento
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import ConflictError, NotFoundError, ValidationError
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compra_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compras WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ajustes_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.inventario.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.compra.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """T1: producto stock 10 mínimo 4, y producto2 stock 3 mínimo 0.
    T2: un producto propio (para las pruebas de aislamiento)."""
    ids = {"producto": uuid.uuid4(), "producto2": uuid.uuid4(), "ajeno": uuid.uuid4()}
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual, stock_minimo) "
                "VALUES (:p, :t, 'Arroz 500g', 2500, 10, 4)"
            ),
            {"p": ids["producto"], "t": T1},
        )
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                "VALUES (:p, :t, 'Huevo und', 600, 3)"
            ),
            {"p": ids["producto2"], "t": T1},
        )
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                "VALUES (:p, :t, 'Panela', 1800, 7)"
            ),
            {"p": ids["ajeno"], "t": T2},
        )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def servicio(pg_app_url: str, semilla):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield InventarioService(session=s, tenant_id=T1, actor_id="almacenista-prueba")
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


def _compra(
    semilla: dict, compra_id: uuid.UUID | None = None, cantidad: str = "10", costo: int = 2000, **cambios
) -> CompraCrear:
    cuerpo = {
        "proveedor_nombre": "Distribuidora La 33",
        "items": [{"producto_id": str(semilla["producto"]), "cantidad": cantidad, "costo_unitario_centavos": costo}],
        **cambios,
    }
    if compra_id is not None:
        cuerpo["id"] = str(compra_id)
    return CompraCrear.model_validate(cuerpo)


def _ajuste(semilla: dict, ajuste_id: uuid.UUID, **cambios) -> AjusteCrear:
    cuerpo = {
        "id": str(ajuste_id),
        "tipo": "ajuste",
        "producto_id": str(semilla["producto"]),
        "stock_contado": "8",
        "motivo": "Conteo de cierre",
        **cambios,
    }
    return AjusteCrear.model_validate(cuerpo)


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


# --- Compras ---------------------------------------------------------------------


async def test_registrar_compra_mueve_stock_actualiza_ultimo_costo_y_emite_evento(servicio, semilla, pg_platform_url):
    compra = await servicio.registrar_compra(_compra(semilla, uuid.uuid4()))
    await servicio._session.commit()

    producto = await _uno(
        pg_platform_url,
        "SELECT stock_actual, ultimo_costo FROM productos WHERE id = :p",
        p=semilla["producto"],
    )
    assert producto.stock_actual == 20  # 10 + 10
    assert producto.ultimo_costo == 2000  # lo que costó ESTA compra (ADR-020: lo costea el P&L)
    movimiento = await _uno(
        pg_platform_url,
        "SELECT tipo, cantidad, referencia_id FROM movimientos_inventario WHERE tenant_id = :t",
        t=T1,
    )
    assert (movimiento.tipo, movimiento.cantidad, movimiento.referencia_id) == ("compra", 10, compra.id)
    evento = await _uno(
        pg_platform_url,
        "SELECT payload->'data'->>'total_centavos' AS total FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.compra.registrada",
    )
    assert evento.total == "20000"


async def test_el_total_de_la_compra_lo_calcula_el_servidor_por_linea(servicio, semilla):
    """Granel: 0.333 kg × $1.00 = 33.3 centavos → la línea redondea a 33
    (ROUND_HALF_UP, decisión 7) y el total es la suma de las líneas."""
    compra = await servicio.registrar_compra(
        _compra(
            semilla,
            uuid.uuid4(),
            cantidad="0.333",
            costo=100,
            items=[
                {"producto_id": str(semilla["producto"]), "cantidad": "0.333", "costo_unitario_centavos": 100},
                {"producto_id": str(semilla["producto2"]), "cantidad": "2", "costo_unitario_centavos": 550},
            ],
        )
    )
    assert compra.total_centavos == 33 + 1100


async def test_registrar_compra_es_idempotente_por_el_id_del_cliente(servicio, semilla, pg_platform_url):
    el_id = uuid.uuid4()
    primera = await servicio.registrar_compra(_compra(semilla, el_id))
    await servicio._session.commit()
    segunda = await servicio.registrar_compra(_compra(semilla, el_id))
    await servicio._session.commit()

    assert segunda.id == primera.id == el_id
    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM movimientos_inventario WHERE tenant_id = :t) AS movimientos, "
        "(SELECT count(*) FROM outbox_messages WHERE routing_key = :k) AS eventos, "
        "(SELECT stock_actual FROM productos WHERE id = :p) AS stock",
        t=T1,
        k=f"{T1}.compra.registrada",
        p=semilla["producto"],
    )
    assert (fila.movimientos, fila.eventos, fila.stock) == (1, 1, 20)  # ni doble stock ni doble evento


async def test_compra_con_producto_de_otro_negocio_es_422_sin_fuga(servicio, semilla):
    """La RLS hace invisible el producto de T2: mismo veredicto que uno
    inexistente (criterio `padre_no_encontrado` del catálogo)."""
    with pytest.raises(ValidationError) as exc:
        await servicio.registrar_compra(
            _compra(
                semilla,
                uuid.uuid4(),
                items=[{"producto_id": str(semilla["ajeno"]), "cantidad": "1", "costo_unitario_centavos": 100}],
            )
        )
    assert exc.value.code == "producto_no_encontrado"


async def test_compra_sobre_producto_dado_de_baja_es_422(servicio, semilla, pg_platform_url):
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE productos SET deleted_at = now() WHERE id = :p"), {"p": semilla["producto"]})
    await engine.dispose()
    with pytest.raises(ValidationError) as exc:
        await servicio.registrar_compra(_compra(semilla, uuid.uuid4()))
    assert exc.value.code == "producto_no_encontrado"


async def test_dos_compras_concurrentes_del_mismo_producto_dejan_el_stock_exacto(pg_app_url, semilla, pg_platform_url):
    """La carrera de la proyección: sin FOR UPDATE, las dos sesiones leerían el
    MISMO stock y el segundo commit pisaría al primero. Con el bloqueo, el
    perdedor espera y re-lee (fix `49553da` de ventas, misma disciplina)."""

    async def compra_con_sesion_propia(cantidad: str) -> None:
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                servicio = InventarioService(session=s, tenant_id=T1, actor_id="almacenista-prueba")
                await servicio.registrar_compra(_compra(semilla, uuid.uuid4(), cantidad=cantidad))
                await s.commit()
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    await asyncio.gather(compra_con_sesion_propia("5"), compra_con_sesion_propia("7"))
    fila = await _uno(
        pg_platform_url,
        "SELECT stock_actual FROM productos WHERE id = :p",
        p=semilla["producto"],
    )
    assert fila.stock_actual == 22  # 10 + 5 + 7, ni una unidad perdida


async def test_comprar_no_emite_alerta_aunque_salga_del_rojo(servicio, semilla, pg_platform_url):
    """La compra que repone el stock MEJORA el nivel: no alerta (ADR-020: el
    evento es solo al cruzar hacia abajo); lo que hace es re-armar el umbral."""
    # Primero, una venta deja el producto en bajo (y emite su alerta).
    producto = await servicio._session.get(Producto, semilla["producto"], with_for_update=True)
    await aplicar_movimiento(
        servicio._session,
        tenant_id=T1,
        producto=producto,
        delta=Decimal("-7"),
        tipo="venta",
        referencia_id=uuid.uuid4(),
    )
    await servicio._session.commit()
    await servicio.registrar_compra(_compra(semilla, uuid.uuid4()))
    await servicio._session.commit()
    fila = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.inventario.alerta_stock",
    )
    assert fila.n == 1  # solo la del cruce hacia abajo; la compra no sumó


# --- Ajustes y mermas ---------------------------------------------------------------


async def test_el_ajuste_calcula_el_delta_contra_el_stock_del_servidor(servicio, semilla, pg_platform_url):
    """ADR-020: «conté 8, el sistema dice 10» → delta -2 calculado AQUÍ, no
    en el cliente. Por eso el ajuste es online: contra un stock viejo, el
    delta sería mentira."""
    creado = await servicio.registrar_ajuste(_ajuste(semilla, uuid.uuid4()))
    await servicio._session.commit()

    assert creado.delta == -2
    assert creado.stock_resultante == 8
    assert creado.nivel == "ok"  # 8 >= mínimo 4
    fila = await _uno(
        pg_platform_url,
        "SELECT tipo, cantidad, referencia_id FROM movimientos_inventario WHERE tenant_id = :t",
        t=T1,
    )
    assert (fila.tipo, fila.cantidad, fila.referencia_id) == ("ajuste", -2, creado.id)


async def test_el_ajuste_al_alza_es_un_movimiento_positivo(servicio, semilla, pg_platform_url):
    creado = await servicio.registrar_ajuste(
        _ajuste(semilla, uuid.uuid4(), stock_contado="14", motivo="Sobrante del conteo")
    )
    await servicio._session.commit()
    assert creado.delta == 4
    fila = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert fila.stock_actual == 14


async def test_el_conteo_que_cuadra_no_escribe_movimiento_pero_si_fila(servicio, semilla, pg_platform_url):
    """El caso que justifica la tabla (decisión 5): sin fila, el reintento de
    este ajuste sería inanclable. `ck_movimientos_cantidad_no_cero` prohíbe el
    movimiento de cero; la fila del ajuste queda como prueba."""
    creado = await servicio.registrar_ajuste(
        _ajuste(semilla, uuid.uuid4(), stock_contado="10", motivo="Cuadró el conteo")
    )
    await servicio._session.commit()
    assert creado.delta == 0
    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM movimientos_inventario WHERE tenant_id = :t) AS movimientos, "
        "(SELECT count(*) FROM ajustes_inventario WHERE tenant_id = :t) AS ajustes",
        t=T1,
    )
    assert (fila.movimientos, fila.ajustes) == (0, 1)


async def test_el_reintento_del_ajuste_devuelve_lo_mismo_sin_mover_stock(servicio, semilla, pg_platform_url):
    el_id = uuid.uuid4()
    primero = await servicio.registrar_ajuste(_ajuste(semilla, el_id))
    await servicio._session.commit()
    segundo = await servicio.registrar_ajuste(_ajuste(semilla, el_id))
    await servicio._session.commit()
    assert segundo.id == primero.id
    assert segundo.delta == -2 and segundo.stock_resultante == 8
    fila = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n, (SELECT stock_actual FROM productos WHERE id = :p) AS stock "
        "FROM movimientos_inventario WHERE tenant_id = :t",
        t=T1,
        p=semilla["producto"],
    )
    assert (fila.n, fila.stock) == (1, 8)  # el delta se aplicó UNA vez


async def test_el_mismo_id_de_ajuste_con_otro_payload_es_409(servicio, semilla):
    """La idempotencia NO es ciega a la divergencia (lección del QA): mismo id
    con otro conteo no es un reintento, es otro ajuste que alguien debe mirar."""
    el_id = uuid.uuid4()
    await servicio.registrar_ajuste(_ajuste(semilla, el_id))
    await servicio._session.commit()
    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_ajuste(_ajuste(semilla, el_id, stock_contado="5"))
    assert exc.value.code == "ajuste_id_divergente"
    assert "stock_contado" in exc.value.details["campos"]


async def test_la_merma_descuenta_y_su_reintento_no_descuenta_dos_veces(servicio, semilla, pg_platform_url):
    """La merma es el caso que hace el `id` REQUERIDO (decisión 4): es un
    delta relativo, y sin ancla el reintento la aplicaría dos veces."""
    el_id = uuid.uuid4()
    datos = _ajuste(
        semilla, el_id, tipo="merma", cantidad="3", stock_contado=None, motivo="Se dañó con la nevera apagada"
    )
    creado = await servicio.registrar_ajuste(datos)
    await servicio._session.commit()
    assert creado.delta == -3 and creado.nivel == "ok"  # 10 → 7, con mínimo 4: sigue ok
    await servicio.registrar_ajuste(datos)  # reintento byte-idéntico
    await servicio._session.commit()
    fila = await _uno(
        pg_platform_url,
        "SELECT cantidad, tipo FROM movimientos_inventario WHERE tenant_id = :t",
        t=T1,
    )
    assert (fila.tipo, fila.cantidad) == ("merma", -3)
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == 7


async def test_la_invariante_del_libro_tras_una_secuencia_mezclada(servicio, semilla, pg_platform_url):
    """El candado de ADR-020: tras ventas, una compra, una merma y un ajuste,
    `stock_actual = SUM(cantidad de los movimientos)`."""
    producto_id = semilla["producto"]
    # La semilla fija el saldo inicial (10) con un INSERT directo de
    # `stock_actual` — un atajo de fixture que en producción no existe: el
    # producto nace con stock 0 (`ProductoCrear` ni siquiera acepta
    # `stock_actual`) y TODO saldo entra por el libro. La invariante solo es
    # comprobable si ese saldo inicial también es una fila del libro, así que
    # se asienta como lo que sería en la vida real: un ajuste de apertura.
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, producto_id) "
                    "VALUES (:t, 'ajuste', 10, :r, :p)"
                ),
                {"t": T1, "r": uuid.uuid4(), "p": producto_id},
            )
    finally:
        await engine.dispose()
    # Venta -3 (por el punto único, como la aplicaría el sync).
    producto = await servicio._session.get(Producto, producto_id, with_for_update=True)
    await aplicar_movimiento(
        servicio._session,
        tenant_id=T1,
        producto=producto,
        delta=Decimal("-3"),
        tipo="venta",
        referencia_id=uuid.uuid4(),
    )
    await servicio.registrar_compra(_compra(semilla, uuid.uuid4(), cantidad="10"))  # +10
    await servicio.registrar_ajuste(
        _ajuste(semilla, uuid.uuid4(), tipo="merma", cantidad="2", stock_contado=None, motivo="Roto en transporte")
    )  # -2
    await servicio.registrar_ajuste(
        _ajuste(semilla, uuid.uuid4(), stock_contado="20", motivo="Reconteo general")
    )  # → 20
    await servicio._session.commit()

    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT stock_actual FROM productos WHERE id = :p) AS proyeccion, "
        "(SELECT COALESCE(SUM(cantidad), 0) FROM movimientos_inventario WHERE tenant_id = :t AND producto_id = :p) AS libro",
        t=T1,
        p=producto_id,
    )
    # 10 (inicial) - 3 + 10 - 2 = 15; el ajuste a 20 aplica +5 → 20 = SUM.
    assert fila.proyeccion == 20 == fila.libro


# --- Estado de stock ------------------------------------------------------------------


async def test_el_estado_de_stock_deriva_el_nivel_y_filtra_las_alertas(servicio, semilla):
    # Arroz: 10 con mínimo 4 → ok. Huevo: 3 con mínimo 0 → ok. Un ajuste deja
    # el huevo en 0 → agotado.
    await servicio.registrar_ajuste(
        _ajuste(
            semilla, uuid.uuid4(), producto_id=str(semilla["producto2"]), stock_contado="0", motivo="No queda ninguno"
        )
    )
    todo, total = await servicio.estado_stock()
    assert total == 2
    niveles = {s.nombre: s.nivel for s in todo}
    assert niveles == {"Arroz 500g": "ok", "Huevo und": "agotado"}
    alertas, total_alertas = await servicio.estado_stock(solo_alertas=True)
    assert total_alertas == 1
    assert alertas[0].nombre == "Huevo und" and alertas[0].stock_actual == 0


async def test_obtener_compra_devuelve_sus_items_y_la_desconocida_es_404(servicio, semilla):
    compra = await servicio.registrar_compra(_compra(semilla, uuid.uuid4()))
    await servicio._session.commit()
    hallada, items = await servicio.obtener_compra(compra.id)
    assert hallada.id == compra.id
    assert [(i.producto_id, i.cantidad, i.costo_unitario_centavos) for i in items] == [
        (semilla["producto"], Decimal("10.000"), 2000)
    ]
    with pytest.raises(NotFoundError) as exc:
        await servicio.obtener_compra(uuid.uuid4())
    assert exc.value.code == "compra_no_encontrada"
