"""Rutas del negocio en sesión: `/api/v1/tenants/*`.

Una sola ruta en Fase 0, y es la que demuestra el aislamiento de punta a punta:
`GET /tenants/me` devuelve **el negocio del token y nada más**. No acepta un id
por URL, ni por cuerpo, ni por cabecera. El único identificador que interviene
es el que `TenantMiddleware` sacó del claim `organization`, firmado por
Keycloak.

Un usuario que pertenece a dos negocios elige con `X-Tenant-Id`, y el middleware
solo acepta ese header si el alias está **en su propio token**: un alias ajeno
cae con 400 antes de llegar aquí.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.modules.tenants.dependencies import negocio_del_token
from app.modules.tenants.models import Tenant
from app.modules.tenants.schemas import TenantSalida
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
