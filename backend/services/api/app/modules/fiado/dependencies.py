"""Dependencias del módulo `fiado`.

El guard de permisos vive en `app.dependencies.exigir_permiso` (su casa desde
el módulo ventas). El reparto (ADR-023 y decisión 10 del plan): clientes →
`cliente:gestionar`; el cuaderno (créditos y su reprogramación) →
`fiado:crear`; cobrar → `fiado:abonar`. El cajero tiene los tres — fía y
cobra, que es el modo normal de la tienda —; el almacenista recibe 403 en
todo, y es la respuesta correcta y esperada.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import exigir_permiso, sesion_de_tenant
from app.modules.fiado.service import FiadoService
from app.modules.tenants.dependencies import exigir_negocio_activo
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.auth.policies import PERM_CLIENTE_GESTIONAR, PERM_FIADO_ABONAR, PERM_FIADO_CREAR
from vendi_core.tenant.context import TenantContext

exigir_cliente_gestionar = exigir_permiso(PERM_CLIENTE_GESTIONAR)
exigir_fiado_crear = exigir_permiso(PERM_FIADO_CREAR)
exigir_fiado_abonar = exigir_permiso(PERM_FIADO_ABONAR)


async def servicio_de_fiado(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
    user: UserContext = Depends(get_current_user),
) -> FiadoService:
    """El servicio del negocio del token, con la sesión que la RLS acota.

    `exigir_negocio_activo` va primero: un negocio suspendido no opera el
    cuaderno (403 `tenant_suspendido`). El `actor_id` queda en cada abono:
    la auditoría del gesto con dinero."""
    return FiadoService(session=session, tenant_id=tenant.tenant_id, actor_id=user.user_id)


__all__ = [
    "exigir_cliente_gestionar",
    "exigir_fiado_abonar",
    "exigir_fiado_crear",
    "servicio_de_fiado",
]
