"""Build a ``EmailMessage`` (multipart/alternative) from rendered text + html.

Includes RFC 8058 one-click unsubscribe headers when ``unsubscribe_url`` is
provided.
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr, make_msgid


def build_mime(
    *,
    sender_address: str,
    sender_name: str,
    to_address: str,
    to_name: str | None,
    subject: str,
    text_body: str,
    html_body: str,
    unsubscribe_url: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    message_id_domain: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name or "", sender_address))
    msg["To"] = formataddr((to_name or "", to_address))
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=message_id_domain or sender_address.split("@")[-1])
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    msg.set_content(text_body or "", subtype="plain", charset="utf-8")
    msg.add_alternative(html_body, subtype="html")
    return msg
