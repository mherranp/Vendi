"""Creación del engine asíncrono con el candado de higiene de conexión.

Cosechado de `base_saas.db.engine`. El hook de checkout cambia de objetivo: en
BaseSaaS reseteaba `search_path` (donde vivía el tenant); en Vendi neutraliza el
GUC `vendi.tenant_id`.
"""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import create_async_engine as _create_engine

# Nombre del GUC de tenant. Un solo sitio: lo usan el hook de checkout, el
# listener de sesión y el SQL de la policy (`vendi_core.db.rls`).
GUC_TENANT = "vendi.tenant_id"


def create_engine(url: str, pool_size: int = 5, max_overflow: int = 10, echo: bool = False) -> AsyncEngine:
    """Crea un `AsyncEngine` con el hook de seguridad cross-tenant instalado.

    El hook ejecuta `SET vendi.tenant_id = ''` en cada conexión de Postgres al
    sacarla del pool, de forma que un handler que se olvide de sembrar su propio
    tenant no pueda heredar el del request anterior que usó esa conexión.
    SQLite no tiene GUCs y la instalación es un no-op.

    SQLite tampoco acepta pool_size/max_overflow, así que esos kwargs se omiten
    cuando la URL usa un driver sqlite.
    """
    is_sqlite = url.startswith("sqlite")
    kwargs: dict = {"echo": echo, "pool_pre_ping": True}
    if not is_sqlite:
        kwargs["pool_size"] = pool_size
        kwargs["max_overflow"] = max_overflow
    engine = _create_engine(url, **kwargs)
    _instalar_reset_del_guc_de_tenant(engine)
    return engine


def _instalar_reset_del_guc_de_tenant(engine: AsyncEngine) -> None:
    if not engine.url.drivername.startswith("postgresql"):
        return

    @event.listens_for(engine.sync_engine, "checkout")
    def _reset(dbapi_conn, conn_record, conn_proxy):  # noqa: ANN001, ARG001
        cursor = dbapi_conn.cursor()
        try:
            # `SET` a cadena vacía, no `RESET`. El spike de RLS (escenarios E/N)
            # midió que en PG 17 `RESET` sobre un GUC personalizado tampoco
            # falla y también deja `''`, así que la elección no es por
            # corrección sino por disciplina: `SET ''` deja el GUC en un estado
            # explícito y observable, idéntico venga la conexión de donde venga,
            # y es un solo camino de código sin ramas según el historial de la
            # sesión. La policy usa `NULLIF(..., '')`, que neutraliza tanto `''`
            # como NULL.
            #
            # Esto es un `SET` de sesión a propósito —no `SET LOCAL`—: en el
            # checkout no hay transacción de request abierta, y lo que se quiere
            # limpiar es justamente una fuga a nivel de sesión.
            cursor.execute(f"SET {GUC_TENANT} = ''")
        finally:
            cursor.close()


async def dispose_engine(engine: AsyncEngine) -> None:
    await engine.dispose()
