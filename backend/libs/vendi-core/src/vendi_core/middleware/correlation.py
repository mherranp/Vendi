import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from vendi_core.tracing.context import bind_correlation_id, clear_context

# W3C traceparent format: "version-traceid-parentid-flags" (00-<32hex>-<16hex>-<2hex>).
# See https://www.w3.org/TR/trace-context/#traceparent-header. We only need the
# trace-id (second group) — the parent span id is not useful as a correlation
# key because it changes between hops.
_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-(?P<parent_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)
# Invalid trace-id per spec: all zeros. Treat as absent so we don't mint
# worthless correlation ids.
_INVALID_TRACE_ID = "0" * 32


def _extract_trace_id(traceparent: str | None) -> str | None:
    """Return the trace-id portion of a W3C ``traceparent`` header, or None.

    Rejects malformed headers and the all-zeros trace-id (spec-invalid). Kept
    as a pure helper so tests can exercise the parse without spinning up a
    FastAPI app.
    """

    if not traceparent:
        return None
    match = _TRACEPARENT_RE.match(traceparent.strip())
    if not match:
        return None
    trace_id = match.group("trace_id")
    if trace_id == _INVALID_TRACE_ID:
        return None
    return trace_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Adds a correlation ID to each request and binds it to structlog context.

    Precedence (highest first):

    1. ``X-Correlation-ID`` — an explicit correlation id set by a caller.
       Services-of-services need this to keep an upstream-chosen id
       authoritative across the whole downstream fan-out.
    2. ``traceparent`` — W3C trace context header. When present, we reuse its
       trace-id as the correlation id so log lines and spans share a single
       pivot in the observability stack (no mental join between two ids per
       request). Requires ``OTEL_EXPORTER_OTLP_ENDPOINT`` to produce usable
       spans, but the merge itself is free of OTEL dependencies.
    3. Fresh UUID4 — the historical default; still the right answer when
       neither upstream header is present.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        explicit = request.headers.get("X-Correlation-ID")
        if explicit:
            correlation_id = explicit
        else:
            trace_id = _extract_trace_id(request.headers.get("traceparent"))
            correlation_id = trace_id or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        bind_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            clear_context()
        response.headers["X-Correlation-ID"] = correlation_id
        return response
