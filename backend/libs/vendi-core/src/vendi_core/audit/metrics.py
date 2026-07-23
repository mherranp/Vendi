"""Prometheus counters for the audit subsystem.

Kept inside :mod:`vendi_core.audit` (rather than the per-service ``metrics``
modules) because every service that persists audit rows needs the same
failure-visibility signal — the counter labels on ``service_name`` so a
single ``vendi_audit_write_failed_total`` series can be sliced per
emitter in Grafana.

The counter is always incremented when :class:`AuditService` fails to
persist an event, independently of whether the configured failure mode
re-raises or swallows the exception. That way a silent
``AUDIT_WRITE_FAILURE_MODE=warn`` deployment still produces an alertable
signal.

``audit_write_failed_counter`` gains an extra ``reason`` label so the
pool-exhaust escalation path can be sliced separately from generic
persistence failures — ``reason="generic"`` is the historical bucket.

``suppressed_errors_counter`` exposes a single series for every
``except`` block across the foundation + services that is legitimately
best-effort but whose silence would hide real outages (Keycloak
idempotency races, usage-query services going down, invitation revoke
races). Each call site uses distinct ``(component, reason)`` labels so
a Grafana panel can pinpoint which silent path is firing.
"""

from __future__ import annotations

from prometheus_client import Counter

# vendi_audit_write_failed_total{service_name, reason} — incremented every
# time AuditService._write() raises (DB down, schema drift, serialization
# bug…). ``reason="pool_exhaust"`` singles out asyncpg TooManyConnectionsError
# / SQLAlchemy TimeoutError so alerting can distinguish "we're out of DB
# capacity" from "the audit row was malformed". Ops alerting:
# rate(vendi_audit_write_failed_total[5m]) > 0 is a compliance-grade
# signal that audit rows are being lost somewhere.
audit_write_failed_counter = Counter(
    "vendi_audit_write_failed_total",
    "Audit-event write failures by service.",
    ["service_name", "reason"],
)

# vendi_suppressed_errors_total{component, reason} — incremented at every
# best-effort ``except`` block where swallowing is intentional but the
# silence would otherwise mask outages. Labels:
#   * component — dotted name of the call site (e.g.
#     ``invitations.revoke.kc_delete``, ``tenants.usage.count_query``,
#     ``keycloak_admin.get_realm_role``).
#   * reason — the exception class seen (e.g. ``KeycloakError``,
#     ``SQLAlchemyError``, ``Exception``).
# Ops: rate(vendi_suppressed_errors_total[5m]) gives a fleet-wide
# "how noisy are our best-effort paths" signal; a spike on a specific
# label pair means that subsystem is degrading.
suppressed_errors_counter = Counter(
    "vendi_suppressed_errors_total",
    "Exceptions intentionally suppressed by best-effort call sites.",
    ["component", "reason"],
)
