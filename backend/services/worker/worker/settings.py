"""Configuración del worker de Vendi.

Un solo DSN, y es el de plataforma. El worker **no tiene** el rol `vendi_app` ni
lo necesita: drena el outbox de todos los negocios en una pasada, purga tablas
de plataforma y recorre los negocios activos. Con `vendi_app` (sin `BYPASSRLS`)
vería cero filas en las tablas de negocio y no tendría privilegio ninguno sobre
las de plataforma — es decir, no funcionaría, pero fallaría en silencio: cero
filas no es un error.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: str = "development"
    service_name: str = "vendi-worker"
    log_level: str = "INFO"
    log_json: bool = True

    platform_database_url: str = Field(description="DSN del rol vendi_platform (con BYPASSRLS).")
    rabbitmq_url: str = ""

    # --- Dispatcher del outbox --------------------------------------------
    outbox_poll_interval: float = 2.0
    outbox_batch_size: int = 100
    outbox_max_retries: int = 5

    # --- Retención ---------------------------------------------------------
    retention_hour_utc: int = 3

    # --- Almacenamiento (para el hook de purga de `files`) -----------------
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    storage_provider: str = "minio"
    storage_secure: bool = False

    # --- Sondas y métricas -------------------------------------------------
    worker_heartbeat_seconds: float = 30.0
    worker_heartbeat_file: str = "/tmp/vendi-worker-latido"
    metrics_port: int = 9090

    # --- Reconexión a RabbitMQ ---------------------------------------------
    # Tope del backoff exponencial. Sin un tope, un RabbitMQ que tarda en
    # levantar acaba con el worker durmiendo horas; sin backoff, el worker
    # entra en crash-loop y llena el log de reintentos por segundo.
    rabbitmq_backoff_max: float = 30.0

    otel_exporter_otlp_endpoint: str = ""


def cargar_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
