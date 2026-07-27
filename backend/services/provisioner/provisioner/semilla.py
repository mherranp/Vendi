"""Siembra del realm y de sus dos usuarios de demostración.

Esta lógica vivía en `app.scripts.seed` y se movió aquí con el cierre de D-02:
todo lo que necesita `manage-realm` —crear roles de realm, mapearlos a grupos,
crear usuarios y meterlos en una Organization— ocurre en el ÚNICO proceso que
tiene la credencial. `scripts/seed.sh` sigue ejecutándose desde el contenedor
de la API, pero ahora orquesta: pide estas operaciones por HTTP interno y solo
toca la base de datos directamente para el negocio demo.

Todo es idempotente de verdad: correrlo tres veces da el mismo estado y
ninguna operación destructiva. Cada paso comprueba antes de crear.
"""

from __future__ import annotations

import uuid

import structlog

from vendi_core.auth.keycloak_aprovisionamiento import VendiKeycloakAprovisionamiento
from vendi_core.auth.policies import (
    PERM_PLATFORM_ADMIN,
    PERMISSION_CATALOG,
    ROLES_DE_NEGOCIO,
    roles_de_realm_del_grupo,
)
from vendi_core.errors.domain import NotFoundError

log = structlog.get_logger("vendi.provisioner.semilla")

USUARIO_ADMIN = "admin@vendi.co"
USUARIO_DUENO = "dueno@demo.vendi.co"
GRUPO_DUENO = "dueno"


async def sembrar_realm(kc: VendiKeycloakAprovisionamiento) -> dict:
    """Permisos (roles de realm) y roles de negocio (grupos), idempotentes."""
    for permiso, recurso in PERMISSION_CATALOG:
        await kc.ensure_realm_role(permiso, description=f"Permiso de Vendi sobre {recurso}")

    # Los roles de negocio son ROLES DE REALM (restricción global del plan), y
    # por eso se crean aquí antes que los grupos: sin el rol creado,
    # `set_group_realm_roles` no tendría qué mapear y `realm_access.roles` no
    # llevaría `dueno` — que era exactamente la deuda D-08.
    for rol in ROLES_DE_NEGOCIO:
        await kc.ensure_realm_role(rol, description=f"Rol de negocio de Vendi: {rol}")

    for rol in ROLES_DE_NEGOCIO:
        group_id = await kc.ensure_group(rol, description=f"Rol de negocio de Vendi: {rol}")
        # `set_group_realm_roles` hace diff: quita lo que sobra. Es lo correcto
        # aquí — el grupo es la definición del rol y `PERMISOS_POR_ROL` es su
        # fuente de verdad al sembrar. El propio rol de negocio entra en el
        # mapeo (ver `roles_de_realm_del_grupo`).
        await kc.set_group_realm_roles(group_id, roles_de_realm_del_grupo(rol))

    resumen = {"permisos": len(PERMISSION_CATALOG), "roles_de_negocio": list(ROLES_DE_NEGOCIO)}
    log.info("realm_sembrado", **resumen)
    return resumen


async def sembrar_admin_de_plataforma(kc: VendiKeycloakAprovisionamiento, password: str) -> dict:
    """`admin@vendi.co` con `platform:admin` y SIN ninguna organización.

    No pertenece a ninguna organización a propósito: es empleado de Vendi, no
    dueño de un negocio. Su token no traerá claim `organization` y por eso solo
    puede entrar por `/api/v1/platform/*`.
    """
    existente = await kc.find_user_by_username(USUARIO_ADMIN)
    creado = existente is None
    if existente:
        user_id = str(existente["id"])
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
    await kc.add_user_realm_roles(user_id, [PERM_PLATFORM_ADMIN])
    log.info("admin_de_plataforma_sembrado", user_id=user_id, creado=creado)
    return {"user_id": user_id, "creado": creado}


async def sembrar_dueno_demo(kc: VendiKeycloakAprovisionamiento, tenant_id: uuid.UUID, password: str) -> dict:
    """`dueno@demo.vendi.co`, en el grupo `dueno` y miembro de la Organization.

    La organización se resuelve por alias (= tenant_id): el provisioner es
    quien sabe hablar con Organizations, así que la comprobación de «el negocio
    tiene organización» ocurre aquí y no en el llamante.
    """
    org = await kc.get_organization_by_alias(tenant_id)
    if org is None:
        raise NotFoundError(
            f"El negocio {tenant_id} no tiene organización en Keycloak. Ejecuta scripts/reconcile-keycloak.sh.",
            code="organizacion_no_encontrada",
        )
    org_id = str(org["id"])

    existente = await kc.find_user_by_username(USUARIO_DUENO)
    creado = existente is None
    if existente:
        user_id = str(existente["id"])
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
            # integración y la siembra dejarían de funcionar. La passkey se
            # registra desde la consola de cuenta.
        )

    await kc.set_user_groups(user_id, [GRUPO_DUENO])
    await kc.add_member(org_id, user_id)
    log.info("dueno_demo_sembrado", user_id=user_id, creado=creado, kc_org_id=org_id)
    return {"user_id": user_id, "creado": creado}
