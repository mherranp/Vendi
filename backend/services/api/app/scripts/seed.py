"""Siembra de desarrollo, idempotente. La ejecuta `scripts/seed.sh`.

Qué deja montado, en este orden:

1. Los **permisos** como roles de realm (`PERMISSION_CATALOG` de
   `vendi_core.auth.policies`).
2. Los **roles de negocio** como grupos de Keycloak (`dueno`, `cajero`,
   `almacenista`) con sus permisos mapeados.
3. El **administrador de plataforma** `admin@vendi.co`, con `platform:admin`
   directo y sin pertenecer a ninguna organización.
4. El **negocio demo** «Tienda Don Carlos» con su Organization (alias =
   tenant_id).
5. El **dueño** `dueno@demo.vendi.co`, en el grupo `dueno` y miembro de la
   organización del negocio demo.

## Idempotente de verdad

Correrlo tres veces seguidas tiene que dar el mismo estado y ninguna operación
destructiva. Cada paso comprueba antes de crear, y el negocio demo se busca por
nombre entre los no eliminados. Si alguien borra el negocio demo a mano, la
siguiente pasada lo vuelve a crear **con un id nuevo** — y eso es correcto: el
id anterior fue alias de una Organization y no se reutiliza jamás.

## Por qué el alta del negocio NO va por HTTP

El plan pedía crear el negocio demo «vía la API» para ejercer el mismo camino de
aprovisionamiento que producción. Se ejerce el mismo camino —se llama a
`TenantService`, el mismo objeto que usa el router— pero en proceso, no por
HTTP. Motivo: por HTTP haría falta un token con `platform:admin`, y el único
modo de obtenerlo sin navegador es el grant de contraseña contra un cliente
público, que es exactamente la deuda D-01 que la Etapa 5 tiene que cerrar. Una
siembra que dependa de ROPC bloquearía apagarlo.

Lo que se pierde con esta decisión, dicho en voz alta: la siembra no ejercita la
cadena de middlewares ni la comprobación de `platform:admin`. Eso lo ejercitan
`tests/api/test_tenants_crud.py` y `tests/api/test_aislamiento_end_to_end.py`,
que son mejores sitios para probarlo que un script de datos de ejemplo.

## Las contraseñas vienen del entorno

Sin defecto. Una contraseña por defecto en un script de siembra es una
contraseña en producción el día que alguien ejecute la siembra donde no debía.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import structlog
from sqlalchemy import select

from app.modules.tenants.models import Tenant
from app.modules.tenants.service import TenantService
from app.settings import cargar_settings
from vendi_core.audit.service import AuditService
from vendi_core.auth.keycloak_admin import VendiKeycloakAprovisionamiento
from vendi_core.auth.policies import (
    PERM_PLATFORM_ADMIN,
    PERMISOS_POR_ROL,
    PERMISSION_CATALOG,
    ROLES_DE_NEGOCIO,
)
from vendi_core.db.engine import create_engine, dispose_engine
from vendi_core.db.session import create_platform_session_factory
from vendi_core.logging.setup import setup_logging

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


async def sembrar_realm(kc: VendiKeycloakAprovisionamiento) -> None:
    """Permisos (roles de realm) y roles de negocio (grupos), idempotentes."""
    for permiso, recurso in PERMISSION_CATALOG:
        await kc.ensure_realm_role(permiso, description=f"Permiso de Vendi sobre {recurso}")
    log.info("permisos_sembrados", cuantos=len(PERMISSION_CATALOG))

    for rol in ROLES_DE_NEGOCIO:
        group_id = await kc.ensure_group(rol, description=f"Rol de negocio de Vendi: {rol}")
        # `set_group_realm_roles` hace diff: quita lo que sobra. Es lo correcto
        # aquí — el grupo es la definición del rol y `PERMISOS_POR_ROL` es su
        # fuente de verdad al sembrar.
        await kc.set_group_realm_roles(group_id, sorted(PERMISOS_POR_ROL[rol]))
    log.info("roles_de_negocio_sembrados", roles=list(ROLES_DE_NEGOCIO))


async def sembrar_admin_de_plataforma(kc: VendiKeycloakAprovisionamiento, password: str) -> str:
    existente = await kc.find_user_by_username(USUARIO_ADMIN)
    if existente:
        user_id = str(existente["id"])
        log.info("admin_de_plataforma_ya_existe", user_id=user_id)
    else:
        user_id = await kc.create_user(
            username=USUARIO_ADMIN,
            email=USUARIO_ADMIN,
            # Obligatorios: sin ellos el perfil declarativo del realm marca
            # VERIFY_PROFILE y el usuario no puede autenticarse — el error que
            # sale es «Account is not fully set up» y no menciona el perfil.
            first_name="Admin",
            last_name="Plataforma",
            password=password,
            email_verified=True,
        )
        log.info("admin_de_plataforma_creado", user_id=user_id)

    # No pertenece a ninguna organización, a propósito: es empleado de Vendi, no
    # dueño de un negocio. Su token no traerá claim `organization` y por eso solo
    # puede entrar por `/api/v1/platform/*`.
    await kc.add_user_realm_roles(user_id, [PERM_PLATFORM_ADMIN])
    return user_id


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


async def sembrar_dueno(
    kc: VendiKeycloakAprovisionamiento,
    tenant_id: uuid.UUID,
    org_id: str | None,
    password: str,
) -> str:
    existente = await kc.find_user_by_username(USUARIO_DUENO)
    if existente:
        user_id = str(existente["id"])
        log.info("dueno_demo_ya_existe", user_id=user_id)
    else:
        user_id = await kc.create_user(
            username=USUARIO_DUENO,
            email=USUARIO_DUENO,
            first_name="Carlos",
            last_name="Demo",
            password=password,
            email_verified=True,
            # SIN required actions: cualquiera pendiente (incluida
            # `webauthn-register-passwordless`) hace fallar el grant de
            # contraseña con «Account is not fully set up», y los tests de
            # integración y esta misma siembra dejarían de funcionar. La passkey
            # se registra desde la consola de cuenta.
        )
        log.info("dueno_demo_creado", user_id=user_id)

    await kc.set_user_groups(user_id, ["dueno"])

    if org_id is None:
        org = await kc.get_organization_by_alias(tenant_id)
        org_id = org["id"] if org else None
    if org_id is None:
        raise SystemExit(
            f"El negocio demo no tiene organización en Keycloak (alias {tenant_id}). "
            "Ejecuta scripts/reconcile-keycloak.sh."
        )
    await kc.add_member(org_id, user_id)
    log.info("dueno_demo_en_la_organizacion", user_id=user_id, kc_org_id=org_id)
    return user_id


async def main() -> int:
    settings = cargar_settings()
    setup_logging(level=settings.log_level, json_output=False)

    clave_admin = _clave("SEED_ADMIN_PASSWORD")
    clave_dueno = _clave("SEED_DUENO_PASSWORD")

    kc = VendiKeycloakAprovisionamiento(
        server_url=settings.keycloak_url_normalizada,
        client_id=settings.keycloak_provisioning_client_id,
        client_secret=settings.keycloak_provisioning_client_secret,
        realm=settings.keycloak_realm,
    )

    await sembrar_realm(kc)
    await sembrar_admin_de_plataforma(kc, clave_admin)

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
                keycloak=kc,
                audit=AuditService(session_factory=fabrica, service_name="seed"),
            )
            tenant = await sembrar_negocio_demo(servicio, session)
            tenant_id, org_id = tenant.id, tenant.kc_org_id
    finally:
        await dispose_engine(engine)

    await sembrar_dueno(kc, tenant_id, org_id, clave_dueno)

    log.info(
        "siembra_completa",
        negocio_demo=str(tenant_id),
        admin=USUARIO_ADMIN,
        dueno=USUARIO_DUENO,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
