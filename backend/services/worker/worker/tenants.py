"""Lista de negocios activos para el planificador y la retención.

Es el `list_active_tenant_ids` que `JobScheduler` y `RetentionRunner` reciben
inyectado. Sin él, **los trabajos con `scope="tenant"` no disparan para nadie**:
el planificador registra `job_sin_lista_de_tenants` y sigue, y la retención
registra `retention_sin_lista_de_tenants` y omite todas las políticas de
negocio. No es un fallo silencioso —queda en el log— pero sí es un fallo que
nadie mira hasta que alguien pregunta por qué no se purga nada.

Se inyecta en vez de cablearse dentro de `vendi-core` porque la tabla `tenants`
la define el módulo homónimo de la API: la librería transversal no tiene por qué
conocer su esquema ni reventar en arranque si todavía no existe.

Solo `activo`. Un negocio suspendido no debe recibir trabajos programados —los
que cuestan dinero (informes, envíos) menos aún— y uno eliminado no debe
recibirlos en absoluto.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = structlog.get_logger()

SQL_NEGOCIOS_ACTIVOS = text("SELECT id FROM tenants WHERE estado = 'activo' AND deleted_at IS NULL ORDER BY created_at")


def lector_de_negocios_activos(session_factory: async_sessionmaker):
    """Devuelve el callable que espera `JobScheduler` / `RetentionRunner`."""

    async def _listar() -> list[uuid.UUID]:
        try:
            async with session_factory() as session:
                filas = (await session.execute(SQL_NEGOCIOS_ACTIVOS)).scalars().all()
                return list(filas)
        except Exception as exc:  # noqa: BLE001
            # Que la base no responda no puede tumbar el bucle del worker. Una
            # lista vacía significa "esta pasada no corre para nadie", que es lo
            # correcto: mejor no correr que correr sin saber para quién.
            logger.error("no_se_pudo_listar_negocios_activos", error=str(exc))
            return []

    return _listar
