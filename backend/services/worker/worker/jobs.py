"""Registro de trabajos programados del worker.

Hoy hay dos: la pasada de retención (Fase 0) y la de vencidos del fiado
(módulo 5). La retención está declarada con `scope="platform"` **a
propósito**, aunque por dentro recorra negocios: el `RetentionRunner` ya hace
su propio fan-out por negocio, con semáforo de concurrencia y tope por
negocio. Declararla como `scope="tenant"` la haría correr una vez por
negocio, y cada una de esas veces volvería a recorrer todos los negocios: N²
pasadas y N filas de auditoría por ciclo diciendo lo mismo.

`fiado.vencimientos` es el primer trabajo con `scope="tenant"`: el
planificador itera los negocios activos con `list_active_tenant_ids` (ya
cableado desde Fase 0 para que este día llegara sin tener que acordarse de
nada) y el handler se limita a filtrar por su `tenant_id`, explícito y
obligatorio porque la sesión del worker es de plataforma (BYPASSRLS).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import text

from vendi_core.events.service import DomainEventService
from vendi_core.jobs.types import JobContext, ScheduledJob
from vendi_core.retention.runner import RetentionRunner

logger = structlog.get_logger()

#: La pasada de vencidos de UN negocio. La sesión del worker es de
#: PLATAFORMA (BYPASSRLS, sin GUC): el `tenant_id` del filtro es obligatorio
#: y explícito — al revés de la API, donde la policy acota. El UPDATE solo
#: toca filas `vigente` y bloquea las que devuelve hasta el commit: una
#: segunda corrida (reintento, concurrencia) actualiza 0 filas y emite 0
#: eventos. La transición de estado ES el anti-duplicado (decisión 7 del
#: plan del módulo): no hay bandera que olvidar resetear cuando el tendero
#: reprograme la fecha.
SQL_MARCAR_VENCIDOS = text(
    """
    UPDATE fiado_creditos
       SET estado = 'vencido', updated_at = now()
     WHERE tenant_id = :tenant_id
       AND estado = 'vigente'
       AND fecha_vencimiento IS NOT NULL
       AND fecha_vencimiento < :hoy
    RETURNING id, cliente_id, monto_total, saldo_pendiente, fecha_vencimiento
    """
)


async def marcar_vencimientos_fiado(ctx: JobContext) -> Mapping[str, Any]:
    """Marca `vencido` los créditos cuya fecha ya pasó — en el calendario de
    America/Bogota, no en el UTC crudo del servidor — y encola UN
    `fiado.credito_vencido` por crédito (ADR-022: lo consume el módulo de
    notificaciones, módulo 7, que lo traduce a `notificacion.enviar`).

    SQL crudo a propósito: los modelos viven en la API (`app.modules.fiado`)
    y el worker no la importa; la sentencia es pequeña y su contrato lo
    fijan los tests contra la base real."""
    hoy = datetime.now(ZoneInfo("America/Bogota")).date()
    async with ctx.session_factory() as session:
        filas = (await session.execute(SQL_MARCAR_VENCIDOS, {"tenant_id": ctx.tenant_id, "hoy": hoy})).all()
        for fila in filas:
            # Sin PII en el payload (ADR-025): el nombre del cliente NO
            # viaja; el módulo 7 arma «Tienes N fiados vencidos».
            await DomainEventService.emit(
                session,
                tenant_id=ctx.tenant_id,
                event_name="fiado.credito_vencido",
                resource_type="fiado_credito",
                resource_id=str(fila.id),
                data={
                    "credito_id": str(fila.id),
                    "cliente_id": str(fila.cliente_id),
                    "monto_total": fila.monto_total,
                    "saldo_pendiente": fila.saldo_pendiente,
                    "fecha_vencimiento": str(fila.fecha_vencimiento),
                },
            )
        await session.commit()
    logger.info("fiado_vencimientos_marcados", tenant=str(ctx.tenant_id), creditos=len(filas))
    return {"creditos_vencidos": len(filas)}


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
        ),
        ScheduledJob(
            name="fiado.vencimientos",
            # 11:30 UTC = 06:30 en Colombia: el recordatorio llega antes de
            # abrir la tienda, que es cuando el tendero decide a quién le
            # cobra hoy. Desplazado de la hora en punto, como la retención.
            cron="30 11 * * *",
            handler=marcar_vencimientos_fiado,
            # Una pasada por negocio activo (el planificador siembra el
            # ContextVar por iteración y audita por negocio): el handler es
            # chico y el fan-out ya está resuelto por el scheduler.
            scope="tenant",
            description="Marca vencidos los fiados del día y encola el recordatorio",
            timeout_sec=300,
        ),
    ]
