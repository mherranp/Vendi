"""Construcción del MIME de correo: multipart/alternative y cabeceras RFC 8058.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_mail_mime.py`.
Adaptaciones: `base_saas` → `vendi_core` y los datos de ejemplo pasan al dominio
de Vendi.
"""

from __future__ import annotations

from vendi_core.mail.mime import build_mime


def test_multipart_con_cabeceras_de_baja():
    msg = build_mime(
        sender_address="noreply@vendi.local",
        sender_name="Vendi",
        to_address="ana@ejemplo.test",
        to_name="Ana",
        subject="Bienvenida",
        text_body="Hola Ana",
        html_body="<p>Hola Ana</p>",
        unsubscribe_url="https://app.vendi.local/baja/xxx",
    )
    assert msg["Subject"] == "Bienvenida"
    assert "Vendi" in msg["From"]
    assert "ana@ejemplo.test" in msg["To"]
    assert msg["List-Unsubscribe"] == "<https://app.vendi.local/baja/xxx>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert msg["Message-ID"]

    # El cuerpo tiene que ser multipart/alternative con las dos partes: hay
    # clientes de correo que no renderizan HTML, y un correo sin parte de texto
    # llega en blanco.
    partes = msg.get_payload()
    assert isinstance(partes, list) and len(partes) == 2
    assert sorted(p.get_content_type() for p in partes) == ["text/html", "text/plain"]


def test_sin_url_de_baja_no_se_ponen_esas_cabeceras():
    msg = build_mime(
        sender_address="a@b.c",
        sender_name="",
        to_address="x@y.z",
        to_name=None,
        subject="s",
        text_body="t",
        html_body="<p>h</p>",
    )
    assert msg["List-Unsubscribe"] is None
    assert msg["List-Unsubscribe-Post"] is None


def test_el_message_id_usa_el_dominio_del_remitente_por_defecto():
    msg = build_mime(
        sender_address="noreply@vendi.local",
        sender_name="Vendi",
        to_address="ana@ejemplo.test",
        to_name=None,
        subject="s",
        text_body="t",
        html_body="<p>h</p>",
    )
    assert msg["Message-ID"].endswith("@vendi.local>")


def test_copia_y_copia_oculta_llegan_a_las_cabeceras():
    msg = build_mime(
        sender_address="noreply@vendi.local",
        sender_name="Vendi",
        to_address="ana@ejemplo.test",
        to_name=None,
        subject="s",
        text_body="t",
        html_body="<p>h</p>",
        cc=["jefe@ejemplo.test"],
        bcc=["registro@ejemplo.test"],
    )
    assert msg["Cc"] == "jefe@ejemplo.test"
    assert msg["Bcc"] == "registro@ejemplo.test"
