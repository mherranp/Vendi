"""Async SMTP provider with per-account connection pool.

Ported & simplified from the MailSystem prototype. Keeps one LIFO pool of
connections per ``(host, port, user)`` tuple, reuses them across sends, closes
idle connections after a TTL.
"""

from __future__ import annotations

import asyncio
import ssl
import time
from email.message import EmailMessage

import aiosmtplib
import structlog

from vendi_core.audit.metrics import suppressed_errors_counter
from vendi_core.mail.providers.base import (
    MailProvider,
    RetryableSendError,
    SentMessage,
    SmtpCredentials,
    TerminalSendError,
)

logger = structlog.get_logger()


def _record_suppressed(component: str, exc: BaseException) -> None:
    """Log at WARN + bump ``suppressed_errors_counter`` for a swallowed SMTP error.

    SMTP teardown/release paths are legitimately best-effort (we can't do
    anything useful if ``quit()`` fails during cleanup) but a total silence
    hides sustained outages. Every caller labels with its own component name
    so Grafana can pinpoint *which* teardown path is flapping.
    """
    logger.warning(
        "smtp_silent_error",
        component=component,
        error=str(exc),
        error_type=type(exc).__name__,
    )
    suppressed_errors_counter.labels(component=component, reason=type(exc).__name__).inc()


class _PooledSmtp:
    def __init__(self, client: aiosmtplib.SMTP, last_used: float):
        self.client = client
        self.last_used = last_used


class SmtpConnectionPool:
    """LIFO pool of aiosmtplib.SMTP connections, keyed by credential tuple."""

    def __init__(self, max_per_account: int = 8, idle_ttl_seconds: float = 300.0):
        self._pools: dict[tuple, list[_PooledSmtp]] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}
        self._max_per_account = max_per_account
        self._idle_ttl = idle_ttl_seconds

    @staticmethod
    def _key(creds: SmtpCredentials) -> tuple:
        return (creds.host, creds.port, creds.username)

    def _get_lock(self, key: tuple) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def acquire(self, creds: SmtpCredentials) -> aiosmtplib.SMTP:
        key = self._key(creds)
        async with self._get_lock(key):
            pool = self._pools.setdefault(key, [])
            now = time.monotonic()
            while pool:
                pooled = pool.pop()
                if now - pooled.last_used > self._idle_ttl:
                    try:
                        await pooled.client.quit()
                    except (TimeoutError, aiosmtplib.SMTPException, OSError) as exc:
                        _record_suppressed("mail.smtp.pool.acquire_quit_idle", exc)
                    continue
                return pooled.client
        return await self._dial(creds)

    async def release(self, creds: SmtpCredentials, client: aiosmtplib.SMTP) -> None:
        key = self._key(creds)
        async with self._get_lock(key):
            pool = self._pools.setdefault(key, [])
            if len(pool) >= self._max_per_account:
                try:
                    await client.quit()
                except (TimeoutError, aiosmtplib.SMTPException, OSError) as exc:
                    _record_suppressed("mail.smtp.pool.release_quit_overflow", exc)
                return
            pool.append(_PooledSmtp(client, time.monotonic()))

    async def _dial(self, creds: SmtpCredentials) -> aiosmtplib.SMTP:
        tls_context = ssl.create_default_context()
        client = aiosmtplib.SMTP(
            hostname=creds.host,
            port=creds.port,
            use_tls=False,  # we STARTTLS later if use_tls=True
            start_tls=False,
            timeout=30.0,
        )
        try:
            await client.connect()
            if creds.use_tls and creds.port != 465:
                await client.starttls(tls_context=tls_context)
            if creds.username:
                await client.login(creds.username, creds.password)
        except aiosmtplib.SMTPAuthenticationError as exc:
            raise TerminalSendError(f"SMTP auth failed: {exc}") from exc
        except aiosmtplib.SMTPConnectError as exc:
            raise RetryableSendError(f"SMTP connect failed: {exc}") from exc
        except aiosmtplib.SMTPServerDisconnected as exc:
            raise RetryableSendError(f"SMTP disconnected: {exc}") from exc
        except TimeoutError as exc:
            raise RetryableSendError("SMTP connect timeout") from exc
        return client

    async def close_all(self) -> None:
        for pool in self._pools.values():
            for pooled in pool:
                try:
                    await pooled.client.quit()
                except (TimeoutError, aiosmtplib.SMTPException, OSError) as exc:
                    _record_suppressed("mail.smtp.pool.close_all_quit", exc)
        self._pools.clear()


class SmtpProvider(MailProvider):
    def __init__(self, pool: SmtpConnectionPool | None = None):
        self._pool = pool or SmtpConnectionPool()

    async def send(self, credentials: SmtpCredentials, message: EmailMessage) -> SentMessage:
        client = await self._pool.acquire(credentials)
        try:
            await client.send_message(message)
        except aiosmtplib.SMTPRecipientsRefused as exc:
            raise TerminalSendError(f"SMTP recipient refused: {exc}") from exc
        except aiosmtplib.SMTPResponseException as exc:
            if 400 <= exc.code < 500:
                raise RetryableSendError(f"SMTP {exc.code}: {exc.message}") from exc
            raise TerminalSendError(f"SMTP {exc.code}: {exc.message}") from exc
        except aiosmtplib.SMTPServerDisconnected as exc:
            try:
                await client.quit()
            except (TimeoutError, aiosmtplib.SMTPException, OSError) as quit_exc:
                _record_suppressed("mail.smtp.send.quit_after_disconnect", quit_exc)
            raise RetryableSendError(f"SMTP disconnected mid-send: {exc}") from exc
        except TimeoutError as exc:
            raise RetryableSendError("SMTP send timeout") from exc
        else:
            await self._pool.release(credentials, client)
            return SentMessage(provider_message_id=message.get("Message-ID"))
