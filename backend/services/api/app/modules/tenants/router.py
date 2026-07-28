"""Rutas del negocio en sesión: `/api/v1/tenants/*`.

`GET /tenants/me` devuelve **el negocio del token y nada más**. No acepta un id
por URL, ni por cuerpo, ni por cabecera. El único identificador que interviene
es el que `TenantMiddleware` sacó del claim `organization`, firmado por
Keycloak.

`GET /tenants/mios` es la excepción amable: la lista de negocios del token
(id, nombre, estado) para el selector de la consola web. Se sirve con el token
validado y SIN resolver tenant (`RUTAS_SIN_TENANT` del middleware), porque su
usuario natural es quien tiene varios negocios y todavía no ha elegido ninguno.

Un usuario que pertenece a dos negocios elige con `X-Tenant-Id`, y el middleware
solo acepta ese header si el alias está **en su propio token**: un alias ajeno
cae con 400 antes de llegar aquí.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.modules.tenants.dependencies import negocio_del_token, servicio_de_tenants
from app.modules.tenants.models import Tenant
from app.modules.tenants.schemas import TenantMioSalida, TenantSalida
from app.modules.tenants.service import TenantService
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.models.responses import ErrorResponse

router = APIRouter(prefix="/tenants", tags=["negocio"])


@router.get(
    "/me",
    response_model=TenantSalida,
    summary="El negocio de la sesión actual",
    responses={
        403: {"model": ErrorResponse, "description": "El negocio está suspendido"},
        404: {"model": ErrorResponse, "description": "El negocio ya no existe"},
    },
)
async def mi_negocio(tenant: Tenant = Depends(negocio_del_token)) -> Tenant:
    return tenant


@router.get(
    "/mios",
    response_model=list[TenantMioSalida],
    summary="Los negocios del usuario autenticado",
    responses={
        401: {"model": ErrorResponse, "description": "Sin token o token inválido"},
    },
)
async def mis_negocios(
    user: UserContext = Depends(get_current_user),
    servicio: TenantService = Depends(servicio_de_tenants),
) -> list[Tenant]:
    ids = [uuid.UUID(alias) for alias in user.alias_de_organizacion]
    return await servicio.listar_por_ids(ids)
