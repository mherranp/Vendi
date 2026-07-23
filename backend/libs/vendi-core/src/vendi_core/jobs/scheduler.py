"""In-process cron scheduler for background jobs.

Runs as a single asyncio task alongside other workers (outbox dispatcher,
mail consumer, …). Each cycle picks the earliest-firing enabled job, sleeps
until its next fire time (or until ``stop`` fires), runs it, and emits one
``audit_events`` row per run so operators can see what happened in the same
log they use for user actions.

Los trabajos con scope de tenant iteran los negocios activos dentro de un solo
disparo; cada negocio recibe su propia fila de auditoría etiquetada con su
``tenant_id``, y el ContextVar ``current_tenant_id`` se siembra por iteración
para que el manejador vea exactamente lo que vería la API.

Cosecha de `base_saas.jobs.scheduler`. Adaptación: la lista de negocios activos
ya no se saca de un `SELECT slug FROM public.tenants` cableado; llega como
callable inyectado ``list_active_tenant_ids``. Motivo: la tabla `tenants` la
crea el módulo homónimo (tarea 4.2) y el planificador no tiene por qué conocer
su esquema, ni fallar en arranque si todavía no existe.

Each ``ScheduledJob`` now supports optional ``timeout_sec`` (handler wrapped
in ``asyncio.wait_for``) and ``max_retries`` with exponential
``retry_backoff_sec`` (attempt ``n`` waits ``backoff * 2**n`` seconds before
retrying). Failures bump
``vendi_job_failed_total{job, reason}`` with reason ∈
``{"timeout", "max_retries", "error"}``.

Deliberate non-goals at this layer (v1):
- No distributed locking. Only one instance should run the scheduler; multi-
  instance rollouts need an external lock (Redis SET NX, pg advisory_lock).
- No DB-configurable schedules. Edits are code changes + redeploy.
- Failed runs do NOT re-queue past the next cron boundary — if all retries
  are exhausted, the scheduler waits for the next firing.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from croniter import croniter
from prometheus_client import Counter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from vendi_core.jobs.types import JobContext, ScheduledJob
from vendi_core.tenant.context import current_tenant_id

logger = structlog.get_logger()


# Shared job-failure counter. ``reason`` splits the failure modes so ops can
# alert differently on timeouts (handler took too long — usually infrastructure
# or a runaway query) vs max_retries (handler raised N+1 times in a row —
# usually a bug or a persistent downstream outage) vs error (single-shot
# failure with ``max_retries=0``, preserving the legacy audit row).
job_failed_counter = Counter(
    "vendi_job_failed_total",
    "Scheduled job runs that ended in failure, split by reason.",
    labelnames=("job", "reason"),
)


@dataclass(frozen=True)
class JobRunResult:
    job_name: str
    tenant_id: uuid.UUID | None
    started_at: datetime
    finished_at: datetime
    status: str  # "success" | "failure"
    changes: dict[str, Any]
    error: str = ""


class JobScheduler:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        engine: AsyncEngine,
        jobs: list[ScheduledJob],
        service_name: str = "worker",
        list_active_tenant_ids: Callable[[], Awaitable[list[uuid.UUID]]] | None = None,
    ):
        self._session_factory = session_factory
        self._engine = engine
        self._jobs = [j for j in jobs if j.enabled]
        self._service_name = service_name
        # Inyectado en vez de cableado a un SELECT: la tabla `tenants` llega con
        # la tarea 4.2 y el planificador no debe conocer su esquema ni reventar
        # en arranque si aún no existe. `services/worker` le pasa el lector real.
        self._list_active_tenant_ids = list_active_tenant_ids

    @property
    def jobs(self) -> list[ScheduledJob]:
        return list(self._jobs)

    async def run(self, stop: asyncio.Event) -> None:
        if not self._jobs:
            logger.info("job_scheduler_no_jobs")
            await stop.wait()
            return

        logger.info("job_scheduler_starting", jobs=[j.name for j in self._jobs])

        next_fires: dict[str, datetime] = {j.name: self._next_fire(j.cron) for j in self._jobs}

        while not stop.is_set():
            # Pick the job whose next fire is earliest.
            next_job_name, next_time = min(next_fires.items(), key=lambda kv: kv[1])
            now = datetime.now(UTC)
            delay = max(0.0, (next_time - now).total_seconds())

            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                return  # stop fired
            except TimeoutError:
                pass

            job = next((j for j in self._jobs if j.name == next_job_name), None)
            if job is None:
                continue

            try:
                await self._fire(job)
            except Exception as exc:  # noqa: BLE001
                logger.error("job_fire_failed", job=job.name, error=str(exc))

            # Re-arm from now (not from next_time) so a slow run doesn't queue
            # a backlog of back-to-back firings.
            next_fires[job.name] = self._next_fire(job.cron)

    async def run_now(self, job_name: str) -> list[JobRunResult]:
        """Fire a job on demand (bypassing the schedule). Useful for tests and
        for a future admin 'run now' button. Returns all run results (one per
        tenant for tenant-scoped jobs, else one)."""
        job = next((j for j in self._jobs if j.name == job_name), None)
        if job is None:
            raise ValueError(f"Unknown or disabled job: {job_name}")
        return await self._fire(job)

    async def _fire(self, job: ScheduledJob) -> list[JobRunResult]:
        if job.scope == "platform":
            return [await self._run_one(job, tenant_id=None)]

        # Scope de tenant: itera los negocios activos.
        results: list[JobRunResult] = []
        for tenant_id in await self._active_tenant_ids():
            results.append(await self._run_one(job, tenant_id=tenant_id))
        return results

    async def _run_one(
        self,
        job: ScheduledJob,
        tenant_id: uuid.UUID | None,
    ) -> JobRunResult:
        started_at = datetime.now(UTC)
        log = logger.bind(job=job.name, tenant=str(tenant_id) if tenant_id else "-")
        log.info("job_run_started")

        ctx = JobContext(
            session_factory=self._session_factory,
            engine=self._engine,
            tenant_id=tenant_id,
        )
        changes: dict[str, Any] = {}
        error = ""
        status = "success"

        # Retry/timeout wrapper.
        #
        # Loop semantics:
        #   - attempt 0 is the first try; attempts 1..max_retries are retries.
        #   - backoff between retries is exponential:
        #       sleep = retry_backoff_sec * 2 ** attempt
        #     i.e. with backoff=30s and max_retries=3 → 30s, 60s, 120s
        #     between attempts 0→1, 1→2, 2→3. First attempt is always
        #     immediate (no leading sleep).
        #   - ``asyncio.TimeoutError`` is terminal: a handler that exceeded
        #     its budget will almost certainly exceed it again, so we don't
        #     burn backoff time on a retry loop. The run records
        #     ``error="timeout"``.
        #   - Any other ``Exception`` is retryable if attempts remain; if
        #     exhausted, the run records ``error="max_retries"`` (or a
        #     plain error message when ``max_retries=0`` — legacy path).
        #
        # El ContextVar `current_tenant_id` se siembra alrededor de TODO el
        # bucle —no de una consulta suelta— para que el manejador pueda abrir
        # las sesiones que quiera y todas emitan su `SET LOCAL`, exactamente
        # como en un request de la API. Se restaura en el `finally` aunque el
        # manejador lance o agote reintentos: si no, la iteración del siguiente
        # negocio heredaría el tenant del anterior, que es la fuga cross-tenant
        # más fácil de escribir sin querer en un worker.
        max_attempts = 1 + max(0, job.max_retries)
        marca_tenant = current_tenant_id.set(tenant_id)
        try:
            for attempt in range(max_attempts):
                try:
                    if job.timeout_sec is not None:
                        result = await asyncio.wait_for(job.handler(ctx), timeout=job.timeout_sec)
                    else:
                        result = await job.handler(ctx)
                    if result:
                        changes = dict(result)
                    break
                except TimeoutError:
                    status = "failure"
                    error = "timeout"
                    log.error(
                        "job_run_timeout",
                        timeout_sec=job.timeout_sec,
                        attempt=attempt,
                    )
                    job_failed_counter.labels(job=job.name, reason="timeout").inc()
                    # Timeouts are terminal — don't retry.
                    break
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "job_run_attempt_failed",
                        error=str(exc),
                        attempt=attempt,
                        max_attempts=max_attempts,
                    )
                    if attempt + 1 < max_attempts:
                        backoff = job.retry_backoff_sec * (2**attempt)
                        await asyncio.sleep(backoff)
                        continue
                    # Exhausted.
                    status = "failure"
                    if job.max_retries > 0:
                        error = "max_retries"
                        job_failed_counter.labels(job=job.name, reason="max_retries").inc()
                    else:
                        error = str(exc)
                        job_failed_counter.labels(job=job.name, reason="error").inc()
                    log.error("job_run_failed", error=error)
                    break
        finally:
            current_tenant_id.reset(marca_tenant)

        finished_at = datetime.now(UTC)
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        await self._write_audit(
            job=job,
            tenant_id=tenant_id,
            status=status,
            duration_ms=duration_ms,
            changes=changes,
            error=error,
            timestamp=finished_at,
        )
        log.info("job_run_finished", status=status, duration_ms=duration_ms)

        return JobRunResult(
            job_name=job.name,
            tenant_id=tenant_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            changes=changes,
            error=error,
        )

    @staticmethod
    def _next_fire(cron: str) -> datetime:
        return croniter(cron, datetime.now(UTC)).get_next(datetime)

    async def _active_tenant_ids(self) -> list[uuid.UUID]:
        """Negocios activos, vía el callable inyectado.

        Sin callable, un trabajo con scope de tenant no dispara para nadie y se
        registra el hecho. Es deliberado: es preferible que un trabajo no corra
        —y se vea en el log— a que corra sin tenant y toque filas de todos.
        """
        if self._list_active_tenant_ids is None:
            logger.warning("job_sin_lista_de_tenants", motivo="list_active_tenant_ids no inyectado")
            return []
        return list(await self._list_active_tenant_ids())

    async def _write_audit(
        self,
        *,
        job: ScheduledJob,
        tenant_id: uuid.UUID | None,
        status: str,
        duration_ms: int,
        changes: Mapping[str, Any],
        error: str,
        timestamp: datetime,
    ) -> None:
        try:
            async with self._session_factory() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO audit_events (
                            id, timestamp, service_name, tenant_id,
                            action, resource_type,
                            status, duration_ms, changes, error
                        ) VALUES (
                            gen_random_uuid(), :ts, :svc, :tenant,
                            :action, 'job',
                            :status, :duration, CAST(:changes AS jsonb), :err
                        )
                        """
                    ),
                    {
                        "ts": timestamp,
                        "svc": self._service_name,
                        "tenant": tenant_id,
                        "action": f"job.run.{job.name}",
                        "status": status,
                        "duration": duration_ms,
                        "changes": json.dumps(dict(changes)),
                        "err": error[:2000],
                    },
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("job_audit_write_failed", job=job.name, error=str(exc))
