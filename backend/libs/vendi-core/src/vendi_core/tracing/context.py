"""Contexto de observabilidad: correlación, tenant y usuario en los logs.

Cosechado de `base_saas.tracing.context`. Única adaptación: donde BaseSaaS
ligaba `tenant_slug` (schema-per-tenant), Vendi liga `tenant_id` — el mismo
UUID que viaja al GUC `vendi.tenant_id` de Postgres. Así una línea de log y
una fila de `pg_stat_activity` se cruzan por el mismo identificador.
"""

from contextvars import ContextVar

import structlog

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")


def bind_correlation_id(correlation_id: str) -> None:
    correlation_id_var.set(correlation_id)
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def bind_tenant_id(tenant_id: str) -> None:
    tenant_id_var.set(tenant_id)
    structlog.contextvars.bind_contextvars(tenant_id=tenant_id)


def bind_user_id(user_id: str) -> None:
    user_id_var.set(user_id)
    structlog.contextvars.bind_contextvars(user_id=user_id)


def get_correlation_id() -> str:
    return correlation_id_var.get()


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
