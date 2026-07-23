"""Defense-in-depth response-body secret redactor.

Problem
-------

Endpoints that mint one-time credentials (service-account create, API-key
rotate, OIDC provider bootstrap) must return the plaintext secret to the
caller exactly once. The audit-row redactor (:mod:`vendi_core.audit.redact`)
keeps secrets out of ``audit_events.metadata``, but a log-everything
"response body" middleware — added by a future observability sweep, or a
third-party access-log integration that captures bodies — would still end
up serialising those same credentials into structured logs / traces.

This middleware installs a single process-wide hook:

 1. When a 2xx JSON response carries a known secret-shaped field at any
    depth (``client_secret``, ``access_token``, ``refresh_token``, plus the
    rest of :data:`SECRET_FIELD_NAMES`), a redacted copy is stashed on
    ``request.state.redacted_response_body`` BEFORE the original bytes go
    out on the wire. Downstream access-log middlewares read that attribute
    instead of the raw response body — the HTTP caller still sees the
    plaintext (by design: one-time reveal), but any logger that opts into
    the redacted view never learns the secret.

 2. The redaction is pure-dict / pure-list — it reuses
    :func:`vendi_core.audit.redact.redact_secrets` so the needle list is
    single-sourced with the audit redactor.

The middleware is a no-op for:

 - non-JSON responses (Content-Type without ``application/json``),
 - 4xx / 5xx responses (error bodies don't carry freshly-minted secrets),
 - streaming responses (we don't buffer arbitrary streams — a streaming
   secret would be a bug in the handler, not a redaction miss). Enforced
   by two guards at dispatch time: an ``isinstance(..., StreamingResponse)``
   check plus a "no Content-Length" check (chunked responses omit it).
 - responses whose advertised ``Content-Length`` exceeds
   :data:`SECRET_REDACTOR_MAX_BODY_BYTES` (default 1 MiB) — tenant
   exports, audit CSVs, etc. must not be buffered into RAM to satisfy a
   redactor that only cares about small one-time-reveal payloads.

It is deliberately low-overhead: a fast path returns early when the body
doesn't parse as JSON or when no known secret-name appears in the raw
bytes (substring scan before the full json.loads).
"""

from __future__ import annotations

import json
import os

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from vendi_core.audit.redact import SECRET_FIELD_NAMES, redact_secrets

logger = structlog.get_logger()

# Lowercased needles — a single substring scan against the raw response body
# tells us whether the full json.loads + deep redaction is worth doing. A
# response like ``{"items": [...]}`` that contains none of these needles
# skips the parse entirely.
_SECRET_NEEDLES_BYTES = tuple(n.encode("ascii") for n in SECRET_FIELD_NAMES)

# Pre-buffering size ceiling. Large responses (tenant export ~50MB, audit CSV
# many MB) must NOT be buffered in memory by this middleware — the redactor
# only needs to observe one-time-reveal bodies, which are tiny. Anything over
# the threshold short-circuits to pass-through. Override via
# ``SECRET_REDACTOR_MAX_BODY_BYTES`` (bytes).
_DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MiB
try:
    SECRET_REDACTOR_MAX_BODY_BYTES: int = int(os.environ.get("SECRET_REDACTOR_MAX_BODY_BYTES", _DEFAULT_MAX_BODY_BYTES))
except ValueError:
    SECRET_REDACTOR_MAX_BODY_BYTES = _DEFAULT_MAX_BODY_BYTES


def _body_might_contain_secret(body: bytes) -> bool:
    """Fast pre-filter: True iff any secret needle appears in ``body``.

    Case-insensitive — we lowercase the body once. The needle list is
    already lowercased (:data:`SECRET_FIELD_NAMES`). This is a string scan,
    not a JSON parse, so the cost is linear in body size + cheap enough to
    run on every response.
    """
    if not body:
        return False
    low = body.lower()
    return any(needle in low for needle in _SECRET_NEEDLES_BYTES)


class SecretRedactorMiddleware(BaseHTTPMiddleware):
    """Stamp ``request.state.redacted_response_body`` on 2xx JSON responses.

    Does NOT alter the outgoing HTTP body — the caller still receives the
    plaintext (which is correct for a one-time-reveal endpoint). The
    redacted copy is parked on ``request.state`` so an access-log /
    response-body-logger middleware downstream can opt into the redacted
    view by reading ``getattr(request.state, "redacted_response_body", None)``
    rather than the raw bytes.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Skip non-JSON / error / streaming responses cheaply. ``body_iterator``
        # is the Starlette streaming primitive; we only buffer when the
        # response is already a plain byte-body response (the default for
        # FastAPI's ``response_model=`` serialisation).
        if response.status_code < 200 or response.status_code >= 300:
            return response
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            return response

        # Guard 1 — genuine streaming responses (e.g. tenant export,
        # audit CSV/JSON stream) must pass through untouched. Buffering
        # them would both consume the stream (breaking client-side
        # streaming semantics) and pin the full body in RAM. The
        # redactor's contract is "observe fully-formed JSON bodies"; a
        # streaming response is not fully-formed at this point.
        #
        # Detection is two-pronged:
        #
        #  (a) An ``isinstance(response, StreamingResponse)`` check —
        #      belt-and-suspenders, defensive against middleware stacks
        #      that might surface the original subtype.
        #  (b) Absence of a ``Content-Length`` header. Under
        #      ``BaseHTTPMiddleware`` the ``response`` is always a
        #      ``BaseHTTPMiddleware._StreamingResponse`` wrapper whose
        #      raw headers are copied from the downstream response, so
        #      isinstance alone won't fire; the real signal is that
        #      ``StreamingResponse`` emits chunked transfer encoding
        #      without a Content-Length, whereas ``Response`` /
        #      ``JSONResponse`` (the bodies we care about redacting)
        #      always set it.
        if isinstance(response, StreamingResponse):
            logger.debug(
                "secret_redactor_skipped_streaming_response",
                path=request.url.path,
                reason="isinstance",
            )
            return response
        content_length_header = response.headers.get("content-length")
        if content_length_header is None:
            logger.debug(
                "secret_redactor_skipped_streaming_response",
                path=request.url.path,
                reason="no_content_length",
            )
            return response

        # Guard 2 — Content-Length based pre-buffering size check.
        # If the route advertises a body larger than the threshold,
        # pass through without buffering. This protects against the
        # large-body memory trap for non-streaming responses that
        # nonetheless carry a big payload.
        try:
            content_length = int(content_length_header)
        except ValueError:
            content_length = -1
        if content_length > SECRET_REDACTOR_MAX_BODY_BYTES:
            logger.debug(
                "secret_redactor_skipped_large_body",
                path=request.url.path,
                content_length=content_length,
                threshold=SECRET_REDACTOR_MAX_BODY_BYTES,
            )
            return response

        # Starlette's BaseHTTPMiddleware wraps the downstream response in an
        # internal ``_StreamingResponse`` whose ``body_iterator`` yields bytes
        # chunks. The base ``Response`` type doesn't declare that attribute
        # (mypy correctly flags ``response.body_iterator`` as missing), so we
        # introspect via ``getattr`` and degrade gracefully if a future
        # Starlette version renames or removes it — the redactor is a
        # defense-in-depth log scrubber, not a security control, so failing
        # open with a WARNING is preferable to a 500 on every request.
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is None:
            logger.warning(
                "secret_redactor_no_body_iterator",
                path=request.url.path,
                response_type=type(response).__name__,
            )
            return response
        body_chunks: list[bytes] = []
        async for chunk in body_iterator:
            body_chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
        body = b"".join(body_chunks)

        if _body_might_contain_secret(body):
            try:
                parsed = json.loads(body)
            except (ValueError, TypeError):
                parsed = None
            if parsed is not None:
                try:
                    request.state.redacted_response_body = redact_secrets(parsed)
                except Exception as exc:  # pragma: no cover — defensive
                    logger.warning(
                        "secret_redactor_failed",
                        error=str(exc),
                        path=request.url.path,
                    )

        # Re-emit the original body unchanged — the caller MUST still see the
        # one-time secret. Preserve status, headers (minus content-length —
        # Starlette will re-compute it), and media_type.
        headers = dict(response.headers)
        # Drop content-length; Response will re-set it from the new body.
        headers.pop("content-length", None)
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )


__all__ = ["SecretRedactorMiddleware"]
