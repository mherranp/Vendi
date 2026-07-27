"""Administración de Keycloak con `manage-realm`: Organizations del realm `vendi-co`.

Esta clase vivía en `keycloak_admin.py` junto a `VendiKeycloakAdmin`. Se separó
a módulo propio al cerrar D-02 (ADR-027): **el código que necesita
`manage-realm` ya no lo carga la API**, solo el servicio `provisioner`
(`backend/services/provisioner`), que es la única unidad de despliegue con el
secreto de `vendi-provisioning`. La API habla con ese servicio por HTTP interno
(`vendi_core.provisioning.cliente`) y en su proceso no hay forma de llegar a
`manage-realm` ni queriendo.

La cabecera de `keycloak_admin.py` explica por qué el privilegio está partido
en dos credenciales; `docs/deuda-tecnica.md` (D-02, cerrada) conserva la
matriz medida que obligó al diseño.
"""

from __future__ import annotations

import uuid

from keycloak.exceptions import KeycloakError

from vendi_core.auth.keycloak_admin import VendiKeycloakAdmin, _codigo, _traducir
from vendi_core.errors.domain import ExternalServiceError

__all__ = ["SUFIJO_DOMINIO_ORG", "VendiKeycloakAprovisionamiento"]

# Sufijo del dominio sintético de cada organización. No es obligatorio para
# Keycloak (pregunta 5 del spike: la org se crea sin `domains`), pero se mantiene
# porque el patrón es único por construcción —el alias es un UUID— y deja abierta
# sin migración la puerta al login identity-first por dominio de email. Coste:
# cero.
SUFIJO_DOMINIO_ORG = "tenants.vendi.co"


class VendiKeycloakAprovisionamiento(VendiKeycloakAdmin):
    """Lo anterior **más** Organizations. Necesita `manage-realm`.

    Se instancia con el cliente `vendi-provisioning` y **solo** la usa el
    servicio `provisioner` (sus rutas internas de alta/baja de negocios y de
    siembra). Los tests de integración la ejercen desde el anfitrión, con el
    secreto leído del `.env` — nunca dentro del proceso de la API.
    """

    # --- Organizations -----------------------------------------------------

    @staticmethod
    def dominio_de(tenant_id: uuid.UUID) -> str:
        return f"{tenant_id}.{SUFIJO_DOMINIO_ORG}"

    async def create_organization(self, tenant_id: uuid.UUID, name: str) -> str:
        """Crea la Organization del negocio y devuelve su id interno de Keycloak.

        `alias = str(tenant_id)`: decisión 3 del informe del spike. Keycloak
        acepta el UUID con guiones y lo devuelve literal en el claim, así que el
        middleware resuelve el tenant desde el token **sin ningún lookup**. Esa
        propiedad es la que hace barata la resolución del tenant, y por eso el
        alias no se toca nunca.

        Un alias duplicado da 409 limpio (medido), que aquí sale como
        `ConflictError`: el servicio de alta puede tratarlo como "ya existe" sin
        parsear trazas.

        ## El `name` de la Organization es el tenant_id, NO el nombre del negocio

        Hallazgo medido contra 26.6.4 en la Etapa 4, y no estaba en el plan:
        **Keycloak exige que el `name` de una Organization sea único en el
        realm.** Dos altas con el mismo nombre y alias distintos:

            POST /admin/realms/vendi-co/organizations  {"name":"Sonda", "alias":"...0001"} → 201
            POST /admin/realms/vendi-co/organizations  {"name":"Sonda", "alias":"...0002"} → 409
            {"errorMessage":"A organization with the same name already exists."}

        Si el `name` de la organización fuera el nombre del negocio, Vendi
        heredaría esa unicidad: el segundo «Tienda Don Carlos» de Colombia no
        podría darse de alta. Eso no es una restricción del producto —el negocio
        se identifica por su UUID— sino de una tabla del IdP, y además filtra
        información entre inquilinos: por los 409 se podría enumerar qué nombres
        de negocio existen ya en la región.

        Así que el `name` de la organización es `str(tenant_id)`, único por
        construcción, y el nombre legible viaja en `description`, que Keycloak
        no obliga a que sea único (medido: acepta 300 caracteres y los devuelve
        completos). Consecuencias que hay que saber:

        - La consola de Keycloak lista organizaciones por UUID; el nombre del
          negocio se ve en la columna de descripción.
        - Renombrar un negocio en Vendi **no toca Keycloak**. Es una propiedad
          buscada: el rename no puede fallar porque el IdP esté caído.
        """
        payload = {
            "name": str(tenant_id),
            "alias": str(tenant_id),
            # 255 por prudencia: es el ancho del `description` de un *cliente*
            # de Keycloak (varchar(255)), donde pasarse revienta el import con
            # un 500 de JDBC. El de las organizaciones aguanta más (medido:
            # 300), pero no hay motivo para acercarse al borde: los nombres de
            # negocio los valida la API en 120 caracteres.
            "description": (name or "")[:255],
            "domains": [{"name": self.dominio_de(tenant_id), "verified": True}],
        }
        try:
            org_id = await self._kc.a_create_organization(payload)
        except KeycloakError as exc:
            raise _traducir(exc, "create_organization", tenant_id=str(tenant_id)) from exc
        if not org_id:
            # python-keycloak deduce el id de la cabecera `Location`. Si no
            # viene, el alta "funcionó" pero no sabemos qué se creó: mejor
            # error explícito que devolver None y que reviente tres capas
            # más arriba.
            raise ExternalServiceError(
                "Keycloak creó la organización pero no devolvió su id (cabecera Location ausente)",
                details={"tenant_id": str(tenant_id)},
            )
        return str(org_id)

    async def get_organization_by_alias(self, tenant_id: uuid.UUID) -> dict | None:
        """Busca la organización por alias (= tenant_id)."""
        try:
            # Sin `exact`: medido contra 26.6.4, `/organizations` **no** admite
            # ese parámetro y pasarlo devuelve cero resultados en vez de un
            # error — es decir, un "no existe" falso, que en el camino de alta
            # de negocio significaría crear una organización duplicada. El
            # filtro exacto se hace abajo, en Python, sobre el alias.
            orgs = await self._kc.a_get_organizations({"search": str(tenant_id)})
        except KeycloakError as exc:
            raise _traducir(exc, "get_organization_by_alias", tenant_id=str(tenant_id)) from exc
        for org in orgs or []:
            if org.get("alias") == str(tenant_id):
                return org
        return None

    async def delete_organization(self, org_id: str) -> None:
        """Borra la organización. Idempotente: un 404 es "ya no está"."""
        try:
            await self._kc.a_delete_organization(org_id)
        except KeycloakError as exc:
            if _codigo(exc) == 404:
                return
            raise _traducir(exc, "delete_organization", org_id=org_id) from exc

    async def set_organization_enabled(self, org_id: str, enabled: bool) -> None:
        """Freno complementario para casos de abuso. **No** es la suspensión.

        El spike midió que deshabilitar la organización no impide el login: solo
        la saca del claim, y no invalida los tokens ya emitidos. La suspensión de
        un negocio es y sigue siendo un estado en la tabla `tenants`. Esto está
        aquí para el runbook, no para el flujo normal de producto.
        """
        try:
            org = await self._kc.a_get_organization(org_id)
            org["enabled"] = enabled
            await self._kc.a_update_organization(org_id, org)
        except KeycloakError as exc:
            raise _traducir(exc, "set_organization_enabled", org_id=org_id) from exc

    async def add_member(self, org_id: str, user_id: str) -> None:
        try:
            await self._kc.a_organization_user_add(user_id, org_id)
        except KeycloakError as exc:
            if _codigo(exc) == 409:
                return  # ya es miembro: idempotente
            raise _traducir(exc, "add_member", org_id=org_id, user_id=user_id) from exc

    async def remove_member(self, org_id: str, user_id: str) -> None:
        try:
            await self._kc.a_organization_user_remove(user_id, org_id)
        except KeycloakError as exc:
            if _codigo(exc) == 404:
                return  # no era miembro: idempotente
            raise _traducir(exc, "remove_member", org_id=org_id, user_id=user_id) from exc

    async def get_organization_members(self, org_id: str) -> list[dict]:
        try:
            return list(await self._kc.a_get_organization_members(org_id) or [])
        except KeycloakError as exc:
            raise _traducir(exc, "get_organization_members", org_id=org_id) from exc

    async def get_user_organizations(self, user_id: str) -> list[dict]:
        """Organizaciones de un usuario, consultadas a Keycloak.

        Ojo con la ruta: python-keycloak llama a
        `/admin/realms/{realm}/organizations/members/{user_id}/organizations`,
        no a `/users/{id}/organizations` —esta última **no existe** en 26.6.4 y
        devuelve 404 con cualquier privilegio. Verificado.

        Existe para el reconciliador y para diagnóstico. **No** lo usa el
        `TenantMiddleware`: ver la nota de `vendi_core.tenant.middleware` sobre
        por qué el fallback se descartó.
        """
        try:
            return list(await self._kc.a_get_user_organizations(user_id) or [])
        except KeycloakError as exc:
            raise _traducir(exc, "get_user_organizations", user_id=user_id) from exc

    async def list_organizations(self, first: int = 0, max_result: int = 100) -> list[dict]:
        try:
            return list(await self._kc.a_get_organizations({"first": first, "max": max_result}) or [])
        except KeycloakError as exc:
            raise _traducir(exc, "list_organizations") from exc
