"""Catálogo de permisos de Vendi y semilla de roles de negocio.

El mapeo semántico, corregido en la Etapa 5 (deuda D-08, ADR-015):

- Un **permiso** de Vendi es un rol de realm en Keycloak (mismo nombre, sin
  prefijo): `tenant:read`, `platform:admin`…
- Un **rol de negocio** de Vendi (`dueno`, `cajero`, `almacenista`) es **también
  un rol de realm**, como manda la restricción global del plan. Además existe un
  **grupo** de Keycloak con el mismo nombre, cuyo role-mapping es {el rol de
  negocio} ∪ {sus permisos}: el grupo es la comodidad de administración —se
  mete al usuario en un grupo y hereda todo— y el rol es lo que viaja al token.
- El claim `realm_access.roles` del JWT trae los roles de realm efectivos
  (directos + heredados de grupos): permisos **y** roles de negocio. Es el único
  canal de autorización.

Por qué no hay claim `groups`: el realm no lo emite (ningún mapper de grupo está
en los default client scopes) y añadirlo exigía gestionar client scopes, que la
credencial de aprovisionamiento no puede (403 medido). Emitir por un segundo
canal lo que ya viaja por el primero no compraba nada. El campo `groups` de
`UserContext` se retiró; `has_role()` lee `roles`.

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

# Catálogo de productos (ADR-019/ADR-023)
PERM_PRODUCTO_LEER = "producto:leer"
PERM_PRODUCTO_EDITAR = "producto:editar"

# Ventas y sync offline (ADR-018/ADR-023). El cajero crea ventas pero NO las
# anula: anular es un gesto con dinero y queda en manos del dueño en el MVP.
PERM_VENTA_CREAR = "venta:crear"
PERM_VENTA_ANULAR = "venta:anular"

# Comodín para superadministradores de plataforma.
PERM_WILDCARD = "*"


PERMISSION_CATALOG: tuple[tuple[str, str], ...] = (
    (PERM_TENANT_READ, "tenant"),
    (PERM_TENANT_CREATE, "tenant"),
    (PERM_TENANT_UPDATE, "tenant"),
    (PERM_TENANT_DELETE, "tenant"),
    (PERM_PLATFORM_ADMIN, "platform"),
    (PERM_AUDIT_READ, "audit"),
    (PERM_PRODUCTO_LEER, "producto"),
    (PERM_PRODUCTO_EDITAR, "producto"),
    (PERM_VENTA_CREAR, "venta"),
    (PERM_VENTA_ANULAR, "venta"),
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
        PERM_PRODUCTO_LEER,
        PERM_PRODUCTO_EDITAR,
        PERM_VENTA_CREAR,
        PERM_VENTA_ANULAR,
    }
)

# ADR-023: el cajero consulta el catálogo y vende, pero NO edita el catálogo
# ni anula ventas (anular y arquear son los gestos con los que se desfalca
# una tienda; son del dueño en el MVP). El almacenista mantiene el catálogo y
# no vende. El resto de permisos de cada rol llega con su módulo.
_PERMISOS_CAJERO: frozenset[str] = frozenset({PERM_PRODUCTO_LEER, PERM_VENTA_CREAR})
_PERMISOS_ALMACENISTA: frozenset[str] = frozenset({PERM_PRODUCTO_LEER, PERM_PRODUCTO_EDITAR})

PERMISOS_POR_ROL: dict[str, frozenset[str]] = {
    ROL_DUENO: _PERMISOS_DUENO,
    ROL_CAJERO: _PERMISOS_CAJERO,
    ROL_ALMACENISTA: _PERMISOS_ALMACENISTA,
}


def roles_de_realm_del_grupo(rol: str) -> list[str]:
    """Roles de realm que el grupo `rol` debe mapear, en orden estable.

    Son sus permisos **más el propio rol de negocio**. Esa última parte es la
    que cierra D-08: sin ella el rol no aparece en `realm_access.roles` y
    `has_role('dueno')` es falso para el dueño. Con ella, meter al usuario en el
    grupo basta para que el token lleve las dos cosas.
    """
    if rol not in PERMISOS_POR_ROL:
        raise KeyError(f"Rol de negocio desconocido: {rol!r}. Los válidos son {list(ROLES_DE_NEGOCIO)}.")
    return sorted(PERMISOS_POR_ROL[rol] | {rol})


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
