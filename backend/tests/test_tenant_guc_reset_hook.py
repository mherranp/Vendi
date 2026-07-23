"""El hook de checkout neutraliza el GUC al sacar la conexión del pool.

Equivalente del `test_search_path_reset_hook.py` de BaseSaaS, con el GUC de
tenant en el sitio del `search_path`.

Qué defiende exactamente: `SET LOCAL` muere con la transacción, pero un `SET`
de sesión —escrito a mano, o dejado por un `SET LOCAL` fuera de transacción, que
Postgres degrada a sesión con un WARNING— sobrevive a la devolución de la
conexión al pool. La siguiente petición que reciba esa conexión física
heredaría el negocio anterior. Sería una fuga cross-tenant sin ninguna línea de
código sospechosa a la vista: el bug estaría a treinta peticiones de distancia
de su síntoma.
"""

from __future__ import annotations

import pytest
from datos_de_prueba import T1
from sqlalchemy import text

from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_guc_de_sesion_no_sobrevive_al_pool(pg_app_url, ventas_de_prueba):
    """Ensucia el GUC a nivel de SESIÓN, devuelve la conexión, y la vuelve a sacar."""
    # pool_size=1 y max_overflow=0: la conexión que se devuelve es exactamente
    # la que se vuelve a sacar. Sin esto el test daría verde por casualidad, al
    # tocarle una conexión distinta.
    engine = create_engine(pg_app_url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET vendi.tenant_id = '{T1}'")
            leido = (await conn.execute(text("SELECT current_setting('vendi.tenant_id', true)"))).scalar()
            assert leido == str(T1), "la fuga simulada no llegó a producirse"
        # Al salir del `async with`, la conexión vuelve al pool.

        async with engine.connect() as conn:
            leido = (await conn.execute(text("SELECT current_setting('vendi.tenant_id', true)"))).scalar()
            assert leido in ("", None), (
                f"el GUC sobrevivió al checkout del pool (valor={leido!r}): la siguiente "
                "petición heredaría el negocio de la anterior"
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_conexion_contaminada_no_filtra_filas(pg_app_url, ventas_de_prueba):
    """La versión con datos: tras la fuga y el reciclado, cero filas sin tenant."""
    engine = create_engine(pg_app_url, pool_size=1, max_overflow=0)
    factory = create_session_factory(engine)
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET vendi.tenant_id = '{T1}'")
            filas = (await conn.execute(text(f"SELECT count(*) FROM {ventas_de_prueba}"))).scalar()
            assert filas == 1, "la fuga simulada no llegó a producirse"

        # Sin tenant en el ContextVar: la sesión no siembra nada y el hook ya
        # limpió. Debe ver cero.
        async with factory() as s:
            assert (await s.execute(text(f"SELECT count(*) FROM {ventas_de_prueba}"))).scalar() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_guc_nunca_definido_tambien_da_cero_filas(pg_app_url, ventas_de_prueba):
    """El tercer estado del GUC: jamás definido en la sesión.

    Los tres estados posibles —nunca definido (NULL), `''` tras el hook, y
    `''` tras un RESET— tienen que converger en cero filas. Es lo que hace que
    `NULLIF(current_setting(...), '')` sea fail-closed de verdad y no solo en el
    camino que probamos.
    """
    engine = create_engine(pg_app_url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("RESET vendi.tenant_id")
            assert (await conn.execute(text(f"SELECT count(*) FROM {ventas_de_prueba}"))).scalar() == 0
    finally:
        await engine.dispose()
