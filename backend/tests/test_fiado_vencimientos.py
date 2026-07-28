"""El trabajo diario de vencidos contra el PostgreSQL real (ADR-022).

El candado firmado: un crédito con vencimiento de ayer pasa a `vencido` y
encola EXACTAMENTE un `fiado.credito_vencido`, idempotente al re-correr.
La sesión es de plataforma (como la del worker real): el filtro por tenant
es explícito y se prueba que T2 no se toca cuando corre la pasada de T1.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.db.session import create_platform_session_factory
from vendi_core.jobs.types import JobContext
from worker.jobs import construir_jobs, marcar_vencimientos_fiado

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM fiado_abonos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM fiado_creditos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM clientes WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.fiado.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """En T1: crédito vencido de ayer, uno a futuro, uno sin fecha y uno
    saldado. En T2: otro vencido de ayer (la pasada de T1 NO debe tocarlo)."""
    engine = create_async_engine(pg_platform_url)
    ids = {
        "vencido": uuid.uuid4(),
        "futuro": uuid.uuid4(),
        "sin_fecha": uuid.uuid4(),
        "saldado": uuid.uuid4(),
        "de_t2": uuid.uuid4(),
    }
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        for tenant in (T1, T2):
            await conn.execute(
                text("INSERT INTO clientes (id, tenant_id, nombre) VALUES (gen_random_uuid(), :t, 'Don Carlos')"),
                {"t": tenant},
            )
            await conn.execute(
                text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (gen_random_uuid(), :t, 'Caja 1')"),
                {"t": tenant},
            )
            await conn.execute(
                text(
                    "INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) "
                    "VALUES (gen_random_uuid(), :t, 'dueno', 0)"
                ),
                {"t": tenant},
            )
        # «Ayer»/«futuro» se calculan en el calendario de America/Bogota, que
        # es el que juzga el vencimiento (ADR-022): el Postgres corre en UTC y
        # su CURRENT_DATE se adelanta un día a Bogotá desde las 19:00.
        hoy_bogota = "(now() AT TIME ZONE 'America/Bogota')::date"
        for tenant, filas in (
            (
                T1,
                (
                    ("vencido", f"{hoy_bogota} - 1", "vigente", 43000, 43000),
                    ("futuro", f"{hoy_bogota} + 10", "vigente", 10000, 10000),
                    ("sin_fecha", "NULL", "vigente", 5000, 5000),
                    ("saldado", f"{hoy_bogota} - 3", "saldado", 8000, 0),
                ),
            ),
            (T2, (("de_t2", f"{hoy_bogota} - 1", "vigente", 7000, 7000),)),
        ):
            cliente = (
                await conn.execute(text("SELECT id FROM clientes WHERE tenant_id = :t"), {"t": tenant})
            ).scalar_one()
            dispositivo = (
                await conn.execute(text("SELECT id FROM dispositivos WHERE tenant_id = :t"), {"t": tenant})
            ).scalar_one()
            sesion = (
                await conn.execute(text("SELECT id FROM caja_sesiones WHERE tenant_id = :t"), {"t": tenant})
            ).scalar_one()
            for consecutivo, (clave, vencimiento, estado, monto, saldo) in enumerate(filas, start=1):
                venta = uuid.uuid4()
                await conn.execute(
                    text(
                        "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                        "medio_pago, total_centavos, cliente_id, creada_en_cliente, secuencia_dispositivo) "
                        "VALUES (:v, :t, :d, :s, :cons, 'fiado', :m, :c, now(), 1)"
                    ),
                    {
                        "v": venta,
                        "t": tenant,
                        "d": dispositivo,
                        "s": sesion,
                        "cons": consecutivo,
                        "m": monto,
                        "c": cliente,
                    },
                )
                await conn.execute(
                    text(
                        f"INSERT INTO fiado_creditos (id, tenant_id, cliente_id, venta_id, monto_total, "
                        f"saldo_pendiente, fecha_vencimiento, estado) "
                        f"VALUES (:cr, :t, :c, :v, :m, :s, {vencimiento}, :e)"
                    ),
                    {"cr": ids[clave], "t": tenant, "c": cliente, "v": venta, "m": monto, "s": saldo, "e": estado},
                )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


def _ctx(pg_platform_url: str, tenant_id: uuid.UUID) -> JobContext:
    from vendi_core.db.engine import create_engine as _crear

    engine = _crear(pg_platform_url)
    return JobContext(session_factory=create_platform_session_factory(engine), engine=engine, tenant_id=tenant_id)


async def _estado(pg_platform_url: str, credito_id: uuid.UUID) -> str:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(text("SELECT estado FROM fiado_creditos WHERE id = :c"), {"c": credito_id})
            ).scalar_one()
    finally:
        await engine.dispose()


async def _conteo_eventos(pg_platform_url: str) -> int:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT count(*) FROM outbox_messages WHERE routing_key LIKE '%.fiado.credito_vencido'")
                )
            ).scalar_one()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_marca_vencido_y_encola_exactamente_un_evento(pg_platform_url, semilla):
    """El candado de ADR-022, literal: el crédito con vencimiento de ayer pasa
    a `vencido` y encola exactamente un `fiado.credito_vencido`."""
    cambios = await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    assert cambios == {"creditos_vencidos": 1}
    assert await _estado(pg_platform_url, semilla["vencido"]) == "vencido"
    assert await _conteo_eventos(pg_platform_url) == 1


@pytest.mark.asyncio
async def test_recorrer_la_pasada_es_noop(pg_platform_url, semilla):
    """La transición ES el anti-duplicado (decisión 7): el UPDATE solo toca
    `vigente`, así que la segunda corrida marca 0 y no re-emite."""
    await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    cambios = await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    assert cambios == {"creditos_vencidos": 0}
    assert await _conteo_eventos(pg_platform_url) == 1


@pytest.mark.asyncio
async def test_no_toca_el_futuro_el_sin_fecha_el_saldado_ni_el_vecino(pg_platform_url, semilla):
    await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    assert await _estado(pg_platform_url, semilla["futuro"]) == "vigente"
    assert await _estado(pg_platform_url, semilla["sin_fecha"]) == "vigente"  # sin fecha = sin recordatorio
    assert await _estado(pg_platform_url, semilla["saldado"]) == "saldado"
    assert await _estado(pg_platform_url, semilla["de_t2"]) == "vigente"  # el filtro explícito por tenant
    # Y cuando corre la pasada de T2, el suyo sí vence.
    await marcar_vencimientos_fiado(_ctx(pg_platform_url, T2))
    assert await _estado(pg_platform_url, semilla["de_t2"]) == "vencido"
    assert await _conteo_eventos(pg_platform_url) == 2


@pytest.mark.asyncio
async def test_el_trabajo_esta_registrado_con_scope_de_tenant(pg_platform_url):
    """El planificador itera los negocios activos (scope `tenant`): una fila
    de auditoría por negocio y el ContextVar sembrado por iteración."""
    runner = None
    jobs = {j.name: j for j in construir_jobs(runner)}
    assert "fiado.vencimientos" in jobs
    assert jobs["fiado.vencimientos"].scope == "tenant"
    assert jobs["fiado.vencimientos"].cron == "30 11 * * *"
