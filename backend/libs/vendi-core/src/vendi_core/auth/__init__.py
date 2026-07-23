from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user, require_permission, require_role
from vendi_core.auth.jwt import REALM_VENDI, JWTValidator, parsear_claim_organization
from vendi_core.auth.keycloak_admin import (
    VendiKeycloakAdmin,
    VendiKeycloakAprovisionamiento,
)
from vendi_core.auth.policies import (
    PERM_AUDIT_READ,
    PERM_PLATFORM_ADMIN,
    PERM_TENANT_CREATE,
    PERM_TENANT_DELETE,
    PERM_TENANT_READ,
    PERM_TENANT_UPDATE,
    PERMISOS_POR_ROL,
    PERMISSION_CATALOG,
    ROL_ALMACENISTA,
    ROL_CAJERO,
    ROL_DUENO,
    ROLES_DE_NEGOCIO,
    has_permission,
)

__all__ = [
    "PERMISOS_POR_ROL",
    "PERMISSION_CATALOG",
    "PERM_AUDIT_READ",
    "PERM_PLATFORM_ADMIN",
    "PERM_TENANT_CREATE",
    "PERM_TENANT_DELETE",
    "PERM_TENANT_READ",
    "PERM_TENANT_UPDATE",
    "REALM_VENDI",
    "ROLES_DE_NEGOCIO",
    "ROL_ALMACENISTA",
    "ROL_CAJERO",
    "ROL_DUENO",
    "JWTValidator",
    "UserContext",
    "VendiKeycloakAdmin",
    "VendiKeycloakAprovisionamiento",
    "get_current_user",
    "has_permission",
    "parsear_claim_organization",
    "require_permission",
    "require_role",
]
