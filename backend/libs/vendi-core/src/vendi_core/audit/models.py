"""Tabla de auditoría.

Cosechada de `base_saas.audit.models` con dos adaptaciones:

1. `tenant_slug String(64)` → `tenant_id UUID NULL`, con el índice
   `ix_audit_events_tenant_timestamp` recolocado sobre la nueva columna.
2. Se quita `{"schema": "public"}`: Vendi es schema único regional, y fijar el
   schema en el modelo rompe los tests sobre SQLite y obliga a calificar el
   nombre en cada consulta sin ganar nada.

**`audit_events` es tabla de PLATAFORMA: no lleva policy RLS.** Es deliberado y
está en la lista de excepciones del test candado `test_rls_coverage.py`. Razón:
la auditoría es inherentemente cross-tenant — la consola de plataforma tiene que
poder responder "qué pasó en el negocio X" y "qué hizo el administrador Y en
todos los negocios", y el purgador de retención la recorre entera. Solo
`vendi_platform` la lee; la API nunca la expone directamente, solo a través de
servicios que filtran por `tenant_id` en Python. Que `tenant_id` sea nullable es
parte del mismo hecho: los eventos de plataforma no pertenecen a ningún negocio.
"""

import uuid
from datetime import datetime

from sqlalchemy import UUID, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base


class AuditLog(Base):
    """Rastro de auditoría append-only. Tabla de plataforma, cross-tenant."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_timestamp", "tenant_id", "timestamp"),
        Index("ix_audit_events_user_timestamp", "user_id", "timestamp"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
        Index("ix_audit_events_correlation", "correlation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), default="", server_default="", nullable=False)
    service_name: Mapped[str] = mapped_column(String(64), default="", server_default="", nullable=False)
    # Nullable a propósito: NULL = evento de plataforma, sin negocio asociado.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[str] = mapped_column(String(64), default="", server_default="", nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), default="", server_default="", nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), default="", server_default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="success", server_default="success", nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    audit_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    error: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
