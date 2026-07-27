"""La API arranca sin la credencial de provisioning: el cierre de D-02 como test.

Antes de ADR-027, `Settings` cargaba `keycloak_provisioning_client_secret` con
defecto `""`: la API arrancaba sin la credencial con `manage-realm` y fallaba
tarde, y peor — cuando la tenía, vivía en el mismo proceso que atiende
peticiones. Ahora el campo **no existe**: no hay variable de entorno que pueda
entregar ese secreto a este proceso, y la aplicación entera se construye sin él.
"""

from __future__ import annotations

import pytest
from ayudas import app_de_prueba, settings_de_prueba
from pydantic import ValidationError

from app.settings import Settings

VARIABLES_DE_PROVISIONING = (
    "VENDI_PROVISIONING_CLIENT_SECRET",
    "KEYCLOAK_PROVISIONING_CLIENT_SECRET",
    "KEYCLOAK_PROVISIONING_CLIENT_ID",
)


def test_los_settings_no_tienen_campo_para_el_secreto_de_provisioning(monkeypatch):
    """Aunque el entorno grite el secreto, `Settings` no lo recoge.

    `extra="ignore"` ya descartaba variables desconocidas; lo que cambia aquí es
    que los campos que lo aceptaban dejaron de existir. Si alguien los
    reintroduce, este test se pone rojo.
    """
    for variable in VARIABLES_DE_PROVISIONING:
        monkeypatch.setenv(variable, "secreto-que-no-debe-entrar")
    settings = settings_de_prueba()
    assert not hasattr(settings, "keycloak_provisioning_client_secret")
    assert not hasattr(settings, "keycloak_provisioning_client_id")


def test_la_api_se_construye_sin_el_secreto_de_provisioning(monkeypatch):
    """La aplicación entera, sin rastro de la variable en el entorno."""
    for variable in VARIABLES_DE_PROVISIONING:
        monkeypatch.delenv(variable, raising=False)
    aplicacion, _, aprovisionamiento = app_de_prueba()
    assert aplicacion.state.recursos.aprovisionamiento is aprovisionamiento


def test_el_secreto_del_cliente_backend_es_obligatorio():
    """La otra mitad de la deuda: defecto `""` = arrancar y fallar tarde.

    El cliente `vendi-backend` sí vive en este proceso, y sin su secreto la API
    no tiene nada que hacer viva: mejor no arrancar, con el nombre exacto de lo
    que falta.
    """
    with pytest.raises(ValidationError, match="keycloak_backend_client_secret"):
        Settings(
            database_url="postgresql+asyncpg://x:y@127.0.0.1:1/z",
            platform_database_url="postgresql+asyncpg://x:y@127.0.0.1:1/z",
            redis_url="",
            keycloak_url="http://keycloak-de-prueba:8080",
            provisioner_url="http://provisioner-de-prueba:8000",
        )  # type: ignore[call-arg]
