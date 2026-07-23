"""Backwards-compat shim.

The security-headers middleware moved to
``vendi_core.middleware.security_headers`` so the module name matches its
responsibility — and leaves room for other security-adjacent middleware
(CSRF tokens, IP allow-lists, …) to land under ``security.*`` later.

Existing imports like ``from vendi_core.middleware.security import
SecurityHeadersMiddleware`` keep working via this re-export.
"""

from vendi_core.middleware.security_headers import SecurityHeadersMiddleware

__all__ = ["SecurityHeadersMiddleware"]
