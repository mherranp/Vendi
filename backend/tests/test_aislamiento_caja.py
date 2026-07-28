"""Aislamiento cross-tenant y reglas duras de `caja_movimientos` (módulo caja).

Hermano de `test_aislamiento_ventas.py`, mismo criterio: SQL crudo con el rol
`vendi_app` y nada de ORM, para que ningún `WHERE` amable dé un falso verde
sobre una policy que no filtra. La tabla la crea la migración `0008_caja`;
hasta que existe, TODOS estos tests fallan — que es el punto del paso TDD.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM caja_movimientos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Una sesión abierta POR NEGOCIO y un movimiento en la de T1. Limpia
    antes y después: la suite es re-entrante."""
    engine = create_async_engine(pg_platform_url)
    ids = {"T1": uuid.uuid4(), "T2": uuid.uuid4(), "movimiento": uuid.uuid4()}
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        for nombre, tenant in (("T1", T1), ("T2", T2)):
            await conn.execute(
                text(
                    "INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) "
                    "VALUES (:s, :t, 'dueno', 50000)"
                ),
                {"s": ids[nombre], "t": tenant},
            )
        await conn.execute(
            text(
                "INSERT INTO caja_movimientos (id, tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, registrado_por) "
                "VALUES (:m, :t, :s, 'egreso', 'servicios', 12000, 'Recibo de la luz', 'dueno')"
            ),
            {"m": ids["movimiento"], "t": T1, "s": ids["T1"]},
        )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def sesion_t1(pg_app_url: str, semilla):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield s
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


@pytest.mark.asyncio
async def test_select_solo_ve_los_movimientos_del_propio_tenant(sesion_t1):
    filas = (await sesion_t1.execute(text("SELECT tenant_id FROM caja_movimientos"))).all()
    assert len(filas) == 1
    assert filas[0][0] == T1


@pytest.mark.asyncio
async def test_insert_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1, semilla):
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(
            text(
                "INSERT INTO caja_movimientos (tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, registrado_por) "
                "VALUES (:t, :s, 'ingreso', 'otro', 100, 'inyectado', 'dueno')"
            ),
            {"t": T2, "s": semilla["T2"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tipo,categoria,monto",
    [
        ("traspaso", "otro", 100),  # tipo fuera de la lista cerrada (≤8: el CHECK, no el varchar, rechaza)
        ("ingreso", "ropa", 100),  # categoría fuera de la lista cerrada
        ("egreso", "otro", 0),  # monto cero: un movimiento de cero no es movimiento
        ("egreso", "otro", -5000),  # monto negativo: el signo lo da el tipo
    ],
)
async def test_los_checks_rechazan_tipo_categoria_y_monto_invalidos(sesion_t1, semilla, tipo, categoria, monto):
    with pytest.raises(IntegrityError):
        await sesion_t1.execute(
            text(
                "INSERT INTO caja_movimientos (tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, registrado_por) "
                "VALUES (:t, :s, :tipo, :cat, :monto, 'prueba de check', 'dueno')"
            ),
            {"t": T1, "s": semilla["T1"], "tipo": tipo, "cat": categoria, "monto": monto},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_movimiento_exige_sesion_existente(sesion_t1):
    """FK RESTRICT: ningún movimiento huérfano de sesión (ni siquiera contra
    un UUID al azar: Postgres no aplica RLS al verificar llaves foráneas)."""
    with pytest.raises(IntegrityError, match="caja_movimientos_sesion_caja_id_fkey"):
        await sesion_t1.execute(
            text(
                "INSERT INTO caja_movimientos (tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, registrado_por) "
                "VALUES (:t, :s, 'ingreso', 'otro', 100, 'huerfano', 'dueno')"
            ),
            {"t": T1, "s": uuid.uuid4()},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_cierre_es_completo_o_no_es(sesion_t1, semilla):
    """`ck_caja_sesiones_cierre_completo`: marcar `cerrada` sin las cinco
    columnas del arqueo revienta. El arqueo a medias no existe (ADR-021)."""
    with pytest.raises(IntegrityError, match="ck_caja_sesiones_cierre_completo"):
        await sesion_t1.execute(
            text("UPDATE caja_sesiones SET estado = 'cerrada' WHERE id = :s"),
            {"s": semilla["T1"]},
        )
    await sesion_t1.rollback()
    # Y con las cinco, cierra.
    await sesion_t1.execute(
        text(
            "UPDATE caja_sesiones SET estado = 'cerrada', cerrada_por = 'dueno', cerrada_en = now(), "
            "efectivo_esperado = 38000, efectivo_contado = 38000, diferencia = 0 WHERE id = :s"
        ),
        {"s": semilla["T1"]},
    )
    await sesion_t1.commit()


@pytest.mark.asyncio
async def test_ventas_tiene_anulada_en(pg_platform_url: str, semilla):
    """La columna que hace caer la devolución en la sesión abierta (decisión 7)."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            dispositivo = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
                {"d": dispositivo, "t": T1},
            )
            venta = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                    "medio_pago, total_centavos, creada_en_cliente, secuencia_dispositivo, estado, anulada_en) "
                    "VALUES (:v, :t, :d, :s, 1, 'efectivo', 2500, now(), 1, 'anulada', now())"
                ),
                {"v": venta, "t": T1, "d": dispositivo, "s": semilla["T1"]},
            )
            fila = (
                await conn.execute(
                    text("SELECT estado, anulada_en IS NOT NULL FROM ventas WHERE id = :v"), {"v": venta}
                )
            ).one()
            assert fila == ("anulada", True)
            await conn.execute(text("DELETE FROM ventas WHERE id = :v"), {"v": venta})
            await conn.execute(text("DELETE FROM dispositivos WHERE id = :d"), {"d": dispositivo})
    finally:
        await engine.dispose()
