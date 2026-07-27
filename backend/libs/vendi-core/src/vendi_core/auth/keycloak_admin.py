"""Administración de Keycloak para el realm regional `vendi-co`.

Reescritura dirigida de `base_saas.auth.keycloak_admin` (797 LOC). El original
era el administrador de un mundo realm-per-tenant: creaba y borraba realms,
montaba proveedores de identidad, acuñaba clientes de cuenta de servicio por
inquilino y suplantaba usuarios. Casi nada de eso sobrevive.

## Qué muere y por qué

- `create_realm`, `delete_realm`, `set_realm_enabled`: no hay un realm por
  negocio. Hay UN realm y una Organization por negocio. Consecuencia que hay que
  decir en voz alta y que también está en ADR-014: **no existe "deshabilitar el
  realm" por tenant. La suspensión de un negocio es un estado en la tabla
  `tenants` que la API consulta en cada request.** El spike de Keycloak lo midió
  (pregunta 6 del informe): deshabilitar la Organization no impide el login,
  solo saca la organización del claim, y no invalida los tokens ya emitidos. Un
  usuario suspendido merece "tu negocio está suspendido por falta de pago", y
  eso solo lo puede decir la aplicación.
- `ensure_identity_provider` / IdPs externos: fuera de Fase 0.
- `create_service_account_client` / `ensure_platform_admin_client`: los clientes
  del realm vienen del realm como código (`infra/keycloak/realm-vendi-co.json`),
  no se crean en caliente. Además la cuenta de servicio de Vendi **no tiene
  `manage-clients`** (medido: 403), así que ni podría.
- `exchange_token_for_user` (suplantación, RFC 8693): **no se porta.** El rol
  `impersonation` se quitó de la cuenta de servicio en la Etapa 2 por ser un
  agujero de aislamiento multi-tenant — con realm regional, quien comprometa el
  secreto del backend podría acuñar un token de cualquier usuario de cualquier
  negocio de la región. El método no está, el permiso `impersonate:user` no está
  en `policies.py`, y el rol no se vuelve a añadir. Esto redefine la tarea 3.5
  del plan, que todavía los declaraba.

## Qué nace

Los métodos de Organizations sobre python-keycloak 7.1.1 (`a_create_organization`,
`a_organization_user_add`, ...), con `alias = str(tenant_id)` — confirmado por el
spike (pregunta 4: Keycloak acepta el UUID con guiones y lo devuelve literal).

## Por qué DOS clases en DOS módulos — cierre de D-02

Medido contra el realm vivo de `vendi-co` en Keycloak 26.6.4 (matriz completa en
`docs/deuda-tecnica.md`, D-02): **ningún subconjunto de roles de
`realm-management` da acceso a la API de Organizations sin `manage-realm`** — ni
siquiera para leer. Y `manage-realm` permite reescribir el realm entero: crear
flujos de autenticación, reenlazar `browserFlow` (sacando el login con passkey),
apagar la protección de fuerza bruta y abrir el auto-registro público.

El privilegio está partido en dos credenciales:

- `VendiKeycloakAdmin` (este módulo) habla con el cliente `vendi-backend`, cuya
  cuenta de servicio tiene **solo `manage-users`**. Es el que usa la API general.
- `VendiKeycloakAprovisionamiento` (`vendi_core.auth.keycloak_aprovisionamiento`)
  habla con el cliente `vendi-provisioning`, con `manage-realm` + `manage-users`.
  Es el único que toca Organizations, y desde el cierre de D-02 (ADR-027) **solo
  lo instancia el servicio `provisioner`** — una unidad de despliegue separada
  que es el único proceso con el secreto. La API ya no recibe esa credencial:
  pide las operaciones de aprovisionamiento por HTTP interno
  (`vendi_core.provisioning.cliente`).

Lo que esto compra, sin adornos: quien comprometa el proceso de la API —por una
traza sin sanear o por ejecución de código— obtiene gestión de usuarios
(`manage-users`), no reescritura del realm. Para alcanzar `manage-realm` tendría
que salir del contenedor de la API y entrar en el del provisioner, que no
publica puertos ni tiene router en el borde. El camino residual que queda —la
API puede pedir al provisioner las operaciones acotadas que este expone— está
medido y descrito en ADR-027.
"""

from __future__ import annotations

from typing import Any

import structlog
from keycloak.exceptions import KeycloakError
from keycloak.keycloak_admin import KeycloakAdmin
from keycloak.openid_connection import KeycloakOpenIDConnection

from vendi_core.audit.metrics import suppressed_errors_counter
from vendi_core.auth.ssl import keycloak_ssl_verify
from vendi_core.errors.domain import ConflictError, ExternalServiceError, NotFoundError

logger = structlog.get_logger()

REALM_VENDI = "vendi-co"


def _codigo(exc: KeycloakError) -> int | None:
    return getattr(exc, "response_code", None)


def _traducir(exc: KeycloakError, operacion: str, **contexto: Any) -> Exception:
    """Convierte un `KeycloakError` en un error de dominio tipado.

    Sin esto, un Keycloak caído sube como `KeycloakError` crudo hasta el
    manejador genérico y el usuario recibe un 500 sin explicación. Con esto,
    cada situación tiene su código y su mensaje en español.
    """
    codigo = _codigo(exc)
    if codigo == 404:
        return NotFoundError(f"No existe el recurso en Keycloak ({operacion})", details=contexto)
    if codigo == 409:
        return ConflictError(f"Ya existe en Keycloak ({operacion})", details=contexto)
    if codigo == 400:
        # 400 en la Admin API suele ser un duplicado semántico (dominio ya
        # enlazado a otra organización) más que un payload mal formado nuestro.
        return ConflictError(f"Keycloak rechazó la operación ({operacion}): {exc}", details=contexto)
    suppressed_errors_counter.labels(component=f"keycloak_admin.{operacion}", reason="KeycloakError").inc()
    logger.warning("keycloak_error", operacion=operacion, status=codigo, error=str(exc), **contexto)
    return ExternalServiceError(
        f"Keycloak no respondió correctamente ({operacion})", details={"status": codigo, **contexto}
    )


class VendiKeycloakAdmin:
    """Administración de usuarios, grupos y roles del realm `vendi-co`.

    Autentica con el cliente confidencial `vendi-backend` por
    `grant_type=client_credentials`. Su cuenta de servicio tiene **solo**
    `manage-users`: no puede leer ni escribir Organizations, ni tocar los ajustes
    del realm, ni crear clientes. Para lo que sí necesita Organizations está
    `VendiKeycloakAprovisionamiento`.

    Mapeo semántico (heredado de BaseSaaS, sigue siendo el correcto):
    permiso de Vendi → rol de realm; rol de negocio de Vendi → grupo de Keycloak.
    """

    def __init__(
        self,
        server_url: str,
        client_id: str,
        client_secret: str,
        realm: str = REALM_VENDI,
    ):
        self._server_url = server_url
        self._client_id = client_id
        self._realm = realm
        # `user_realm_name` no aplica en client_credentials: el cliente vive en
        # el mismo realm que administra. Es justo lo contrario del patrón de
        # BaseSaaS (admin de `master` administrando otros realms), y es lo que
        # hace que este objeto no pueda salirse de `vendi-co` ni queriendo.
        self._conexion = KeycloakOpenIDConnection(
            server_url=server_url,
            realm_name=realm,
            client_id=client_id,
            client_secret_key=client_secret,
            grant_type="client_credentials",
            verify=keycloak_ssl_verify(),
        )
        self._kc = KeycloakAdmin(connection=self._conexion)

    @property
    def realm(self) -> str:
        return self._realm

    @property
    def client_id(self) -> str:
        return self._client_id

    # --- Usuarios ----------------------------------------------------------

    async def create_user(
        self,
        username: str,
        email: str,
        first_name: str,
        last_name: str,
        password: str | None = None,
        groups: list[str] | None = None,
        required_actions: list[str] | None = None,
        email_verified: bool = True,
    ) -> str:
        """Crea un usuario del realm y devuelve su id de Keycloak.

        `first_name` y `last_name` son **obligatorios y posicionales**, no
        opcionales con defecto `""` como en BaseSaaS. Hallazgo medido del spike
        de Keycloak: el perfil de usuario declarativo del realm los exige, y un
        usuario creado sin ellos arrastra la required action `VERIFY_PROFILE`.
        El síntoma es un `invalid_grant` con `"Account is not fully set up"` en
        el login —un mensaje que no menciona el perfil por ningún lado— y horas
        buscando en el sitio equivocado. Que la firma no deje omitirlos es la
        única forma de que no vuelva a pasar.

        Cuidado relacionado, del mismo hallazgo: **cualquier required action
        pendiente dispara el mismo error** en el grant directo, no solo
        `VERIFY_PROFILE`. Si se pasa `required_actions=["webauthn-register-passwordless"]`
        para que el usuario registre su passkey en el primer login, ese usuario
        NO podrá obtener token por `password` grant hasta completarla. Los tests
        de integración y `seed.sh` tienen que tenerlo en cuenta.
        """
        if not first_name or not last_name:
            raise ValueError(
                "first_name y last_name son obligatorios: sin ellos Keycloak marca "
                "VERIFY_PROFILE y el usuario no puede autenticarse "
                "('Account is not fully set up')."
            )
        payload: dict[str, Any] = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "emailVerified": email_verified,
            "enabled": True,
        }
        if password:
            payload["credentials"] = [{"type": "password", "value": password, "temporary": False}]
        if required_actions:
            payload["requiredActions"] = list(required_actions)
        try:
            user_id = await self._kc.a_create_user(payload)
        except KeycloakError as exc:
            raise _traducir(exc, "create_user", username=username) from exc
        if groups:
            await self.set_user_groups(user_id, groups)
        return str(user_id)

    async def get_user(self, user_id: str) -> dict | None:
        try:
            return await self._kc.a_get_user(user_id)
        except KeycloakError as exc:
            if _codigo(exc) == 404:
                return None
            raise _traducir(exc, "get_user", user_id=user_id) from exc

    async def find_user_by_username(self, username: str) -> dict | None:
        try:
            usuarios = await self._kc.a_get_users({"username": username, "exact": True})
        except KeycloakError as exc:
            raise _traducir(exc, "find_user_by_username", username=username) from exc
        for u in usuarios or []:
            if u.get("username") == username:
                return u
        return None

    async def disable_user(self, user_id: str) -> None:
        try:
            await self._kc.a_update_user(user_id, {"enabled": False})
        except KeycloakError as exc:
            raise _traducir(exc, "disable_user", user_id=user_id) from exc

    async def delete_user(self, user_id: str) -> None:
        """Borra el usuario. Idempotente: un 404 es "ya no está", no un error."""
        try:
            await self._kc.a_delete_user(user_id)
        except KeycloakError as exc:
            if _codigo(exc) == 404:
                return
            raise _traducir(exc, "delete_user", user_id=user_id) from exc

    async def set_user_required_actions(self, user_id: str, actions: list[str]) -> None:
        try:
            await self._kc.a_update_user(user_id, {"requiredActions": list(actions)})
        except KeycloakError as exc:
            raise _traducir(exc, "set_user_required_actions", user_id=user_id) from exc

    async def list_user_required_actions(self, user_id: str) -> list[str]:
        usuario = await self.get_user(user_id)
        return list((usuario or {}).get("requiredActions") or [])

    async def user_has_credential_type(self, user_id: str, credential_type: str) -> bool:
        """¿Tiene el usuario al menos una credencial de ese tipo?

        `credential_type` útiles: `"password"`, `"webauthn-passwordless"`.
        """
        try:
            creds = await self._kc.a_get_credentials(user_id)
        except KeycloakError as exc:
            raise _traducir(exc, "user_has_credential_type", user_id=user_id) from exc
        return any(c.get("type") == credential_type for c in creds or [])

    async def promote_credential(self, user_id: str, credential_id: str) -> None:
        """Mueve una credencial al primer puesto de la lista del usuario.

        Hallazgo de UX con consecuencia operativa, medido en el spike (pregunta
        10): cuando el usuario tiene contraseña **y** passkey, Keycloak ofrece en
        la segunda pantalla la credencial que esté primera en su lista, y deja la
        otra tras "Try Another Way". Como la contraseña se crea antes, por
        defecto gana la contraseña — y el POS que vendíamos como "entra con la
        huella" pide contraseña. Esta llamada es la que arregla eso, y hay que
        hacerla justo después de que el usuario registre su passkey.
        """
        try:
            # python-keycloak no expone moveToFirst; se va a REST crudo.
            await self._kc.connection.a_raw_post(
                f"/admin/realms/{self._realm}/users/{user_id}/credentials/{credential_id}/moveToFirst",
                data="",
            )
        except KeycloakError as exc:
            raise _traducir(exc, "promote_credential", user_id=user_id) from exc

    # --- Roles de realm (= permisos de Vendi) ------------------------------

    async def get_realm_role(self, name: str) -> dict | None:
        try:
            return await self._kc.a_get_realm_role(name)
        except KeycloakError as exc:
            if _codigo(exc) != 404:
                suppressed_errors_counter.labels(
                    component="keycloak_admin.get_realm_role", reason="KeycloakError"
                ).inc()
                logger.warning(
                    "keycloak_get_realm_role_failed",
                    role=name,
                    status=_codigo(exc),
                    error=str(exc),
                )
            return None

    async def ensure_realm_role(self, name: str, description: str = "") -> dict:
        """Alta idempotente: devuelve el rol, exista ya o se acabe de crear.

        El camino del `except` es el rápido de "el rol no existe todavía → se
        crea". Un 404 es la señal *esperada* durante el bootstrap; cualquier otro
        estado (5xx, fallo de autenticación, corte de red) incrementa el contador
        y deja un warning, para que un Keycloak realmente roto no se confunda con
        un realm recién nacido.
        """
        try:
            return await self._kc.a_get_realm_role(name)
        except KeycloakError as exc:
            if _codigo(exc) != 404:
                suppressed_errors_counter.labels(
                    component="keycloak_admin.ensure_realm_role", reason="KeycloakError"
                ).inc()
                logger.warning(
                    "keycloak_ensure_realm_role_get_failed",
                    role=name,
                    status=_codigo(exc),
                    error=str(exc),
                )
            try:
                await self._kc.a_create_realm_role({"name": name, "description": description})
            except KeycloakError as exc_crear:
                if _codigo(exc_crear) != 409:
                    raise _traducir(exc_crear, "ensure_realm_role", role=name) from exc_crear
                # 409 = otra pasada concurrente lo creó primero. Es el resultado
                # que queríamos; seguir.
            return await self._kc.a_get_realm_role(name)

    # --- Grupos (= roles de negocio de Vendi) ------------------------------

    async def get_group_by_name(self, name: str) -> dict | None:
        try:
            grupos = await self._kc.a_get_groups({"search": name, "exact": "true"})
        except KeycloakError as exc:
            raise _traducir(exc, "get_group_by_name", group=name) from exc
        for g in grupos or []:
            if g.get("name") == name:
                return g
        return None

    async def ensure_group(self, name: str, description: str = "") -> str:
        """Alta idempotente de grupo. Devuelve su id."""
        existente = await self.get_group_by_name(name)
        if existente:
            return str(existente["id"])
        payload: dict[str, Any] = {"name": name}
        if description:
            payload["attributes"] = {"description": [description]}
        try:
            group_id = await self._kc.a_create_group(payload)
        except KeycloakError as exc:
            if _codigo(exc) == 409:
                otra_vez = await self.get_group_by_name(name)
                if otra_vez:
                    return str(otra_vez["id"])
            raise _traducir(exc, "ensure_group", group=name) from exc
        if group_id is None:
            raise ExternalServiceError(f"Keycloak no devolvió id al crear el grupo {name!r}")
        return str(group_id)

    async def set_group_realm_roles(self, group_id: str, role_names: list[str]) -> None:
        """Diff: añade y quita mapeos hasta que el grupo tenga exactamente `role_names`."""
        try:
            actuales = {r["name"]: r for r in await self._kc.a_get_group_realm_roles(group_id)}
            deseados = set(role_names)
            a_quitar = [actuales[n] for n in actuales.keys() - deseados]
            a_poner = [await self._kc.a_get_realm_role(n) for n in deseados - actuales.keys()]
            if a_quitar:
                await self._kc.a_delete_group_realm_roles(group_id, a_quitar)
            if a_poner:
                await self._kc.a_assign_group_realm_roles(group_id, a_poner)
        except KeycloakError as exc:
            raise _traducir(exc, "set_group_realm_roles", group_id=group_id) from exc

    async def add_user_realm_roles(self, user_id: str, role_names: list[str]) -> None:
        """Añade roles de realm (= permisos de Vendi) directamente al usuario.

        Se **añade**, no se sincroniza. Un `set` que quitara lo que sobra
        borraría también `default-roles-vendi-co`, que es el rol compuesto del
        que cuelgan `offline_access`, `uma_authorization` y los roles de cliente
        de `account`. Un usuario sin él sigue autenticándose, pero pierde la
        consola de cuenta —donde se registra la passkey—, y el síntoma aparece
        muy lejos de la causa.

        Lo usa la siembra para dar `platform:admin` al administrador de la
        consola. El camino normal de un usuario de negocio es heredar sus
        permisos del grupo, no tenerlos directos.
        """
        try:
            actuales = {r["name"] for r in await self._kc.a_get_realm_roles_of_user(user_id)}
            faltan = [n for n in role_names if n not in actuales]
            if not faltan:
                return
            roles = [await self._kc.a_get_realm_role(n) for n in faltan]
            await self._kc.a_assign_realm_roles(user_id, roles)
        except KeycloakError as exc:
            raise _traducir(exc, "add_user_realm_roles", user_id=user_id) from exc

    async def set_user_groups(self, user_id: str, group_names: list[str]) -> None:
        """Diff: añade y quita membresías hasta que el usuario esté exactamente en `group_names`."""
        try:
            actuales = {g["name"]: g for g in await self._kc.a_get_user_groups(user_id)}
            deseados = set(group_names)
            for nombre in actuales.keys() - deseados:
                await self._kc.a_group_user_remove(user_id, actuales[nombre]["id"])
            for nombre in deseados - actuales.keys():
                grupo = await self.get_group_by_name(nombre)
                if grupo:
                    await self._kc.a_group_user_add(user_id, grupo["id"])
        except KeycloakError as exc:
            raise _traducir(exc, "set_user_groups", user_id=user_id) from exc
