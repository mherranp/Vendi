"""Consola de plataforma: `/api/v1/platform/tenants`.

Es el único router cross-tenant de la API. Todo lo que hay aquí trabaja con la
sesión de plataforma (`vendi_platform`, con `BYPASSRLS`) y por eso **todas** sus
rutas cuelgan de `exigir_admin_de_plataforma`: el permiso `platform:admin` es lo
que separa a un empleado de Vendi del dueño de un negocio, y ningún rol de
negocio lo tiene (ver `vendi_core.auth.policies`).

El prefijo `/api/v1/platform` también lo conoce `TenantMiddleware`: bajo él se
exige token válido pero **no** organización en el claim, porque un administrador
de plataforma no pertenece a ningún negocio. Es decir, hay exactamente dos
puertas y las dos tienen que abrirse: token válido (middleware) y
`platform:admin` (esta dependencia). Un token de dueño de negocio pasa la
primera y se estrella contra la segunda con 403.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import exigir_admin_de_plataforma
from app.modules.tenants.dependencies import servicio_de_tenants
from app.modules.tenants.schemas import TenantActualizar, TenantCrear, TenantSalida
from app.modules.tenants.service import TenantService
from vendi_core.auth.context import UserContext
from vendi_core.models.pagination import PagedList
from vendi_core.models.responses import ErrorResponse

router = APIRouter(
    prefix="/platform",
    tags=["plataforma"],
    dependencies=[Depends(exigir_admin_de_plataforma)],
    responses={
        401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
        403: {"model": ErrorResponse, "description": "El token no trae el permiso platform:admin"},
    },
)


@router.post(
    "/tenants",
    response_model=TenantSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Dar de alta un negocio",
    responses={
        502: {"model": ErrorResponse, "description": "Keycloak no pudo crear la organización"},
    },
)
async def crear_tenant(
    datos: TenantCrear,
    servicio: TenantService = Depends(servicio_de_tenants),
    actor: UserContext = Depends(exigir_admin_de_plataforma),
) -> TenantSalida:
    """Crea el negocio y su Organization en Keycloak, en ese orden y con compensación.

    Si Keycloak falla, no queda fila: se deshace la transacción y sube un error
    tipado (502 con sobre estándar), no un 500 con traza.

    Dos negocios pueden llamarse igual: el nombre no es identidad. Ver la nota
    de `create_organization` sobre por qué el `name` de la Organization es el
    UUID y no el nombre comercial.
    """
    tenant = await servicio.crear(datos.nombre, actor=actor)
    return TenantSalida.model_validate(tenant)


@router.get(
    "/tenants",
    response_model=PagedList[TenantSalida],
    summary="Listar negocios",
)
async def listar_tenants(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    incluir_eliminados: bool = Query(default=False),
    servicio: TenantService = Depends(servicio_de_tenants),
) -> PagedList[TenantSalida]:
    filas, total = await servicio.listar(skip=skip, limit=limit, incluir_eliminados=incluir_eliminados)
    return PagedList[TenantSalida](
        items=[TenantSalida.model_validate(f) for f in filas],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantSalida,
    summary="Ver un negocio",
    responses={404: {"model": ErrorResponse, "description": "No existe"}},
)
async def ver_tenant(
    tenant_id: uuid.UUID,
    servicio: TenantService = Depends(servicio_de_tenants),
) -> TenantSalida:
    return TenantSalida.model_validate(await servicio.obtener(tenant_id))


@router.patch(
    "/tenants/{tenant_id}",
    response_model=TenantSalida,
    summary="Renombrar o suspender un negocio",
    responses={404: {"model": ErrorResponse, "description": "No existe"}},
)
async def actualizar_tenant(
    tenant_id: uuid.UUID,
    datos: TenantActualizar,
    servicio: TenantService = Depends(servicio_de_tenants),
    actor: UserContext = Depends(exigir_admin_de_plataforma),
) -> TenantSalida:
    """Cambia nombre y/o estado. Suspender aquí corta el acceso en ≤ TTL del cache.

    `estado="eliminado"` se rechaza a propósito: la baja tiene efectos en
    Keycloak y tiene su propio verbo (`DELETE`).
    """
    tenant = await servicio.actualizar(
        tenant_id,
        nombre=datos.nombre,
        estado=datos.estado.value if datos.estado else None,
        actor=actor,
    )
    return TenantSalida.model_validate(tenant)


@router.delete(
    "/tenants/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dar de baja un negocio",
    responses={404: {"model": ErrorResponse, "description": "No existe"}},
)
async def eliminar_tenant(
    tenant_id: uuid.UUID,
    servicio: TenantService = Depends(servicio_de_tenants),
    actor: UserContext = Depends(exigir_admin_de_plataforma),
) -> Response:
    """Borrado lógico de la fila + borrado de la Organization en Keycloak.

    La fila sobrevive para la auditoría y para que su `id` —que fue alias de una
    Organization— no se reutilice jamás.
    """
    await servicio.eliminar(tenant_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
