"""Mail provider interface. One implementation is shipped in v1 (SMTP)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage


class RetryableSendError(Exception):
    """Transient failure (4xx SMTP, timeout, connection reset). The worker will retry."""


class TerminalSendError(Exception):
    """Permanent failure (5xx SMTP, auth failed, invalid recipient). No retry."""


@dataclass(frozen=True)
class SmtpCredentials:
    host: str
    port: int
    username: str = ""
    password: str = ""
    use_tls: bool = True


@dataclass(frozen=True)
class SentMessage:
    provider_message_id: str | None  # Message-ID header for SMTP, or provider id for API providers


class MailProvider(ABC):
    """Abstract interface for delivering a rendered email.

    Implementations are stateless; per-account config (credentials, sender
    address) is passed in via the call — so the same provider instance can
    serve multiple tenants with different SMTP accounts.
    """

    @abstractmethod
    async def send(self, credentials: SmtpCredentials, message: EmailMessage) -> SentMessage:  # noqa: D401
        """Deliver ``message``. Raise ``RetryableSendError`` or ``TerminalSendError`` on failure."""
