"""Attach an ``X-API-Version`` header (and, when applicable, ``Deprecation`` +
``Sunset`` per RFC 8594) to every response.

Making the served API version *explicit* in the response is the cheapest piece
of the versioning contract: clients, proxies, and log pipelines can record the
version without parsing URLs, and the header shows up on error responses where
the URL routing may not have matched anything.

When a route is in the deprecation registry, this middleware also emits the
RFC 8594 ``Deprecation: true`` and ``Sunset: <HTTP-date>`` headers so well-behaved
clients (and proxies that surface deprecation in their UI) get a structured
heads-up months before the route disappears.

Declaration of which version is served stays with each service
(``app.config.API_VERSION`` in platform-service). When v2 ships, the middleware
should emit ``v2`` for routes mounted under ``/api/v2/*`` and keep ``v1`` for
legacy routes — see ``docs/runbooks/api-versioning.md`` for the fork recipe.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from email.utils import format_datetime

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


def _format_http_date(iso_date: str) -> str:
    """Convert ``YYYY-MM-DD`` to the RFC 7231 IMF-fixdate format both
    ``Deprecation`` and ``Sunset`` headers require."""
    parsed = datetime.combine(
        datetime.fromisoformat(iso_date).date(),
        time(tzinfo=UTC),
    )
    return format_datetime(parsed, usegmt=True)


class APIVersionMiddleware(BaseHTTPMiddleware):
    """Stamp ``X-API-Version`` (plus optional ``Deprecation`` / ``Sunset``).

    ``deprecated_routes`` maps a path *prefix* to a sunset date string in
    ``YYYY-MM-DD`` form. Any request whose ``url.path`` starts with one of
    those prefixes gets ``Deprecation: true`` + ``Sunset: <HTTP-date>``
    attached to the response. The map is empty by default — the middleware
    is a no-op for new forks until they explicitly register a deprecation,
    which keeps the wire format predictable.
    """

    def __init__(
        self,
        app,
        version: str = "v1",
        deprecated_routes: dict[str, str] | None = None,
    ) -> None:
        super().__init__(app)
        self._version = version
        # Pre-compute the HTTP-date string per prefix so we don't reformat
        # on every request. A bad ISO date raises at wiring time, which is
        # the right place to surface a typo'd sunset.
        self._sunset_by_prefix: dict[str, str] = {
            prefix: _format_http_date(iso) for prefix, iso in (deprecated_routes or {}).items()
        }

    def _sunset_for(self, path: str) -> str | None:
        # Longest-match wins so a more specific deprecated subroute can
        # override a broader prefix's sunset (e.g. ``/api/v1/users`` vs
        # ``/api/v1/users/legacy``).
        match = ""
        for prefix in self._sunset_by_prefix:
            if path.startswith(prefix) and len(prefix) > len(match):
                match = prefix
        return self._sunset_by_prefix[match] if match else None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        # Don't clobber a value set by downstream code (e.g. a v2 router that
        # already wrote ``v2``). This keeps the middleware a safe default.
        response.headers.setdefault("X-API-Version", self._version)
        sunset = self._sunset_for(request.url.path)
        if sunset is not None:
            response.headers.setdefault("Deprecation", "true")
            response.headers.setdefault("Sunset", sunset)
        return response
