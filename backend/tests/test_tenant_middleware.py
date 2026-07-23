"""`TenantMiddleware`: resolución del negocio desde el claim `organization`.

Se monta una app FastAPI mínima con un validador de JWT falso. No hace falta
Keycloak: lo que se prueba es la máquina de estados del middleware —qué status
devuelve ante cada forma del claim— y el ciclo de vida del ContextVar.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vendi_core.auth.context import UserContext
from vendi_core.tenant.context import current_tenant_id
from vendi_core.tenant.middleware import HEADER_TENANT, TenantMiddleware

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")


class ValidadorFalso:
    """Traduce el token literal a un `UserContext`. Sin criptografía."""

    def __init__(self, por_token: dict[str, UserContext | Exception]):
        self._por_token = por_token

    async def validate_token(self, token: str) -> UserContext:
        resultado = self._por_token.get(token)
        if resultado is None:
            raise ValueError("token desconocido")
        if isinstance(resultado, Exception):
            raise resultado
        return resultado


def _usuario(**orgs: str) -> UserContext:
    return UserContext(user_id="u1", username="cajera1", organizations=dict(orgs))


def _app(validador) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantMiddleware)
    app.state.jwt_validator = validador

    @app.get("/health")
    async def salud():
        return {"status": "ok"}

    @app.get("/api/v1/ventas")
    async def ventas():
        return {"tenant": str(current_tenant_id.get())}

    @app.get("/api/v1/platform/tenants")
    async def plataforma():
        return {"tenant": str(current_tenant_id.get())}

    @app.get("/api/v1/explota")
    async def explota():
        raise RuntimeError("fallo del handler")

    return app


@pytest.fixture
def cliente_una_org():
    validador = ValidadorFalso({"tok": _usuario(**{str(T1): "org-1"})})
    return TestClient(_app(validador), raise_server_exceptions=False)


@pytest.fixture
def cliente_dos_orgs():
    validador = ValidadorFalso({"tok": _usuario(**{str(T1): "org-1", str(T2): "org-2"})})
    return TestClient(_app(validador), raise_server_exceptions=False)


@pytest.fixture
def cliente_sin_orgs():
    return TestClient(_app(ValidadorFalso({"tok": _usuario()})), raise_server_exceptions=False)


# --- (a) una organización ---------------------------------------------------


def test_una_org_resuelve_el_tenant(cliente_una_org):
    r = cliente_una_org.get("/api/v1/ventas", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    assert r.json() == {"tenant": str(T1)}


def test_el_contextvar_queda_limpio_al_terminar_el_request(cliente_una_org):
    assert current_tenant_id.get() is None
    cliente_una_org.get("/api/v1/ventas", headers={"Authorization": "Bearer tok"})
    assert current_tenant_id.get() is None


def test_el_contextvar_queda_limpio_aunque_el_handler_lance(cliente_una_org):
    """El `reset` va en un `finally`, no después del `return`."""
    r = cliente_una_org.get("/api/v1/explota", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 500
    assert current_tenant_id.get() is None


# --- (b) sin organizaciones -------------------------------------------------


def test_ruta_publica_pasa_sin_token(cliente_sin_orgs):
    assert cliente_sin_orgs.get("/health").status_code == 200


def test_sin_orgs_403_en_ruta_de_tenant(cliente_sin_orgs):
    r = cliente_sin_orgs.get("/api/v1/ventas", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 403
    cuerpo = r.json()
    assert cuerpo["code"] == "sin_organizacion_en_token"
    # El mensaje tiene que decir qué hacer: es el sustituto del fallback a
    # get_user_organizations, que se descartó por exigir manage-realm (D-02).
    assert "organization:*" in cuerpo["message"]


def test_sin_orgs_pasa_en_ruta_de_plataforma(cliente_sin_orgs):
    """La consola de Vendi trabaja cross-tenant: no tiene ni debe tener negocio."""
    r = cliente_sin_orgs.get("/api/v1/platform/tenants", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    assert r.json() == {"tenant": "None"}


# --- (c) dos organizaciones -------------------------------------------------


def test_dos_orgs_sin_header_da_400(cliente_dos_orgs):
    r = cliente_dos_orgs.get("/api/v1/ventas", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 400
    assert r.json()["code"] == "tenant_no_especificado"


def test_dos_orgs_con_header_valido(cliente_dos_orgs):
    r = cliente_dos_orgs.get(
        "/api/v1/ventas",
        headers={"Authorization": "Bearer tok", HEADER_TENANT: str(T2)},
    )
    assert r.status_code == 200
    assert r.json() == {"tenant": str(T2)}


def test_header_con_negocio_ajeno_se_rechaza(cliente_dos_orgs):
    """EL ataque: pedir el negocio del vecino por cabecera.

    El header se compara contra los alias DEL TOKEN, no contra la base de datos
    ni contra sí mismo. Un alias perfectamente válido de un negocio del que el
    usuario no es miembro cae aquí, y cae con 400 antes de tocar la base.
    """
    ajeno = str(uuid.uuid4())
    r = cliente_dos_orgs.get(
        "/api/v1/ventas",
        headers={"Authorization": "Bearer tok", HEADER_TENANT: ajeno},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "tenant_no_especificado"


def test_header_ignorado_cuando_solo_hay_una_org(cliente_una_org):
    """Con una sola membresía el header no puede cambiar de negocio."""
    r = cliente_una_org.get(
        "/api/v1/ventas",
        headers={"Authorization": "Bearer tok", HEADER_TENANT: str(T2)},
    )
    assert r.status_code == 200
    assert r.json() == {"tenant": str(T1)}


# --- (d) alias que no es UUID ----------------------------------------------


def test_alias_no_uuid_da_401_y_no_500():
    """Un alias libre en Keycloak no puede convertirse en un error de cast.

    El spike midió que un GUC con basura produce `invalid input syntax for type
    uuid` y aborta la transacción: fail-closed, pero un 500 sin pistas por un
    problema de configuración perfectamente diagnosticable.
    """
    validador = ValidadorFalso({"tok": _usuario(**{"tienda-don-carlos": "org-1"})})
    cliente = TestClient(_app(validador), raise_server_exceptions=False)
    r = cliente.get("/api/v1/ventas", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 401
    assert r.json()["code"] == "alias_de_organizacion_invalido"


# --- Tokens rechazados ------------------------------------------------------


def test_sin_cabecera_authorization_da_401(cliente_una_org):
    r = cliente_una_org.get("/api/v1/ventas")
    assert r.status_code == 401
    assert r.json()["code"] == "token_ausente"


def test_cabecera_sin_bearer_da_401(cliente_una_org):
    r = cliente_una_org.get("/api/v1/ventas", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


def test_token_rechazado_por_el_validador_da_401(cliente_una_org):
    """Expirado, realm malo, firma mala: todos terminan en 401, jamás en 500."""
    r = cliente_una_org.get("/api/v1/ventas", headers={"Authorization": "Bearer otro"})
    assert r.status_code == 401
    assert r.json()["code"] == "token_invalido"


def test_keycloak_inalcanzable_da_503_no_401():
    """Un IdP caído no es un token inválido, y confundirlos manda al usuario a
    reintentar el login en vez de esperar a que el servicio vuelva."""
    validador = ValidadorFalso({"tok": ConnectionError("keycloak no responde")})
    cliente = TestClient(_app(validador), raise_server_exceptions=False)
    r = cliente.get("/api/v1/ventas", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 503
    assert r.json()["code"] == "verificacion_no_disponible"


def test_sin_validador_cableado_da_500_no_401():
    """Un despliegue mal cableado no debe disfrazarse de problema de credenciales."""
    app = FastAPI()
    app.add_middleware(TenantMiddleware)

    @app.get("/api/v1/ventas")
    async def ventas():
        return {}

    cliente = TestClient(app, raise_server_exceptions=False)
    r = cliente.get("/api/v1/ventas", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 500
    assert r.json()["code"] == "config_invalida"


def test_el_sobre_de_error_es_el_mismo_que_el_del_error_handler(cliente_sin_orgs):
    """Un solo camino de parseo de errores para el frontend."""
    r = cliente_sin_orgs.get("/api/v1/ventas", headers={"Authorization": "Bearer tok"})
    cuerpo = r.json()
    assert set(cuerpo) == {"success", "message", "code"}
    assert cuerpo["success"] is False
