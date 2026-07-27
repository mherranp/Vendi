"""Dependencias del módulo `catalogo`.

El guard de permisos vive en `app.dependencies.exigir_permiso` (decisión 12
del plan del módulo ventas: dos módulos lo usan; su casa es la de
`exigir_admin_de_plataforma`, que existe por el mismo motivo). Aquí se
reexporta para no tocar el router ni los tests del catálogo.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import contexto_de_tenant, exigir_permiso, sesion_de_tenant
from app.modules.catalogo.service import TIER_DEL_PILOTO, CatalogoService
from app.modules.tenants.dependencies import exigir_negocio_activo
from vendi_core.auth.policies import PERM_PRODUCTO_EDITAR, PERM_PRODUCTO_LEER
from vendi_core.tenant.context import TenantContext

exigir_producto_leer = exigir_permiso(PERM_PRODUCTO_LEER)
exigir_producto_editar = exigir_permiso(PERM_PRODUCTO_EDITAR)


async def tier_del_negocio(tenant: TenantContext = Depends(contexto_de_tenant)) -> str:
    """El tier del negocio en sesión. Hoy: `pro` para todos.

    Decisión 2 del plan del módulo: en Fase 1 no existe módulo de
    suscripciones ni columna de tier en `tenants`, y el plan maestro §5
    registra a todo negocio nuevo en el trial de Pro. El límite ya se
    verifica de verdad en `CatalogoService` (testeado con los tres tiers vía
    `dependency_overrides`); esta función es el ÚNICO punto de cambio cuando
    llegue la suscripción.
    """
    return TIER_DEL_PILOTO


async def servicio_de_catalogo(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
    tier: str = Depends(tier_del_negocio),
) -> CatalogoService:
    """El servicio del negocio del token, con la sesión que la RLS acota.

    `exigir_negocio_activo` va primero: un negocio suspendido corta con 403
    `tenant_suspendido` antes de tocar el catálogo (la suspensión es
    app-level; el token sigue siendo criptográficamente válido).
    """
    return CatalogoService(session=session, tenant_id=tenant.tenant_id, tier=tier)


__all__ = [
    "exigir_permiso",
    "exigir_producto_editar",
    "exigir_producto_leer",
    "servicio_de_catalogo",
    "tier_del_negocio",
]
