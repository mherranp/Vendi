"""Configuración del provisioner de Vendi.

La misma regla que la API, y aquí más importante que en ningún otro sitio:
**ningún secreto tiene valor por defecto.** Este proceso existe para ser el
único dueño de la credencial con `manage-realm` (cierre de D-02, ADR-027); un
defecto plausible convertiría un despliegue mal configurado en uno que arranca
y falla tarde, que es exactamente la deuda que se cerró en `app/settings.py`
de la API con este mismo cambio.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    service_name: str = "vendi-provisioner"
    log_level: str = "INFO"
    log_json: bool = True

    # --- Keycloak ----------------------------------------------------------
    keycloak_url: str = Field(description="URL base de Keycloak, sin barra final.")
    keycloak_realm: str = "vendi-co"
    keycloak_provisioning_client_id: str = "vendi-provisioning"
    # LA credencial que este servicio existe para custodiar: la única con
    # `manage-realm` (más `manage-users`). Sin ella el proceso no arranca: un
    # provisioner sin credencial es un proceso que acepta peticiones y falla
    # en cada una, peor que no estar.
    keycloak_provisioning_client_secret: str = Field(
        description="Secreto del cliente `vendi-provisioning` (manage-realm + manage-users)."
    )

    @property
    def keycloak_url_normalizada(self) -> str:
        return self.keycloak_url.rstrip("/")


def cargar_settings() -> Settings:
    """Lee la configuración del entorno. Aborta si falta algo obligatorio."""
    return Settings()  # type: ignore[call-arg]
