"""Registro de trabajos programados del worker.

Fase 0 tiene uno: la pasada de retención. Está declarado con
`scope="platform"` **a propósito**, aunque por dentro recorra negocios: el
`RetentionRunner` ya hace su propio fan-out por negocio, con semáforo de
concurrencia y tope por negocio. Declararlo como `scope="tenant"` lo haría
correr una vez por negocio, y cada una de esas veces volvería a recorrer todos
los negocios: N² pasadas y N filas de auditoría por ciclo diciendo lo mismo.

Aun así el planificador recibe `list_active_tenant_ids`, porque el primer
trabajo con `scope="tenant"` que alguien añada tiene que disparar sin que haya
que acordarse de cablear nada. Que hoy no lo use nadie es exactamente el motivo
por el que se olvidaría.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog

from vendi_core.jobs.types import JobContext, ScheduledJob
from vendi_core.retention.runner import RetentionRunner

logger = structlog.get_logger()


def construir_jobs(runner: RetentionRunner) -> list[ScheduledJob]:
    async def _retencion(_: JobContext) -> Mapping[str, Any]:
        resultados = await runner.run_once()
        return {"filas_borradas": sum(resultados.values()), "por_politica": resultados}

    return [
        ScheduledJob(
            name="retention.run",
            # 03:15 UTC = 22:15 en Colombia. Fuera de la hora punta de un
            # comercio y desplazado 15 minutos de la hora en punta para no
            # coincidir con todo lo demás que el mundo programa a las 03:00.
            cron="15 3 * * *",
            handler=_retencion,
            scope="platform",
            description="Purga de datos según las políticas de retención",
            # Tope generoso: la pasada recorre todos los negocios. Si se pasa de
            # aquí es que algo va mal, y conviene enterarse por la métrica
            # `vendi_job_failed_total{reason="timeout"}` y no por el disco.
            timeout_sec=3600,
        )
    ]
