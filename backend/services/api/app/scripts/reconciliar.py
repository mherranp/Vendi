"""Corrección de la deriva entre la tabla `tenants` y las Organizations de Keycloak.

Lo ejecuta `scripts/reconcile-keycloak.sh` con `RECONCILE_APLICAR=1`. El script
detecta; esto corrige.

## Qué corrige y qué NO

- **Negocio sin organización** → se crea. Es el lado que rompe el producto: los
  usuarios de ese negocio no pueden entrar, porque sin organización no hay claim
  `organization` en su token y `TenantMiddleware` responde 403. Es también la
  ventana que deja abierta la compensación del alta: si la transacción se cae
  entre `create_organization` y el `COMMIT`, queda el caso inverso; si se cae
  después del `COMMIT` de un alta que no llegó a Keycloak, queda éste.
- **Organización huérfana** (sin negocio vivo) → se **informa**, y solo se borra
  con `--borrar-huerfanas`. Borrar organizaciones es destructivo e irreversible:
  se lleva por delante la membresía de sus usuarios. Y una huérfana no rompe
  nada — el alias que ocupa es un UUID que jamás se reutiliza, y un token con
  ese claim se estrella contra la dependencia de estado con 404.

## Por qué en proceso y no por HTTP

Igual que la siembra: usa `TenantService`, el mismo objeto que el router, y
evita necesitar un token con `platform:admin` — que hoy solo se consigue con el
grant de contraseña contra un cliente público, la deuda D-01 que la Etapa 5
tiene que poder apagar sin romper las herramientas de operación.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog
from sqlalchemy import select

from app.modules.tenants.models import EstadoTenant, Tenant
from app.modules.tenants.service import TenantService
from app.settings import cargar_settings
from vendi_core.audit.service import AuditService
from vendi_core.auth.keycloak_admin import VendiKeycloakAprovisionamiento
from vendi_core.db.engine import create_engine, dispose_engine
from vendi_core.db.session import create_platform_session_factory
from vendi_core.logging.setup import setup_logging

log = structlog.get_logger("vendi.reconcile")


async def reconciliar(borrar_huerfanas: bool = False) -> int:
    settings = cargar_settings()
    kc = VendiKeycloakAprovisionamiento(
        server_url=settings.keycloak_url_normalizada,
        client_id=settings.keycloak_provisioning_client_id,
        client_secret=settings.keycloak_provisioning_client_secret,
        realm=settings.keycloak_realm,
    )

    engine = create_engine(settings.platform_database_url)
    fabrica = create_platform_session_factory(engine)
    creadas = 0
    reenlazadas = 0
    huerfanas: list[str] = []
    try:
        async with fabrica() as session:
            # `TenantService` se construye aquí solo por su candado de sesión:
            # si un día alguien cablea esto con la fábrica de la API, revienta
            # en el constructor y no a mitad de la reconciliación.
            TenantService(
                session=session,
                keycloak=kc,
                audit=AuditService(session_factory=fabrica, service_name="reconcile"),
            )
            vivos = (
                (
                    await session.execute(
                        select(Tenant).where(Tenant.estado != EstadoTenant.ELIMINADO).where(Tenant.deleted_at.is_(None))
                    )
                )
                .scalars()
                .all()
            )

            alias_vivos = {str(t.id) for t in vivos}

            for tenant in vivos:
                org = await kc.get_organization_by_alias(tenant.id)
                if org is not None:
                    if tenant.kc_org_id != org["id"]:
                        # La organización existe pero la fila apuntaba a otro id
                        # (o a ninguno). Reenlazar es barato y evita que la
                        # baja del negocio deje la organización sin borrar.
                        log.warning(
                            "reenlazando_organizacion",
                            tenant_id=str(tenant.id),
                            antes=tenant.kc_org_id,
                            despues=org["id"],
                        )
                        tenant.kc_org_id = org["id"]
                        reenlazadas += 1
                    continue
                org_id = await kc.create_organization(tenant.id, tenant.nombre)
                tenant.kc_org_id = org_id
                creadas += 1
                log.info("organizacion_creada_por_reconciliacion", tenant_id=str(tenant.id), kc_org_id=org_id)

            await session.commit()

        # Huérfanas: se recorren TODAS las organizaciones con paginación. Sin
        # paginar, la Admin API devuelve 10 por defecto y con 200 negocios el
        # informe estaría truncado a la primera página sin decirlo.
        primero, pagina = 0, 100
        while True:
            lote = await kc.list_organizations(first=primero, max_result=pagina)
            for org in lote:
                if org.get("alias") not in alias_vivos:
                    huerfanas.append(f"{org.get('alias')} ({org.get('id')})")
            if len(lote) < pagina:
                break
            primero += pagina
    finally:
        await dispose_engine(engine)

    if huerfanas:
        if borrar_huerfanas:
            for entrada in huerfanas:
                org_id = entrada.rsplit("(", 1)[1].rstrip(")")
                await kc.delete_organization(org_id)
                log.warning("organizacion_huerfana_borrada", kc_org_id=org_id)
        else:
            log.warning(
                "organizaciones_huerfanas",
                cuantas=len(huerfanas),
                alias=huerfanas,
                accion="no se borran sin --borrar-huerfanas: es destructivo e irreversible",
            )

    log.info(
        "reconciliacion_terminada",
        organizaciones_creadas=creadas,
        organizaciones_reenlazadas=reenlazadas,
        huerfanas=len(huerfanas),
    )
    # Código 0 solo si no queda nada pendiente de decisión humana.
    return 0 if (borrar_huerfanas or not huerfanas) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcilia `tenants` con las Organizations de Keycloak.")
    parser.add_argument(
        "--borrar-huerfanas",
        action="store_true",
        help="Borra las organizaciones sin negocio vivo. Destructivo: se lleva la membresía de sus usuarios.",
    )
    args = parser.parse_args()
    settings = cargar_settings()
    setup_logging(level=settings.log_level, json_output=False)
    return asyncio.run(reconciliar(borrar_huerfanas=args.borrar_huerfanas))


if __name__ == "__main__":
    sys.exit(main())
