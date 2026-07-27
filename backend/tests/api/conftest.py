"""Fixtures de los tests de la API. Los dobles y constructores están en `ayudas.py`."""

from __future__ import annotations

import pytest
import pytest_asyncio
from ayudas import PREFIJO_PRUEBA, app_de_prueba, settings_de_prueba
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
def app_sin_base():
    """App de humo: los DSN no conectan, así que solo sirve para rutas que no
    tocan la base (salud, métricas, la cadena de middlewares y sus 401/403)."""
    aplicacion, validador, keycloak = app_de_prueba()
    with TestClient(aplicacion, raise_server_exceptions=False) as cliente:
        yield cliente, validador, keycloak


# --- Base de datos real (tests `integration`) --------------------------------


@pytest_asyncio.fixture
async def limpiar_tenants_de_prueba(pg_platform_url: str):
    """Borra a conciencia lo que dejen los tests, antes y después.

    Antes **y** después: si una corrida anterior se murió a mitad, la siguiente
    tiene que arrancar limpia sin intervención manual.
    """
    engine = create_async_engine(pg_platform_url)

    async def _borrar() -> None:
        async with engine.begin() as conn:
            ids = (
                (await conn.execute(text("SELECT id FROM tenants WHERE nombre LIKE :p"), {"p": PREFIJO_PRUEBA + "%"}))
                .scalars()
                .all()
            )
            if ids:
                await conn.execute(
                    text("DELETE FROM audit_events WHERE tenant_id = ANY(:ids)"),
                    {"ids": list(ids)},
                )
                await conn.execute(
                    text("DELETE FROM outbox_messages WHERE payload->>'tenant_id' = ANY(:ids)"),
                    {"ids": [str(i) for i in ids]},
                )
                for tabla in ("movimientos_inventario", "ventas_items", "ventas", "caja_sesiones", "dispositivos"):
                    await conn.execute(
                        text(f"DELETE FROM {tabla} WHERE tenant_id = ANY(:ids)"),
                        {"ids": list(ids)},
                    )
                await conn.execute(
                    text("DELETE FROM productos WHERE tenant_id = ANY(:ids)"),
                    {"ids": list(ids)},
                )
            await conn.execute(text("DELETE FROM tenants WHERE nombre LIKE :p"), {"p": PREFIJO_PRUEBA + "%"})

    await _borrar()
    try:
        yield
    finally:
        await _borrar()
        await engine.dispose()


@pytest.fixture
def app_con_base(pg_app_url: str, pg_platform_url: str, limpiar_tenants_de_prueba):
    """La aplicación contra el PostgreSQL del compose, con los DOS roles reales.

    `database_url` va al rol `vendi_app` (sin BYPASSRLS) a propósito: es lo que
    hace que el candado de arranque `_comprobar_rol_de_la_api` se ejerza de
    verdad en cada test de esta suite, y no solo en producción.
    """
    settings = settings_de_prueba(database_url=pg_app_url, platform_database_url=pg_platform_url)
    aplicacion, validador, keycloak = app_de_prueba(settings)
    with TestClient(aplicacion, raise_server_exceptions=False) as cliente:
        yield cliente, validador, keycloak
