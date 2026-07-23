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
    - ``development`` → **the path to the mkcert root CA**, so the local
      chain is verified rather than ignored. Falls back to ``True`` when
      that CA can't be located.
    - everything else (``staging``, ``production``, unset) → ``True``.

Fail-safe bias: when in doubt, verify. A dev who really wants the old
behaviour can set ``KEYCLOAK_VERIFY_SSL=false`` and accept the warning.

Why ``development`` stopped returning ``False``
-----------------------------------------------
It used to. That was inherited from BaseSaaS, where the only HTTPS hop
in development was a self-signed cert on the in-network KC container.
In Vendi that premise is simply false:

- Inside the compose network the API reaches Keycloak over **plain
  HTTP** (``KEYCLOAK_URL: http://keycloak:8080``), so ``verify`` never
  even applies there. Returning ``False`` bought nothing.
- The only caller that does speak HTTPS in development is the test
  suite on the host, going to ``https://accounts.vendi.co`` through
  Traefik with a **mkcert** certificate — a chain that verifies
  perfectly well. Turning verification off was pure downside.

And the downside was not theoretical. ``vendi.co`` is a **real,
registered TLD**: when the local resolver is missing, the name resolves
to a public host on the Internet. With ``verify=False`` the client would
hand the ``vendi-provisioning`` client secret to whatever answered,
without so much as checking whose certificate it was. Anchoring to the
mkcert CA makes that impossible: no third party can present a chain
signed by a CA that only exists on this laptop.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

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


def mkcert_ca_bundle() -> str | None:
    """Absolute path to the mkcert root CA, or ``None`` if not on this box.

    Resolution order, cheapest and most explicit first:

    1. ``VENDI_MKCERT_CAROOT`` — escape hatch for CI images and for anyone
       whose CA lives somewhere unusual.
    2. ``mkcert -CAROOT`` — the authoritative answer when the tool is
       installed. Guarded with a timeout so a wedged binary can't hang an
       outbound request path.
    3. The documented per-platform defaults, so the lookup still works on a
       machine that has the CA but not the ``mkcert`` binary.

    Returns ``None`` rather than raising: every caller has a safe fallback
    (verify against the system trust store), and failing to find a *dev*
    convenience must never take down a request.
    """
    explicito = os.getenv("VENDI_MKCERT_CAROOT", "").strip()
    candidatos: list[pathlib.Path] = []
    if explicito:
        candidatos.append(pathlib.Path(explicito))
    else:
        try:
            salida = subprocess.run(  # noqa: S603
                ["mkcert", "-CAROOT"],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if salida.returncode == 0 and salida.stdout.strip():
                candidatos.append(pathlib.Path(salida.stdout.strip()))
        except (OSError, subprocess.SubprocessError):
            pass
        hogar = pathlib.Path.home()
        candidatos += [
            hogar / "Library" / "Application Support" / "mkcert",  # macOS
            hogar / ".local" / "share" / "mkcert",  # Linux
        ]

    for raiz in candidatos:
        ca = raiz / "rootCA.pem"
        if ca.is_file():
            return str(ca)
    return None


def keycloak_ssl_verify() -> bool | str:
    """Return the TLS-verification setting for outbound KC calls.

    ``True`` (verify against the system trust store), ``False`` (do not
    verify — only on an explicit operator override), or a **path to a CA
    bundle**, which is what development uses so the local mkcert chain is
    verified instead of ignored. ``requests``/``httpx`` accept all three
    for their ``verify`` argument.

    Note for whoever comes to silence the ``DeprecationWarning``: httpx
    wants an ``ssl.SSLContext`` instead of a path these days, but
    ``requests`` does **not** accept one — and python-keycloak uses
    requests for its sync calls and httpx for the ``a_*`` async ones,
    with this single value feeding both. A plain path is the only form
    the two agree on. Swapping it for an ``SSLContext`` fixes the warning
    and breaks every synchronous Keycloak call.

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
        # Anchor to the local CA instead of switching verification off.
        # This is what makes it structurally impossible for a development
        # client to complete a handshake with a host that isn't ours: no
        # public CA can sign a chain that validates against this root.
        ca = mkcert_ca_bundle()
        if ca is not None:
            return ca
        logger.warning(
            "keycloak_ssl_verify_sin_ca_de_mkcert",
            reason="no se encontró rootCA.pem de mkcert; se verifica contra el almacén del sistema",
            hint="ejecuta 'mkcert -install' o define VENDI_MKCERT_CAROOT",
        )
    return True
