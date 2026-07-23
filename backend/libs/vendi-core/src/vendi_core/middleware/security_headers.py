"""HTTP security-headers middleware.

Stamps every response with a baseline set of defense-in-depth headers that
cost nothing to add and are cheap to get right once. Products can tune the
Content-Security-Policy per-deployment via the ``SECURITY_CSP`` env var
(empty / unset = use this module's default).

Header set (see ``_STATIC_HEADERS`` for the literal values):

* ``X-Content-Type-Options: nosniff`` — stop browsers from MIME-sniffing
  uploads and rendering them as HTML / script.
* ``X-Frame-Options: DENY`` — block framing entirely. We intentionally pick
  ``DENY`` over ``SAMEORIGIN``: the admin/app/www subdomains never embed
  each other via ``<iframe>``, so the tighter value is a free win. Products
  that *do* need ``SAMEORIGIN`` can wrap / subclass this middleware.
* ``Referrer-Policy: strict-origin-when-cross-origin`` — only send the
  origin (no path / query) when navigating off-domain.
* ``Permissions-Policy: camera=(), microphone=(), geolocation=()`` —
  deny-by-default for the three APIs that most often leak via 3rd-party
  iframes. Products that need these open them explicitly per route.
* ``Strict-Transport-Security: max-age=31536000; includeSubDomains`` —
  1-year HSTS pin. Only attached when ``APP_ENV=production`` **and** the
  request arrived via HTTPS (check ``request.url.scheme``). Attaching HSTS
  over plaintext HTTP is ignored by browsers but confuses reverse proxies;
  guarding prevents accidental dev-stack breakage.
* ``Content-Security-Policy`` — starter policy. Every product should
  review + tighten; Angular SPAs typically want nonce-based ``script-src``
  instead of ``'unsafe-inline'``. Tuning guide:
  ``docs/runbooks/security-headers.md``.

Wired into ``vendi_core.app.factory.create_app`` so every service picks
this up automatically. Placed *after* CORSMiddleware in middleware order
so preflight OPTIONS responses also carry the security headers (defence in
depth; most browsers ignore them on CORS preflights but it's cheap).
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Static header set — identical on every response regardless of env.
_STATIC_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


#: Default Content-Security-Policy. Intentionally permissive enough that a
#: vanilla Angular 21 SPA + FastAPI backend works out of the box, and tight
#: enough that the common XSS / clickjack vectors are blocked. Products
#: review + tighten on a per-deployment basis — in particular swapping
#: ``'unsafe-inline'`` on ``script-src`` for a nonce once the SPA build is
#: audited.
DEFAULT_CSP: str = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self' https: wss:; "
    "frame-ancestors 'none'"
)


#: One-year HSTS pin with subdomain coverage. Not ``preload``: we leave
#: preload-list opt-in to the deployer because it's a one-way trip that
#: can brick a product if a sub-cert isn't renewed.
HSTS_VALUE: str = "max-age=31536000; includeSubDomains"


def _resolve_csp(override: str | None) -> str:
    """Pick CSP: explicit override > ``SECURITY_CSP`` env var > module default.

    Factored so tests can exercise all three branches without monkey-patching
    the module constant. Whitespace-only env values are treated as unset so
    ``SECURITY_CSP=''`` doesn't accidentally strip the header entirely.
    """
    if override and override.strip():
        return override
    env = os.getenv("SECURITY_CSP")
    if env and env.strip():
        return env
    return DEFAULT_CSP


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds standard security response headers on every response.

    Parameters
    ----------
    app:
        The ASGI app (passed automatically by ``add_middleware``).
    csp:
        Explicit Content-Security-Policy override. ``None`` → read
        ``SECURITY_CSP`` env var at request time, falling back to
        :data:`DEFAULT_CSP`. Pass an explicit string in tests that need
        deterministic behaviour independent of the process env.
    app_env:
        ``None`` (default) → read ``APP_ENV`` env var at request time.
        Only ``"production"`` enables the HSTS header; anything else keeps
        it off so dev stacks don't pin browsers to HTTPS for their
        ``localhost`` dev loop.
    """

    def __init__(
        self,
        app,
        *,
        csp: str | None = None,
        app_env: str | None = None,
    ) -> None:
        super().__init__(app)
        self._csp_override = csp
        self._app_env_override = app_env

    def _current_app_env(self) -> str:
        if self._app_env_override is not None:
            return self._app_env_override
        return os.getenv("APP_ENV", "development")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name, value in _STATIC_HEADERS.items():
            response.headers.setdefault(name, value)

        response.headers.setdefault("Content-Security-Policy", _resolve_csp(self._csp_override))

        # HSTS only makes sense over HTTPS in production. Attaching it over
        # plaintext HTTP is ignored by browsers but confuses some reverse
        # proxies and tools — guard so dev stacks never see it.
        if self._current_app_env() == "production" and request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)

        return response
