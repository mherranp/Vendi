"""Dependencias de FastAPI de autenticación y manejador de errores de dominio.

`vendi_core.auth.dependencies` viene de `base_saas.auth.dependencies` con el
camino de API keys eliminado (el módulo `api_keys` está fuera del alcance de
Fase 0). `vendi_core.middleware.error_handler` viene de su homónimo.

El test que justifica el archivo por sí solo:
`test_no_se_reutiliza_un_usuario_puesto_a_mano_en_request_state`. La dependencia
reaprovecha la validación de `TenantMiddleware` **solo** si el token es byte a
byte el mismo. Sin esa comparación, bastaría con que un middleware intermedio
dejara un `request.state.user` a su gusto para que la dependencia lo aceptara
como usuario autenticado — escalada de privilegios sin tocar el token.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user, require_permission, require_role
from vendi_core.auth.policies import (
    PERM_AUDIT_READ,
    PERM_TENANT_READ,
    PERM_TENANT_UPDATE,
    ROL_CAJERO,
    ROL_DUENO,
    roles_de_realm_del_grupo,
)
from vendi_core.errors import ConflictError, NotFoundError
from vendi_core.middleware.error_handler import ErrorHandlerMiddleware

TOKEN_BUENO = "token-valido"
TOKEN_MALO = "token-invalido"


class _ValidadorDoblado:
    def __init__(self, usuario: UserContext):
        self.usuario = usuario
        self.validaciones = 0

    async def validate_token(self, token: str) -> UserContext:
        self.validaciones += 1
        if token != TOKEN_BUENO:
            raise ValueError("firma inválida")
        return self.usuario


def _usuario(**kwargs) -> UserContext:
    datos = {"user_id": "kc-1", "username": "ana", "email": "ana@ejemplo.test"}
    datos.update(kwargs)
    return UserContext(**datos)


def _app(usuario: UserContext, *, sembrar_state: dict | None = None):
    validador = _ValidadorDoblado(usuario)
    app = FastAPI()
    app.state.jwt_validator = validador

    if sembrar_state is not None:

        @app.middleware("http")
        async def _sembrador(request, call_next):
            for clave, valor in sembrar_state.items():
                setattr(request.state, clave, valor)
            return await call_next(request)

    @app.get("/yo")
    async def yo(user: UserContext = Depends(get_current_user)):
        return {"user_id": user.user_id}

    @app.get("/solo-dueno")
    async def solo_dueno(user: UserContext = Depends(require_role(ROL_DUENO))):
        return {"ok": True}

    @app.get("/solo-con-permiso")
    async def solo_con_permiso(user: UserContext = Depends(require_permission(PERM_TENANT_READ))):
        return {"ok": True}

    return TestClient(app), validador


def _cabecera(token: str = TOKEN_BUENO) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_sin_cabecera_de_autorizacion_da_401():
    """Lo corta `HTTPBearer` antes de llegar al validador. Se afirma 401 —no
    403— porque es lo que devuelve la versión de FastAPI que trae el lockfile:
    un 403 aquí significaría "estás autenticado pero no puedes", que es
    exactamente lo contrario de lo que pasa."""
    cliente, _ = _app(_usuario())
    assert cliente.get("/yo").status_code == 401


def test_un_token_invalido_da_401_con_www_authenticate():
    cliente, _ = _app(_usuario())
    respuesta = cliente.get("/yo", headers=_cabecera(TOKEN_MALO))
    assert respuesta.status_code == 401
    assert respuesta.headers["WWW-Authenticate"] == "Bearer"
    assert "firma inválida" in respuesta.json()["detail"]


def test_un_token_valido_resuelve_el_usuario():
    cliente, validador = _app(_usuario())
    assert cliente.get("/yo", headers=_cabecera()).json() == {"user_id": "kc-1"}
    assert validador.validaciones == 1


def test_se_reutiliza_la_validacion_cuando_el_token_es_el_mismo():
    """`TenantMiddleware` ya validó el token en el mismo request: revalidarlo
    sería una segunda verificación de firma por petición."""
    previo = _usuario(user_id="kc-del-middleware")
    cliente, validador = _app(
        _usuario(),
        sembrar_state={"token_validado": TOKEN_BUENO, "user": previo},
    )
    assert cliente.get("/yo", headers=_cabecera()).json() == {"user_id": "kc-del-middleware"}
    assert validador.validaciones == 0


def test_no_se_reutiliza_un_usuario_puesto_a_mano_en_request_state():
    """El candado. `request.state.user` sin el token que lo produjo no vale
    nada: se revalida y gana el token de la cabecera."""
    intruso = _usuario(user_id="kc-intruso", is_superuser=True)
    cliente, validador = _app(
        _usuario(user_id="kc-real"),
        sembrar_state={"user": intruso},  # sin `token_validado`
    )
    assert cliente.get("/yo", headers=_cabecera()).json() == {"user_id": "kc-real"}
    assert validador.validaciones == 1


def test_no_se_reutiliza_si_el_token_marcado_no_coincide():
    intruso = _usuario(user_id="kc-intruso")
    cliente, validador = _app(
        _usuario(user_id="kc-real"),
        sembrar_state={"token_validado": "otro-token", "user": intruso},
    )
    assert cliente.get("/yo", headers=_cabecera()).json() == {"user_id": "kc-real"}
    assert validador.validaciones == 1


def test_require_role_deja_pasar_al_rol_correcto_y_corta_al_resto():
    """El candado de D-08 sobre la ruta HTTP real.

    Los dos usuarios se construyen con el mismo mapeo que la siembra escribe en
    Keycloak (`roles_de_realm_del_grupo`), así que si alguien vuelve a leer el
    rol de un claim que el realm no emite, el primer assert se pone rojo — antes
    los DOS pasaban, el 200 por el campo `groups` que solo existía en el test y
    el 403 por no tener nada.
    """
    cliente, _ = _app(_usuario(roles=frozenset(roles_de_realm_del_grupo(ROL_DUENO))))
    assert cliente.get("/solo-dueno", headers=_cabecera()).status_code == 200

    cliente, _ = _app(_usuario(roles=frozenset(roles_de_realm_del_grupo(ROL_CAJERO))))
    respuesta = cliente.get("/solo-dueno", headers=_cabecera())
    assert respuesta.status_code == 403
    assert ROL_DUENO in respuesta.json()["detail"]


def test_require_role_corta_a_quien_solo_trae_permisos():
    """Un usuario con permisos de sobra pero sin el rol NO entra. Distingue
    «tiene privilegios» de «es el dueño de este negocio»."""
    cliente, _ = _app(_usuario(roles=frozenset({PERM_TENANT_READ, PERM_AUDIT_READ, PERM_TENANT_UPDATE})))
    respuesta = cliente.get("/solo-dueno", headers=_cabecera())
    assert respuesta.status_code == 403


def test_require_permission_deja_pasar_con_el_permiso_y_corta_sin_el():
    cliente, _ = _app(_usuario(roles=frozenset({PERM_TENANT_READ})))
    assert cliente.get("/solo-con-permiso", headers=_cabecera()).status_code == 200

    cliente, _ = _app(_usuario(roles=frozenset({PERM_AUDIT_READ})))
    respuesta = cliente.get("/solo-con-permiso", headers=_cabecera())
    assert respuesta.status_code == 403
    assert PERM_TENANT_READ in respuesta.json()["detail"]


def test_un_superusuario_pasa_cualquier_permiso_pero_no_cualquier_rol():
    """`is_superuser` es un atajo de permisos, no de pertenencia a un negocio:
    un empleado de plataforma no es "el dueño de este negocio"."""
    cliente, _ = _app(_usuario(is_superuser=True))
    assert cliente.get("/solo-con-permiso", headers=_cabecera()).status_code == 200
    assert cliente.get("/solo-dueno", headers=_cabecera()).status_code == 403


# ---------------------------------------------------------------------------
# Manejador de errores
# ---------------------------------------------------------------------------


def _app_con_manejador() -> TestClient:
    app = FastAPI()
    app.add_middleware(ErrorHandlerMiddleware)

    @app.get("/no-existe")
    async def no_existe():
        raise NotFoundError("no hay tal venta")

    @app.get("/conflicto")
    async def conflicto():
        raise ConflictError("nombre ocupado", code="NOMBRE_OCUPADO", details={"nombre": "acme"})

    @app.get("/pum")
    async def pum():
        raise RuntimeError("detalle interno que no debe salir")

    return TestClient(app, raise_server_exceptions=False)


def test_un_error_de_dominio_sale_con_su_codigo_http_y_su_sobre():
    respuesta = _app_con_manejador().get("/no-existe")
    assert respuesta.status_code == 404
    assert respuesta.json() == {
        "success": False,
        "message": "no hay tal venta",
        "code": "NOT_FOUND",
        "details": {},
    }


def test_un_error_de_dominio_conserva_codigo_y_detalles_a_medida():
    cuerpo = _app_con_manejador().get("/conflicto").json()
    assert cuerpo["code"] == "NOMBRE_OCUPADO"
    assert cuerpo["details"] == {"nombre": "acme"}


def test_una_excepcion_no_controlada_no_filtra_el_detalle_interno():
    """El mensaje interno va al log, no al cliente: es donde se cuelan rutas de
    ficheros, nombres de tabla y fragmentos de SQL."""
    respuesta = _app_con_manejador().get("/pum")
    assert respuesta.status_code == 500
    cuerpo = respuesta.json()
    assert cuerpo == {"success": False, "message": "Internal server error", "code": "INTERNAL_ERROR"}
    assert "detalle interno" not in respuesta.text


def test_una_excepcion_no_controlada_mueve_el_contador_de_errores_tragados():
    from prometheus_client import REGISTRY

    def _leer() -> float:
        v = REGISTRY.get_sample_value(
            "vendi_suppressed_errors_total",
            labels={"component": "middleware.error_handler", "reason": "RuntimeError"},
        )
        return float(v or 0.0)

    antes = _leer()
    _app_con_manejador().get("/pum")
    assert _leer() == antes + 1


@pytest.mark.parametrize("ruta", ["/no-existe", "/conflicto"])
def test_los_errores_de_dominio_no_mueven_el_contador_de_500(ruta):
    """Un 404 de negocio no es una caída: contarlo como tal envenena la alerta."""
    from prometheus_client import REGISTRY

    def _leer() -> float:
        v = REGISTRY.get_sample_value(
            "vendi_suppressed_errors_total",
            labels={"component": "middleware.error_handler", "reason": "NotFoundError"},
        )
        return float(v or 0.0)

    antes = _leer()
    _app_con_manejador().get(ruta)
    assert _leer() == antes
