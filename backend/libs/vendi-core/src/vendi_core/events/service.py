"""Emisión de eventos de dominio.

Envoltorio fino sobre el outbox transaccional. El código de negocio llama a
``DomainEventService.emit(session, ...)`` dentro de la misma transacción que la
escritura que causó el evento; el dispatcher del outbox lo publica después en
RabbitMQ.

Cosechado de `base_saas.events.service`. Adaptación: `tenant_slug: str` pasa a
`tenant_id: uuid.UUID | None` (schema único regional; el tenant es el UUID que
también gobierna el GUC `vendi.tenant_id`). Los eventos de plataforma —los que
no pertenecen a ningún negocio— llevan `tenant_id=None` y salen con la clave de
enrutado `plataforma.<evento>`.

Forma del payload (estable para v1):

    {
        "id": "<uuid>",             # id único del evento (clave de idempotencia)
        "event": "tenant.creado",   # nombre punteado del evento
        "tenant_id": "<uuid>|null",
        "resource_type": "tenant",
        "resource_id": "<uuid>",
        "data": { ... },            # payload específico del evento
        "occurred_at": "2026-07-22T22:00:00.000000+00:00"
    }
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from vendi_core.messaging.outbox import OutboxService

EVENT_EXCHANGE = "events.tenant"

# Clave de enrutado para eventos que no pertenecen a ningún negocio.
CLAVE_PLATAFORMA = "plataforma"


class DomainEventService:
    @staticmethod
    async def emit(
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID | None,
        event_name: str,
        resource_type: str,
        resource_id: str,
        data: Mapping[str, Any] | None = None,
    ) -> str:
        """Encola un evento de dominio para su fan-out vía outbox. Devuelve el
        id generado del evento (que también va dentro del payload).

        Debe llamarse dentro de una transacción activa de ``session``: si quien
        llama hace rollback, el evento no se publica. Esa es toda la garantía
        del patrón outbox.
        """
        event_id = str(uuid.uuid4())
        payload = {
            "id": event_id,
            "event": event_name,
            "tenant_id": str(tenant_id) if tenant_id is not None else None,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "data": dict(data) if data else {},
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        prefijo = str(tenant_id) if tenant_id is not None else CLAVE_PLATAFORMA
        await OutboxService.enqueue(
            session,
            exchange=EVENT_EXCHANGE,
            routing_key=f"{prefijo}.{event_name}",
            payload=payload,
            tenant_id=tenant_id,
        )
        return event_id
