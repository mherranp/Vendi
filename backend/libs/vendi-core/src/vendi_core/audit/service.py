import asyncio
import os
from typing import Literal

import structlog
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import async_sessionmaker

from vendi_core.audit.events import AuditEvent
from vendi_core.audit.metrics import audit_write_failed_counter
from vendi_core.audit.models import AuditLog
from vendi_core.audit.redact import redact_secrets

# asyncpg is an optional-at-import-time transitive dep (it's installed in
# the main backend but not exposed from vendi_core' own pyproject). Import
# lazily + fall back to a sentinel so unit tests that stub the session
# factory don't force the dependency.
try:  # pragma: no cover - import guard
    from asyncpg.exceptions import TooManyConnectionsError as _AsyncpgTooMany
except Exception:  # pragma: no cover - fallback

    class _AsyncpgTooMany(Exception):  # type: ignore[no-redef]
        """Stand-in when asyncpg is not installed in the test env."""


_POOL_EXHAUST_EXC: tuple[type[BaseException], ...] = (SATimeoutError, _AsyncpgTooMany)

logger = structlog.get_logger()

FailureMode = Literal["warn", "raise"]
_VALID_FAILURE_MODES: tuple[FailureMode, ...] = ("warn", "raise")
_DEFAULT_FAILURE_MODE: FailureMode = "warn"


def _resolve_failure_mode(explicit: FailureMode | None) -> FailureMode:
    """Pick the failure mode from an explicit arg or AUDIT_WRITE_FAILURE_MODE.

    Precedence: explicit kwarg > env var > default ("warn"). An unknown
    value (either in the env or passed in) is logged as an error and the
    default is used, so a typo in deployment config never escalates an
    audit hiccup into a service outage on its own.
    """
    if explicit is not None:
        if explicit in _VALID_FAILURE_MODES:
            return explicit
        logger.error(
            "audit_invalid_failure_mode",
            source="argument",
            value=explicit,
            fallback=_DEFAULT_FAILURE_MODE,
        )
        return _DEFAULT_FAILURE_MODE

    raw = os.getenv("AUDIT_WRITE_FAILURE_MODE")
    if raw is None or raw == "":
        return _DEFAULT_FAILURE_MODE
    normalized = raw.strip().lower()
    if normalized in _VALID_FAILURE_MODES:
        return normalized
    logger.error(
        "audit_invalid_failure_mode",
        source="env",
        value=raw,
        fallback=_DEFAULT_FAILURE_MODE,
    )
    return _DEFAULT_FAILURE_MODE


class AuditService:
    """Audit writer with a configurable failure mode.

    Two modes exist, driven by ``AUDIT_WRITE_FAILURE_MODE`` (or the
    explicit ``failure_mode`` kwarg for tests):

    * ``warn`` (default, legacy behavior): write failures are logged at
      warning level and swallowed so the caller is never interrupted.
    * ``raise``: write failures are logged and re-raised so the caller
      can decide how to handle the loss of an audit row (e.g. fail the
      enclosing HTTP request in compliance-sensitive deployments).

    In both modes a failure always increments the
    ``vendi_audit_write_failed_total`` counter labeled by
    ``service_name`` — visibility is not optional.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        service_name: str,
        failure_mode: FailureMode | None = None,
        *,
        inflight_tasks: set[asyncio.Task] | None = None,
    ):
        self._session_factory = session_factory
        self._service_name = service_name
        self._failure_mode: FailureMode = _resolve_failure_mode(failure_mode)
        # ``_inflight`` is a strong-reference supervisor set. Without it,
        # Python GC can collect the fire-and-forget task created by
        # ``log()`` between checkpoints, silently dropping both the write
        # *and* the failure counter. Callers can inject a shared set (e.g.
        # ``app.state.inflight_tasks``) so the lifespan shutdown hook can
        # drain pending audit writes before the process exits.
        self._inflight: set[asyncio.Task] = inflight_tasks if inflight_tasks is not None else set()

    @property
    def failure_mode(self) -> FailureMode:
        return self._failure_mode

    @property
    def inflight_tasks(self) -> set[asyncio.Task]:
        """Supervisor set for tests + lifespan drain."""
        return self._inflight

    def _on_task_done(self, task: asyncio.Task) -> None:
        """Remove the task from the supervisor + surface swallowed errors.

        Exceptions inside ``_write`` are already logged and have bumped the
        ``audit_write_failed`` counter by the time the task finishes — but
        if anything raises *outside* that try-block (schema drift,
        import-time failure in a test monkey-patch) there is no
        observability path. The done callback catches that gap.
        """
        self._inflight.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.warning(
            "audit_task_supervisor",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        audit_write_failed_counter.labels(service_name=self._service_name, reason="task_supervisor").inc()

    async def log(self, event: AuditEvent) -> None:
        """Schedule a write without awaiting. Returns immediately.

        The task is added to ``self._inflight`` and wired with a done
        callback so (a) Python can't GC it mid-run and (b) any exception
        that escapes ``_write`` still fires a counter + warning.
        """
        task = asyncio.create_task(self._write(event), name="audit.log")
        self._inflight.add(task)
        task.add_done_callback(self._on_task_done)

    async def log_sync(self, event: AuditEvent) -> None:
        """Await the write. Use when you need to confirm persistence."""
        await self._write(event)

    async def _write(self, event: AuditEvent) -> None:
        try:
            data = event.model_dump()
            data["service_name"] = event.service_name or self._service_name
            metadata = data.pop("metadata", {})
            status_value = data.pop("status")
            # Defensive redaction — any field that looks like a secret
            # (``password`` / ``client_secret`` / ``token`` / …) is
            # replaced with ``"***"`` before persisting. This catches both
            # the decorator's call sites and any ad-hoc ``audit_service.log``
            # that happens to serialise a request body into metadata.
            # See ``vendi_core.audit.redact.SECRET_FIELD_NAMES`` for the
            # full match list.
            safe_metadata = redact_secrets(metadata)
            safe_changes = redact_secrets(data["changes"])
            record = AuditLog(
                **{
                    "timestamp": data["timestamp"],
                    "correlation_id": data["correlation_id"],
                    "service_name": data["service_name"],
                    "tenant_id": data["tenant_id"],
                    "user_id": data["user_id"],
                    "user_email": data["user_email"],
                    "action": data["action"],
                    "resource_type": data["resource_type"],
                    "resource_id": data["resource_id"],
                    "status": status_value.value if hasattr(status_value, "value") else status_value,
                    "duration_ms": data["duration_ms"],
                    "changes": safe_changes,
                    "audit_metadata": safe_metadata,
                    "error": data["error"],
                }
            )
            async with self._session_factory() as session:
                session.add(record)
                await session.commit()
        except _POOL_EXHAUST_EXC as exc:
            # Connection-pool-exhaust is load-related: the pool is saturated
            # and the problem will not fix itself by swallowing. Escalate
            # the log to ERROR and tag the counter with reason="pool_exhaust"
            # so alerting can page on this independently of garden-variety
            # audit-write failures. Re-raise behavior still follows
            # failure_mode so compliance-strict deployments surface the
            # error to the caller.
            audit_write_failed_counter.labels(service_name=self._service_name, reason="pool_exhaust").inc()
            logger.error(
                "audit_write_failed",
                reason="pool_exhaust",
                error=str(exc),
                error_type=type(exc).__name__,
                action=event.action,
                resource_type=event.resource_type,
                failure_mode=self._failure_mode,
            )
            if self._failure_mode == "raise":
                raise
        except Exception as exc:
            # Always emit the metric so ops see the failure regardless of
            # whether we're in swallow-or-raise mode.
            audit_write_failed_counter.labels(service_name=self._service_name, reason="generic").inc()
            logger.warning(
                "audit_write_failed",
                reason="generic",
                error=str(exc),
                action=event.action,
                resource_type=event.resource_type,
                failure_mode=self._failure_mode,
            )
            if self._failure_mode == "raise":
                raise
