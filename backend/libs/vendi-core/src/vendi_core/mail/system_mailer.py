"""Correo de plataforma: el único correo que envía Vendi en Fase 0.

De todo el paquete `mail` de BaseSaaS solo sobrevive esto. **No** se portan:

- `mailer.py`: el mailer por tenant, que escribía en `email_messages` dentro
  del schema del inquilino y dependía de un consumidor `mail-worker`. Sin
  schema-per-tenant no tiene dónde escribir, y Vendi no tiene correo
  transaccional por negocio en Fase 0.
- `renderer.py`: renderizaba plantillas guardadas en base de datos, editables
  por cada inquilino. Aquí el catálogo de plantillas es Jinja **dentro del
  paquete**: se versiona con el código y se revisa en el mismo PR. Las
  plantillas de facturación y dunning llegan en la Fase 2.
- `tracking.py`: píxeles de apertura y reescritura de enlaces. Vendi no
  rastrea aperturas.
- `secrets.py`: credenciales SMTP cifradas por inquilino. Hay unas credenciales,
  las de la plataforma.

Lo que queda hace tres cosas y ninguna más:

  1. Renderiza plantillas Jinja que viajan en este paquete (sistema de
     archivos, no base de datos).
  2. Construye el MIME.
  3. Envía directamente por `aiosmtplib` con las credenciales de plataforma.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import aiosmtplib
import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from vendi_core.mail.mime import build_mime

logger = structlog.get_logger()

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@dataclass(frozen=True)
class SystemSmtpConfig:
    host: str
    port: int
    username: str
    password: str
    use_tls: bool
    sender_address: str
    sender_name: str


class SystemMailer:
    """Render + send emails before any tenant exists.

    Templates live in ``vendi_core/mail/templates/{key}.{html.j2,subject.txt,txt.j2}``.
    ``{key}`` is the dotted template name, e.g. ``auth.signup_confirm``.
    """

    def __init__(self, smtp: SystemSmtpConfig):
        self._smtp = smtp
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "htm", "j2"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    async def send(
        self,
        *,
        template_key: str,
        to_address: str,
        context: Mapping[str, object],
        to_name: str | None = None,
    ) -> None:
        subject = self._env.get_template(f"{template_key}.subject.txt").render(context).strip()
        html = self._env.get_template(f"{template_key}.html.j2").render(context)
        # Sin respaldo automático de HTML a texto plano. BaseSaaS derivaba el
        # texto del HTML con `html2text` cuando faltaba la plantilla `.txt.j2`;
        # esa dependencia no se porta (ver la cabecera del módulo) y el respaldo
        # tampoco, porque producía texto plano de calidad impredecible sin que
        # nadie se enterara. Aquí falta de plantilla es error: toda plantilla
        # trae sus tres archivos, y el test de humo lo comprueba.
        text = self._env.get_template(f"{template_key}.txt.j2").render(context)

        mime = build_mime(
            sender_address=self._smtp.sender_address,
            sender_name=self._smtp.sender_name,
            to_address=to_address,
            to_name=to_name,
            subject=subject,
            text_body=text,
            html_body=html,
            unsubscribe_url=None,
        )
        await aiosmtplib.send(
            mime,
            hostname=self._smtp.host,
            port=self._smtp.port,
            username=self._smtp.username or None,
            password=self._smtp.password or None,
            start_tls=self._smtp.use_tls,
            timeout=15.0,
        )
        logger.info("system_mail_sent", template_key=template_key, to=to_address)
