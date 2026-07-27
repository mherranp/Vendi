"""Dobles y constructores compartidos por los tests de la API.

Vive fuera de `conftest.py` para poder importarse por nombre
(`from ayudas import app_de_prueba`) sin depender de que pytest exponga el
conftest como módulo, que es un detalle de su mecanismo de carga y no un
contrato. Mismo criterio que `tests/datos_de_prueba.py`.

Regla de esta carpeta: **se prueba la aplicación real**. `crear_app()` con unos
`Settings` de prueba devuelve la misma cadena de middlewares, en el mismo orden,
con las mismas rutas y las mismas dependencias que sirve producción. Lo único
que se dobla son las dos fronteras externas que no se pueden ejercer en un test
unitario:

- el **validador de JWT**, sustituido por uno que traduce el token literal a un
  `UserContext`. Doblarlo no afloja nada de lo que estos tests miden: lo que se
  prueba es qué hace la API con un usuario que trae ciertos claims, no si
  python-jose sabe verificar una firma RS256 (eso ya lo prueban
  `test_jwt_validator.py` y `test_keycloak_admin_orgs.py` contra el Keycloak del
  compose).
- el **cliente del provisioner**, sustituido por un doble con memoria. Los
  tests que sí deben tocar el camino real de aprovisionamiento están marcados
  `integration` y van contra el `provisioner` del compose por
  `http://127.0.0.1:8010` (el puerto que el override de desarrollo publica
  solo en loopback).

La base de datos NO se dobla en los tests marcados `integration`: RLS, los
privilegios por rol y la policy del outbox solo existen en PostgreSQL, y un
doble los daría siempre por buenos.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI

from app.factory import crear_app
from app.settings import Settings
from vendi_core.auth.context import UserContext
from vendi_core.auth.policies import PERM_PLATFORM_ADMIN, ROL_DUENO, roles_de_realm_del_grupo
from vendi_core.errors.domain import ExternalServiceError

#: Prefijo de los nombres de negocio que crean los tests. La limpieza borra por
#: este prefijo, así que una corrida abortada a mitad no deja basura que haga
#: fallar la siguiente (la suite tiene que ser re-entrante: lo exige la
#: superficie de ataque de QA).
PREFIJO_PRUEBA = "PRUEBA "

TOKEN_METRICAS = "token-de-metricas-de-prueba"


# --- Dobles -----------------------------------------------------------------


class ValidadorFalso:
    """Traduce el token literal a un `UserContext`. Sin criptografía."""

    def __init__(self) -> None:
        self.por_token: dict[str, UserContext | Exception] = {}

    def registrar(self, token: str, usuario: UserContext | Exception) -> str:
        self.por_token[token] = usuario
        return token

    async def validate_token(self, token: str) -> UserContext:
        resultado = self.por_token.get(token)
        if resultado is None:
            raise ValueError("token desconocido")
        if isinstance(resultado, Exception):
            raise resultado
        return resultado


class AprovisionamientoFalso:
    """Doble con memoria del `PuertoAprovisionamiento` (el provisioner).

    Guarda `alias -> (org_id, name, description)` para que los tests puedan
    afirmar qué se le pidió al provisioner, y expone `fallar_al_crear` para
    provocar la compensación del alta sin tener que apagar un contenedor.
    """

    def __init__(self) -> None:
        self.organizaciones: dict[str, dict] = {}
        self.fallar_al_crear = False
        self.fallar_al_borrar = False
        self.borradas: list[str] = []

    async def create_organization(self, tenant_id: uuid.UUID, name: str) -> str:
        if self.fallar_al_crear:
            raise ExternalServiceError("El servicio de aprovisionamiento no responde")
        alias = str(tenant_id)
        if alias in self.organizaciones:
            raise ExternalServiceError("alias duplicado")
        org_id = f"org-{uuid.uuid4()}"
        # Réplica exacta de lo que deja el camino real: `name` es el alias
        # (Keycloak exige nombre único por realm) y el nombre legible va en
        # `description`.
        self.organizaciones[alias] = {"id": org_id, "name": alias, "description": name[:255]}
        return org_id

    async def delete_organization(self, org_id: str) -> None:
        if self.fallar_al_borrar:
            raise ExternalServiceError("El servicio de aprovisionamiento no responde")
        self.borradas.append(org_id)
        for alias, org in list(self.organizaciones.items()):
            if org["id"] == org_id:
                del self.organizaciones[alias]


# --- Usuarios de prueba ------------------------------------------------------


def usuario_de_plataforma(user_id: str = "admin-plataforma") -> UserContext:
    """Empleado de Vendi: tiene `platform:admin` y NINGUNA organización."""
    return UserContext(
        user_id=user_id,
        username="admin@vendi.co",
        email="admin@vendi.co",
        roles=frozenset({PERM_PLATFORM_ADMIN}),
        realm="vendi-co",
        organizations={},
    )


def usuario_de_negocio(*tenant_ids: uuid.UUID, user_id: str = "dueno") -> UserContext:
    """Dueño de uno o varios negocios. Sin ningún permiso de plataforma.

    `roles` lleva el rol de negocio **y** sus permisos, que es exactamente lo que
    trae `realm_access.roles` de un token real desde que el grupo `dueno` mapea
    los dos (Etapa 5, D-08). Antes el rol viajaba en un campo `groups` que el
    realm nunca llenaba, así que este doble era más generoso que la realidad.
    """
    return UserContext(
        user_id=user_id,
        username="dueno@demo.vendi.co",
        email="dueno@demo.vendi.co",
        roles=frozenset(roles_de_realm_del_grupo(ROL_DUENO)),
        realm="vendi-co",
        organizations={str(t): f"org-{t}" for t in tenant_ids},
    )


def usuario_con_rol(rol: str, *tenant_ids: uuid.UUID) -> UserContext:
    """Un usuario con un rol de negocio concreto (cajero, almacenista...).

    `roles` lleva el rol y sus permisos, que es lo que `realm_access.roles`
    trae de un token real desde que el grupo mapea las dos cosas
    (`roles_de_realm_del_grupo`). Sirve para probar los 200/403 por rol sin
    inventar claims que el realm jamás emitiría.
    """
    return UserContext(
        user_id=f"{rol}-prueba",
        username=f"{rol}@demo.vendi.co",
        email=f"{rol}@demo.vendi.co",
        roles=frozenset(roles_de_realm_del_grupo(rol)),
        realm="vendi-co",
        organizations={str(t): f"org-{t}" for t in tenant_ids},
    )


# --- Fábrica de la aplicación ------------------------------------------------


def settings_de_prueba(**anulaciones) -> Settings:
    """`Settings` mínimos. Los DSN por defecto NO conectan a ninguna parte.

    Los tests que necesitan base de datos pasan los DSN reales del compose por
    las fixtures `pg_app_url` / `pg_platform_url`.
    """
    base = {
        "app_env": "test",
        "database_url": "postgresql+asyncpg://nadie:nada@127.0.0.1:1/inexistente",
        "platform_database_url": "postgresql+asyncpg://nadie:nada@127.0.0.1:1/inexistente",
        "redis_url": "",
        "keycloak_url": "http://keycloak-de-prueba:8080",
        "keycloak_backend_client_secret": "secreto-de-prueba",
        "provisioner_url": "http://provisioner-de-prueba:8000",
        "metrics_token": TOKEN_METRICAS,
        "log_json": False,
        "log_level": "WARNING",
        # Se fijan explícitamente aunque coincidan con el defecto del código:
        # pydantic-settings lee el ENTORNO del proceso, y el `.env` de la raíz
        # —que `conftest.py` carga para los tests de integración— trae
        # `DOCS_PUBLICOS=true`. Sin esta línea, un test que afirma «por defecto
        # /docs no existe» pasa o falla según qué haya en el `.env` de quien lo
        # ejecuta, que es la definición de test no determinista.
        "docs_publicos": False,
        "keycloak_audience": "",
    }
    base.update(anulaciones)
    return Settings(**base)  # type: ignore[arg-type]


def app_de_prueba(settings: Settings | None = None) -> tuple[FastAPI, ValidadorFalso, AprovisionamientoFalso]:
    """La aplicación real con las dos fronteras externas dobladas."""
    aplicacion = crear_app(settings or settings_de_prueba())
    validador = ValidadorFalso()
    aprovisionamiento = AprovisionamientoFalso()
    aplicacion.state.jwt_validator = validador
    aplicacion.state.recursos.jwt_validator = validador
    aplicacion.state.recursos.aprovisionamiento = aprovisionamiento
    return aplicacion, validador, aprovisionamiento
