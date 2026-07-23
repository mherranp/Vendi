"""OpenTelemetry tracing wiring — opt-in via ``OTEL_EXPORTER_OTLP_ENDPOINT``.

Tracing is a foundation primitive: every backend service can bootstrap spans by
calling :func:`configure_tracing` from its lifespan. When the OTLP endpoint is
empty (the dev default) this is a no-op — no TracerProvider is installed, no
instrumentation is wired, no span data is emitted. Flip the env var to an
OTLP/HTTP collector URL (e.g. ``http://jaeger:4318/v1/traces``) and the
instrumentors attach transparently.

Design notes
------------

- **Instrumentors, not manual spans.** We rely on the auto-instrumentation
  packages so business code does not pepper itself with ``tracer.start_span``.
  FastAPI, SQLAlchemy, and HTTPX are covered today — add more instrumentors
  here as services grow them (e.g. ``opentelemetry-instrumentation-redis``).

- **W3C propagation is automatic.** Once ``FastAPIInstrumentor`` is wired it
  extracts the incoming ``traceparent`` header and attaches the same
  trace-id to downstream spans. The correlation-id middleware reads that same
  trace-id so log lines and traces share an id — see
  ``vendi_core.middleware.correlation``.

- **Imports are deferred** inside :func:`configure_tracing`. The
  ``opentelemetry-*`` packages are declared as the ``tracing`` extra on
  ``base-saas`` so a service that never traces never imports them.
"""

from __future__ import annotations

import os
from typing import Any


def configure_tracing(
    service_name: str,
    otlp_endpoint: str | None = None,
    app_env: str = "development",
    app: Any = None,
    engine: Any = None,
    service_version: str = "0.1.0",
) -> bool:
    """Install the OpenTelemetry TracerProvider + wire instrumentors.

    Parameters
    ----------
    service_name:
        Logical service identifier (``platform-service`` /
        ``storage-service`` / ``realtime-service`` / ``mail-worker``). Stamped
        on every emitted span via the ``service.name`` resource attribute.
    otlp_endpoint:
        OTLP/HTTP collector URL (e.g. ``http://jaeger:4318/v1/traces``). When
        empty or ``None`` tracing is disabled and this call returns ``False``.
    app_env:
        Deployment environment — becomes the ``deployment.environment``
        resource attribute. Kept free-form to match whatever each service's
        ``Settings.app_env`` holds (``development`` / ``staging`` /
        ``production``).
    app:
        The FastAPI ``app`` to wrap with ``FastAPIInstrumentor``. Optional —
        the mail-worker has no FastAPI app but still benefits from SQLAlchemy
        + HTTPX spans.
    engine:
        SQLAlchemy ``AsyncEngine`` (or sync ``Engine``) to instrument. The
        instrumentor attaches via the underlying sync engine, so async engines
        must expose ``.sync_engine`` — true for every engine built by
        :func:`vendi_core.db.engine.create_engine`.
    service_version:
        Value for the ``service.version`` resource attribute. Propagated from
        each service's ``Settings.api_version`` so traces can be sliced by
        deployed version.

    Returns
    -------
    bool
        ``True`` if tracing was configured, ``False`` if the endpoint was
        empty (opt-in no-op). Callers can log the outcome.
    """

    endpoint = (otlp_endpoint or "").strip()
    if not endpoint:
        # Tracing is opt-in. Without an OTLP endpoint we install nothing so
        # import-time cost + in-process span overhead stay at zero.
        return False

    # Deferred imports — otherwise services that never trace pay the import
    # cost of the whole opentelemetry package tree on every boot.
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource(
        attributes={
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": app_env,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    # FastAPI instrumentation is app-scoped (so tests don't accidentally
    # double-instrument a shared app) — skip when called without an app, as
    # mail-worker does.
    if app is not None:
        FastAPIInstrumentor.instrument_app(app)

    if engine is not None:
        # AsyncEngine wraps a sync engine; the SQLAlchemy instrumentor hooks
        # the sync engine directly. The ``.sync_engine`` attribute is stable
        # across SQLAlchemy 2.x — documented public API.
        sync_engine = getattr(engine, "sync_engine", engine)
        SQLAlchemyInstrumentor().instrument(engine=sync_engine)

    # HTTPX is process-global (patches the AsyncClient/Client send path).
    # Safe to call more than once — the instrumentor no-ops when already
    # installed.
    HTTPXClientInstrumentor().instrument()

    return True


def otlp_endpoint_from_env() -> str:
    """Read the OTLP endpoint from the canonical env var.

    Both the OpenTelemetry spec-defined ``OTEL_EXPORTER_OTLP_ENDPOINT`` and
    the pydantic-settings ``otel_exporter_otlp_endpoint`` resolve to the same
    name — we read directly from the environment here so helpers that don't
    carry a ``Settings`` instance (e.g. mail-worker bootstrap) still get the
    correct value.
    """

    return (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()


__all__ = ["configure_tracing", "otlp_endpoint_from_env"]
