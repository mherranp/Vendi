"""Configuración de la API de Vendi.

Todo lo que cambia entre entornos entra por variable de entorno y sale por
aquí. Dos reglas que este archivo hace cumplir y conviene leer antes de añadir
un campo:

1. **Nada de valores por defecto para secretos ni para DSN de producción.** Un
   defecto plausible ("postgresql://localhost/vendi") convierte un despliegue
   mal configurado en un despliegue que arranca y apunta al sitio equivocado.
   Los campos obligatorios se declaran sin defecto y pydantic aborta el arranque
   con el nombre exacto de lo que falta.

2. **Los dos DSN son campos distintos y ambos obligatorios.** `database_url` es
   el del rol `vendi_app` (sin BYPASSRLS, el de los handlers) y
   `platform_database_url` el de `vendi_platform` (con BYPASSRLS, el del
   aprovisionamiento y la consola). Que sean dos campos y no uno con un flag es
   deliberado: el error que este diseño tiene que hacer imposible es usar el
   segundo donde tocaba el primero, y para eso hay que poder verlos separados en
   el arranque —`lifespan.py` comprueba contra la base que el primero NO tiene
   BYPASSRLS y se niega a arrancar si lo tiene.
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

    # --- Identidad del servicio -------------------------------------------
    app_env: str = "development"
    service_name: str = "vendi-api"
    api_version: str = "v1"
    base_domain: str = "vendi.co"

    # --- Base de datos -----------------------------------------------------
    database_url: str = Field(description="DSN del rol vendi_app (sin BYPASSRLS). Lo usan los handlers.")
    platform_database_url: str = Field(
        description="DSN del rol vendi_platform (con BYPASSRLS). Aprovisionamiento y consola."
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- Dependencias ------------------------------------------------------
    redis_url: str = Field(description="DSN de Redis. Cache del estado de los negocios.")
    rabbitmq_url: str = ""

    # --- Keycloak ----------------------------------------------------------
    keycloak_url: str = Field(description="URL base de Keycloak, sin barra final.")
    keycloak_realm: str = "vendi-co"
    keycloak_backend_client_id: str = "vendi-backend"
    keycloak_backend_client_secret: str = ""
    keycloak_provisioning_client_id: str = "vendi-provisioning"
    keycloak_provisioning_client_secret: str = ""
    # Audiencia que la API exige en el claim `aud`. Vacío = NO se valida, y eso
    # es una línea base peor de lo que parece: sin esta comprobación, cualquier
    # token legítimamente firmado por el realm `vendi-co` sirve contra la API,
    # aunque se haya emitido para otro público (por ejemplo el de la consola de
    # cuenta de Keycloak, `aud: account`, que un usuario obtiene sin pasar por
    # ninguna aplicación de Vendi). El valor por defecto es el que emite el
    # realm: el client scope `vendi-audiencia` pone `aud: vendi-backend` en los
    # tokens de `vendi-web` y `vendi-admin` (infra/keycloak/realm-vendi-co.json).
    #
    # Se deja con DEFECTO y no vacío a propósito: un despliegue que olvide la
    # variable debe fallar cerrado (rechazar tokens sin audiencia), no abrir la
    # puerta. Para las topologías que aún no tengan el mapper aplicado, la
    # salida es poner `KEYCLOAK_AUDIENCE=` explícitamente y saber lo que se
    # apaga. Ver `JWTValidator`: una cadena vacía significa "sin audiencia".
    keycloak_audience: str = "vendi-backend"

    # --- Observabilidad ----------------------------------------------------
    otel_exporter_otlp_endpoint: str = ""
    log_level: str = "INFO"
    log_json: bool = True
    # Credencial de `/metrics`. Sin valor, la ruta responde 503 y NO se abre:
    # una exposición de Prometheus lleva nombres de negocio en las etiquetas y
    # el mapa entero de rutas internas. Ver `app/metrics.py`.
    metrics_token: str = ""
    # ¿Se publican `/docs`, `/redoc` y `/openapi.json`? **False por defecto.**
    #
    # Hasta la Etapa 5 estaban abiertos en el borde sin decisión escrita. Lo que
    # publican no es documentación de marketing: es el mapa completo de rutas,
    # parámetros, esquemas y códigos de error de la API —incluidas las de
    # plataforma—, es decir, el índice del sistema para quien busque por dónde
    # entrar. No es un secreto (la seguridad no depende de ocultarlo) pero
    # tampoco hay razón para regalarlo, y en Fase 0 no hay ni un consumidor
    # externo que lo necesite: el cliente TypeScript del frontend se genera en
    # desarrollo (`scripts/codegen-api-client.sh`) contra el contrato
    # versionado en `docs/api/openapi-fase0.json`.
    #
    # En desarrollo se enciende desde el compose (`DOCS_PUBLICOS=true` en
    # docker-compose.override.dev.yml), que es donde sí hace falta. Con esto en
    # False las tres rutas devuelven 404, y el 404 lo da la aplicación: no hay
    # forma de olvidarse de una regla de Traefik y dejarlas abiertas.
    docs_publicos: bool = False

    # --- Borde -------------------------------------------------------------
    # CIDR de los proxies de confianza. Con la lista vacía, `trusted_client_ip`
    # ignora `X-Forwarded-For` y devuelve el peer: falla cerrado, que es lo
    # correcto por defecto. En el compose el peer es Traefik dentro de la red
    # de Docker.
    trusted_proxies: str = ""
    # Orígenes CORS gestionados POR LA APLICACIÓN. Vacío por defecto, y no es
    # un olvido: en el despliegue de Vendi el CORS lo termina Traefik
    # (middleware `cors-api` de infra/traefik/templates/dynamic.yml.tpl).
    # Declarar aquí un origen sin quitarlo de Traefik produce DOS cabeceras
    # `Access-Control-Allow-Origin` en la misma respuesta, y el navegador
    # rechaza la respuesta entera — un fallo que se manifiesta como «CORS
    # error» en las cuatro SPAs y no aparece en ningún log del backend.
    # Existe para las topologías sin ese borde delante (ejecutar la API a pelo,
    # otro proxy). Formato: lista separada por comas.
    cors_origins: str = ""
    cors_origin_regex: str = ""

    # --- Reglas de negocio de la fundación ---------------------------------
    # TTL del cache del estado del negocio (activo/suspendido). Es la latencia
    # máxima entre suspender un negocio en la consola y que sus tokens dejen de
    # servir. 60 s es el número del plan.
    tenant_estado_cache_ttl: int = 60

    @property
    def cors_origins_lista(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_proxies_tupla(self) -> tuple[str, ...]:
        return tuple(c.strip() for c in self.trusted_proxies.split(",") if c.strip())

    @property
    def keycloak_url_normalizada(self) -> str:
        return self.keycloak_url.rstrip("/")


def cargar_settings() -> Settings:
    """Lee la configuración del entorno. Aborta si falta algo obligatorio."""
    return Settings()  # type: ignore[call-arg]
