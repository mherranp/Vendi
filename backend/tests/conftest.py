"""Fixtures compartidas de la suite del backend.

Los tests marcados `integration` necesitan el Postgres del compose levantado
(`bash scripts/dev.sh`). Los demás corren en seco.

Sobre la conexión: los tests corren en el host, no dentro de un contenedor, así
que hablan con Postgres por el puerto que el compose publica en loopback
(`127.0.0.1:5432`). Esto **no** contradice la regla de "probar siempre por el
dominio y a través de Traefik": Traefik enruta HTTP, y Postgres no habla HTTP.
Lo que sí va por el dominio es todo lo que es HTTP —Keycloak por
`https://accounts.vendi.local`, la API por `https://api.vendi.local`— y así
está escrito en los tests que los usan.
"""

from __future__ import annotations

import os
import pathlib

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2, TABLA_PRUEBA
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _cargar_env() -> None:
    """Lee el `.env` de la raíz del repo si las variables no están ya puestas.

    Sin esto, `uv run pytest` desde `backend/` no ve las contraseñas y los tests
    de integración fallarían con un error de autenticación que parece un
    problema de Postgres y no lo es.
    """
    raiz = pathlib.Path(__file__).resolve().parents[2]
    archivo = raiz / ".env"
    if not archivo.exists():
        return
    for linea in archivo.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip())


_cargar_env()

PG_HOST = os.getenv("VENDI_TEST_PG_HOST", "127.0.0.1")
PG_PORT = os.getenv("VENDI_TEST_PG_PORT", "5432")
PG_DB = os.getenv("VENDI_TEST_PG_DB", "vendi")


def _dsn(rol: str, password_env: str) -> str:
    clave = os.getenv(password_env, "")
    return f"postgresql+asyncpg://{rol}:{clave}@{PG_HOST}:{PG_PORT}/{PG_DB}"


@pytest.fixture(scope="session")
def pg_app_url() -> str:
    """DSN del rol `vendi_app`: sin BYPASSRLS. Es el que usa la API."""
    return _dsn("vendi_app", "VENDI_APP_DB_PASSWORD")


@pytest.fixture(scope="session")
def pg_platform_url() -> str:
    """DSN del rol `vendi_platform`: con BYPASSRLS. Es el de Alembic y el worker."""
    return _dsn("vendi_platform", "VENDI_PLATFORM_DB_PASSWORD")


@pytest_asyncio.fixture
async def ventas_de_prueba(pg_platform_url: str):
    """Crea `ventas_de_prueba` con la policy del spike y una fila por negocio.

    Se crea y se destruye por test **a propósito**, no por sesión: la superficie
    de ataque de QA exige que la suite sea re-entrante (correr `pytest` dos
    veces seguidas contra el mismo compose sin limpiar a mano). Un `DROP TABLE
    IF EXISTS` al principio y otro al final lo garantizan aunque una corrida
    anterior se haya muerto a mitad.

    El DDL va con `vendi_platform` porque `vendi_app` no tiene `CREATE` en
    `public` — verificado en el escenario J del spike de RLS.
    """
    engine = create_async_engine(pg_platform_url, poolclass=None)
    ddl = f"""
    DROP TABLE IF EXISTS {TABLA_PRUEBA};
    CREATE TABLE {TABLA_PRUEBA} (
        id        serial PRIMARY KEY,
        tenant_id uuid NOT NULL,
        total     numeric NOT NULL DEFAULT 0
    );
    CREATE INDEX ix_{TABLA_PRUEBA}_tenant_id ON {TABLA_PRUEBA} (tenant_id);
    GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLA_PRUEBA} TO vendi_app;
    GRANT USAGE, SELECT ON SEQUENCE {TABLA_PRUEBA}_id_seq TO vendi_app;
    ALTER TABLE {TABLA_PRUEBA} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {TABLA_PRUEBA} FORCE  ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON {TABLA_PRUEBA}
      USING      (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid);
    """
    async with engine.begin() as conn:
        for sentencia in filter(None, (x.strip() for x in ddl.split(";"))):
            await conn.execute(text(sentencia))
        await conn.execute(
            text(f"INSERT INTO {TABLA_PRUEBA} (tenant_id, total) VALUES (:t, 100)"),
            {"t": T1},
        )
        await conn.execute(
            text(f"INSERT INTO {TABLA_PRUEBA} (tenant_id, total) VALUES (:t, 200)"),
            {"t": T2},
        )
    try:
        yield TABLA_PRUEBA
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {TABLA_PRUEBA}"))
        await engine.dispose()
