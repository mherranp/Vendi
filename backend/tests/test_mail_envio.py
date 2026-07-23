"""Envío de correo: `SystemMailer` y el proveedor SMTP con pool.

`vendi_core.mail` viene de `base_saas.mail` recortado a lo que Fase 0 usa. Los
tests de correo de BaseSaaS (`test_mail_renderer.py`, `test_mail_tracking.py`,
`test_mail_bounce_webhook.py`, `test_mail_worker_supervisor.py`,
`test_mail_secrets.py`) NO se portan: cubren el mailer por inquilino, el
renderizador de plantillas guardadas en base de datos, el rastreo de aperturas y
las credenciales SMTP cifradas por negocio, y nada de eso existe aquí.

Lo que sí se cubre, y estaba a cero:

- `SystemMailer`: renderiza las tres piezas de la plantilla y envía sin caer en
  ningún respaldo silencioso;
- `SmtpProvider`: la clasificación de errores en reintentable / terminal, que es
  lo que decide si un correo se reintenta o se descarta;
- `SmtpConnectionPool`: reutilización, expiración por inactividad y tope por
  cuenta.

No se toca la red: `aiosmtplib` se dobla.
"""

from __future__ import annotations

import time
from email.message import EmailMessage
from unittest.mock import AsyncMock, patch

import aiosmtplib
import pytest
from jinja2 import TemplateNotFound

from vendi_core.mail.providers.base import (
    RetryableSendError,
    SentMessage,
    SmtpCredentials,
    TerminalSendError,
)
from vendi_core.mail.providers.smtp import SmtpConnectionPool, SmtpProvider
from vendi_core.mail.system_mailer import SystemMailer, SystemSmtpConfig

CONFIG = SystemSmtpConfig(
    host="mailhog",
    port=1025,
    username="",
    password="",
    use_tls=False,
    sender_address="noreply@vendi.co",
    sender_name="Vendi",
)

CREDENCIALES = SmtpCredentials(host="mailhog", port=1025, username="ana", password="x", use_tls=False)


# ---------------------------------------------------------------------------
# SystemMailer
# ---------------------------------------------------------------------------


async def test_el_mailer_renderiza_las_tres_piezas_y_envia():
    mailer = SystemMailer(CONFIG)
    with patch("vendi_core.mail.system_mailer.aiosmtplib.send", new=AsyncMock()) as enviar:
        await mailer.send(
            template_key="sistema.prueba",
            to_address="ana@ejemplo.test",
            to_name="Ana",
            context={"nombre": "Ana"},
        )

    enviar.assert_awaited_once()
    mime = enviar.call_args.args[0]
    assert mime["To"].endswith("<ana@ejemplo.test>")
    assert "noreply@vendi.co" in mime["From"]
    assert mime["Subject"]
    partes = mime.get_payload()
    assert sorted(p.get_content_type() for p in partes) == ["text/html", "text/plain"]


async def test_falta_de_plantilla_es_error_y_no_un_respaldo_silencioso():
    """BaseSaaS derivaba el texto plano del HTML con `html2text` cuando faltaba
    la plantilla `.txt.j2`. Ese respaldo producía texto de calidad impredecible
    sin que nadie se enterara; aquí falta de plantilla revienta."""
    mailer = SystemMailer(CONFIG)
    with patch("vendi_core.mail.system_mailer.aiosmtplib.send", new=AsyncMock()):
        with pytest.raises(TemplateNotFound):
            await mailer.send(
                template_key="plantilla.que.no.existe",
                to_address="ana@ejemplo.test",
                context={},
            )


async def test_las_credenciales_vacias_viajan_como_none():
    """`aiosmtplib` interpreta `""` como "intenta autenticarte con usuario
    vacío" y falla contra MailHog, que no pide autenticación."""
    mailer = SystemMailer(CONFIG)
    with patch("vendi_core.mail.system_mailer.aiosmtplib.send", new=AsyncMock()) as enviar:
        await mailer.send(template_key="sistema.prueba", to_address="a@b.c", context={"nombre": "A"})

    kwargs = enviar.call_args.kwargs
    assert kwargs["username"] is None
    assert kwargs["password"] is None
    assert kwargs["hostname"] == "mailhog"
    assert kwargs["port"] == 1025


# ---------------------------------------------------------------------------
# SmtpProvider: clasificación de errores
# ---------------------------------------------------------------------------


class _PoolDoblado:
    def __init__(self, cliente):
        self.cliente = cliente
        self.liberados: list = []

    async def acquire(self, creds):
        return self.cliente

    async def release(self, creds, client):
        self.liberados.append(client)


def _mensaje() -> EmailMessage:
    msg = EmailMessage()
    msg["Message-ID"] = "<id-1@vendi.co>"
    msg.set_content("hola")
    return msg


async def test_un_envio_correcto_devuelve_el_message_id_y_devuelve_la_conexion():
    cliente = AsyncMock()
    pool = _PoolDoblado(cliente)
    resultado = await SmtpProvider(pool).send(CREDENCIALES, _mensaje())

    assert resultado == SentMessage(provider_message_id="<id-1@vendi.co>")
    assert pool.liberados == [cliente]


async def test_un_destinatario_rechazado_es_terminal():
    """No se reintenta: la dirección seguirá siendo inválida dentro de una hora."""
    cliente = AsyncMock()
    cliente.send_message.side_effect = aiosmtplib.SMTPRecipientsRefused([])
    with pytest.raises(TerminalSendError):
        await SmtpProvider(_PoolDoblado(cliente)).send(CREDENCIALES, _mensaje())


async def test_un_4xx_es_reintentable_y_un_5xx_es_terminal():
    """La frontera exacta entre "vuelve a intentarlo" y "tíralo" del RFC 5321."""
    cliente = AsyncMock()
    cliente.send_message.side_effect = aiosmtplib.SMTPResponseException(451, "buzón ocupado")
    with pytest.raises(RetryableSendError, match="451"):
        await SmtpProvider(_PoolDoblado(cliente)).send(CREDENCIALES, _mensaje())

    cliente = AsyncMock()
    cliente.send_message.side_effect = aiosmtplib.SMTPResponseException(550, "buzón inexistente")
    with pytest.raises(TerminalSendError, match="550"):
        await SmtpProvider(_PoolDoblado(cliente)).send(CREDENCIALES, _mensaje())


async def test_una_desconexion_a_mitad_de_envio_es_reintentable_y_cierra_la_conexion():
    cliente = AsyncMock()
    cliente.send_message.side_effect = aiosmtplib.SMTPServerDisconnected("se cayó")
    pool = _PoolDoblado(cliente)

    with pytest.raises(RetryableSendError):
        await SmtpProvider(pool).send(CREDENCIALES, _mensaje())

    cliente.quit.assert_awaited_once()
    # Una conexión rota NO vuelve al pool.
    assert pool.liberados == []


async def test_un_timeout_de_envio_es_reintentable():
    cliente = AsyncMock()
    cliente.send_message.side_effect = TimeoutError()
    with pytest.raises(RetryableSendError, match="timeout"):
        await SmtpProvider(_PoolDoblado(cliente)).send(CREDENCIALES, _mensaje())


# ---------------------------------------------------------------------------
# SmtpConnectionPool
# ---------------------------------------------------------------------------


async def test_el_pool_reutiliza_una_conexion_liberada():
    pool = SmtpConnectionPool()
    cliente = AsyncMock()
    await pool.release(CREDENCIALES, cliente)
    assert await pool.acquire(CREDENCIALES) is cliente


async def test_el_pool_descarta_las_conexiones_pasadas_de_inactividad():
    """Un servidor SMTP corta las conexiones ociosas por su cuenta: reutilizar
    una caducada convierte cada envío en un reintento."""
    pool = SmtpConnectionPool(idle_ttl_seconds=0.0)
    caducada = AsyncMock()
    await pool.release(CREDENCIALES, caducada)
    # Se envejece a mano para no dormir en el test.
    pool._pools[pool._key(CREDENCIALES)][0].last_used = time.monotonic() - 10

    nueva = AsyncMock()
    with patch.object(SmtpConnectionPool, "_dial", new=AsyncMock(return_value=nueva)):
        assert await pool.acquire(CREDENCIALES) is nueva
    caducada.quit.assert_awaited_once()


async def test_el_pool_cierra_lo_que_pasa_del_tope_por_cuenta():
    pool = SmtpConnectionPool(max_per_account=1)
    await pool.release(CREDENCIALES, AsyncMock())
    sobrante = AsyncMock()
    await pool.release(CREDENCIALES, sobrante)

    sobrante.quit.assert_awaited_once()
    assert len(pool._pools[pool._key(CREDENCIALES)]) == 1


async def test_credenciales_distintas_no_comparten_pool():
    """La clave es (host, puerto, usuario): mezclarlos enviaría correo de un
    remitente por la conexión autenticada de otro."""
    pool = SmtpConnectionPool()
    otras = SmtpCredentials(host="mailhog", port=1025, username="otro", password="x")
    cliente_a = AsyncMock()
    await pool.release(CREDENCIALES, cliente_a)

    cliente_b = AsyncMock()
    with patch.object(SmtpConnectionPool, "_dial", new=AsyncMock(return_value=cliente_b)):
        assert await pool.acquire(otras) is cliente_b


async def test_close_all_cierra_todo_y_vacia_los_pools():
    pool = SmtpConnectionPool()
    cliente = AsyncMock()
    await pool.release(CREDENCIALES, cliente)

    await pool.close_all()

    cliente.quit.assert_awaited_once()
    assert pool._pools == {}


async def test_un_quit_que_falla_al_cerrar_no_propaga():
    """El cierre es best-effort: si `quit()` revienta no se puede hacer nada
    útil, pero el silencio total escondería una caída sostenida — por eso hay
    contador y aviso."""
    pool = SmtpConnectionPool()
    cliente = AsyncMock()
    cliente.quit.side_effect = aiosmtplib.SMTPException("adiós fallido")
    await pool.release(CREDENCIALES, cliente)

    await pool.close_all()  # no debe lanzar
    assert pool._pools == {}
