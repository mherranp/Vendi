"""Dependencias del módulo `inventario`.

El guard de permisos vive en `app.dependencies.exigir_permiso` (su casa desde
el módulo ventas, por el mismo motivo que `exigir_admin_de_plataforma`).

Los permisos (ADR-023 y decisión 10 del plan): compras y ajustes exigen
`compra:crear` e `inventario:ajustar` también para LEER — el catálogo de
permisos es cerrado y los costos/ajustes no son para el cajero—; el estado
de stock exige `producto:leer` (los tres roles: el cajero ya ve el stock en
el POS).
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import exigir_permiso, sesion_de_tenant
from app.modules.inventario.service import InventarioService
from app.modules.tenants.dependencies import exigir_negocio_activo
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.auth.policies import PERM_COMPRA_CREAR, PERM_INVENTARIO_AJUSTAR, PERM_PRODUCTO_LEER
from vendi_core.tenant.context import TenantContext

exigir_compra_crear = exigir_permiso(PERM_COMPRA_CREAR)
exigir_inventario_ajustar = exigir_permiso(PERM_INVENTARIO_AJUSTAR)
exigir_producto_leer = exigir_permiso(PERM_PRODUCTO_LEER)


async def servicio_de_inventario(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
    user: UserContext = Depends(get_current_user),
) -> InventarioService:
    """El servicio del negocio del token, con la sesión que la RLS acota.

    `exigir_negocio_activo` va primero: un negocio suspendido no compra ni
    ajusta (403 `tenant_suspendido`). El `actor_id` queda grabado en cada
    ajuste (`aplicado_por`): la auditoría del gesto con stock.
    """
    return InventarioService(session=session, tenant_id=tenant.tenant_id, actor_id=user.user_id)


__all__ = [
    "exigir_compra_crear",
    "exigir_inventario_ajustar",
    "exigir_producto_leer",
    "servicio_de_inventario",
]
