"""Las rutas del provisioner contra la aplicación real, con Keycloak doblado.

Mismo criterio que `tests/api/ayudas.py`: se prueba la aplicación real —las
rutas, la validación, el sobre de errores— y solo se dobla la frontera externa
que un test unitario no puede ejercer, el cliente de Keycloak. El camino
completo contra el Keycloak de verdad lo cubren los tests `integration`.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from provisioner.factory import crear_app
from provisioner.settings import Settings
from vendi_core.auth.policies import PERM_PLATFORM_ADMIN, PERMISSION_CATALOG, ROLES_DE_NEGOCIO
from vendi_core.errors.domain import ConflictError


class KeycloakDeMentira:
    """Doble con memoria de `VendiKeycloakAprovisionamiento`."""

    def __init__(self) -> None:
        self.organizaciones: dict[str, dict] = {}
        self.roles: dict[str, dict] = {}
        self.grupos: dict[str, str] = {}
        self.mapeos_de_grupo: dict[str, list[str]] = {}
        self.usuarios: dict[str, dict] = {}
        self.roles_de_usuario: dict[str, list[str]] = {}
        self.grupos_de_usuario: dict[str, list[str]] = {}
        self.miembros: set[tuple[str, str]] = set()
        self.siguiente = 0

    # --- Organizations ---

    async def create_organization(self, tenant_id: uuid.UUID, name: str) -> str:
        alias = str(tenant_id)
        if alias in self.organizaciones:
            raise ConflictError("Ya existe en Keycloak (create_organization)")
        self.siguiente += 1
        org = {"id": f"org-{self.siguiente}", "alias": alias, "name": alias, "description": name}
        self.organizaciones[alias] = org
        return org["id"]

    async def get_organization_by_alias(self, tenant_id: uuid.UUID) -> dict | None:
        return self.organizaciones.get(str(tenant_id))

    async def list_organizations(self, first: int = 0, max_result: int = 100) -> list[dict]:
        return list(self.organizaciones.values())[first : first + max_result]

    async def delete_organization(self, org_id: str) -> None:
        for alias, org in list(self.organizaciones.items()):
            if org["id"] == org_id:
                del self.organizaciones[alias]

    async def add_member(self, org_id: str, user_id: str) -> None:
        self.miembros.add((org_id, user_id))

    async def get_user_organizations(self, user_id: str) -> list[dict]:
        return [org for org in self.organizaciones.values() if (org["id"], user_id) in self.miembros]

    # --- Siembra ---

    async def ensure_realm_role(self, name: str, description: str = "") -> dict:
        return self.roles.setdefault(name, {"id": f"rol-{name}", "name": name})

    async def ensure_group(self, name: str, description: str = "") -> str:
        return self.grupos.setdefault(name, f"grupo-{name}")

    async def set_group_realm_roles(self, group_id: str, role_names: list[str]) -> None:
        self.mapeos_de_grupo[group_id] = list(role_names)

    async def find_user_by_username(self, username: str) -> dict | None:
        return self.usuarios.get(username)

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
        user_id = f"user-{len(self.usuarios) + 1}"
        self.usuarios[username] = {"id": user_id, "username": username, "password": password}
        return user_id

    async def add_user_realm_roles(self, user_id: str, role_names: list[str]) -> None:
        self.roles_de_usuario.setdefault(user_id, []).extend(role_names)

    async def set_user_groups(self, user_id: str, group_names: list[str]) -> None:
        self.grupos_de_usuario[user_id] = list(group_names)


@pytest.fixture
def cliente():
    settings = Settings(
        keycloak_url="http://keycloak-de-prueba:8080",
        keycloak_provisioning_client_secret="secreto-de-prueba",
        log_json=False,
        log_level="WARNING",
    )
    aplicacion = crear_app(settings)
    kc = KeycloakDeMentira()
    aplicacion.state.kc = kc
    with TestClient(aplicacion, raise_server_exceptions=False) as c:
        yield c, kc


# --- Salud y cierre de la superficie -------------------------------------------


def test_health_responde_sin_tocar_keycloak(cliente):
    c, _ = cliente
    assert c.get("/health").json() == {"status": "ok"}


def test_no_hay_docs_ni_openapi(cliente):
    """Servicio interno: el mapa de rutas no se publica ni en la red interna."""
    c, _ = cliente
    assert c.get("/docs").status_code == 404
    assert c.get("/openapi.json").status_code == 404


# --- Organizations ---------------------------------------------------------------


def test_ciclo_completo_de_una_organizacion(cliente):
    c, _ = cliente
    tenant_id = uuid.uuid4()

    creada = c.post("/interno/v1/organizaciones", json={"tenant_id": str(tenant_id), "nombre": "Tienda"})
    assert creada.status_code == 201, creada.text
    org_id = creada.json()["kc_org_id"]

    consulta = c.get("/interno/v1/organizaciones", params={"alias": str(tenant_id)})
    assert consulta.status_code == 200
    assert consulta.json()["alias"] == str(tenant_id)

    listado = c.get("/interno/v1/organizaciones")
    assert any(o["id"] == org_id for o in listado.json()["items"])

    assert c.delete(f"/interno/v1/organizaciones/{org_id}").status_code == 204
    assert c.get("/interno/v1/organizaciones", params={"alias": str(tenant_id)}).status_code == 404


def test_alias_duplicado_devuelve_409_con_el_sobre_estandar(cliente):
    c, _ = cliente
    tenant_id = uuid.uuid4()
    c.post("/interno/v1/organizaciones", json={"tenant_id": str(tenant_id), "nombre": "Uno"})

    repetida = c.post("/interno/v1/organizaciones", json={"tenant_id": str(tenant_id), "nombre": "Dos"})

    assert repetida.status_code == 409
    cuerpo = repetida.json()
    assert cuerpo["success"] is False
    assert cuerpo["code"] == "CONFLICT"


def test_el_nombre_vacio_se_rechaza_en_la_frontera(cliente):
    c, _ = cliente
    respuesta = c.post("/interno/v1/organizaciones", json={"tenant_id": str(uuid.uuid4()), "nombre": ""})
    assert respuesta.status_code == 422


def test_miembros_de_una_organizacion(cliente):
    c, _ = cliente
    org_id = c.post("/interno/v1/organizaciones", json={"tenant_id": str(uuid.uuid4()), "nombre": "T"}).json()[
        "kc_org_id"
    ]

    assert c.put(f"/interno/v1/organizaciones/{org_id}/miembros/user-7").status_code == 204

    orgs = c.get("/interno/v1/usuarios/user-7/organizaciones").json()["items"]
    assert [o["id"] for o in orgs] == [org_id]


# --- Siembra ---------------------------------------------------------------------


def test_la_siembra_del_realm_crea_roles_grupos_y_mapeos(cliente):
    c, kc = cliente

    respuesta = c.post("/interno/v1/semilla/realm")
    assert respuesta.status_code == 200, respuesta.text
    resumen = respuesta.json()
    assert resumen["permisos"] == len(PERMISSION_CATALOG)
    assert sorted(resumen["roles_de_negocio"]) == sorted(ROLES_DE_NEGOCIO)

    # Cada permiso es un rol de realm; cada rol de negocio es rol Y grupo con
    # su mapeo. Y es idempotente: la segunda pasada devuelve lo mismo.
    for permiso, _ in PERMISSION_CATALOG:
        assert permiso in kc.roles
    for rol in ROLES_DE_NEGOCIO:
        assert rol in kc.roles
        grupo_id = kc.grupos[rol]
        assert rol in kc.mapeos_de_grupo[grupo_id]
    assert c.post("/interno/v1/semilla/realm").json() == resumen


def test_la_siembra_del_admin_es_idempotente_y_le_da_platform_admin(cliente):
    c, kc = cliente

    primero = c.post("/interno/v1/semilla/admin-plataforma", json={"password": "clave-1"})
    assert primero.status_code == 201
    assert primero.json()["creado"] is True
    user_id = primero.json()["user_id"]

    segundo = c.post("/interno/v1/semilla/admin-plataforma", json={"password": "clave-2"})
    assert segundo.json()["creado"] is False
    assert segundo.json()["user_id"] == user_id
    # La segunda pasada NO cambia la contraseña: la siembra no es un mecanismo
    # de rotación, es un "asegura que existe".
    assert kc.usuarios["admin@vendi.co"]["password"] == "clave-1"
    assert PERM_PLATFORM_ADMIN in kc.roles_de_usuario[user_id]


def test_el_dueno_demo_exige_que_la_organizacion_exista(cliente):
    c, _ = cliente
    respuesta = c.post("/interno/v1/semilla/dueno-demo", json={"tenant_id": str(uuid.uuid4()), "password": "x"})
    assert respuesta.status_code == 404
    assert respuesta.json()["code"] == "organizacion_no_encontrada"


def test_el_dueno_demo_queda_en_el_grupo_y_en_la_organizacion(cliente):
    c, kc = cliente
    tenant_id = uuid.uuid4()
    org_id = c.post("/interno/v1/organizaciones", json={"tenant_id": str(tenant_id), "nombre": "Demo"}).json()[
        "kc_org_id"
    ]

    respuesta = c.post("/interno/v1/semilla/dueno-demo", json={"tenant_id": str(tenant_id), "password": "clave"})
    assert respuesta.status_code == 201, respuesta.text
    user_id = respuesta.json()["user_id"]

    assert kc.grupos_de_usuario[user_id] == ["dueno"]
    assert (org_id, user_id) in kc.miembros
