"""Fábrica de la API de Vendi: la cadena de middlewares y el montaje de rutas.

## El orden de los middlewares es contrato, no estilo

Starlette aplica los middlewares de fuera hacia dentro en el orden inverso al de
registro: `add_middleware` **inserta al principio** de `app.user_middleware`, así
que el último registrado es el más externo. Eso hace que el código se lea al
revés de como se ejecuta, que es precisamente cómo se cuelan los errores de
orden. Por eso aquí se declara la cadena en orden de EJECUCIÓN
(`_cadena_en_orden_de_ejecucion`) y se registra al revés en un solo sitio, y por
eso hay un test que fija la lista resultante
(`tests/api/test_orden_de_middlewares.py`).

De fuera hacia dentro:

1. `CORSMiddleware` — **solo si la aplicación gestiona CORS** (ver el bloque de
   más abajo). Tiene que ser el más externo: si algo por debajo corta el
   request, la respuesta de error sigue llevando `Access-Control-Allow-*` y el
   navegador puede mostrarle al SPA el código real en vez de un «CORS error»
   opaco.
2. `CorrelationIdMiddleware` — asigna el id de correlación y lo ata al contexto
   de logging. Va arriba para que TODO lo de debajo, incluidos los errores,
   quede correlacionado.
3. `SecurityHeadersMiddleware` — cabeceras de seguridad en toda respuesta,
   también en las de error.
4. `APIVersionMiddleware` — `X-API-Version` en toda respuesta.
5. `ErrorHandlerMiddleware` — convierte `DomainError` en su status y su sobre, y
   cualquier excepción no controlada en un 500 con sobre. Va por DEBAJO de los
   tres anteriores para que sus respuestas también lleven cabeceras y
   correlación.
6. `TenantMiddleware` — valida el JWT y resuelve el negocio. El más interno de
   los propios, porque necesita que ya exista correlación y que sus 401/403
   salgan con cabeceras.
7. `PrometheusInstrumentatorMiddleware` — mide latencia y códigos. Se registra
   el primero (queda el más interno) para que mida el trabajo real de la API y
   no el coste de la cadena de cabeceras.

La resolución de IP de cliente (`trusted_client_ip`) **no es un middleware**, a
diferencia de lo que sugiere el plan: en `vendi-core` es una función que leen el
decorador de auditoría y quien la necesite, configurada por
`app.state.trusted_proxies`. Se anota aquí porque el plan la lista dentro de la
cadena y quien compare las dos cosas merece la explicación.

## CORS: lo termina Traefik, y por eso la aplicación no lo duplica

Medido contra el stack levantado:

    curl --resolve api.vendi.co:443:127.0.0.1 -i -X OPTIONS https://api.vendi.co/health \
         -H 'Origin: http://localhost:4200' -H 'Access-Control-Request-Method: GET'
    HTTP/2 200 · access-control-allow-origin: http://localhost:4200 · content-length: 0

La respuesta no lleva `server: uvicorn`: el preflight **no llega a la API**, lo
contesta el middleware `cors-api` de Traefik. Y en el request real Traefik
inyecta `Access-Control-Allow-Origin`. Si la aplicación añadiera el suyo, la
respuesta saldría con la cabecera DUPLICADA y el navegador rechaza la respuesta
entera: las cuatro SPAs caerían con «CORS error» y sin un solo log en el
backend.

Un solo dueño, entonces: Traefik. `CORS_ORIGINS` existe para las topologías sin
ese borde delante (la API a pelo, otro proxy) y por defecto está vacío.

Lo que sí se arregla en la aplicación, porque es un defecto suyo y no del borde:
`TenantMiddleware` ya no responde 401 a un preflight de CORS. Un preflight no
lleva `Authorization` —la especificación de Fetch lo prohíbe— así que exigirle
token era garantizar que el navegador nunca hiciera el request real.

Nota de la Etapa 5 sobre `allow_headers=["*"]`: cuando la aplicación sí gestiona
CORS (topologías sin Traefik delante), el comodín se combina con
`allow_credentials=True`, y la especificación de Fetch dice que en una petición
**con credenciales** el `*` de `Access-Control-Allow-Headers` se compara
LITERALMENTE: no es un comodín. El preflight de cualquier petición con
`Authorization` fallaría. Por eso aquí va la lista explícita. El mismo defecto
estaba en el middleware `cors-api` de Traefik y se corrigió allí igual.

## `/docs`, `/redoc` y `/openapi.json`: cerrados salvo que se pidan

Ver `Settings.docs_publicos`. Por defecto no se registran las rutas.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware import Middleware

from app import health, metrics
from app.lifespan import construir_recursos, lifespan, publicar_en_estado
from app.modules.catalogo.router import router as router_catalogo
from app.modules.platform.router import router as router_plataforma
from app.modules.tenants.router import router as router_tenants
from app.settings import Settings, cargar_settings
from vendi_core.logging.setup import setup_logging
from vendi_core.middleware.api_version import APIVersionMiddleware
from vendi_core.middleware.correlation import CorrelationIdMiddleware
from vendi_core.middleware.error_handler import ErrorHandlerMiddleware
from vendi_core.middleware.security_headers import SecurityHeadersMiddleware
from vendi_core.tenant.middleware import TenantMiddleware

DESCRIPCION = """
API regional de Vendi. Fase 1: fundación + catálogo de productos.

El negocio (tenant) se resuelve del claim `organization` del token: el alias de
la Organization de Keycloak **es** el identificador del negocio. Un usuario que
pertenece a varios negocios indica cuál con la cabecera `X-Tenant-Id`, y solo
puede elegir entre los que ya trae su token.
"""

#: Cabeceras que la API acepta en una petición cruzada. Tiene que coincidir con
#: `accessControlAllowHeaders` del middleware `cors-api` de Traefik
#: (infra/traefik/templates/dynamic.yml.tpl): las dos listas describen la misma
#: superficie desde los dos lados del borde, y `tests/api/test_cors.py` compara
#: literalmente los dos archivos para que no puedan separarse en silencio.
CABECERAS_CORS = [
    "Accept",
    "Accept-Language",
    "Authorization",
    "Content-Type",
    "X-Correlation-Id",
    "X-Requested-With",
    "X-Tenant-Id",
]


def _cadena_en_orden_de_ejecucion(settings: Settings) -> list[Middleware]:
    """La cadena de fuera hacia dentro. `crear_app` la registra invertida."""
    cadena: list[Middleware] = []

    origenes = settings.cors_origins_lista
    if origenes or settings.cors_origin_regex:
        cadena.append(
            Middleware(
                CORSMiddleware,
                allow_origins=origenes,
                allow_origin_regex=settings.cors_origin_regex or None,
                allow_credentials=True,
                allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                # Lista explícita, NO `["*"]`: con `allow_credentials=True` el
                # comodín se compara literalmente (Fetch §CORS-preflight) y el
                # preflight de cualquier petición con `Authorization` fallaría.
                allow_headers=CABECERAS_CORS,
                max_age=3600,
            )
        )

    cadena.extend(
        [
            Middleware(CorrelationIdMiddleware),
            Middleware(SecurityHeadersMiddleware),
            Middleware(APIVersionMiddleware, version=settings.api_version),
            Middleware(ErrorHandlerMiddleware),
            Middleware(TenantMiddleware),
        ]
    )
    return cadena


def crear_app(settings: Settings | None = None) -> FastAPI:
    """Construye la aplicación. Sin E/S: no toca red ni base de datos.

    Los tests la llaman con unos `Settings` de prueba y obtienen la app real —la
    misma cadena de middlewares, las mismas rutas— sin necesitar el stack.
    """
    settings = settings or cargar_settings()
    setup_logging(level=settings.log_level, json_output=settings.log_json)

    # `/docs`, `/redoc` y `/openapi.json` solo existen si se piden. Ver
    # `Settings.docs_publicos`: por defecto NO, y entonces FastAPI ni siquiera
    # registra las rutas —el 404 es real, no un middleware que las tape.
    app = FastAPI(
        title="Vendi API",
        version="0.1.0",
        description=DESCRIPCION,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_publicos else None,
        redoc_url="/redoc" if settings.docs_publicos else None,
        openapi_url="/openapi.json" if settings.docs_publicos else None,
    )

    publicar_en_estado(app, construir_recursos(settings))

    # Se instrumenta ANTES de registrar la cadena para que el middleware de
    # Prometheus quede el más interno. `expose()` no se llama a propósito:
    # montaría `/metrics` SIN credencial. El endpoint lo pone `app.metrics`,
    # con la suya.
    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/health", "/health/live", "/health/ready", "/metrics"],
    ).instrument(app)

    # `reversed`: el último `add_middleware` queda el más externo, así que para
    # obtener el orden de ejecución declarado hay que registrar del revés.
    for capa in reversed(_cadena_en_orden_de_ejecucion(settings)):
        app.add_middleware(capa.cls, *capa.args, **capa.kwargs)

    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(router_plataforma, prefix="/api/v1")
    app.include_router(router_tenants, prefix="/api/v1")
    app.include_router(router_catalogo, prefix="/api/v1")

    return app
