"""Las alertas de umbral de ADR-020, contra el PostgreSQL real.

Los niveles se derivan de `stock_minimo`: agotado (`stock <= 0`), crítico
(`< stock_minimo / 2`), bajo (`< stock_minimo`), ok el resto. El evento
`inventario.alerta_stock` se emite SOLO cuando el nivel empeora al aplicar
un movimiento — nunca por movimiento, nunca al recuperarse, nunca dos veces
por el mismo cruce.

Semilla del producto de estos tests: stock 10, `stock_minimo` 4. El mapa:

    stock >= 4    ok
    2 <= stock < 4  bajo
    0 < stock < 2   crítico
    stock <= 0    agotado
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.catalogo.models import Producto
from app.modules.inventario.stock import aplicar_movimiento, nivel_de_stock
from app.modules.ventas.schemas import LoteSync
from app.modules.ventas.service import VentasService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.inventario.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Un producto con stock 10 y mínimo 4 en T1, y un dispositivo para las
    ventas por sync."""
    ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4()}
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
        )
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual, stock_minimo) "
                "VALUES (:p, :t, 'Arroz 500g', 2500, 10, 4)"
            ),
            {"p": ids["producto"], "t": T1},
        )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def sesion(pg_app_url: str, semilla):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield s
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def _alertas(pg_platform_url: str) -> list[str]:
    """Los niveles de las alertas emitidas por T1, en orden de emisión."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            filas = (
                (
                    await conn.execute(
                        text(
                            "SELECT payload->'data'->>'nivel' FROM outbox_messages "
                            "WHERE routing_key = :k ORDER BY created_at, id"
                        ),
                        {"k": f"{T1}.inventario.alerta_stock"},
                    )
                )
                .scalars()
                .all()
            )
            return list(filas)
    finally:
        await engine.dispose()


async def _aplicar(sesion, semilla, delta: str, tipo: str = "venta") -> None:
    producto = await sesion.get(Producto, semilla["producto"], with_for_update=True)
    await aplicar_movimiento(
        sesion,
        tenant_id=T1,
        producto=producto,
        delta=Decimal(delta),
        tipo=tipo,
        referencia_id=uuid.uuid4(),
    )
    await sesion.commit()


# --- La función pura -----------------------------------------------------------------


@pytest.mark.parametrize(
    "stock,minimo,esperado",
    [
        ("10", "4", "ok"),
        ("4", "4", "ok"),  # el mínimo exacto NO es bajo: bajo es estricto
        ("3.999", "4", "bajo"),
        ("2", "4", "bajo"),  # la mitad exacta NO es crítico: crítico es estricto
        ("1.999", "4", "critico"),
        ("0.001", "4", "critico"),
        ("0", "4", "agotado"),
        ("-3", "4", "agotado"),  # el negativo es legítimo y es agotado (ADR-020)
        ("0", "0", "agotado"),  # sin mínimo configurado, el cero ya es agotado
        ("5", "0", "ok"),  # sin mínimo, no hay bajo ni crítico
    ],
)
def test_nivel_de_stock_en_los_bordes(stock, minimo, esperado):
    assert nivel_de_stock(Decimal(stock), Decimal(minimo)) == esperado


# --- El cruce hacia abajo emite; lo demás, no ----------------------------------------


async def test_cruzar_hacia_abajo_emite_un_evento_por_cruce_y_no_por_movimiento(sesion, semilla, pg_platform_url):
    await _aplicar(sesion, semilla, "-7")  # 10 → 3: ok → bajo. EMITE.
    await _aplicar(sesion, semilla, "-1")  # 3 → 2: bajo → bajo. NO emite.
    await _aplicar(sesion, semilla, "-1")  # 2 → 1: bajo → crítico. EMITE.
    await _aplicar(sesion, semilla, "-0.5")  # 1 → 0.5: crítico → crítico. NO emite.
    await _aplicar(sesion, semilla, "-1")  # 0.5 → -0.5: crítico → agotado. EMITE.
    await _aplicar(sesion, semilla, "-1")  # -0.5 → -1.5: agotado → agotado. NO emite.
    assert await _alertas(pg_platform_url) == ["bajo", "critico", "agotado"]


async def test_recuperarse_no_emite_y_volver_a_cruzar_si(sesion, semilla, pg_platform_url):
    """El candado de ADR-020: N movimientos que cruzan el MISMO umbral emiten
    UN evento por cruce — y una recuperación «re-arma» el umbral."""
    await _aplicar(sesion, semilla, "-7")  # ok → bajo. EMITE (1).
    await _aplicar(sesion, semilla, "20", tipo="compra")  # 3 → 23: bajo → ok. NO emite.
    await _aplicar(sesion, semilla, "-20")  # 23 → 3: ok → bajo. EMITE (2).
    assert await _alertas(pg_platform_url) == ["bajo", "bajo"]


async def test_dos_ventas_seguidas_por_debajo_del_minimo_emiten_una_sola_alerta(sesion, semilla, pg_platform_url):
    """El escenario anti-spam firmado: la cola de sync con varias ventas del
    mismo producto NO manda una notificación por venta. Aquí por el camino
    real del sync (VentasService), no por el helper."""

    def venta(consecutivo: int, cantidad: str, total: int) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "tipo": "venta.crear",
            "secuencia": consecutivo,
            "datos": {
                "consecutivo_local": consecutivo,
                "medio_pago": "efectivo",
                "total_centavos": total,
                "creada_en_cliente": "2026-07-28T10:00:00+00:00",
                "items": [
                    {"producto_id": str(semilla["producto"]), "cantidad": cantidad, "precio_unitario_centavos": 2500}
                ],
            },
        }

    servicio = VentasService(session=sesion, tenant_id=T1, actor_id="cajero-prueba", puede_anular=False)
    # Primera venta: 10 → 3 (ok → bajo, EMITE). Segunda, ya por debajo del
    # mínimo: 3 → 2.5 (bajo → bajo, NO emite). El umbral se cruzó UNA vez.
    lote = LoteSync.model_validate(
        {"dispositivo_id": str(semilla["dispositivo"]), "operaciones": [venta(1, "7", 17500), venta(2, "0.5", 1250)]}
    )
    resultados = await servicio.procesar_lote(lote)
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada"]
    await sesion.commit()
    assert await _alertas(pg_platform_url) == ["bajo"]


async def test_la_operacion_duplicada_no_reemite_la_alerta(sesion, semilla, pg_platform_url):
    """Anti-duplicado por construcción (decisión 14): el reintento del mismo
    lote es `duplicada` antes de mover stock, así que jamás llega a la
    emisión."""
    operacion = {
        "id": str(uuid.uuid4()),
        "tipo": "venta.crear",
        "secuencia": 1,
        "datos": {
            "consecutivo_local": 1,
            "medio_pago": "efectivo",
            "total_centavos": 17500,
            "creada_en_cliente": "2026-07-28T10:00:00+00:00",
            "items": [{"producto_id": str(semilla["producto"]), "cantidad": "7", "precio_unitario_centavos": 2500}],
        },
    }
    servicio = VentasService(session=sesion, tenant_id=T1, actor_id="cajero-prueba", puede_anular=False)
    lote = LoteSync.model_validate({"dispositivo_id": str(semilla["dispositivo"]), "operaciones": [operacion]})
    await servicio.procesar_lote(lote)
    await sesion.commit()
    reintento = await servicio.procesar_lote(lote)
    assert reintento[0].resultado == "duplicada"
    await sesion.commit()
    assert await _alertas(pg_platform_url) == ["bajo"]  # 10 → 3: una sola, no dos
