"""Política de verificación TLS de las llamadas salientes a Keycloak.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_keycloak_ssl_verify.py`.
Adaptación: `base_saas` → `vendi_core`.

Contexto: antes, cada llamada httpx a Keycloak llevaba `verify=False` cableado.
Es correcto para el compose local (certificado autofirmado dentro de la red) y
está mal en todo lo demás: desactiva el handshake TLS también en producción, así
que un intermediario dentro de la red del clúster sería indetectable.

En Vendi hay un matiz que hace esto más importante, no menos: `mkcert` instala
la CA en el sistema precisamente para que el desarrollo funcione **con**
verificación por `https://accounts.vendi.local`. Es decir, ni siquiera en
desarrollo hace falta apagarla.
"""

from __future__ import annotations

from unittest.mock import patch

from vendi_core.auth.ssl import keycloak_ssl_verify


def test_produccion_verifica_por_defecto(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("KEYCLOAK_VERIFY_SSL", raising=False)
    assert keycloak_ssl_verify() is True


def test_staging_verifica_por_defecto(monkeypatch):
    """Todo lo que no sea `development` se trata como producción: mejor fallar
    ruidosamente ante un certificado autofirmado que confiar en él en silencio."""
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("KEYCLOAK_VERIFY_SSL", raising=False)
    assert keycloak_ssl_verify() is True


def test_un_app_env_sin_definir_verifica(monkeypatch):
    """Sesgo a prueba de fallos: en la duda, se verifica."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("KEYCLOAK_VERIFY_SSL", raising=False)
    assert keycloak_ssl_verify() is True


def test_un_app_env_desconocido_verifica(monkeypatch):
    monkeypatch.setenv("APP_ENV", "qa-de-alguien")
    monkeypatch.delenv("KEYCLOAK_VERIFY_SSL", raising=False)
    assert keycloak_ssl_verify() is True


def test_development_no_verifica_por_defecto(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("KEYCLOAK_VERIFY_SSL", raising=False)
    assert keycloak_ssl_verify() is False


def test_el_override_explicito_gana_sobre_el_entorno(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("KEYCLOAK_VERIFY_SSL", "true")
    assert keycloak_ssl_verify() is True


def test_desactivarlo_a_mano_deja_rastro_en_el_log(monkeypatch):
    """Una decisión insegura explícita merece un registro ruidoso: si no, se
    pudre sin que nadie se entere."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("KEYCLOAK_VERIFY_SSL", "false")
    with patch("vendi_core.auth.ssl.logger") as logger_doblado:
        assert keycloak_ssl_verify() is False
    assert logger_doblado.warning.called
    evento, *_ = logger_doblado.warning.call_args.args
    assert evento == "keycloak_ssl_verify_disabled"


def test_un_valor_basura_en_el_override_se_ignora(monkeypatch):
    """Una errata no puede apagar TLS por accidente: se cae al defecto del
    entorno, que en producción es verificar."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("KEYCLOAK_VERIFY_SSL", "puede-ser")
    assert keycloak_ssl_verify() is True


def test_se_aceptan_las_formas_habituales_de_booleano(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    for valor in ("1", "yes", "on", "TRUE"):
        monkeypatch.setenv("KEYCLOAK_VERIFY_SSL", valor)
        assert keycloak_ssl_verify() is True, valor
    monkeypatch.setenv("APP_ENV", "production")
    for valor in ("0", "no", "off", "FALSE"):
        monkeypatch.setenv("KEYCLOAK_VERIFY_SSL", valor)
        assert keycloak_ssl_verify() is False, valor


def test_la_decision_se_relee_en_cada_llamada(monkeypatch):
    """Sin cachear: un operador que rota variables con un sidecar no debería
    tener que reiniciar el proceso."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("KEYCLOAK_VERIFY_SSL", raising=False)
    assert keycloak_ssl_verify() is True
    monkeypatch.setenv("APP_ENV", "development")
    assert keycloak_ssl_verify() is False
