"""Runner diario de retención.

Como tarea asyncio: quien lo arranca le pasa un `asyncio.Event` para pararlo
limpiamente; el runner duerme hasta la siguiente hora UTC configurada y aplica
todas las políticas (las de plataforma una vez, las de tenant una por negocio
activo). Los conteos de purga se resumen en una fila de `audit_events` con
`action='retention.run'`.

Cosechado de `base_saas.retention.runner` con tres adaptaciones:

1. **Fuera `search_path`.** BaseSaaS cambiaba de schema por inquilino. Aquí el
   runner usa la **sesión de plataforma** (rol `vendi_platform`, `BYPASSRLS`) y
   siembra `current_tenant_id` en cada pasada, de modo que el borrado por
   negocio ejerce el mismo camino RLS que la API en vez de un camino paralelo
   que nadie prueba.

   Matiz importante y deliberado: con la sesión de plataforma el `BYPASSRLS`
   gana y la policy **no** filtra, así que el `DELETE` de una política de tenant
   se acota con un `WHERE tenant_id = :tenant_id` explícito además de la
   condición. Sembrar el ContextVar sirve para los pre-purge hooks, que sí
   abren sus propias sesiones. Usar aquí la sesión de tenant sería más elegante
   pero no funcionaría: `vendi_app` no tiene permiso de borrado sobre las tablas
   de plataforma, y el runner necesita las dos clases de tabla en la misma
   pasada.

2. La lista de negocios activos llega como callable inyectado, no como un
   `SELECT ... FROM public.tenants` cableado (la tabla llega en la tarea 4.2).

3. `PUBLIC_POLICIES` pasa a llamarse `PLATFORM_POLICIES`: en schema único no hay
   un "schema public" que distinguir, lo que hay son tablas de plataforma.

Per-tenant work is fanned out with a configurable concurrency cap
(``max_concurrency``, default 5) and a per-tenant timeout
(``per_tenant_timeout_sec``, default 120). Without these a single slow
pre-purge hook would serialize the whole run — for a product with thousands
of tenants, one degraded object-store would stall retention for hours.
The semaphore bounds in-flight tenants; the timeout skips any tenant whose
cycle exceeds the budget and emits a metric so ops can page on chronic
stallers.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta

import structlog
from prometheus_client import Counter
from sqlalchemy import bindparam, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vendi_core.retention.policies import (
    PLATFORM_POLICIES,
    TENANT_POLICIES,
    RetentionPolicy,
)
from vendi_core.tenant.context import current_tenant_id

logger = structlog.get_logger()

# vendi_retention_tenant_skipped_total{reason} — each time a tenant's
# retention slot is skipped. Reasons:
#   * ``timeout`` — ``asyncio.wait_for`` fired because ``_purge_tenant``
#     exceeded ``per_tenant_timeout_sec``.
#   * ``abort`` — the session was killed mid-run (e.g. Postgres
#     ``pg_terminate_backend``, connection reset) → ``OperationalError``
#     bubbles up instead of ``TimeoutError``.
# Ops can alert on ``rate([15m]) > 0`` per reason to distinguish a slow
# pre-purge hook (``timeout``) from pool flapping / DB restarts (``abort``).
retention_tenant_skipped_counter = Counter(
    "vendi_retention_tenant_skipped_total",
    "Tenants whose retention cycle was skipped by the runner.",
    ["reason"],
)

# Defaults live at module level so callers (and tests) can introspect them.
DEFAULT_MAX_CONCURRENCY = 5
DEFAULT_PER_TENANT_TIMEOUT_SEC = 120.0


# A pre-purge hook runs just before the retention runner deletes rows from a
# table. The runner passes the open session + the rows it is about to delete;
# the hook can do side-effects (e.g. object-store cleanup for `files`). If the
# hook raises, the runner keeps the rows intact and retries the next cycle.
PrePurgeHook = Callable[[AsyncSession, list[Mapping]], Awaitable[None]]


class RetentionRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        hour_utc: int = 3,
        service_name: str = "mail-worker",
        pre_purge_hooks: dict[str, PrePurgeHook] | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        per_tenant_timeout_sec: float = DEFAULT_PER_TENANT_TIMEOUT_SEC,
        list_active_tenant_ids: Callable[[], Awaitable[list[uuid.UUID]]] | None = None,
    ):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if per_tenant_timeout_sec <= 0:
            raise ValueError("per_tenant_timeout_sec must be > 0")
        self._session_factory = session_factory
        self._hour_utc = hour_utc
        self._service_name = service_name
        self._hooks: dict[str, PrePurgeHook] = pre_purge_hooks or {}
        self._max_concurrency = max_concurrency
        self._per_tenant_timeout_sec = per_tenant_timeout_sec
        self._list_active_tenant_ids = list_active_tenant_ids

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            delay = self._seconds_until_next_run()
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                return  # stop fired
            except TimeoutError:
                pass
            try:
                await self.run_once()
            except Exception as exc:
                logger.error("retention_run_failed", error=str(exc))

    def _seconds_until_next_run(self) -> float:
        now = datetime.now(UTC)
        today_target = now.replace(hour=self._hour_utc, minute=0, second=0, microsecond=0)
        target = today_target if now < today_target else today_target + timedelta(days=1)
        return (target - now).total_seconds()

    async def run_once(self) -> dict[str, int]:
        """Apply every policy once. Returns ``{table_or_tenant.table: rows_deleted}``."""
        started_at = datetime.now(UTC)
        results: dict[str, int] = {}
        self._skipped_this_run: set[str] = set()
        # Políticas que reventaron en esta pasada. Sin esta lista el ciclo se
        # cerraba siempre con `status='success'`: una tabla mal escrita o aún
        # sin migrar convertía la retención entera en un no-op que parecía
        # funcionar. Ver `_purge`.
        self._failed_this_run: list[str] = []
        logger.info("retention_run_started")

        # Tablas de plataforma (sin RLS): una pasada.
        async with self._session_factory() as session:
            for policy in PLATFORM_POLICIES:
                rows = await self._purge(session, policy, ambito="plataforma")
                results[f"plataforma.{policy.table}"] = rows
            await session.commit()

        # Negocios activos.
        if self._list_active_tenant_ids is None:
            logger.warning(
                "retention_sin_lista_de_tenants",
                motivo="list_active_tenant_ids no inyectado; se omiten las políticas de tenant",
            )
            tenants: list[uuid.UUID] = []
        else:
            tenants = list(await self._list_active_tenant_ids())

        # Fan out with a bounded semaphore. Each coroutine is wrapped with
        # ``asyncio.wait_for`` so one pathological tenant can't starve the
        # rest of the run. Results dict is merged after gather — tasks only
        # return their own slice to avoid cross-coroutine mutation races.
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _bounded(tenant_id: uuid.UUID) -> dict[str, int]:
            async with semaphore:
                return await self._run_one_tenant(tenant_id)

        tenant_results = await asyncio.gather(*(_bounded(tid) for tid in tenants), return_exceptions=False)
        for partial in tenant_results:
            results.update(partial)

        finished_at = datetime.now(UTC)
        await self._write_audit(started_at, finished_at, results, self._failed_this_run)
        skipped_count = len(self._skipped_this_run)
        logger.info(
            "retention_run_finished",
            total_rows=sum(results.values()),
            failed_policies=sorted(self._failed_this_run),
            skipped_tenants=skipped_count,
            skipped_tenant_ids=sorted(self._skipped_this_run) if skipped_count else [],
        )
        return results

    async def _run_one_tenant(self, tenant_id: uuid.UUID) -> dict[str, int]:
        """Run every TENANT_POLICIES entry for one tenant inside the
        configured per-tenant timeout. On timeout the partial progress is
        rolled back (the session context manager exits without commit) and
        a counter is emitted so ops can spot chronic slow tenants.

        We broaden the caught exceptions beyond ``TimeoutError``: when
        Postgres terminates the backend mid-run (``pg_terminate_backend``
        or a connection reset) the session raises ``OperationalError``
        rather than ``TimeoutError``. Without catching the SA error here
        a single killed tenant connection would crash the entire retention
        run and block every subsequent tenant. We tag the counter with
        ``reason="abort"`` for that path and ``reason="timeout"`` for the
        ``asyncio.wait_for`` path so alerts can distinguish a slow hook
        from pool flapping.
        """
        try:
            # Session setup is inside wait_for so a stalled connection
            # checkout (e.g. saturated pool) counts against the per-tenant
            # budget instead of hanging the whole run.
            return await asyncio.wait_for(
                self._purge_tenant(tenant_id),
                timeout=self._per_tenant_timeout_sec,
            )
        except TimeoutError:
            retention_tenant_skipped_counter.labels(reason="timeout").inc()
            if hasattr(self, "_skipped_this_run"):
                self._skipped_this_run.add(str(tenant_id))
            logger.warning(
                "retention_tenant_timeout",
                tenant_id=str(tenant_id),
                timeout_sec=self._per_tenant_timeout_sec,
            )
            return {}
        except (OperationalError, SQLAlchemyError) as exc:
            retention_tenant_skipped_counter.labels(reason="abort").inc()
            if hasattr(self, "_skipped_this_run"):
                self._skipped_this_run.add(str(tenant_id))
            logger.warning(
                "retention_tenant_aborted",
                tenant_id=str(tenant_id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {}

    async def _purge_tenant(self, tenant_id: uuid.UUID) -> dict[str, int]:
        partial: dict[str, int] = {}
        # El ContextVar se siembra para los pre-purge hooks, que abren sus
        # propias sesiones (el de `files` borra el objeto del bucket antes de
        # que desaparezca la fila). El acotado del DELETE de esta sesión lo hace
        # el `WHERE tenant_id`, porque la sesión de plataforma salta la policy.
        marca = current_tenant_id.set(tenant_id)
        try:
            async with self._session_factory() as session:
                for policy in TENANT_POLICIES:
                    rows = await self._purge(session, policy, ambito=str(tenant_id), tenant_id=tenant_id)
                    if rows:
                        partial[f"{tenant_id}.{policy.table}"] = rows
                await session.commit()
        finally:
            current_tenant_id.reset(marca)
        return partial

    async def _purge(
        self,
        session,
        policy: RetentionPolicy,
        ambito: str,
        tenant_id: uuid.UUID | None = None,
    ) -> int:
        # Acotado explícito por negocio. La sesión del runner es la de
        # plataforma (`BYPASSRLS`), así que la policy `tenant_isolation` NO
        # filtra aquí: sin este `AND tenant_id = :tenant_id`, una política de
        # tenant borraría las filas vencidas de TODOS los negocios en la
        # primera iteración y devolvería cero en las demás. El síntoma sería un
        # informe de retención con números absurdos, no un error.
        acotado = " AND tenant_id = :tenant_id" if tenant_id is not None else ""
        parametros = {"tenant_id": str(tenant_id)} if tenant_id is not None else {}

        # ## Por qué cada política va dentro de un SAVEPOINT
        #
        # Todas las políticas del mismo ámbito comparten UNA transacción. En
        # PostgreSQL, un error deja la transacción **abortada**: cualquier
        # sentencia posterior falla con `current transaction is aborted`. Como
        # aquí los errores se tragan y se devuelve 0, el efecto real era este:
        # una sola tabla mal escrita —o todavía sin migrar— hacía que TODAS las
        # políticas siguientes de la pasada devolvieran 0 en silencio y el ciclo
        # se cerrara como `retention_run_finished` con éxito y una fila de
        # auditoría `status='success'`. La retención entera se convertía en un
        # no-op que parecía funcionar.
        #
        # `begin_nested()` emite un SAVEPOINT: al fallar se revierte solo esta
        # política y la transacción externa sigue utilizable, así que las demás
        # se aplican de verdad. Y el fallo se anota en `_failed_this_run` para
        # que la fila de auditoría diga `status='failure'` en vez de mentir.
        etiqueta = f"{ambito}.{policy.table}"

        def _anotar_fallo(evento: str, exc: Exception, **extra) -> int:
            if hasattr(self, "_failed_this_run"):
                self._failed_this_run.append(etiqueta)
            logger.warning(
                evento,
                ambito=ambito,
                table=policy.table,
                error=str(exc),
                error_type=type(exc).__name__,
                **extra,
            )
            return 0

        hook = self._hooks.get(policy.table)
        if hook is None:
            try:
                async with session.begin_nested():
                    result = await session.execute(
                        text(f"DELETE FROM {policy.table} WHERE ({policy.condition}){acotado}"),
                        parametros,
                    )
                    return result.rowcount or 0
            except Exception as exc:
                return _anotar_fallo("retention_purge_error", exc)

        # Con hook: SELECT de las filas → hook → DELETE por id. Si el hook
        # revienta, las filas se quedan y retención lo reintenta el ciclo
        # siguiente. El SAVEPOINT abarca las dos sentencias y el hook, así que
        # un hook a medias no deja el SELECT aplicado ni la transacción rota.
        try:
            async with session.begin_nested():
                rows = (
                    (
                        await session.execute(
                            text(f"SELECT * FROM {policy.table} WHERE ({policy.condition}){acotado}"),
                            parametros,
                        )
                    )
                    .mappings()
                    .all()
                )
        except Exception as exc:
            return _anotar_fallo("retention_purge_error", exc)
        if not rows:
            return 0
        try:
            await hook(session, list(rows))
        except Exception as exc:
            # El hook NO es un fallo de política: es el caso previsto de "el
            # bucket no responde, dejamos las filas para el ciclo siguiente".
            # No marca la pasada como fallida, pero sí se registra.
            logger.warning(
                "retention_pre_purge_hook_failed",
                ambito=ambito,
                table=policy.table,
                row_count=len(rows),
                error=str(exc),
            )
            return 0
        ids = [r["id"] for r in rows]
        try:
            async with session.begin_nested():
                stmt = text(f"DELETE FROM {policy.table} WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
                result = await session.execute(stmt, {"ids": ids})
                return result.rowcount or 0
        except Exception as exc:
            return _anotar_fallo("retention_purge_error", exc)

    async def _write_audit(
        self,
        started_at: datetime,
        finished_at: datetime,
        results: dict[str, int],
        failed: list[str] | None = None,
    ) -> None:
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        import json as _json

        fallidas = sorted(set(failed or ()))
        cambios: dict[str, object] = {k: v for k, v in results.items() if v > 0}
        if fallidas:
            # Va dentro de `changes` a propósito: quien lee la fila de
            # auditoría tiene que poder saber QUÉ política falló sin volver al
            # log de la aplicación.
            cambios["politicas_fallidas"] = fallidas
        changes_json = _json.dumps(cambios)
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO audit_events (
                        id, timestamp, service_name, action, resource_type,
                        status, duration_ms, changes
                    ) VALUES (
                        gen_random_uuid(), :ts, :svc, 'retention.run', 'retention',
                        :status, :duration, CAST(:changes AS jsonb)
                    )
                    """
                ),
                {
                    "ts": finished_at,
                    "svc": self._service_name,
                    # Antes era `"success" if total >= 0 else "failure"`, que es
                    # siempre "success" porque una suma de conteos nunca es
                    # negativa. Ahora la fila dice la verdad.
                    "status": "failure" if fallidas else "success",
                    "duration": duration_ms,
                    "changes": changes_json,
                },
            )
            await session.commit()
