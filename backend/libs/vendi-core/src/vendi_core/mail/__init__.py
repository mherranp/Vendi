"""Correo de plataforma reducido: ver `system_mailer` para qué NO se portó."""

from vendi_core.mail.mime import build_mime
from vendi_core.mail.providers import (
    MailProvider,
    RetryableSendError,
    SentMessage,
    SmtpConnectionPool,
    SmtpProvider,
    TerminalSendError,
)
from vendi_core.mail.system_mailer import SystemMailer, SystemSmtpConfig

__all__ = [
    "MailProvider",
    "RetryableSendError",
    "SentMessage",
    "SmtpConnectionPool",
    "SmtpProvider",
    "SystemMailer",
    "SystemSmtpConfig",
    "TerminalSendError",
    "build_mime",
]
