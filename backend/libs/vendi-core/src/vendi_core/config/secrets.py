"""Pluggable secret resolution.

Purpose
-------
Give every service a single entry point to read a secret, so we can flip the
*where* without touching the *what*. Two backends ship in v1:

- ``env`` (default) — read from an environment variable. This is what dev +
  docker-compose + CI already do; everything keeps working.
- ``file`` — read from ``/run/secrets/<name>`` (Docker / Kubernetes secret
  mount convention). Enabled in prod by setting ``SECRETS_BACKEND=file``.

Selecting the backend is an env variable (``SECRETS_BACKEND``) rather than a
per-service knob on purpose: a deployment unit has one secrets delivery
mechanism, and mixing the two inside a single service is almost always an
operational mistake.

Future backends
---------------
When we need Vault / AWS Secrets Manager / Azure Key Vault, add a new backend
branch below (e.g. ``SECRETS_BACKEND=vault``) and an adapter module. The
``resolve_secret`` signature is the seam; callers do not change. Do **not**
add SDK dependencies here — keep the foundation dependency graph small.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_FILE_ROOT = Path("/run/secrets")

# Sentinel so ``default=None`` stays a valid explicit value.
_MISSING = object()


def _backend() -> str:
    """Return the active secrets backend id.

    Accepts ``env`` or ``file``; anything else is treated as ``env`` so a typo
    in a deploy manifest does not silently fall through to a missing secret.
    """

    raw = (os.environ.get("SECRETS_BACKEND") or "env").strip().lower()
    if raw not in {"env", "file"}:
        return "env"
    return raw


def _file_root() -> Path:
    """Root directory for file-backed secrets.

    Overridable via ``SECRETS_FILE_ROOT`` (tests, non-standard mount paths).
    """

    override = os.environ.get("SECRETS_FILE_ROOT")
    return Path(override) if override else _DEFAULT_FILE_ROOT


def resolve_secret(name: str, default: str | None | object = _MISSING) -> str:
    """Resolve a secret by logical name.

    Parameters
    ----------
    name:
        Logical secret name (e.g. ``"MAIL_FERNET_KEY"``). Case is preserved
        for file lookups and uppercased for env lookups, so call sites can
        use the same canonical name regardless of backend.
    default:
        Returned when the active backend has no value for ``name``. If
        omitted, a missing secret raises ``RuntimeError`` — callers opt into
        "tolerate missing" explicitly.

    Resolution order
    ----------------
    Exactly one backend is consulted. We never silently fall back from
    ``file`` to ``env``: a missing file in ``file`` mode is a deploy bug,
    not a cue to reach for the process environment.
    """

    backend = _backend()

    if backend == "file":
        path = _file_root() / name
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _fallback_or_raise(name, default, backend, reason=f"file {path} not found")
        # Trailing newlines are the norm for ``echo "secret" > file`` flows;
        # strip a single trailing newline but preserve anything intentional.
        return raw.rstrip("\n")

    # backend == "env"
    env_key = name.upper()
    value = os.environ.get(env_key)
    if value is None or value == "":
        return _fallback_or_raise(name, default, backend, reason=f"env var {env_key} unset")
    return value


def _fallback_or_raise(name: str, default: str | None | object, backend: str, *, reason: str) -> str:
    if default is _MISSING:
        raise RuntimeError(
            f"Secret '{name}' not found via SECRETS_BACKEND={backend} ({reason}) and no default was provided."
        )
    # ``default`` may be ``None``; callers that pass it accept the Optional.
    # We still return ``str`` for happy-path typing — None-accepting callers
    # will type-check on their end.
    return default  # type: ignore[return-value]
