"""Dependencias de FastAPI comunes a todos los módulos de la API.

Aquí viven las dos que sostienen el aislamiento:

- `sesion_de_tenant`: la sesión con RLS. Comprueba en caliente que NO es una
  sesión de plataforma. El chequeo parece redundante —la fábrica es otra— pero
  el error que previene es el más caro del diseño: un handler de negocio que
  recibe la sesión de plataforma funciona, no lanza nada, y devuelve los datos
  de todos los negocios de la región.
- `sesion_de_plataforma`: la que salta RLS. Solo la piden los routers de
  `/platform/*` y el aprovisionamiento, y siempre filtrando en Python por el
  `tenant_id` que salió del token.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.lifespan import Recursos
from app.settings import Settings
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.auth.policies import PERM_PLATFORM_ADMIN, has_permission
from vendi_core.cache.redis import RedisCache
from vendi_core.db.session import es_sesion_de_plataforma
from vendi_core.errors.domain import AuthenticationError, PermissionDeniedError
from vendi_core.tenant.context import TenantContext


def recursos_de(request: Request) -> Recursos:
    return request.app.state.recursos


def settings_de(request: Request) -> Settings:
    return request.app.state.settings


def redis_de(request: Request) -> RedisCache | None:
    return request.app.state.recursos.redis


async def sesion_de_tenant(request: Request) -> AsyncIterator[AsyncSession]:
    """Sesión con RLS activo. Es la que deben usar los handlers de negocio."""
    recursos: Recursos = request.app.state.recursos
    async with recursos.sesion_tenant() as session:
        if es_sesion_de_plataforma(session):
            # Cableado imposible por construcción hoy; el assert existe para el
            # día que alguien "simplifique" el lifespan pasando una fábrica por
            # la otra. Sin él, ese cambio pasaría todos los tests de negocio.
            raise RuntimeError(
                "sesion_de_tenant recibió una sesión de PLATAFORMA: saltaría RLS y el "
                "handler vería las filas de todos los negocios."
            )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def sesion_de_plataforma(request: Request) -> AsyncIterator[AsyncSession]:
    """Sesión sin RLS (rol `vendi_platform`). Cross-tenant por definición."""
    recursos: Recursos = request.app.state.recursos
    async with recursos.sesion_plataforma() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def contexto_de_tenant(request: Request) -> TenantContext:
    """El negocio que `TenantMiddleware` resolvió del token.

    Si falta es un error de cableado (la ruta se montó fuera del alcance del
    middleware), no del cliente: por eso 401 con código propio y no un 403 que
    parecería un problema de permisos.
    """
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise AuthenticationError(
            "Esta ruta necesita un negocio resuelto del token y no lo hay.",
            code="sin_tenant_en_el_contexto",
        )
    return tenant


def tenant_id_actual(tenant: TenantContext = Depends(contexto_de_tenant)) -> uuid.UUID:
    return tenant.tenant_id


async def exigir_admin_de_plataforma(user: UserContext = Depends(get_current_user)) -> UserContext:
    """Permiso `platform:admin`: separa al empleado de Vendi del dueño de un negocio.

    Se declara aquí y no se reutiliza `require_permission` de `vendi-core` por
    una razón concreta: aquella lanza `HTTPException`, cuyo cuerpo es
    `{"detail": ...}`, y toda la API contesta con el sobre
    `{"success": false, "message": ..., "code": ...}`. Dos formatos de error en
    la misma API significan dos caminos de parseo en el frontend, y el segundo
    siempre acaba sin escribirse.
    """
    if not has_permission(user, PERM_PLATFORM_ADMIN):
        raise PermissionDeniedError(
            "Esta operación es de la consola de Vendi y requiere el permiso platform:admin.",
            code="requiere_platform_admin",
        )
    return user
