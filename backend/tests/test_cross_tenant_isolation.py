"""Aislamiento cross-tenant en SQL directo, con el rol `vendi_app`.

Éste y sus dos hermanos (`test_tenant_guc_reset_hook.py` y
`test_rls_coverage.py`) son los tres candados del aislamiento. No prueban
código de Vendi: prueban que **Postgres** hace lo que creemos que hace, con
nuestro rol, nuestra policy y nuestro GUC. Si alguno de los tres falla, no hay
producto que entregar.

Deliberadamente en SQL crudo y no por el ORM: el ORM podría estar añadiendo un
`WHERE tenant_id = ...` por su cuenta y dar un falso verde sobre una policy que
en realidad no filtra nada.
"""

from __future__ import annotations

import pytest
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration


@pytest.fixture
async def sesion_t1(pg_app_url, ventas_de_prueba):
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
async def test_select_solo_ve_el_propio_tenant(sesion_t1, ventas_de_prueba):
    filas = (await sesion_t1.execute(text(f"SELECT tenant_id, total FROM {ventas_de_prueba}"))).all()
    assert len(filas) == 1
    assert filas[0][0] == T1


@pytest.mark.asyncio
async def test_select_for_update_no_bloquea_filas_ajenas(sesion_t1, ventas_de_prueba):
    """`FOR UPDATE` es un camino distinto en el planificador. También filtra.

    Importa más de lo que parece: si `FOR UPDATE` viera la fila ajena, un
    `SELECT ... FOR UPDATE` de un negocio podría **bloquear** filas de otro y
    convertir un pico de carga de un tenant en una caída del vecino, aunque
    nunca llegara a leer sus datos.
    """
    filas = (await sesion_t1.execute(text(f"SELECT id FROM {ventas_de_prueba} FOR UPDATE"))).scalars().all()
    assert len(filas) == 1


@pytest.mark.asyncio
async def test_update_no_toca_filas_ajenas(sesion_t1, ventas_de_prueba):
    resultado = await sesion_t1.execute(text(f"UPDATE {ventas_de_prueba} SET total = total + 1"))
    assert resultado.rowcount == 1, "el UPDATE sin WHERE tocó filas de otro negocio"


@pytest.mark.asyncio
async def test_delete_returning_no_devuelve_filas_ajenas(sesion_t1, ventas_de_prueba):
    filas = (await sesion_t1.execute(text(f"DELETE FROM {ventas_de_prueba} RETURNING tenant_id"))).scalars().all()
    assert filas == [T1], "el DELETE ... RETURNING alcanzó filas de otro negocio"
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_insert_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1, ventas_de_prueba):
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(
            text(f"INSERT INTO {ventas_de_prueba} (tenant_id, total) VALUES (:t, 1)"),
            {"t": T2},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_update_que_regala_la_fila_a_otro_tenant_lo_bloquea_with_check(sesion_t1, ventas_de_prueba):
    """El ataque que `USING` por sí solo NO cubre.

    `USING` decide qué filas ve la consulta; `WITH CHECK`, cómo pueden quedar
    tras escribirlas. Sin `WITH CHECK`, este `UPDATE` es legal: la fila es mía
    al leerla, y al escribirla pasa a ser de otro. Es una fuga de datos hacia
    afuera —regalar una venta al negocio vecino— y no la detecta ninguna prueba
    de lectura.
    """
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(text(f"UPDATE {ventas_de_prueba} SET tenant_id = :t"), {"t": T2})
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_join_entre_dos_tablas_de_tenant_filtra_las_dos(pg_app_url, pg_platform_url):
    """Un JOIN aplica la policy a CADA tabla, no solo a la primera.

    Es el caso que más fácilmente se asume sin comprobar: si la policy solo
    mordiera la tabla del `FROM`, un JOIN sería la forma trivial de leer los
    datos del vecino.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    plataforma = create_async_engine(pg_platform_url)
    ddl = """
    DROP TABLE IF EXISTS lineas_de_prueba;
    DROP TABLE IF EXISTS cabeceras_de_prueba;
    CREATE TABLE cabeceras_de_prueba (
        id serial PRIMARY KEY, tenant_id uuid NOT NULL, nombre text NOT NULL);
    CREATE TABLE lineas_de_prueba (
        id serial PRIMARY KEY, tenant_id uuid NOT NULL,
        cabecera_id int NOT NULL, importe numeric NOT NULL);
    CREATE INDEX ix_cabeceras_de_prueba_tenant_id ON cabeceras_de_prueba (tenant_id);
    CREATE INDEX ix_lineas_de_prueba_tenant_id ON lineas_de_prueba (tenant_id);
    GRANT SELECT, INSERT, UPDATE, DELETE ON cabeceras_de_prueba, lineas_de_prueba TO vendi_app;
    ALTER TABLE cabeceras_de_prueba ENABLE ROW LEVEL SECURITY;
    ALTER TABLE cabeceras_de_prueba FORCE  ROW LEVEL SECURITY;
    ALTER TABLE lineas_de_prueba    ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lineas_de_prueba    FORCE  ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON cabeceras_de_prueba
      USING      (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid);
    CREATE POLICY tenant_isolation ON lineas_de_prueba
      USING      (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid);
    """
    try:
        async with plataforma.begin() as conn:
            for sentencia in filter(None, (x.strip() for x in ddl.split(";"))):
                await conn.execute(text(sentencia))
            for tenant in (T1, T2):
                cab = (
                    await conn.execute(
                        text("INSERT INTO cabeceras_de_prueba (tenant_id, nombre) VALUES (:t, 'x') RETURNING id"),
                        {"t": tenant},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO lineas_de_prueba (tenant_id, cabecera_id, importe) VALUES (:t, :c, 10)"),
                    {"t": tenant, "c": cab},
                )

        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                filas = (
                    await s.execute(
                        text(
                            "SELECT c.tenant_id, l.tenant_id "
                            "FROM cabeceras_de_prueba c "
                            "JOIN lineas_de_prueba l ON l.cabecera_id = c.id"
                        )
                    )
                ).all()
                assert len(filas) == 1, "el JOIN devolvió filas de más de un negocio"
                assert filas[0] == (T1, T1)
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()
    finally:
        async with plataforma.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS lineas_de_prueba"))
            await conn.execute(text("DROP TABLE IF EXISTS cabeceras_de_prueba"))
        await plataforma.dispose()


@pytest.mark.asyncio
async def test_vendi_app_no_puede_escalar_a_vendi_platform(pg_app_url, ventas_de_prueba):
    """`SET ROLE` se evalúa contra el *session user*, y `vendi_app` no es miembro."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as s:
            with pytest.raises((DBAPIError, ProgrammingError), match="permission denied"):
                await s.execute(text("SET ROLE vendi_platform"))
            await s.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_vendi_app_no_puede_desactivar_rls(pg_app_url, ventas_de_prueba):
    """Si `vendi_app` pudiera hacer `DISABLE ROW LEVEL SECURITY`, todo lo demás sobra."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as s:
            for sentencia in (
                f"ALTER TABLE {ventas_de_prueba} DISABLE ROW LEVEL SECURITY",
                f"ALTER TABLE {ventas_de_prueba} NO FORCE ROW LEVEL SECURITY",
                f"DROP POLICY tenant_isolation ON {ventas_de_prueba}",
            ):
                with pytest.raises((DBAPIError, ProgrammingError), match="must be owner"):
                    await s.execute(text(sentencia))
                await s.rollback()
    finally:
        await engine.dispose()
