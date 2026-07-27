"""Siembra de desarrollo, idempotente. La ejecuta `scripts/seed.sh`.

Qué deja montado, y DÓNDE ocurre cada cosa desde el cierre de D-02 (ADR-027):

1. Los **permisos** como roles de realm y los **roles de negocio** como roles
   de realm y grupos homónimos con sus mapeos → los hace el **provisioner**
   (`POST /interno/v1/semilla/realm`). Necesita `manage-realm`, que ya no vive
   en este proceso.
2. El **administrador de plataforma** `admin@vendi.co`, con `platform:admin`
   → también el provisioner (`/semilla/admin-plataforma`).
3. El **negocio demo** «Tienda Don Carlos» → AQUÍ, con `TenantService` contra
   la base de datos; la Organization la crea el provisioner por HTTP interno a
   través del mismo cliente que usa la API.
4. El **dueño** `dueno@demo.vendi.co`, en el grupo `dueno` y miembro de la
   organización del negocio demo → el provisioner (`/semilla/dueno-demo`),
   que resuelve la organización por alias y falla con 404 si no existe.

Este script se sigue ejecutando DENTRO del contenedor de la API (así usa la
misma configuración y los mismos DSN que producción), pero ya no instancia el
cliente de Keycloak de aprovisionamiento: orquesta llamadas al provisioner.
La credencial con `manage-realm` no pasa por aquí ni de camino.

## Idempotente de verdad

Correrlo tres veces seguidas tiene que dar el mismo estado y ninguna operación
destructiva. Cada paso comprueba antes de crear (los endpoints de siembra del
provisioner también), y el negocio demo se busca por nombre entre los no
eliminados. Si alguien borra el negocio demo a mano, la siguiente pasada lo
vuelve a crear **con un id nuevo** — y eso es correcto: el id anterior fue
alias de una Organization y no se reutiliza jamás.

## Por qué el alta del negocio NO va por HTTP contra la API

El plan pedía crear el negocio demo «vía la API» para ejercer el mismo camino de
aprovisionamiento que producción. Se ejerce el mismo camino —se llama a
`TenantService`, el mismo objeto que usa el router— pero en proceso, no por
HTTP. Motivo: por HTTP haría falta un token con `platform:admin`, y el único
modo de obtenerlo sin navegador es el grant de contraseña contra un cliente
público, que es exactamente la deuda D-01 que la Etapa 5 cerró. Una siembra que
dependa de ROPC impediría mantenerlo apagado.

## Las contraseñas vienen del entorno

Sin defecto. Una contraseña por defecto en un script de siembra es una
contraseña en producción el día que alguien ejecute la siembra donde no debía.
"""

from __future__ import annotations

import asyncio
import os
import sys

import structlog
from sqlalchemy import select

from app.modules.tenants.models import Tenant
from app.modules.tenants.service import TenantService
from app.settings import cargar_settings
from vendi_core.audit.service import AuditService
from vendi_core.db.engine import create_engine, dispose_engine
from vendi_core.db.session import create_platform_session_factory
from vendi_core.logging.setup import setup_logging
from vendi_core.provisioning.cliente import ClienteAprovisionamiento

log = structlog.get_logger("vendi.seed")

NOMBRE_NEGOCIO_DEMO = "Tienda Don Carlos"
USUARIO_ADMIN = "admin@vendi.co"
USUARIO_DUENO = "dueno@demo.vendi.co"


def _clave(variable: str) -> str:
    valor = os.getenv(variable, "")
    if not valor:
        raise SystemExit(
            f"Falta {variable}. La siembra no inventa contraseñas: una contraseña por "
            "defecto en un script de siembra acaba siendo una contraseña en producción. "
            "Ponla en el .env de la raíz."
        )
    return valor


async def sembrar_negocio_demo(servicio: TenantService, session) -> Tenant:  # noqa: ANN001
    existente = (
        (
            await session.execute(
                select(Tenant).where(Tenant.nombre == NOMBRE_NEGOCIO_DEMO).where(Tenant.deleted_at.is_(None))
            )
        )
        .scalars()
        .first()
    )
    if existente is not None:
        log.info("negocio_demo_ya_existe", tenant_id=str(existente.id), kc_org_id=existente.kc_org_id)
        return existente
    tenant = await servicio.crear(NOMBRE_NEGOCIO_DEMO)
    log.info("negocio_demo_creado", tenant_id=str(tenant.id), kc_org_id=tenant.kc_org_id)
    return tenant


async def main() -> int:
    settings = cargar_settings()
    setup_logging(level=settings.log_level, json_output=False)

    clave_admin = _clave("SEED_ADMIN_PASSWORD")
    clave_dueno = _clave("SEED_DUENO_PASSWORD")

    provisioner = ClienteAprovisionamiento(settings.provisioner_url)
    try:
        resumen_realm = await provisioner.sembrar_realm()
        log.info("realm_sembrado", **resumen_realm)

        admin = await provisioner.sembrar_admin_de_plataforma(clave_admin)
        log.info("admin_de_plataforma_listo", user_id=admin["user_id"], creado=admin["creado"])

        # El aprovisionamiento va con la fábrica de PLATAFORMA. Con la de la API
        # (`vendi_app`) esto fallaría con un `permission denied` opaco: `tenants`
        # está revocada para ese rol y el evento `tenant.creado` viaja con
        # `tenant_id NULL`, que la policy de INSERT del outbox rechaza.
        engine = create_engine(settings.platform_database_url)
        fabrica = create_platform_session_factory(engine)
        try:
            async with fabrica() as session:
                servicio = TenantService(
                    session=session,
                    aprovisionamiento=provisioner,
                    audit=AuditService(session_factory=fabrica, service_name="seed"),
                )
                tenant = await sembrar_negocio_demo(servicio, session)
                tenant_id = tenant.id
        finally:
            await dispose_engine(engine)

        dueno = await provisioner.sembrar_dueno_demo(tenant_id, clave_dueno)
        log.info("dueno_demo_listo", user_id=dueno["user_id"], creado=dueno["creado"])
    finally:
        await provisioner.aclose()

    log.info(
        "siembra_completa",
        negocio_demo=str(tenant_id),
        admin=USUARIO_ADMIN,
        dueno=USUARIO_DUENO,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
