"""EL candado del sync offline (ADR-017, ADR-018, ADR-020).

El mismo lote enviado DOS veces —el reintento de red del dispositivo, la
doble pulsación, el drenado reanudado a medias— deja exactamente: UNA venta,
UN movimiento de stock por ítem, la proyección descontada UNA vez y UN evento
`venta.creada`. La segunda aplicación se reporta `duplicada`, no error.

La base no se dobla: la idempotencia la dan la PK del cliente y el índice
único `ux_movimientos_origen`, y ambos solo existen en PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

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
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.inventario.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Un dispositivo y un producto con stock 10 en T1. Limpia antes y después."""
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
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                "VALUES (:p, :t, 'Arroz 500g', 2500, 10)"
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


def _lote(semilla: dict, venta_id: uuid.UUID) -> LoteSync:
    return LoteSync.model_validate(
        {
            "dispositivo_id": str(semilla["dispositivo"]),
            "operaciones": [
                {
                    "id": str(venta_id),
                    "tipo": "venta.crear",
                    "secuencia": 7,
                    "datos": {
                        "consecutivo_local": 42,
                        "medio_pago": "efectivo",
                        "total_centavos": 5000,
                        "creada_en_cliente": datetime.now(UTC).isoformat(),
                        "items": [
                            {"producto_id": str(semilla["producto"]), "cantidad": "2", "precio_unitario_centavos": 2500}
                        ],
                    },
                }
            ],
        }
    )


async def _contar(pg_platform_url: str, sql: str, **params) -> int:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar_one()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_el_mismo_lote_dos_veces_deja_una_venta_un_movimiento_y_un_evento(
    pg_app_url: str, pg_platform_url: str, semilla
):
    venta_id = uuid.uuid4()
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        for esperado in ("aceptada", "duplicada"):
            async with factory() as s:
                servicio = VentasService(session=s, tenant_id=T1, actor_id="cajero-prueba", puede_anular=True)
                resultados = await servicio.procesar_lote(_lote(semilla, venta_id))
                assert [r.resultado for r in resultados] == [esperado]
                await s.commit()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()

    assert await _contar(pg_platform_url, "SELECT count(*) FROM ventas WHERE tenant_id = :t", t=T1) == 1
    assert (
        await _contar(
            pg_platform_url,
            "SELECT count(*) FROM movimientos_inventario WHERE tenant_id = :t AND tipo = 'venta'",
            t=T1,
        )
        == 1
    )
    stock = await _contar(pg_platform_url, "SELECT stock_actual::int FROM productos WHERE tenant_id = :t", t=T1)
    assert stock == 8, "el stock se descontó UNA vez, no dos"
    eventos = await _contar(
        pg_platform_url, "SELECT count(*) FROM outbox_messages WHERE routing_key = :k", k=f"{T1}.venta.creada"
    )
    assert eventos == 1, "una sola vez por operación aceptada (ADR-017): la duplicada NO re-emite"
