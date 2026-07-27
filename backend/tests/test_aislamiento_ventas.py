"""Aislamiento cross-tenant y unicidades duras de las tablas del módulo ventas.

Hermano de `test_aislamiento_productos.py`, mismo criterio: SQL crudo con el
rol `vendi_app` y nada de ORM, para que ningún `WHERE` amable del ORM dé un
falso verde sobre una policy que no filtra. Las tablas las crea la migración
`0005_ventas`; hasta que existe, TODOS estos tests fallan — que es el punto
del paso TDD.
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
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
)


@pytest_asyncio.fixture
async def ventas_de_los_dos_tenants(pg_platform_url: str):
    """Un dispositivo, una sesión, un producto, una venta con su ítem y su
    movimiento POR NEGOCIO — con el MISMO consecutivo en los dos (válido: la
    unicidad es por tenant+dispositivo). Limpia antes y después: la suite es
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
            dispositivo = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
                {"d": dispositivo, "t": tenant},
            )
            sesion = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por) VALUES (:s, :t, 'dueno')"),
                {"s": sesion, "t": tenant},
            )
            venta = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, "
                    "consecutivo_local, medio_pago, total_centavos, creada_en_cliente, "
                    "secuencia_dispositivo) "
                    "VALUES (:v, :t, :d, :s, 1, 'efectivo', 2500, now(), 1)"
                ),
                {"v": venta, "t": tenant, "d": dispositivo, "s": sesion},
            )
            await conn.execute(
                text(
                    "INSERT INTO ventas_items (tenant_id, venta_id, producto_id, cantidad, "
                    "precio_unitario_centavos) VALUES (:t, :v, :p, 1, 2500)"
                ),
                {"t": tenant, "v": venta, "p": producto},
            )
            await conn.execute(
                text(
                    "INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                    "producto_id) VALUES (:t, 'venta', -1, :v, :p)"
                ),
                {"t": tenant, "v": venta, "p": producto},
            )
            ids[nombre] = {"dispositivo": dispositivo, "sesion": sesion, "venta": venta, "producto": producto}
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def sesion_t1(pg_app_url: str, ventas_de_los_dos_tenants):
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
@pytest.mark.parametrize(
    "tabla",
    ["dispositivos", "caja_sesiones", "ventas", "ventas_items", "movimientos_inventario"],
)
async def test_select_solo_ve_las_filas_del_propio_tenant(sesion_t1, tabla):
    filas = (await sesion_t1.execute(text(f"SELECT tenant_id FROM {tabla}"))).all()
    assert len(filas) == 1
    assert filas[0][0] == T1


@pytest.mark.asyncio
async def test_insert_de_venta_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1, ventas_de_los_dos_tenants):
    ids = ventas_de_los_dos_tenants["T2"]
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(
            text(
                "INSERT INTO ventas (tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                "medio_pago, total_centavos, creada_en_cliente, secuencia_dispositivo) "
                "VALUES (:t, :d, :s, 99, 'efectivo', 100, now(), 99)"
            ),
            {"t": T2, "d": ids["dispositivo"], "s": ids["sesion"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_consecutivo_se_repite_entre_tenants_pero_no_en_el_mismo_dispositivo(
    sesion_t1, ventas_de_los_dos_tenants
):
    """El fixture ya sembró el consecutivo 1 en T1 y en T2. Repetirlo en el
    mismo dispositivo de T1 revienta contra `ux_ventas_consecutivo`."""
    ids = ventas_de_los_dos_tenants["T1"]
    with pytest.raises(IntegrityError, match="ux_ventas_consecutivo"):
        await sesion_t1.execute(
            text(
                "INSERT INTO ventas (tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                "medio_pago, total_centavos, creada_en_cliente, secuencia_dispositivo) "
                "VALUES (:t, :d, :s, 1, 'efectivo', 100, now(), 2)"
            ),
            {"t": T1, "d": ids["dispositivo"], "s": ids["sesion"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_la_segunda_aplicacion_del_mismo_movimiento_choca_con_el_indice_unico(
    sesion_t1, ventas_de_los_dos_tenants
):
    """La red de idempotencia de ADR-020: `(tenant_id, tipo, referencia_id,
    producto_id)`. El reintento del mismo movimiento de salida no puede
    descontar dos veces: la base lo hace imposible."""
    ids = ventas_de_los_dos_tenants["T1"]
    with pytest.raises(IntegrityError, match="ux_movimientos_origen"):
        await sesion_t1.execute(
            text(
                "INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                "producto_id) VALUES (:t, 'venta', -1, :v, :p)"
            ),
            {"t": T1, "v": ids["venta"], "p": ids["producto"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_una_segunda_sesion_abierta_en_el_mismo_tenant_no_cabe(sesion_t1):
    """La regla «una caja por tienda» de ADR-021 la hace cumplir el índice
    único parcial, no el código: la apertura implícita del sync se apoya en él."""
    with pytest.raises(IntegrityError, match="ux_caja_sesion_abierta"):
        await sesion_t1.execute(
            text("INSERT INTO caja_sesiones (tenant_id, abierta_por) VALUES (:t, 'otro')"),
            {"t": T1},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_una_sesion_cerrada_si_permite_abrir_otra(sesion_t1):
    await sesion_t1.execute(text("UPDATE caja_sesiones SET estado = 'cerrada', cerrada_en = now()"))
    await sesion_t1.execute(
        text("INSERT INTO caja_sesiones (tenant_id, abierta_por) VALUES (:t, 'otro')"),
        {"t": T1},
    )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_stock_puede_quedar_negativo(sesion_t1, ventas_de_los_dos_tenants):
    """ADR-020: el negativo es un estado legítimo (la tienda ya vendió
    físicamente esa unidad); ninguna constraint lo prohíbe."""
    ids = ventas_de_los_dos_tenants["T1"]
    await sesion_t1.execute(
        text("UPDATE productos SET stock_actual = stock_actual - 50 WHERE id = :p"),
        {"p": ids["producto"]},
    )
    stock = (await sesion_t1.execute(text("SELECT stock_actual FROM productos"))).scalar_one()
    assert stock < 0
    await sesion_t1.rollback()
