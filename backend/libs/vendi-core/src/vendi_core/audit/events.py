"""Evento de auditoría serializable. Lo persiste `AuditService`.

Cosechado de `base_saas.audit.events`. Adaptación: `tenant_slug: str` pasa a
`tenant_id: uuid.UUID | None`. `None` significa "evento de plataforma" (alta de
un negocio, login de un administrador de la consola), no "tenant desconocido":
en schema único regional no hay slug de schema al que caer.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditAction(StrEnum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"
    GRANT = "grant"
    REVOKE = "revoke"
    EXECUTE = "execute"


class AuditStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class AuditEvent(BaseModel):
    """Evento de auditoría serializable. Lo persiste `AuditService`."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = ""
    service_name: str = ""
    # None = evento de plataforma (sin negocio asociado).
    tenant_id: uuid.UUID | None = None
    user_id: str = ""
    user_email: str = ""
    action: str
    resource_type: str = ""
    resource_id: str = ""
    status: AuditStatus = AuditStatus.SUCCESS
    duration_ms: int | None = None
    changes: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
