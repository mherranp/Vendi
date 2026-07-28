"""Aislamiento cross-tenant y reglas duras del fiado (módulo fiado y clientes).

Hermano de `test_aislamiento_caja.py`, mismo criterio: SQL crudo con el rol
`vendi_app` y nada de ORM, para que ningún `WHERE` amable dé un falso verde
sobre una policy que no filtra. Las tablas las crea la migración `0009_fiado`;
hasta que existen, TODOS estos tests fallan — que es el punto del paso TDD.
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
    "DELETE FROM fiado_abonos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM fiado_creditos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM clientes WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Un cliente por negocio, un crédito de 100.000 en T1 (con su venta y su
    sesión) y un abono de 30.000. Limpia antes y después: la suite es re-entrante."""
    engine = create_async_engine(pg_platform_url)
    ids = {
        "cliente_t1": uuid.uuid4(),
        "cliente_t2": uuid.uuid4(),
        "dispositivo": uuid.uuid4(),
        "sesion": uuid.uuid4(),
        "venta": uuid.uuid4(),
        "credito": uuid.uuid4(),
        "abono": uuid.uuid4(),
    }
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        for nombre, tenant in (("cliente_t1", T1), ("cliente_t2", T2)):
            await conn.execute(
                text("INSERT INTO clientes (id, tenant_id, nombre) VALUES (:c, :t, 'Don Carlos')"),
                {"c": ids[nombre], "t": tenant},
            )
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) VALUES (:s, :t, 'dueno', 0)"),
            {"s": ids["sesion"], "t": T1},
        )
        await conn.execute(
            text(
                "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                "medio_pago, total_centavos, cliente_id, creada_en_cliente, secuencia_dispositivo) "
                "VALUES (:v, :t, :d, :s, 1, 'fiado', 100000, :c, now(), 1)"
            ),
            {"v": ids["venta"], "t": T1, "d": ids["dispositivo"], "s": ids["sesion"], "c": ids["cliente_t1"]},
        )
        await conn.execute(
            text(
                "INSERT INTO fiado_creditos (id, tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, "
                "fecha_vencimiento, estado) "
                "VALUES (:cr, :t, :c, :v, 100000, 70000, CURRENT_DATE + 10, 'vigente')"
            ),
            {"cr": ids["credito"], "t": T1, "c": ids["cliente_t1"], "v": ids["venta"]},
        )
        await conn.execute(
            text(
                "INSERT INTO fiado_abonos (id, tenant_id, credito_id, sesion_caja_id, monto, metodo_pago, registrado_por) "
                "VALUES (:a, :t, :cr, :s, 30000, 'efectivo', 'dueno')"
            ),
            {"a": ids["abono"], "t": T1, "cr": ids["credito"], "s": ids["sesion"]},
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
async def test_select_solo_ve_las_tres_tablas_del_propio_tenant(sesion_t1):
    for tabla, esperado in (("clientes", 1), ("fiado_creditos", 1), ("fiado_abonos", 1)):
        filas = (await sesion_t1.execute(text(f"SELECT tenant_id FROM {tabla}"))).all()
        assert len(filas) == esperado, tabla
        assert all(f[0] == T1 for f in filas), tabla


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tabla, sentencia",
    [
        ("clientes", "INSERT INTO clientes (tenant_id, nombre) VALUES (:t, 'inyectado')"),
        (
            "fiado_creditos",
            "INSERT INTO fiado_creditos (tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, estado) "
            "VALUES (:t, :c, :v, 100, 100, 'vigente')",
        ),
        (
            "fiado_abonos",
            "INSERT INTO fiado_abonos (tenant_id, credito_id, monto, metodo_pago, registrado_por) "
            "VALUES (:t, :cr, 100, 'efectivo', 'dueno')",
        ),
    ],
)
async def test_insert_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1, semilla, tabla, sentencia):
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(
            text(sentencia),
            {"t": T2, "c": semilla["cliente_t2"], "v": semilla["venta"], "cr": semilla["credito"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_saldo_pendiente_no_puede_quedar_negativo(sesion_t1, semilla):
    """`ck_fiado_creditos_saldo_no_negativo`: el desfase es un error, no un
    dato malo (ADR-022). Es la red final del descuento del abono."""
    with pytest.raises(IntegrityError, match="ck_fiado_creditos_saldo_no_negativo"):
        await sesion_t1.execute(
            text("UPDATE fiado_creditos SET saldo_pendiente = -1 WHERE id = :cr"),
            {"cr": semilla["credito"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_saldo_no_puede_superar_el_monto_total(sesion_t1, semilla):
    with pytest.raises(IntegrityError, match="ck_fiado_creditos_saldo_acotado"):
        await sesion_t1.execute(
            text("UPDATE fiado_creditos SET saldo_pendiente = 100001 WHERE id = :cr"),
            {"cr": semilla["credito"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "estado",
    ["moroso", "pagado", "VIGENTE"],
)
async def test_el_estado_es_de_la_lista_cerrada(sesion_t1, semilla, estado):
    with pytest.raises(IntegrityError, match="ck_fiado_creditos_estado"):
        await sesion_t1.execute(
            text("UPDATE fiado_creditos SET estado = :e WHERE id = :cr"),
            {"e": estado, "cr": semilla["credito"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_una_venta_tiene_un_solo_credito(sesion_t1, semilla):
    """`ux_fiado_creditos_venta`: la red del doble crédito (decisión 5)."""
    with pytest.raises(IntegrityError, match="ux_fiado_creditos_venta"):
        await sesion_t1.execute(
            text(
                "INSERT INTO fiado_creditos (tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, estado) "
                "VALUES (:t, :c, :v, 100, 100, 'vigente')"
            ),
            {"t": T1, "c": semilla["cliente_t1"], "v": semilla["venta"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "monto,metodo",
    [
        (0, "efectivo"),  # un abono de cero no es abono
        (-5000, "efectivo"),  # el movimiento inverso NO es un abono negativo
        (1000, "nequi"),  # método fuera de la lista cerrada
    ],
)
async def test_los_checks_del_abono_rechazan_monto_y_metodo_invalidos(sesion_t1, semilla, monto, metodo):
    with pytest.raises(IntegrityError):
        await sesion_t1.execute(
            text(
                "INSERT INTO fiado_abonos (tenant_id, credito_id, monto, metodo_pago, registrado_por) "
                "VALUES (:t, :cr, :m, :mp, 'dueno')"
            ),
            {"t": T1, "cr": semilla["credito"], "m": monto, "mp": metodo},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_abono_exige_credito_existente(sesion_t1):
    """FK RESTRICT: ningún abono huérfano de crédito (ni siquiera contra un
    UUID al azar: Postgres no aplica RLS al verificar llaves foráneas)."""
    with pytest.raises(IntegrityError, match="fiado_abonos_credito_id_fkey"):
        await sesion_t1.execute(
            text(
                "INSERT INTO fiado_abonos (tenant_id, credito_id, monto, metodo_pago, registrado_por) "
                "VALUES (:t, :cr, 100, 'efectivo', 'dueno')"
            ),
            {"t": T1, "cr": uuid.uuid4()},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_limite_de_credito_no_es_negativo(sesion_t1, semilla):
    with pytest.raises(IntegrityError, match="ck_clientes_limite_no_negativo"):
        await sesion_t1.execute(
            text("UPDATE clientes SET limite_credito = -1 WHERE id = :c"),
            {"c": semilla["cliente_t1"]},
        )
    await sesion_t1.rollback()
