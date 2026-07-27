"""Fábrica del provisioner: la cadena de middlewares y el montaje de rutas.

Separada de `main.py` por el mismo motivo que en la API: este módulo se puede
importar sin una sola variable de entorno, y por eso los tests construyen la
aplicación **real** con unos `Settings` de prueba y un doble de Keycloak en
`app.state.kc`.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI

from provisioner.rutas import router
from provisioner.settings import Settings, cargar_settings
from vendi_core.auth.keycloak_aprovisionamiento import VendiKeycloakAprovisionamiento
from vendi_core.logging.setup import setup_logging
from vendi_core.middleware.correlation import CorrelationIdMiddleware
from vendi_core.middleware.error_handler import ErrorHandlerMiddleware

logger = structlog.get_logger()


def crear_app(settings: Settings | None = None) -> FastAPI:
    """Construye la aplicación. Sin E/S: `VendiKeycloakAprovisionamiento` no
    habla con Keycloak hasta la primera llamada, igual que en la API."""
    settings = settings or cargar_settings()
    setup_logging(level=settings.log_level, json_output=settings.log_json)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("provisioner_arrancado", entorno=settings.app_env, realm=settings.keycloak_realm)
        yield
        logger.info("provisioner_detenido")

    app = FastAPI(
        title="Vendi Provisioner",
        version="0.1.0",
        lifespan=lifespan,
        # Servicio interno: la documentación interactiva no se registra jamás.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.state.settings = settings
    app.state.kc = VendiKeycloakAprovisionamiento(
        server_url=settings.keycloak_url_normalizada,
        client_id=settings.keycloak_provisioning_client_id,
        client_secret=settings.keycloak_provisioning_client_secret,
        realm=settings.keycloak_realm,
    )

    # Solo dos capas, en orden de ejecución (el último registrado queda más
    # externo): correlación para que todo lo de abajo herede el id que mandó
    # la API, y el manejador de errores para que un `DomainError` salga con el
    # mismo sobre que el cliente sabe traducir.
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    app.include_router(router)
    return app
