"""TLS-verification policy for outbound calls to Keycloak.

Historical context: every httpx call-site that talks to Keycloak used to
hardcode ``verify=False``. That's correct for ``docker compose`` (self-
signed cert on the in-network KC container) but wrong everywhere else —
it silently disables the TLS handshake in staging and production, so a
MITM inside the cluster network would be undetectable.

``keycloak_ssl_verify()`` centralises the decision:

- ``KEYCLOAK_VERIFY_SSL`` — explicit operator override, truthy/falsy
  (``true``/``false``/``1``/``0``/``yes``/``no``, case-insensitive). If
  set to a falsy value we still return ``False`` but emit a warning so
  the choice can't rot unnoticed. Garbage values are ignored and we fall
  back to the default.
- ``APP_ENV`` — when no explicit override is present:
    - ``development`` → ``False`` (compose self-signed certs).
    - everything else (``staging``, ``production``, unset) → ``True``.

Fail-safe bias: when in doubt, verify. A dev who really wants the old
behaviour can set ``KEYCLOAK_VERIFY_SSL=false`` and accept the warning.
"""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger()

_TRUTHY = {"true", "1", "yes", "on"}
_FALSY = {"false", "0", "no", "off"}


def _parse_bool(raw: str | None) -> bool | None:
    """Return True/False for a recognised boolean literal, else None."""
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return None


def keycloak_ssl_verify() -> bool:
    """Return whether outbound KC httpx calls should verify TLS certs.

    Reads env on every call (not cached) so a test that flips
    ``APP_ENV`` mid-run sees the new value, and operators who rotate
    env-vars via a sidecar don't need a process restart to take effect.
    """
    override = _parse_bool(os.getenv("KEYCLOAK_VERIFY_SSL"))
    if override is False:
        # Explicit opt-out deserves a loud record. A single WARNING per
        # call-site is acceptable here because this helper is invoked
        # once per KC HTTP request; we'd rather repeat ourselves in logs
        # than silently paper over an insecure config.
        logger.warning(
            "keycloak_ssl_verify_disabled",
            reason="KEYCLOAK_VERIFY_SSL explicit override",
            app_env=os.getenv("APP_ENV", ""),
        )
        return False
    if override is True:
        return True

    # No explicit override — pick a default by environment.
    app_env = (os.getenv("APP_ENV") or "").strip().lower()
    if app_env == "development":
        return False
    return True
