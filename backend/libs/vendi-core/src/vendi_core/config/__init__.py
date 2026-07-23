"""Configuration primitives shared across services (secrets resolution, etc.)."""

from vendi_core.config.secrets import resolve_secret

__all__ = ["resolve_secret"]
