"""IP de cliente de confianza: `X-Forwarded-For` solo desde proxies conocidos.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_client_ip.py` y
`test_audit_xff.py`, unificados. Adaptación: `base_saas` → `vendi_core`.

Por qué importa en Vendi: las cuatro SPAs llegan por Traefik, así que el peer
que ve la API es siempre el proxy y la IP real viaja en `X-Forwarded-For`.
Confiar en esa cabecera sin comprobar de quién viene es regalarle a cualquier
cliente la posibilidad de escribir la IP que quiera en el rastro de auditoría.
"""

from __future__ import annotations

from unittest.mock import Mock

from vendi_core.middleware.client_ip import _validated_xff_entry, trusted_client_ip


def _peticion(peer: str | None, xff: str | None = None):
    request = Mock()
    request.client = Mock(host=peer) if peer else None
    request.headers = {"x-forwarded-for": xff} if xff else {}
    return request


def test_sin_cliente_devuelve_none():
    assert trusted_client_ip(_peticion(peer=None), ()) is None


def test_sin_cidrs_de_confianza_devuelve_el_peer_e_ignora_xff():
    assert trusted_client_ip(_peticion("10.0.0.5", "1.2.3.4"), ()) == "10.0.0.5"


def test_un_peer_fuera_de_la_lista_no_puede_falsificar_su_ip():
    """El caso de ataque: un cliente en 8.8.8.8 que manda
    `X-Forwarded-For: 1.2.3.4` tiene que quedar auditado como 8.8.8.8."""
    assert trusted_client_ip(_peticion("8.8.8.8", "1.2.3.4"), ("10.0.0.0/8",)) == "8.8.8.8"


def test_un_proxy_de_confianza_sí_aporta_la_ip_real():
    assert trusted_client_ip(_peticion("10.0.0.5", "1.2.3.4, 10.0.0.5"), ("10.0.0.0/8",)) == "1.2.3.4"


def test_una_cadena_de_proxies_usa_la_primera_entrada():
    peticion = _peticion("10.0.0.5", "203.0.113.1, 10.0.0.50, 10.0.0.5")
    assert trusted_client_ip(peticion, ("10.0.0.0/8",)) == "203.0.113.1"


def test_un_xff_con_zona_ipv6_se_rechaza_y_cae_al_peer():
    assert trusted_client_ip(_peticion("10.0.0.5", "fe80::1%eth0"), ("10.0.0.0/8",)) == "10.0.0.5"


def test_un_xff_con_puerto_se_rechaza_y_cae_al_peer():
    assert trusted_client_ip(_peticion("10.0.0.5", "1.2.3.4:5678"), ("10.0.0.0/8",)) == "10.0.0.5"


def test_un_xff_con_nombre_de_maquina_se_rechaza_y_cae_al_peer():
    assert trusted_client_ip(_peticion("10.0.0.5", "proxy.local"), ("10.0.0.0/8",)) == "10.0.0.5"


def test_un_xff_vacio_cae_al_peer():
    assert trusted_client_ip(_peticion("10.0.0.5", ""), ("10.0.0.0/8",)) == "10.0.0.5"


def test_un_peer_que_no_es_ip_se_devuelve_tal_cual():
    assert trusted_client_ip(_peticion("no-es-una-ip", "1.2.3.4"), ("10.0.0.0/8",)) == "no-es-una-ip"


def test_validacion_de_entrada_xff_ipv6():
    assert _validated_xff_entry("2001:db8::1") == "2001:db8::1"


def test_validacion_de_entrada_xff_vacia():
    assert _validated_xff_entry("") is None
    assert _validated_xff_entry("   ") is None
