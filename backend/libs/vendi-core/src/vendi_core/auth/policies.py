"""Catálogo de permisos de Vendi y semilla de roles de negocio.

Se mantiene el mapeo semántico de BaseSaaS, que sigue siendo el correcto:

- Un **permiso** de Vendi es un rol de realm en Keycloak (mismo nombre, sin prefijo).
- Un **rol de negocio** de Vendi es un grupo de Keycloak, cuyos "role-mappings"
  son los permisos.
- El claim `realm_access.roles` del JWT trae los roles de realm efectivos del
  usuario (directos + heredados de grupos), es decir, el conjunto completo de
  permisos.
- El claim `groups` trae los grupos (= roles de negocio) del usuario.

La autorización en caliente lee **solo el token**: ni una consulta a base de
datos en la ruta de cada request.

`PERMISOS_POR_ROL` se usa exclusivamente como semilla inicial al aprovisionar el
realm (`scripts/seed.sh`, tarea 4.4). A partir de ahí, los permisos por grupo se
editan en Keycloak, que es la fuente de verdad.

## Nota sobre identificadores: sin tildes ni eñes

`dueno`, no `dueño`. Es una restricción global del plan y tiene motivo: estos
nombres viajan como roles de realm de Keycloak, como claves de JSON en el token,
como segmentos de URL en la Admin API y como literales en el código TypeScript
del frontend. Cada uno de esos saltos es una oportunidad de que alguien haga mal
el round-trip de UTF-8. La etiqueta que ve el usuario sí lleva la eñe: vive en
el catálogo de i18n, no aquí.

## Nota sobre la suplantación: NO existe en Fase 0

BaseSaaS tenía `user:impersonate` y `exchange_token_for_user`, y una versión
anterior de este plan (tarea 3.5) los declaraba para Vendi. **No se implementan,
y el permiso no está en el catálogo.** En la Etapa 2 se quitó el rol
`impersonation` de la cuenta de servicio de `vendi-backend` por ser un agujero
de aislamiento multi-tenant: con él, quien comprometiera el secreto del backend
podía acuñar un token de cualquier usuario de cualquier negocio de la región. En
realm-per-tenant el daño quedaba acotado a un inquilino; en realm regional, no.

Declarar el permiso sin el camino que lo ejerce sería peor que no declararlo:
aparecería en la consola de Keycloak, alguien se lo asignaría a un rol, y
quedaría un permiso que promete algo que el sistema no puede cumplir. Si la
suplantación vuelve, vuelve con su propio diseño (probablemente un flujo de
soporte con consentimiento del dueño y auditoría separada), no reactivando un
rol de servicio.
"""

from vendi_core.auth.context import UserContext

# --- Catálogo de permisos (recurso:accion) ---------------------------------

# Gestión de negocios (nivel plataforma: la consola de Vendi, no el negocio)
PERM_TENANT_READ = "tenant:read"
PERM_TENANT_CREATE = "tenant:create"
PERM_TENANT_UPDATE = "tenant:update"
PERM_TENANT_DELETE = "tenant:delete"

# Acceso a la consola de plataforma. Es el permiso que separa "empleado de
# Vendi" de "dueño de un negocio", y el que exige el router `/platform/*`.
PERM_PLATFORM_ADMIN = "platform:admin"

# Auditoría
PERM_AUDIT_READ = "audit:read"

# Comodín para superadministradores de plataforma.
PERM_WILDCARD = "*"


PERMISSION_CATALOG: tuple[tuple[str, str], ...] = (
    (PERM_TENANT_READ, "tenant"),
    (PERM_TENANT_CREATE, "tenant"),
    (PERM_TENANT_UPDATE, "tenant"),
    (PERM_TENANT_DELETE, "tenant"),
    (PERM_PLATFORM_ADMIN, "platform"),
    (PERM_AUDIT_READ, "audit"),
)


# --- Roles de negocio (se siembran como grupos de Keycloak) -----------------

ROL_DUENO = "dueno"
ROL_CAJERO = "cajero"
ROL_ALMACENISTA = "almacenista"

ROLES_DE_NEGOCIO: tuple[str, ...] = (ROL_DUENO, ROL_CAJERO, ROL_ALMACENISTA)

# El dueño puede todo lo de SU negocio. Nótese lo que NO tiene: ningún permiso
# de plataforma. `platform:admin` no se le asigna nunca — el aislamiento entre
# negocios no puede depender de que a nadie se le vaya la mano en la consola.
_PERMISOS_DUENO = frozenset(
    {
        PERM_TENANT_READ,
        PERM_TENANT_UPDATE,
        PERM_AUDIT_READ,
    }
)

# Cajero y almacenista quedan declarados y VACÍOS a propósito. Sus permisos son
# los del modelo de datos del MVP (ventas, inventario, cierres de caja), que es
# el subproyecto 1 y no existe todavía. Se declaran ahora para que el grupo
# exista en el realm desde el primer día —y así el alta de usuarios de la Etapa
# 4 pueda asignarlo— pero inventarles permisos hoy sería inventarse el modelo de
# permisos del MVP a ciegas.
_PERMISOS_CAJERO: frozenset[str] = frozenset()
_PERMISOS_ALMACENISTA: frozenset[str] = frozenset()

PERMISOS_POR_ROL: dict[str, frozenset[str]] = {
    ROL_DUENO: _PERMISOS_DUENO,
    ROL_CAJERO: _PERMISOS_CAJERO,
    ROL_ALMACENISTA: _PERMISOS_ALMACENISTA,
}


def has_permission(user: UserContext, permission: str) -> bool:
    """Comprobación de permiso contra los claims del JWT y nada más.

    El `realm_access.roles` del token trae los permisos efectivos (directos +
    heredados de grupos). Sin consulta a base de datos.
    """
    if user.is_superuser:
        return True
    if PERM_WILDCARD in user.roles:
        return True
    return permission in user.roles
