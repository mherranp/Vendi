"""Contexto del usuario autenticado, extraído del JWT.

Cosechado de `base_saas.auth.context`. Cambios de Vendi:

- Muere `tenant_slug`. En BaseSaaS el tenant era el realm (realm-per-tenant) y
  el slug era su nombre. En Vendi hay un único realm regional `vendi-co` y el
  negocio se lee del claim `organization` de Keycloak Organizations.
- Nace `organizations: dict[str, str]` — alias → id interno de la organización.
  El alias **es** el `tenant_id` (`str(tenant_id)`), decisión 3 del informe
  `2026-07-22-verificacion-kc-organizations.md`, así que el tenant se resuelve
  del token sin ninguna consulta a Keycloak ni a base de datos. El valor (el id
  interno) puede venir vacío: el claim solo lo trae si el mapper tiene
  `addOrganizationId=true`.
- Muere `actor`. Ese claim (RFC 8693 `act`) solo aparece en tokens acuñados por
  token-exchange, es decir, por suplantación. En la Etapa 2 se quitó el rol
  `impersonation` de la cuenta de servicio del backend por ser un agujero de
  aislamiento multi-tenant, así que en Fase 0 **no existe camino que produzca
  ese claim** y mantener el campo sugeriría que sí. Si la suplantación vuelve
  en alguna fase futura, vuelve con su propio diseño y su propia auditoría.
- **Muere `groups` (Etapa 5, deuda D-08).** El campo leía el claim `groups`, que
  el realm de Vendi **no emite**: ningún mapper de grupo está en los default
  client scopes, así que `has_role()` y `require_role()` devolvían siempre
  `False` — es decir, cualquier comprobación de rol de negocio pasaba o fallaba
  por la razón equivocada. Ver la decisión completa en el ADR-015.

  El arreglo NO fue añadir el mapper: la restricción global del plan dice que
  los roles de negocio de Vendi (`dueno`, `cajero`, `almacenista`) son **roles
  de realm**, y los roles de realm ya viajan en `realm_access.roles` con el
  scope `roles`, que es un default client scope de fábrica. Añadir un mapper de
  grupos habría necesitado gestionar client scopes (403 para
  `vendi-provisioning`, medido) para acabar emitiendo por un segundo canal lo
  mismo que ya viaja por el primero.

  Consecuencia que conviene tener presente: permisos (`tenant:read`) y roles de
  negocio (`dueno`) comparten el espacio de nombres de los roles de realm. Se
  distinguen por forma —el permiso lleva `recurso:accion` con dos puntos, el rol
  no— y por catálogo (`PERMISSION_CATALOG` frente a `ROLES_DE_NEGOCIO`).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserContext:
    """Contexto inmutable del usuario autenticado.

    `roles` lleva el `realm_access.roles` del token, y lleva **las dos cosas**:

    - los **permisos** efectivos del usuario (`tenant:read`, `platform:admin`…),
      heredados de sus grupos de Keycloak más las asignaciones directas, que se
      consultan con `has_permission()`;
    - los **roles de negocio** de Vendi (`dueno`, `cajero`, `almacenista`), que
      son roles de realm por decisión del plan y se consultan con `has_role()`.

    No hay dos claims porque no hay dos canales: `realm_access.roles` es el
    único que el realm emite de fábrica (scope `roles`). Ver la cabecera del
    módulo y el ADR-015 para el porqué de que `groups` ya no exista.

    `organizations` lleva el claim `organization` ya normalizado a
    `{alias: id_interno}`. Un diccionario vacío significa "el token no trae
    ninguna organización", que es un estado legítimo y frecuente: un
    administrador de plataforma, o un usuario multi-organización cuyo cliente
    olvidó pedir `scope=organization:*`. Quien decide qué hacer con eso es
    `TenantMiddleware`, no esta clase.
    """

    user_id: str
    username: str
    email: str = ""
    roles: frozenset[str] = field(default_factory=frozenset)
    realm: str = ""
    organizations: dict[str, str] = field(default_factory=dict)
    display_name: str = ""
    is_superuser: bool = False
    # `acr` (Authentication Context Class Reference): Keycloak emite "1" cuando
    # la sesión autenticó solo con contraseña y "2" cuando hubo segundo factor.
    # Útil para auditoría y para futuros step-up.
    acr: str | None = None
    # Claim `exp` del JWT (timestamp Unix). Se rellena desde el token ya
    # validado para que los consumidores no tengan que volver a decodificarlo.
    token_exp: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.roles, list | set):
            object.__setattr__(self, "roles", frozenset(self.roles))

    @property
    def permissions(self) -> frozenset[str]:
        return self.roles

    @property
    def alias_de_organizacion(self) -> list[str]:
        """Alias de las organizaciones del token. Cada alias es un `tenant_id`."""
        return list(self.organizations)

    def has_role(self, role: str) -> bool:
        """¿Tiene el usuario ese rol de negocio? Se lee de `realm_access.roles`.

        Nota deliberada: `is_superuser` y el comodín `*` **no** intervienen aquí,
        a diferencia de `has_permission()`. Un permiso es «puede hacer esto»; un
        rol de negocio es «es esto». Que un administrador de plataforma pudiera
        pasar por `dueno` de cualquier negocio sería exactamente el cruce que el
        producto promete que no ocurre.
        """
        return role in self.roles

    def has_any_role(self, *roles: str) -> bool:
        return bool(self.roles & frozenset(roles))

    def has_permission(self, permission: str) -> bool:
        if self.is_superuser:
            return True
        return permission in self.roles

    def has_any_permission(self, *permissions: str) -> bool:
        if self.is_superuser:
            return True
        return bool(self.roles & frozenset(permissions))
