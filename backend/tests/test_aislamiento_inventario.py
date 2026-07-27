"""Aislamiento cross-tenant y reglas duras de las tablas del módulo inventario.

Hermano de `test_aislamiento_ventas.py`, mismo criterio: SQL crudo con el rol
`vendi_app` y nada de ORM, para que ningún `WHERE` amable del ORM dé un falso
verde sobre una policy que no filtra. Las tablas las crea la migración
`0007_inventario`; hasta que existe, TODOS estos tests fallan — que es el
punto del paso TDD.

Además del aislamiento, este archivo fija la decisión 6 del plan: el CHECK
de tipos de `movimientos_inventario` YA admite `compra`, `ajuste` y `merma`
desde la migración 0005 (la 0006 añadió `anulacion`), así que la 0007 no la
toca — y aquí se demuestra insertando los tres tipos de verdad.
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
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compra_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compras WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ajustes_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
)


@pytest_asyncio.fixture
async def semilla_de_los_dos_tenants(pg_platform_url: str):
    """Un producto, una compra con su ítem y un ajuste POR NEGOCIO, más tres
    movimientos del libro (compra, ajuste, merma) en T1 — la prueba de que el
    CHECK de tipos ya los admite. Limpia antes y después: la suite es
    re-entrante."""
    engine = create_async_engine(pg_platform_url)
    ids: dict[str, dict] = {}
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        for nombre, tenant in (("T1", T1), ("T2", T2)):
            producto = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                    "VALUES (:p, :t, 'Arroz 500g', 2500, 10)"
                ),
                {"p": producto, "t": tenant},
            )
            compra = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO compras (id, tenant_id, proveedor_nombre, total_centavos) "
                    "VALUES (:c, :t, 'Distribuidora La 33', 25000)"
                ),
                {"c": compra, "t": tenant},
            )
            await conn.execute(
                text(
                    "INSERT INTO compra_items (tenant_id, compra_id, producto_id, cantidad, "
                    "costo_unitario_centavos) VALUES (:t, :c, :p, 10, 2500)"
                ),
                {"t": tenant, "c": compra, "p": producto},
            )
            ajuste = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO ajustes_inventario (id, tenant_id, producto_id, tipo, "
                    "stock_contado, delta, motivo, aplicado_por, stock_resultante) "
                    "VALUES (:a, :t, :p, 'ajuste', 8, -2, 'Conteo de cierre', 'dueno', 8)"
                ),
                {"a": ajuste, "t": tenant, "p": producto},
            )
            ids[nombre] = {"producto": producto, "compra": compra, "ajuste": ajuste}
        # Los tres tipos del libro que este módulo estrena (decisión 6: el
        # CHECK ya los admite; si no, estos INSERT revientan aquí).
        await conn.execute(
            text(
                "INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                "producto_id) VALUES (:t, 'compra', 10, :r, :p)"
            ),
            {"t": T1, "r": ids["T1"]["compra"], "p": ids["T1"]["producto"]},
        )
        await conn.execute(
            text(
                "INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                "producto_id) VALUES (:t, 'ajuste', -2, :r, :p)"
            ),
            {"t": T1, "r": ids["T1"]["ajuste"], "p": ids["T1"]["producto"]},
        )
        await conn.execute(
            text(
                "INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                "producto_id) VALUES (:t, 'merma', -1, :r, :p)"
            ),
            {"t": T1, "r": uuid.uuid4(), "p": ids["T1"]["producto"]},
        )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def sesion_t1(pg_app_url: str, semilla_de_los_dos_tenants):
    """Sesión de `vendi_app` con el negocio T1 en contexto."""
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
@pytest.mark.parametrize("tabla", ["compras", "compra_items", "ajustes_inventario"])
async def test_select_solo_ve_las_filas_del_propio_tenant(sesion_t1, tabla):
    filas = (await sesion_t1.execute(text(f"SELECT tenant_id FROM {tabla}"))).all()
    assert len(filas) == 1
    assert filas[0][0] == T1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sentencia",
    [
        "INSERT INTO compras (tenant_id, proveedor_nombre, total_centavos) VALUES (:t, 'Proveedor X', 100)",
        "INSERT INTO ajustes_inventario (tenant_id, producto_id, tipo, stock_contado, delta, "
        "motivo, aplicado_por, stock_resultante) "
        "VALUES (:t, :p, 'ajuste', 1, 1, 'x', 'dueno', 1)",
    ],
)
async def test_insert_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1, semilla_de_los_dos_tenants, sentencia):
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(text(sentencia), {"t": T2, "p": semilla_de_los_dos_tenants["T1"]["producto"]})
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_movimiento_de_una_compra_no_se_puede_aplicar_dos_veces(sesion_t1, semilla_de_los_dos_tenants):
    """La red de idempotencia de ADR-020 también cubre las compras: el
    reintento del mismo movimiento de entrada choca contra
    `ux_movimientos_origen` — la base lo hace imposible, no el código."""
    ids = semilla_de_los_dos_tenants["T1"]
    with pytest.raises(IntegrityError, match="ux_movimientos_origen"):
        await sesion_t1.execute(
            text(
                "INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                "producto_id) VALUES (:t, 'compra', 10, :r, :p)"
            ),
            {"t": T1, "r": ids["compra"], "p": ids["producto"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_check_de_tipos_ya_admite_compra_ajuste_y_merma_sin_migrarla(sesion_t1):
    """Decisión 6: la 0005 dejó el CHECK con los cinco tipos y la 0007 no lo
    recrea. El fixture ya insertó los tres tipos nuevos en T1; si la
    constraint no los admitiera, este test ni siquiera arrancaría."""
    tipos = (
        (
            await sesion_t1.execute(
                text("SELECT DISTINCT tipo FROM movimientos_inventario WHERE tipo IN ('compra', 'ajuste', 'merma')")
            )
        )
        .scalars()
        .all()
    )
    assert sorted(tipos) == ["ajuste", "compra", "merma"]


@pytest.mark.asyncio
async def test_un_ajuste_con_la_forma_equivocada_no_cabe(sesion_t1, semilla_de_los_dos_tenants):
    """`ck_ajustes_forma`: tipo 'ajuste' exige `stock_contado` y prohíbe
    `cantidad`; tipo 'merma', al revés. La forma la hace cumplir la base."""
    ids = semilla_de_los_dos_tenants["T1"]
    with pytest.raises(IntegrityError, match="ck_ajustes_forma"):
        await sesion_t1.execute(
            text(
                "INSERT INTO ajustes_inventario (tenant_id, producto_id, tipo, cantidad, delta, "
                "motivo, aplicado_por, stock_resultante) "
                "VALUES (:t, :p, 'ajuste', 2, -2, 'forma rota', 'dueno', 8)"
            ),
            {"t": T1, "p": ids["producto"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_una_merma_de_cantidad_cero_no_cabe(sesion_t1, semilla_de_los_dos_tenants):
    ids = semilla_de_los_dos_tenants["T1"]
    with pytest.raises(IntegrityError, match="ck_ajustes_cantidad_positiva"):
        await sesion_t1.execute(
            text(
                "INSERT INTO ajustes_inventario (tenant_id, producto_id, tipo, cantidad, delta, "
                "motivo, aplicado_por, stock_resultante) "
                "VALUES (:t, :p, 'merma', 0, 0, 'nada se dañó', 'dueno', 10)"
            ),
            {"t": T1, "p": ids["producto"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_un_ajuste_de_delta_cero_si_cabe(sesion_t1, semilla_de_los_dos_tenants):
    """El conteo que CUADRA es legítimo y frecuente: `delta` admite 0 (la
    fila del ajuste es la prueba de idempotencia aunque no haya movimiento,
    decisión 5). Lo que no admite cero es el libro (`ck_movimientos_cantidad_no_cero`)."""
    ids = semilla_de_los_dos_tenants["T1"]
    await sesion_t1.execute(
        text(
            "INSERT INTO ajustes_inventario (tenant_id, producto_id, tipo, stock_contado, delta, "
            "motivo, aplicado_por, stock_resultante) "
            "VALUES (:t, :p, 'ajuste', 10, 0, 'Cuadró el conteo', 'dueno', 10)"
        ),
        {"t": T1, "p": ids["producto"]},
    )
    await sesion_t1.rollback()
