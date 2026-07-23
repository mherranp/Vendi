"""Resolución del negocio (tenant) a partir del token.

Reescritura completa del middleware de BaseSaaS. **No** se porta: la resolución
por subdominio (Vendi no da un subdominio por negocio), el header `X-Organization`
por slug (no hay slugs), los prefijos `sk_live_`/`sk_test_` (las API keys están
fuera de Fase 0) y el enriquecimiento con `tenant_status_resolver` para el
freeze (el freeze no existe; la suspensión llega en la tarea 4.2 y se cablea
como dependencia, no aquí).

Sí se porta el orden de resolución y el hábito de registrar los fallos con log
en vez de dejar subir un 500.

## Cambio de comportamiento respecto a BaseSaaS: aquí se falla, no se sigue

El middleware de BaseSaaS envolvía la validación del token en un `try/except`
que **registraba el error y continuaba**. Con schema-per-tenant eso era
tolerable: sin tenant no había `search_path` y la consulta fallaba sola. Aquí
no: sin tenant la sesión no siembra el GUC y las consultas devuelven **cero
filas sin error**. Un token expirado se convertiría en "tu negocio no tiene
ventas". Por eso este middleware corta con 401/403/400 explícitos.

## Por qué NO hay fallback a `get_user_organizations`

El informe del spike de Keycloak recomienda, para el caso del usuario
multi-organización que llega sin claim, un fallback contra
`get_user_organizations` con caché. Se ha medido lo que cuesta y se ha
descartado. La medición (matriz completa en `docs/deuda-tecnica.md`, D-02):

    C1 · solo manage-users                    NO 403  GET /organizations/members/{id}/organizations
    C2 · manage-users + view-users + query-*  NO 403  GET /organizations/members/{id}/organizations
    C3 · manage-realm + manage-users          OK 200  GET /organizations/members/{id}/organizations

Es decir: **ese fallback exige `manage-realm` en el cliente de Keycloak que use
la API general**, y `manage-realm` permite reescribir el realm entero — crear
flujos de autenticación, reenlazar `browserFlow` sacando el login con passkey,
apagar la protección de fuerza bruta, abrir el auto-registro. Poner eso en el
camino de cada request para arreglar un caso que **ya falla cerrado** es un mal
negocio: un usuario multi-organización cuyo cliente olvidó pedir
`scope=organization:*` recibe un 403, no ve datos de nadie. Es un fallo de
usabilidad, no de aislamiento.

Lo que sí se hace, y es más barato y más útil: el 403 lleva el código
`sin_organizacion_en_token` y un mensaje que dice exactamente qué falta. El
frontend puede reaccionar a ese código (rehacer el login pidiendo el scope
correcto) sin que el backend necesite privilegios de administrador de realm.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from vendi_core.auth.jwt import JWTValidator
from vendi_core.tenant.context import TenantContext, current_tenant_id
from vendi_core.tracing.context import bind_tenant_id

logger = structlog.get_logger()

# Rutas que no necesitan token de ninguna clase.
RUTAS_PUBLICAS: frozenset[str] = frozenset(
    {"/health", "/health/ready", "/health/live", "/docs", "/redoc", "/openapi.json", "/metrics"}
)

# Prefijo de las rutas de plataforma: exigen token válido pero **no** tenant.
# Son las de la consola de Vendi, que trabaja cross-tenant por definición.
PREFIJO_PLATAFORMA = "/api/v1/platform"

# Header con el que un usuario multi-organización elige negocio.
HEADER_TENANT = "X-Tenant-Id"


def _error(status: int, mensaje: str, codigo: str) -> JSONResponse:
    """Respuesta con el mismo sobre que emite `ErrorHandlerMiddleware`.

    Se construye a mano porque un `BaseHTTPMiddleware` que devuelve en vez de
    llamar a `call_next` no pasa por el manejador de errores de dominio.
    Mantener el sobre idéntico es lo que hace que el frontend tenga un solo
    camino de parseo de errores.
    """
    return JSONResponse(
        status_code=status,
        content={"success": False, "message": mensaje, "code": codigo},
    )


class TenantMiddleware(BaseHTTPMiddleware):
    """Resuelve el negocio desde el claim `organization` del token.

    El alias de la Organization **es** el `tenant_id` (`alias = str(tenant_id)`,
    decisión 3 del informe del spike de Keycloak), así que la resolución es una
    conversión de tipo y no una consulta: ni a Keycloak ni a base de datos.

    Publica el resultado en `request.state.tenant` (para los handlers y el
    decorador de auditoría) y en el ContextVar `current_tenant_id` (para el
    `SET LOCAL` que emite la sesión en cada transacción).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        ruta = request.url.path.rstrip("/") or "/"
        if ruta in RUTAS_PUBLICAS:
            return await call_next(request)

        es_plataforma = ruta == PREFIJO_PLATAFORMA or ruta.startswith(PREFIJO_PLATAFORMA + "/")

        cabecera = request.headers.get("Authorization", "")
        if not cabecera.startswith("Bearer "):
            return _error(401, "Falta el token de acceso", "token_ausente")
        token = cabecera[7:]

        validador: JWTValidator | None = getattr(request.app.state, "jwt_validator", None)
        if validador is None:
            # Error de cableado de la app, no del cliente. 500 con log, porque
            # devolver 401 escondería un fallo de despliegue detrás de lo que
            # parecería un problema de credenciales del usuario.
            logger.error("tenant_middleware_sin_validador", ruta=ruta)
            return _error(500, "La API no está correctamente configurada", "config_invalida")

        try:
            user = await validador.validate_token(token)
        except ValueError as exc:
            # Todo lo que el validador rechaza —expirado, sin kid, realm no
            # permitido, audiencia mala, firma inválida— sale por aquí como 401
            # tipado. Nunca como 500.
            logger.warning("tenant_middleware_token_rechazado", ruta=ruta, error=str(exc))
            return _error(401, "Token inválido o expirado", "token_invalido")
        except Exception as exc:  # noqa: BLE001
            # Keycloak inalcanzable al buscar el JWKS, por ejemplo. No es culpa
            # del token, así que no es 401: es 503 y se distingue en los logs.
            logger.error("tenant_middleware_validacion_fallida", ruta=ruta, error=str(exc))
            return _error(503, "No se pudo verificar el token en este momento", "verificacion_no_disponible")

        request.state.user = user
        # El token en crudo, para que `get_current_user` pueda reutilizar esta
        # validación solo si el header es exactamente el mismo (ver la nota en
        # `vendi_core.auth.dependencies`).
        request.state.token_validado = token

        if es_plataforma:
            # Las rutas de plataforma no llevan tenant. El permiso
            # `platform:admin` lo exige la dependencia del router, no esto.
            return await call_next(request)

        alias = list(user.organizations)

        if not alias:
            return _error(
                403,
                "El token no trae ninguna organización. Si el usuario pertenece a más de un "
                "negocio, el cliente debe pedir 'scope=organization:*' al iniciar sesión.",
                "sin_organizacion_en_token",
            )

        if len(alias) == 1:
            elegido = alias[0]
        else:
            elegido = request.headers.get(HEADER_TENANT, "")
            if elegido not in alias:
                # Nótese qué se compara: el header contra los alias DEL TOKEN.
                # El header por sí solo no vale nada; solo sirve para desempatar
                # entre negocios de los que el usuario ya es miembro según
                # Keycloak. Un header con el alias de un negocio ajeno cae aquí.
                return _error(
                    400,
                    f"El usuario pertenece a varios negocios: indica cuál en la cabecera {HEADER_TENANT}.",
                    "tenant_no_especificado",
                )

        try:
            tenant_id = uuid.UUID(elegido)
        except (ValueError, AttributeError, TypeError):
            # El alias tiene que ser un UUID porque ES el tenant_id. Si no lo
            # es, el realm está mal aprovisionado (alguien creó una Organization
            # a mano con alias libre). Se corta aquí y no en la base de datos:
            # el spike midió que un GUC con basura produce
            # `invalid input syntax for type uuid` y aborta la transacción — un
            # 500 feo por un problema de configuración que sabemos diagnosticar.
            logger.warning(
                "tenant_middleware_alias_no_uuid",
                ruta=ruta,
                alias=elegido,
                usuario=user.user_id,
            )
            return _error(401, "La organización del token no es válida", "alias_de_organizacion_invalido")

        marca = current_tenant_id.set(tenant_id)
        try:
            request.state.tenant = TenantContext(tenant_id=tenant_id)
            bind_tenant_id(str(tenant_id))
            return await call_next(request)
        finally:
            # `reset` en `finally` y no después del `return`: si el handler
            # lanza, el ContextVar tiene que quedar limpio igual. Starlette
            # ejecuta cada request en su propio contexto de `contextvars`, así
            # que una fuga aquí no cruzaría requests — pero `BaseHTTPMiddleware`
            # corre el resto de la cadena en una tarea aparte y no conviene
            # depender de ese detalle de implementación para algo de lo que
            # depende el aislamiento.
            current_tenant_id.reset(marca)
