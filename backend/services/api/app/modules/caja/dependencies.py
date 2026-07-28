"""Dependencias del módulo `caja`.

El guard de permisos vive en `app.dependencies.exigir_permiso` (su casa desde
el módulo ventas). El reparto (ADR-023 y decisión 4 del plan): el cajero
abre, lee y mueve caja; cerrar y el historial de arqueos exigen
`caja:cerrar`; los reportes exigen `reporte:leer`. El 403 del cajero al
cerrar es la respuesta correcta y esperada, no un error a ocultar.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import exigir_permiso, sesion_de_tenant
from app.modules.caja.reportes import ReportesService
from app.modules.caja.service import CajaService
from app.modules.tenants.dependencies import exigir_negocio_activo
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.auth.policies import (
    PERM_CAJA_ABRIR,
    PERM_CAJA_CERRAR,
    PERM_CAJA_LEER,
    PERM_CAJA_MOVIMIENTO,
    PERM_REPORTE_LEER,
    has_permission,
)
from vendi_core.tenant.context import TenantContext

exigir_caja_leer = exigir_permiso(PERM_CAJA_LEER)
exigir_caja_abrir = exigir_permiso(PERM_CAJA_ABRIR)
exigir_caja_cerrar = exigir_permiso(PERM_CAJA_CERRAR)
exigir_caja_movimiento = exigir_permiso(PERM_CAJA_MOVIMIENTO)
exigir_reporte_leer = exigir_permiso(PERM_REPORTE_LEER)


async def servicio_de_caja(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
    user: UserContext = Depends(get_current_user),
) -> CajaService:
    """El servicio del negocio del token, con la sesión que la RLS acota.

    `exigir_negocio_activo` va primero: un negocio suspendido no opera caja
    (403 `tenant_suspendido`). El veredicto sobre cerrar se deriva AQUÍ del
    token y viaja al servicio como flag — el servicio no lee claims
    (ADR-015/ADR-023) — y condiciona el esperado vivo (decisión 4). El
    `actor_id` queda en cada sesión y movimiento: la auditoría del gesto
    con dinero."""
    return CajaService(
        session=session,
        tenant_id=tenant.tenant_id,
        actor_id=user.user_id,
        puede_cerrar=has_permission(user, PERM_CAJA_CERRAR),
    )


async def servicio_de_reportes(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
) -> ReportesService:
    return ReportesService(session=session, tenant_id=tenant.tenant_id)


__all__ = [
    "exigir_caja_abrir",
    "exigir_caja_cerrar",
    "exigir_caja_leer",
    "exigir_caja_movimiento",
    "exigir_reporte_leer",
    "servicio_de_caja",
    "servicio_de_reportes",
]
