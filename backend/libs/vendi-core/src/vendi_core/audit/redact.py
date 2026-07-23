"""Field-name redaction for audit event payloads.

We never want secret-shaped field names (``password``, ``client_secret``,
``token``, …) to land in the audit log's ``metadata`` or ``changes``
dictionaries — even though the current call sites don't put them there,
a future refactor that serialises an incoming request body straight into
``metadata`` would silently leak the secret.

``redact_secrets`` walks a dict (or nested dicts / lists) and replaces any
value whose key matches :data:`SECRET_FIELD_NAMES` with ``"***"``. Match
is case-insensitive and substring-based so ``new_password`` / ``api_key``
/ ``client_secret`` all hit. Non-dict inputs are returned unchanged.

The ``AuditService._write`` path calls this before persisting, so every
audit row benefits from the redaction — including rows written through
the ``audit_operation`` decorator and ad-hoc ``audit_service.log`` calls
scattered across routers.
"""

from __future__ import annotations

from typing import Any

#: Substrings (case-insensitive) that flag a field as a secret.
#:
#: Kept intentionally broad — a false positive just shows ``"***"`` in
#: the audit log, while a false negative leaks a credential. Add new
#: substrings here as new secret-shaped fields appear in the codebase.
SECRET_FIELD_NAMES: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "client_secret",
    "token",
    "access_key",
    "api_key",
    "private_key",
    "fernet",
    "authorization",
)

_REDACTED = "***"


def _is_secret_name(name: str) -> bool:
    low = name.lower()
    return any(needle in low for needle in SECRET_FIELD_NAMES)


def redact_secrets(value: Any) -> Any:
    """Return ``value`` with secret-shaped fields replaced by ``"***"``.

    * ``dict`` — recurse into values; replace at keys matching
      :data:`SECRET_FIELD_NAMES` (case-insensitive substring).
    * ``list`` / ``tuple`` — recurse into elements.
    * anything else — returned as-is.

    The function is pure; it never mutates the input.
    """
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_secret_name(k):
                out[k] = _REDACTED
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(v) for v in value)
    return value
