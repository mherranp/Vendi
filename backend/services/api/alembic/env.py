"""Entorno de Alembic — una sola pasada, un solo schema.

Diferencia estructural con BaseSaaS, que es de donde viene este archivo: allí el
`env.py` recorría los schemas de todos los inquilinos y aplicaba cada migración
una vez por cada uno, con toda la maquinaria de `search_path` y de "¿qué pasa si
la migración falla en el inquilino 47 de 200?". Aquí no hay bucle: un schema
regional, una pasada, una transacción.

**El rol importa y no es negociable.** Alembic corre con `vendi_platform`
(owner de las tablas **y** `BYPASSRLS`), y el DSN lo fija `scripts/migrate.sh`.
El motivo lo midió el escenario D del spike de RLS: bajo `FORCE ROW LEVEL
SECURITY`, hasta el owner de la tabla ve cero filas si no tiene `BYPASSRLS`. Una
migración de backfill corrida con `vendi_app` no fallaría — actualizaría cero
filas y diría "OK".
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importar los modelos registra sus tablas en `Base.metadata`, que es lo que
# `--autogenerate` (y `alembic check`, el candado D-17 del CI) compara contra
# la base. Los de la propia API van también: sin ellos aquí, `alembic check`
# propondría **borrar** sus tablas por no encontrarlas en el metadata — que
# es exactamente lo que hacía con `productos`, `ventas` y demás hasta que el
# candado lo puso en evidencia. La lista es la misma que registra
# `backend/tests/test_rls_coverage.py`: un modelo nuevo se importa en ambos
# sitios (el candado de RLS lo exige allí; aquí lo delata el propio check).
from app.modules.caja.models import CajaMovimiento  # noqa: F401
from app.modules.catalogo.models import Producto  # noqa: F401
from app.modules.fiado.models import Cliente, FiadoAbono, FiadoCredito  # noqa: F401
from app.modules.inventario.models import AjusteInventario, Compra, CompraItem  # noqa: F401
from app.modules.tenants.models import Tenant  # noqa: F401
from app.modules.ventas.models import CajaSesion, Dispositivo, MovimientoInventario, Venta, VentaItem  # noqa: F401
from vendi_core.audit.models import AuditLog  # noqa: F401
from vendi_core.db.base import Base
from vendi_core.files.models import File  # noqa: F401
from vendi_core.messaging.outbox import OutboxMessage  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL no está definida. Alembic tiene que correr con el DSN de "
            "vendi_platform: usa `bash scripts/migrate.sh`, que ya lo fija."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:  # noqa: ANN001
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # Sin esto, `--autogenerate` propondría borrar la tabla `tenants` y
        # cualquier otra que no esté declarada como modelo de SQLAlchemy.
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuracion = config.get_section(config.config_ini_section, {})
    configuracion["sqlalchemy.url"] = _url()
    engine = async_engine_from_config(configuracion, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
