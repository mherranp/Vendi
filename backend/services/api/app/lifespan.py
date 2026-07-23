"""Ciclo de vida de la API: qué se construye al arrancar y qué se cierra al parar.

Todo lo caro y compartido —engines, fábricas de sesión, validador de JWT,
clientes de Keycloak, Redis— se crea una vez aquí y se publica en `app.state`.
Los handlers no construyen nada: lo piden por dependencia.

## El candado del arranque: `vendi_app` no puede tener BYPASSRLS

`create_session_factory` emite el `SET LOCAL vendi.tenant_id` en cada
transacción, pero eso no sirve de nada si el engine que recibe apunta a un rol
con `BYPASSRLS`: la policy no se evalúa y **todos los handlers de tenant ven las
filas de todos los negocios, sin un solo error**. Es el peor fallo posible de
este diseño y no se puede detectar leyendo el DSN (el nombre del rol es una
convención, el atributo está en la base).

Por eso el arranque lo pregunta a PostgreSQL:

    SELECT current_user, rolbypassrls FROM pg_roles WHERE rolname = current_user

Si el rol de la API tiene `BYPASSRLS`, el proceso **no arranca**. La alternativa
—arrancar y registrar un warning— es exactamente la clase de defensa que nadie
lee hasta después del incidente.

Si la base no responde durante el arranque no se aborta: se registra el fallo y
`/health/ready` lo refleja. Un Postgres que tarda en levantar es una condición
de despliegue normal; un rol mal configurado no lo es.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import structlog
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.settings import Settings
from vendi_core.audit.service import AuditService
from vendi_core.auth.jwt import JWTValidator
from vendi_core.auth.keycloak_admin import VendiKeycloakAdmin, VendiKeycloakAprovisionamiento
from vendi_core.cache.redis import RedisCache
from vendi_core.db.engine import create_engine, dispose_engine
from vendi_core.db.session import create_platform_session_factory, create_session_factory
from vendi_core.tracing.otel import configure_tracing

logger = structlog.get_logger()


class ErrorDeCableado(RuntimeError):
    """El proceso está configurado de una forma que rompe el aislamiento.

    No es una excepción de dominio ni un fallo transitorio: es un despliegue que
    no debe servir tráfico. Sube hasta el arranque y mata el proceso.
    """


@dataclass
class Recursos:
    """Lo que vive mientras vive el proceso. Se publica en `app.state.recursos`."""

    settings: Settings
    engine_tenant: AsyncEngine
    engine_plataforma: AsyncEngine
    sesion_tenant: async_sessionmaker[AsyncSession]
    sesion_plataforma: async_sessionmaker[AsyncSession]
    jwt_validator: JWTValidator
    keycloak: VendiKeycloakAdmin
    keycloak_aprovisionamiento: VendiKeycloakAprovisionamiento
    audit_service: AuditService
    redis: RedisCache | None = None
    tareas_en_vuelo: set[asyncio.Task] = field(default_factory=set)


async def _comprobar_rol_de_la_api(engine: AsyncEngine) -> None:
    """Se niega a arrancar si el rol de la API puede saltarse RLS."""
    try:
        async with engine.connect() as conn:
            fila = (
                await conn.execute(
                    text(
                        """
                        SELECT current_user AS rol,
                               (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) AS salta_rls
                        """
                    )
                )
            ).one()
    except ErrorDeCableado:
        raise
    except Exception as exc:  # noqa: BLE001
        # Base todavía no disponible. No es motivo para abortar: `/health/ready`
        # lo reporta y el orquestador reintenta.
        logger.warning("arranque_sin_comprobar_el_rol_de_la_api", error=str(exc))
        return

    if fila.salta_rls:
        raise ErrorDeCableado(
            f"El rol de la API es {fila.rol!r} y tiene BYPASSRLS: con él la policy de "
            "aislamiento no se evalúa y cada negocio vería los datos de todos. "
            "DATABASE_URL debe apuntar a vendi_app (sin BYPASSRLS); vendi_platform va "
            "en PLATFORM_DATABASE_URL."
        )
    logger.info("rol_de_la_api_verificado", rol=fila.rol, salta_rls=False)


def construir_recursos(settings: Settings) -> Recursos:
    """Crea los objetos de larga vida. Sin E/S: no toca red ni base.

    Separado del `lifespan` para que los tests puedan construir la app entera
    sin levantar nada, y para que el orden de construcción sea legible.
    """
    engine_tenant = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        echo=settings.db_echo,
    )
    engine_plataforma = create_engine(
        settings.platform_database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        echo=settings.db_echo,
    )
    sesion_plataforma = create_platform_session_factory(engine_plataforma)
    tareas: set[asyncio.Task] = set()
    return Recursos(
        settings=settings,
        engine_tenant=engine_tenant,
        engine_plataforma=engine_plataforma,
        sesion_tenant=create_session_factory(engine_tenant),
        sesion_plataforma=sesion_plataforma,
        jwt_validator=JWTValidator(
            keycloak_url=settings.keycloak_url_normalizada,
            audience=settings.keycloak_audience or None,
            allowed_realms=(settings.keycloak_realm,),
        ),
        keycloak=VendiKeycloakAdmin(
            server_url=settings.keycloak_url_normalizada,
            client_id=settings.keycloak_backend_client_id,
            client_secret=settings.keycloak_backend_client_secret,
            realm=settings.keycloak_realm,
        ),
        keycloak_aprovisionamiento=VendiKeycloakAprovisionamiento(
            server_url=settings.keycloak_url_normalizada,
            client_id=settings.keycloak_provisioning_client_id,
            client_secret=settings.keycloak_provisioning_client_secret,
            realm=settings.keycloak_realm,
        ),
        # La auditoría va SIEMPRE con la fábrica de plataforma: abre su propia
        # sesión fuera de la transacción del llamante (si fuera dentro, un
        # rollback de negocio borraría la prueba de que se intentó la
        # operación) y `vendi_app` no tiene privilegio ninguno sobre
        # `audit_events`. Lo vigila `test_auditoria_no_usa_el_rol_de_la_api`.
        audit_service=AuditService(
            session_factory=sesion_plataforma,
            service_name=settings.service_name,
            inflight_tasks=tareas,
        ),
        tareas_en_vuelo=tareas,
    )


def publicar_en_estado(app: FastAPI, recursos: Recursos) -> None:
    """Deja los recursos donde los buscan las dependencias y los middlewares.

    Los nombres planos (`app.state.jwt_validator`, `app.state.audit_service`)
    son contrato de `vendi-core`: los leen `TenantMiddleware`,
    `get_jwt_validator` y el decorador `audit_operation`. `app.state.recursos`
    es la vista completa para el código de la API.
    """
    app.state.recursos = recursos
    app.state.settings = recursos.settings
    app.state.jwt_validator = recursos.jwt_validator
    app.state.audit_service = recursos.audit_service
    app.state.trusted_proxies = recursos.settings.trusted_proxies_tupla
    app.state.inflight_tasks = recursos.tareas_en_vuelo


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    recursos: Recursos = app.state.recursos
    settings = recursos.settings

    await _comprobar_rol_de_la_api(recursos.engine_tenant)

    if settings.redis_url:
        try:
            recursos.redis = await RedisCache.connect(settings.redis_url)
        except Exception as exc:  # noqa: BLE001
            # Redis solo acelera la consulta del estado del negocio; sin él se
            # va a la base en cada request. Degradar es correcto; abortar no.
            logger.warning("redis_no_disponible_al_arrancar", error=str(exc))
            recursos.redis = None

    if settings.otel_exporter_otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otel_exporter_otlp_endpoint,
            app_env=settings.app_env,
            app=app,
            engine=recursos.engine_tenant,
            service_version=settings.api_version,
        )

    logger.info("api_arrancada", entorno=settings.app_env, realm=settings.keycloak_realm)
    try:
        yield
    finally:
        # Drenar las escrituras de auditoría en vuelo antes de cerrar los
        # engines: son fire-and-forget, y cerrar el pool debajo de ellas
        # convierte cada una en un `audit_write_failed` gratuito.
        if recursos.tareas_en_vuelo:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    asyncio.gather(*list(recursos.tareas_en_vuelo), return_exceptions=True),
                    timeout=5,
                )
        if recursos.redis is not None:
            with contextlib.suppress(Exception):
                await recursos.redis.close()
        await dispose_engine(recursos.engine_tenant)
        await dispose_engine(recursos.engine_plataforma)
        logger.info("api_detenida")
