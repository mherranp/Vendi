"""Aislamiento cross-tenant y unicidad del EAN sobre la tabla real `productos`.

Hermano de `test_cross_tenant_isolation.py`, mismo criterio: SQL crudo con el
rol `vendi_app` y nada de ORM, para que ningún `WHERE` amable del ORM dé un
falso verde sobre una policy que no filtra. La tabla la crea la migración
`0004_catalogo`; hasta que existe, TODOS estos tests fallan — que es el punto
del paso TDD.
"""

from __future__ import annotations

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


@pytest_asyncio.fixture
async def productos_de_prueba(pg_platform_url: str):
    """Una fila por negocio, con el MISMO EAN en los dos (válido: el índice
    único es por tenant). Limpia antes y después: la suite es re-entrante."""
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM productos WHERE tenant_id = ANY(:ids)"), {"ids": [T1, T2]})
        for tenant in (T1, T2):
            await conn.execute(
                text(
                    "INSERT INTO productos (tenant_id, nombre, codigo_barras) VALUES (:t, 'Arroz 500g', '770000000001')"
                ),
                {"t": tenant},
            )
    try:
        yield
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM productos WHERE tenant_id = ANY(:ids)"), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def sesion_t1(pg_app_url: str, productos_de_prueba):
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
async def test_select_solo_ve_los_productos_del_propio_tenant(sesion_t1):
    filas = (await sesion_t1.execute(text("SELECT tenant_id, nombre FROM productos"))).all()
    assert len(filas) == 1
    assert filas[0][0] == T1


@pytest.mark.asyncio
async def test_update_no_toca_productos_ajenos(sesion_t1):
    resultado = await sesion_t1.execute(text("UPDATE productos SET precio_venta = 2500"))
    assert resultado.rowcount == 1, "el UPDATE sin WHERE tocó productos de otro negocio"


@pytest.mark.asyncio
async def test_insert_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1):
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(
            text("INSERT INTO productos (tenant_id, nombre) VALUES (:t, 'Fuga')"),
            {"t": T2},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_mismo_ean_cabe_en_dos_tenants(pg_platform_url: str, productos_de_prueba):
    """El fixture ya insertó el EAN '770000000001' en T1 y en T2. Si el índice
    único parcial fuera global en vez de por tenant, el fixture no habría
    podido sembrar y este test no correría."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            cuantos = (
                await conn.execute(
                    text("SELECT count(*) FROM productos WHERE codigo_barras = '770000000001'"),
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert cuantos == 2


@pytest.mark.asyncio
async def test_el_ean_duplicado_en_el_mismo_tenant_se_rechaza(sesion_t1):
    with pytest.raises(IntegrityError, match="ux_productos_ean"):
        await sesion_t1.execute(
            text("INSERT INTO productos (tenant_id, nombre, codigo_barras) VALUES (:t, 'Otro arroz', '770000000001')"),
            {"t": T1},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_ean_queda_libre_al_liberarlo_en_el_borrado_logico(sesion_t1):
    """Decisión 3 del plan: el índice firmado en ADR-019 NO excluye filas
    borradas, así que el borrado lógico anula `codigo_barras` para liberar el
    EAN. Este test fija que, liberado, el EAN se puede reusar en el mismo
    tenant."""
    await sesion_t1.execute(
        text("UPDATE productos SET deleted_at = now(), codigo_barras = NULL WHERE codigo_barras = '770000000001'")
    )
    await sesion_t1.execute(
        text("INSERT INTO productos (tenant_id, nombre, codigo_barras) VALUES (:t, 'Arroz nuevo', '770000000001')"),
        {"t": T1},
    )
    await sesion_t1.rollback()
