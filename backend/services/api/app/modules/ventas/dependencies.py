"""Dependencias del módulo `ventas`.

El guard de permisos vive en `app.dependencies.exigir_permiso` (decisión 12
del plan: dos módulos lo usan; su casa es la de `exigir_admin_de_plataforma`,
que existe por el mismo motivo).
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import exigir_permiso, sesion_de_tenant
from app.modules.tenants.dependencies import exigir_negocio_activo
from app.modules.ventas.service import VentasService
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.auth.policies import PERM_PRODUCTO_LEER, PERM_VENTA_ANULAR, PERM_VENTA_CREAR, has_permission
from vendi_core.tenant.context import TenantContext

exigir_venta_crear = exigir_permiso(PERM_VENTA_CREAR)
exigir_venta_anular = exigir_permiso(PERM_VENTA_ANULAR)
exigir_producto_leer = exigir_permiso(PERM_PRODUCTO_LEER)


async def servicio_de_ventas(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
    user: UserContext = Depends(get_current_user),
) -> VentasService:
    """El servicio del negocio del token, con la sesión que la RLS acota.

    `exigir_negocio_activo` va primero: un negocio suspendido no sincroniza
    (403 `tenant_suspendido`). El veredicto sobre anular se deriva AQUÍ del
    token y viaja al servicio como flag: el servicio no lee claims (la
    autorización lee solo el JWT, ADR-015/ADR-023), y la operación
    `venta.anular` de un cajero se rechaza por operación, no con un 403 del
    lote entero (decisión 12 del plan).
    """
    return VentasService(
        session=session,
        tenant_id=tenant.tenant_id,
        actor_id=user.user_id,
        puede_anular=has_permission(user, PERM_VENTA_ANULAR),
    )


__all__ = [
    "exigir_producto_leer",
    "exigir_venta_anular",
    "exigir_venta_crear",
    "servicio_de_ventas",
]
