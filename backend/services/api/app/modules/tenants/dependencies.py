"""Dependencias del módulo `tenants`, incluida la suspensión app-level.

## La suspensión es de la aplicación, y por qué

El spike de Keycloak (pregunta 6 del informe) midió que deshabilitar la
Organization de un negocio **no impide el login** y **no invalida los tokens ya
emitidos**: solo saca la organización del claim del *siguiente* token. Es decir,
el IdP no sabe suspender un negocio. Así que lo hace la API: cada request de
tenant consulta el estado del negocio y corta con 403 si no es `activo`.

## El cache y su TTL son la latencia de la suspensión

Consultar la tabla `tenants` en cada request sería un viaje a Postgres antes de
cada operación. El estado va a Redis con TTL de 60 s (`TENANT_ESTADO_CACHE_TTL`)
y las mutaciones invalidan la clave, así que en la práctica la suspensión se ve
al instante y el TTL solo cubre el caso de que la invalidación se pierda (Redis
reiniciado, otra instancia). **Ese TTL es el número que hay que citar cuando
alguien pregunta "¿cuánto tarda en cortarse el acceso?": como mucho 60 s, con un
token todavía criptográficamente válido.**

## Qué pasa si Redis se cae

Se degrada a consultar la base, nunca a dejar pasar. Un cache caído no puede
convertirse en "todos los negocios están activos": eso sería un fallo abierto en
el único control que corta el acceso de un negocio suspendido.
"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import contexto_de_tenant, sesion_de_plataforma
from app.modules.tenants.models import ESTADOS_QUE_SIRVEN, EstadoTenant, Tenant
from app.modules.tenants.service import TenantService
from vendi_core.errors.domain import NotFoundError, PermissionDeniedError
from vendi_core.tenant.context import TenantContext


def servicio_de_tenants(
    request: Request,
    session: AsyncSession = Depends(sesion_de_plataforma),
) -> TenantService:
    recursos = request.app.state.recursos
    return TenantService(
        session=session,
        keycloak=recursos.keycloak_aprovisionamiento,
        audit=recursos.audit_service,
        cache=recursos.redis,
        cache_ttl=recursos.settings.tenant_estado_cache_ttl,
    )


async def exigir_negocio_activo(
    tenant: TenantContext = Depends(contexto_de_tenant),
    servicio: TenantService = Depends(servicio_de_tenants),
) -> TenantContext:
    """Corta el request si el negocio del token no está activo.

    Los tres desenlaces son deliberadamente distintos porque significan cosas
    distintas para quien los recibe:

    - `activo` → sigue.
    - `suspendido` → 403 `tenant_suspendido`. El frontend puede mostrar
      "tu negocio está suspendido" en vez de una pantalla vacía.
    - no existe (o eliminado) → 404 `tenant_no_encontrado`. Ocurre con un token
      cuyo claim apunta a una Organization que quedó huérfana en Keycloak, y
      merece un mensaje distinto del de la suspensión: no es un problema de
      pago, es un negocio que ya no está.
    """
    estado = await servicio.estado_de(tenant.tenant_id)
    if estado is None:
        raise NotFoundError(
            "El negocio de tu sesión ya no existe. Vuelve a iniciar sesión.",
            code="tenant_no_encontrado",
        )
    if estado not in ESTADOS_QUE_SIRVEN:
        raise PermissionDeniedError(
            "Tu negocio está suspendido. Contacta con soporte de Vendi para reactivarlo.",
            code="tenant_suspendido",
            details={"estado": estado},
        )
    return tenant


async def negocio_del_token(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    servicio: TenantService = Depends(servicio_de_tenants),
) -> Tenant:
    """La fila completa del negocio del token. Siempre filtrada por el token.

    Nótese lo que NO recibe: ningún identificador que venga del cuerpo, de la
    URL o de una cabecera libre. El único `tenant_id` que llega aquí es el que
    `TenantMiddleware` sacó del claim `organization`, y ese claim lo firma
    Keycloak.
    """
    return await servicio.obtener(tenant.tenant_id)


__all__ = [
    "EstadoTenant",
    "exigir_negocio_activo",
    "negocio_del_token",
    "servicio_de_tenants",
]
