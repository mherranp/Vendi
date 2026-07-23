"""Humo de la fábrica de la API: arranca, responde salud y falla cerrado.

Sin base de datos, sin Redis y sin Keycloak: lo que se prueba es que la
aplicación se construye entera y que la cadena de middlewares hace su trabajo
sobre las rutas que no necesitan dependencias externas.
"""

from __future__ import annotations

import uuid

import pytest
from ayudas import app_de_prueba, settings_de_prueba, usuario_de_negocio, usuario_de_plataforma
from fastapi.testclient import TestClient


def test_health_responde_sin_dependencias(app_sin_base):
    cliente, _, _ = app_sin_base
    respuesta = cliente.get("/health")
    assert respuesta.status_code == 200
    # El literal importa: es lo que grepean el healthcheck del compose y el
    # check 10 de verify-setup.sh.
    assert respuesta.json() == {"status": "ok"}


def test_health_live_es_alias_de_health(app_sin_base):
    cliente, _, _ = app_sin_base
    assert cliente.get("/health/live").json() == {"status": "ok"}


def test_health_ready_con_todo_caido_da_503_y_no_500(app_sin_base):
    """La sonda de disponibilidad tiene que RESPONDER cuando todo está caído.

    Es su único momento útil. Una sonda que revienta con 500 no distingue
    "la aplicación está mal" de "sus dependencias están mal", que es
    exactamente lo que existe para distinguir.
    """
    cliente, _, _ = app_sin_base
    respuesta = cliente.get("/health/ready")
    assert respuesta.status_code == 503
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "no_disponible"
    assert set(cuerpo["dependencias"]) == {"postgres_app", "postgres_plataforma", "redis", "keycloak"}
    # El motivo del fallo NO viaja en el cuerpo: la ruta es pública.
    assert "traceback" not in respuesta.text.lower()
    assert "password" not in respuesta.text.lower()


def test_health_y_ready_no_piden_token(app_sin_base):
    """Una sonda con credenciales es una sonda que el orquestador no puede usar."""
    cliente, _, _ = app_sin_base
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/health/ready").status_code in (200, 503)


def test_ruta_protegida_sin_token_da_401_con_el_sobre_estandar(app_sin_base):
    cliente, _, _ = app_sin_base
    respuesta = cliente.get("/api/v1/tenants/me")
    assert respuesta.status_code == 401
    cuerpo = respuesta.json()
    # El sobre de `ErrorResponse`: success/message/code. Un segundo formato de
    # error (el `{"detail": ...}` de HTTPException) obligaría al frontend a
    # tener dos caminos de parseo, y el segundo nunca se escribe.
    assert cuerpo["success"] is False
    assert cuerpo["code"] == "token_ausente"
    assert isinstance(cuerpo["message"], str) and cuerpo["message"]


def test_ruta_de_plataforma_sin_token_da_401(app_sin_base):
    cliente, _, _ = app_sin_base
    respuesta = cliente.get("/api/v1/platform/tenants")
    assert respuesta.status_code == 401
    assert respuesta.json()["code"] == "token_ausente"


def test_token_no_valido_da_401_y_nunca_500(app_sin_base):
    cliente, validador, _ = app_sin_base
    validador.registrar("caducado", ValueError("Token expirado"))
    respuesta = cliente.get("/api/v1/tenants/me", headers={"Authorization": "Bearer caducado"})
    assert respuesta.status_code == 401
    assert respuesta.json()["code"] == "token_invalido"


def test_las_respuestas_de_error_llevan_correlacion_y_cabeceras_de_seguridad(app_sin_base):
    """Lo que compra el orden de la cadena: el 401 del middleware más interno
    sale con las cabeceras que ponen los más externos."""
    cliente, _, _ = app_sin_base
    respuesta = cliente.get("/api/v1/tenants/me")
    assert respuesta.status_code == 401
    assert respuesta.headers["X-Correlation-ID"]
    assert respuesta.headers["X-API-Version"] == "v1"
    assert respuesta.headers["X-Content-Type-Options"] == "nosniff"
    assert respuesta.headers["X-Frame-Options"] == "DENY"


def test_el_correlation_id_de_entrada_se_respeta(app_sin_base):
    cliente, _, _ = app_sin_base
    respuesta = cliente.get("/health", headers={"X-Correlation-ID": "abc-123"})
    assert respuesta.headers["X-Correlation-ID"] == "abc-123"


def test_un_token_sin_organizacion_no_pasa_a_una_ruta_de_negocio(app_sin_base):
    cliente, validador, _ = app_sin_base
    validador.registrar("plataforma", usuario_de_plataforma())
    respuesta = cliente.get("/api/v1/tenants/me", headers={"Authorization": "Bearer plataforma"})
    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "sin_organizacion_en_token"


def test_un_token_de_negocio_no_entra_en_la_consola_de_plataforma(app_sin_base):
    """El dueño de un negocio pasa el middleware (token válido) y se estrella
    contra `platform:admin`. Las dos puertas, en ese orden."""
    cliente, validador, _ = app_sin_base
    validador.registrar("dueno", usuario_de_negocio(uuid.uuid4()))
    respuesta = cliente.get("/api/v1/platform/tenants", headers={"Authorization": "Bearer dueno"})
    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "requiere_platform_admin"


def test_la_app_se_construye_sin_tocar_red_ni_base():
    """`crear_app` no puede hacer E/S: los tests y el arranque dependen de ello."""
    aplicacion, _, _ = app_de_prueba()
    assert aplicacion.state.recursos.engine_tenant is not None
    assert aplicacion.state.recursos.redis is None  # se conecta en el lifespan, no antes


def test_openapi_expone_el_contrato_de_fase_0():
    aplicacion, _, _ = app_de_prueba()
    rutas = set(aplicacion.openapi()["paths"])
    assert {
        "/health",
        "/health/ready",
        "/metrics",
        "/api/v1/platform/tenants",
        "/api/v1/platform/tenants/{tenant_id}",
        "/api/v1/tenants/me",
    } <= rutas


@pytest.mark.parametrize("ruta", ["/api/v1/tenants/me", "/api/v1/platform/tenants"])
def test_el_preflight_de_cors_nunca_recibe_401(app_sin_base, ruta):
    """El defecto que mataba a las cuatro SPAs.

    Un preflight es un `OPTIONS` que el navegador emite por su cuenta y al que
    la especificación de Fetch le prohíbe llevar credenciales. Contestarle 401
    significa que el request real nunca ocurre, y como la respuesta de error
    tampoco lleva cabeceras `Access-Control-Allow-*`, lo único que ve el
    desarrollador del SPA es «CORS error»: ni rastro del 401.
    """
    cliente, _, _ = app_sin_base
    respuesta = cliente.options(
        ruta,
        headers={
            "Origin": "http://localhost:4200",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert respuesta.status_code != 401, (
        "El preflight de CORS recibió 401: el navegador nunca hará el request real "
        "y el SPA verá un «CORS error» sin causa visible."
    )


def test_un_options_normal_sigue_pidiendo_token(app_sin_base):
    """La exención es del PREFLIGHT, no del verbo OPTIONS.

    Sin esta distinción, `OPTIONS` sería un agujero: bastaría con usar ese verbo
    para saltarse la resolución de tenant en cualquier ruta futura que lo
    implemente.
    """
    cliente, _, _ = app_sin_base
    respuesta = cliente.options("/api/v1/tenants/me")  # sin Access-Control-Request-Method
    assert respuesta.status_code == 401
    assert respuesta.json()["code"] == "token_ausente"


def test_con_cors_de_aplicacion_el_preflight_se_responde_con_cabeceras():
    """La topología sin Traefik delante: `CORS_ORIGINS` configurado.

    En el despliegue de Vendi el CORS lo termina Traefik y esto está vacío (ver
    la cabecera de `app.factory`), pero la capacidad tiene que funcionar y estar
    probada, porque es la que se usará el día que la API se sirva sin ese borde.
    """
    settings = settings_de_prueba(cors_origins="http://localhost:4200")
    aplicacion, _, _ = app_de_prueba(settings)
    with TestClient(aplicacion, raise_server_exceptions=False) as cliente:
        respuesta = cliente.options(
            "/api/v1/tenants/me",
            headers={
                "Origin": "http://localhost:4200",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert respuesta.status_code == 200
    assert respuesta.headers["access-control-allow-origin"] == "http://localhost:4200"


# --- La documentación interactiva: cerrada salvo que se pida ----------------


def test_por_defecto_docs_openapi_y_redoc_no_existen():
    """404 real, no un middleware que las tape: con `docs_publicos=False`
    FastAPI ni siquiera registra las rutas.

    Hasta la Etapa 5 estaban abiertas en el borde sin decisión escrita. Lo que
    publican es el mapa completo de la API —rutas, esquemas, códigos de error,
    incluidas las de plataforma—, y en Fase 0 no hay ningún consumidor externo
    que lo necesite: el cliente TypeScript se genera contra el contrato
    versionado en docs/api/openapi-fase0.json.
    """
    app, _, _ = app_de_prueba()
    cliente = TestClient(app)
    for ruta in ("/docs", "/redoc", "/openapi.json"):
        assert cliente.get(ruta).status_code == 404, f"{ruta} no debería existir con DOCS_PUBLICOS apagado"


def test_con_docs_publicos_las_tres_rutas_se_sirven():
    """El interruptor tiene que funcionar en los dos sentidos: si solo se
    probara el 404, un cambio que las apagara para siempre pasaría igual."""
    app, _, _ = app_de_prueba(settings_de_prueba(docs_publicos=True))
    cliente = TestClient(app)
    assert cliente.get("/openapi.json").status_code == 200
    assert cliente.get("/docs").status_code == 200
    assert cliente.get("/redoc").status_code == 200
