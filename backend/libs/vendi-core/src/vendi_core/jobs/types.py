"""Tipos compartidos entre el planificador y los manejadores de trabajos.

Cosechado de `base_saas.jobs.types`. Adaptación: el contexto pasa de
`tenant_slug`/`tenant_schema` (dos strings que identificaban el schema del
inquilino) a un único `tenant_id: uuid.UUID | None`, que es lo que gobierna la
policy de RLS.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

JobScope = Literal["platform", "tenant"]


@dataclass(frozen=True)
class JobContext:
    """Runtime context handed to a job handler for each invocation.

    En los trabajos con ``scope='tenant'`` el planificador itera los negocios
    activos e invoca el manejador una vez por negocio, con ``tenant_id`` puesto
    **y el ContextVar `current_tenant_id` sembrado**, de modo que el manejador
    ejerce exactamente el mismo camino RLS que la API. En los de
    ``scope='platform'`` vale ``None`` y el manejador se encarga de su propia
    iteración cross-tenant si la necesita.
    """

    session_factory: async_sessionmaker
    engine: AsyncEngine
    tenant_id: uuid.UUID | None


# Jobs return an optional ``changes`` dict that lands as the JSONB ``changes``
# column on the audit_events row — useful for run-specific metrics like
# ``{"rows_deleted": 42}``.
JobHandler = Callable[[JobContext], Awaitable[Mapping[str, Any] | None]]


@dataclass(frozen=True)
class ScheduledJob:
    """Declarative spec for one background job."""

    name: str
    """Machine identifier (dotted, e.g. ``retention.run``). Used in audit logs."""

    cron: str
    """5-field cron expression (UTC). Example: ``"0 3 * * *"`` — daily 03:00."""

    handler: JobHandler

    scope: JobScope = "platform"
    """Either ``platform`` (handler runs once per firing) or ``tenant`` (handler
    runs once per active tenant, with the tenant context preset)."""

    description: str = ""
    """Short human-readable summary shown in the admin UI."""

    enabled: bool = True
    """Schedule-off switch without touching the registry code."""

    timeout_sec: int | None = None
    """Per-invocation wall-clock budget enforced via ``asyncio.wait_for``. When
    the handler runs longer than this the scheduler cancels it, records the
    run as ``failure`` with ``error="timeout"`` and bumps
    ``vendi_job_failed_total{reason="timeout"}``. ``None`` (default) means
    the handler may run unbounded — cron-firing semantics fall back to the
    old best-effort behaviour."""

    max_retries: int = 0
    """Number of **additional** attempts after the first failure. ``0`` (default)
    keeps the legacy "one shot, log + audit on failure" behaviour. With
    ``max_retries=3`` the handler can be invoked up to 4 times total; each
    retry is gated by an exponential backoff (see ``retry_backoff_sec``).
    Timeouts do NOT trigger retries — a timed-out handler fails fast so ops
    can investigate rather than waiting ``N*timeout`` before auditing."""

    retry_backoff_sec: int = 30
    """Base delay (seconds) for retry backoff. The scheduler sleeps
    ``retry_backoff_sec * 2**attempt`` between retries, so with the default
    30s and ``max_retries=3`` the sleeps are 30s, 60s, 120s. Set lower in
    tests via the dataclass kwarg; callers that want a fixed backoff can set
    ``max_retries=1`` to get exactly one retry after ``retry_backoff_sec``
    seconds."""
