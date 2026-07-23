"""Middlewares HTTP transversales: correlación, cabeceras de seguridad y
redactor de secretos en el cuerpo de respuesta.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_otel_optin.py` (la
mitad de la fusión con `traceparent`), `test_security_headers.py` y
`test_oidc_client_secret_redaction.py` / `test_service_account_secret_redaction.py`.
Adaptación: `base_saas` → `vendi_core`.

Los tres paquetes entraban al repositorio sin una sola línea ejecutada.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from vendi_core.middleware.correlation import CorrelationIdMiddleware, _extract_trace_id
from vendi_core.middleware.secret_redactor import SecretRedactorMiddleware
from vendi_core.middleware.security_headers import (
    DEFAULT_CSP,
    HSTS_VALUE,
    SecurityHeadersMiddleware,
    _resolve_csp,
)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACEPARENT = f"00-{TRACE_ID}-00f067aa0ba902b7-01"


# ---------------------------------------------------------------------------
# Correlación
# ---------------------------------------------------------------------------


def test_extraer_trace_id_de_un_traceparent_valido():
    assert _extract_trace_id(TRACEPARENT) == TRACE_ID


@pytest.mark.parametrize(
    "cabecera",
    [
        None,
        "",
        "basura",
        "00-corto-00f067aa0ba902b7-01",
        f"00-{'0' * 32}-00f067aa0ba902b7-01",  # trace-id todo ceros: inválido por spec
        f"00-{TRACE_ID}-00f067aa0ba902b7",  # falta el campo de flags
    ],
)
def test_un_traceparent_invalido_no_produce_correlacion(cabecera):
    assert _extract_trace_id(cabecera) is None


def _app_con_correlacion() -> TestClient:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/eco")
    async def eco(): ...

    @app.get("/eco2")
    async def eco2():
        return {"ok": True}

    return TestClient(app)


def test_sin_cabeceras_se_acuna_un_uuid_nuevo():
    respuesta = _app_con_correlacion().get("/eco2")
    devuelto = respuesta.headers["X-Correlation-ID"]
    uuid.UUID(devuelto)  # revienta si no es un UUID


def test_el_traceparent_se_reutiliza_como_id_de_correlacion():
    """Así los logs y las trazas comparten un único identificador: sin esto hay
    que cruzar dos ids a mano en cada incidencia."""
    respuesta = _app_con_correlacion().get("/eco2", headers={"traceparent": TRACEPARENT})
    assert respuesta.headers["X-Correlation-ID"] == TRACE_ID


def test_un_x_correlation_id_explicito_gana_sobre_el_traceparent():
    respuesta = _app_con_correlacion().get(
        "/eco2",
        headers={"traceparent": TRACEPARENT, "X-Correlation-ID": "el-mio"},
    )
    assert respuesta.headers["X-Correlation-ID"] == "el-mio"


# ---------------------------------------------------------------------------
# Cabeceras de seguridad
# ---------------------------------------------------------------------------


def _app_con_seguridad(**kwargs) -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, **kwargs)

    @app.get("/x")
    async def x():
        return {"ok": True}

    return TestClient(app)


def test_las_cabeceras_estaticas_van_en_toda_respuesta():
    cabeceras = _app_con_seguridad(app_env="development").get("/x").headers
    assert cabeceras["X-Content-Type-Options"] == "nosniff"
    assert cabeceras["X-Frame-Options"] == "DENY"
    assert cabeceras["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in cabeceras["Permissions-Policy"]
    assert cabeceras["Content-Security-Policy"] == DEFAULT_CSP


def test_sin_produccion_no_se_pone_hsts():
    """Fijar HSTS en el bucle de desarrollo ancla el navegador a HTTPS para el
    dominio y deja al desarrollador sin salida obvia."""
    assert "Strict-Transport-Security" not in _app_con_seguridad(app_env="development").get("/x").headers


def test_la_csp_se_puede_sobrescribir_por_argumento_y_por_entorno(monkeypatch):
    monkeypatch.delenv("SECURITY_CSP", raising=False)
    assert _resolve_csp(None) == DEFAULT_CSP
    assert _resolve_csp("default-src 'none'") == "default-src 'none'"

    monkeypatch.setenv("SECURITY_CSP", "default-src 'self' https://cdn.vendi.co")
    assert _resolve_csp(None) == "default-src 'self' https://cdn.vendi.co"
    # El argumento explícito gana sobre la variable de entorno.
    assert _resolve_csp("default-src 'none'") == "default-src 'none'"


def test_una_csp_de_solo_espacios_se_trata_como_ausente(monkeypatch):
    """`SECURITY_CSP=''` no puede acabar borrando la cabecera entera."""
    monkeypatch.setenv("SECURITY_CSP", "   ")
    assert _resolve_csp(None) == DEFAULT_CSP
    assert _resolve_csp("   ") == DEFAULT_CSP


def test_el_valor_de_hsts_es_de_un_ano_con_subdominios_y_sin_preload():
    """`preload` es un viaje de ida: se deja como opción del que despliega."""
    assert HSTS_VALUE == "max-age=31536000; includeSubDomains"
    assert "preload" not in HSTS_VALUE


# ---------------------------------------------------------------------------
# Redactor de secretos del cuerpo de respuesta
# ---------------------------------------------------------------------------


def _app_con_redactor() -> tuple[TestClient, dict]:
    """Devuelve el cliente y un diccionario donde un middleware de aguas abajo
    deposita lo que vería un logger de cuerpos de respuesta."""
    visto: dict = {}
    app = FastAPI()

    # El orden importa y es el mismo que en producción: el redactor va DENTRO
    # del logger de accesos. `add_middleware` apila hacia fuera, así que se
    # registra primero el redactor y después el logger, que queda por encima y
    # lee `request.state` cuando el redactor ya lo ha rellenado.
    app.add_middleware(SecretRedactorMiddleware)

    @app.middleware("http")
    async def _logger_falso(request, call_next):
        respuesta = await call_next(request)
        visto["redactado"] = getattr(request.state, "redacted_response_body", None)
        return respuesta

    @app.post("/cuentas")
    async def cuentas():
        return {"client_id": "publico", "client_secret": "SUPER-SECRETO"}

    @app.get("/sin-secretos")
    async def sin_secretos():
        return {"items": [1, 2, 3]}

    @app.get("/no-json")
    async def no_json():
        return JSONResponse(content="texto", media_type="text/plain")

    @app.get("/error")
    async def error():
        return JSONResponse({"client_secret": "no-deberia-mirarse"}, status_code=400)

    @app.get("/chorro")
    async def chorro():
        async def _gen():
            yield b'{"client_secret": "en-chorro"}'

        return StreamingResponse(_gen(), media_type="application/json")

    return TestClient(app), visto


def test_el_llamante_sigue_recibiendo_el_secreto_en_claro():
    """Es un endpoint de revelado único: el HTTP tiene que llevar el valor. Lo
    que el redactor evita es que acabe en los logs."""
    cliente, _ = _app_con_redactor()
    cuerpo = cliente.post("/cuentas").json()
    assert cuerpo["client_secret"] == "SUPER-SECRETO"


def test_el_cuerpo_redactado_queda_disponible_para_el_logger():
    cliente, visto = _app_con_redactor()
    cliente.post("/cuentas")
    assert visto["redactado"] == {"client_id": "publico", "client_secret": "***"}


def test_un_cuerpo_sin_secretos_no_se_redacta_ni_se_analiza():
    cliente, visto = _app_con_redactor()
    respuesta = cliente.get("/sin-secretos")
    assert respuesta.json() == {"items": [1, 2, 3]}
    assert visto["redactado"] is None


def test_una_respuesta_de_error_no_se_toca():
    """Los cuerpos de error no llevan credenciales recién acuñadas."""
    cliente, visto = _app_con_redactor()
    assert cliente.get("/error").status_code == 400
    assert visto["redactado"] is None


def test_una_respuesta_que_no_es_json_no_se_toca():
    cliente, visto = _app_con_redactor()
    cliente.get("/no-json")
    assert visto["redactado"] is None


def test_una_respuesta_en_chorro_pasa_intacta():
    """Bufferearla rompería el streaming y fijaría el cuerpo entero en memoria:
    exportaciones de negocio y CSV de auditoría van por aquí."""
    cliente, visto = _app_con_redactor()
    respuesta = cliente.get("/chorro")
    assert json.loads(respuesta.content) == {"client_secret": "en-chorro"}
    assert visto["redactado"] is None


def test_un_cuerpo_mayor_que_el_tope_no_se_bufferea(monkeypatch):
    """El tope existe para que el redactor no se convierta en una trampa de
    memoria con exportaciones grandes."""
    import vendi_core.middleware.secret_redactor as mod

    monkeypatch.setattr(mod, "SECRET_REDACTOR_MAX_BODY_BYTES", 10)
    cliente, visto = _app_con_redactor()
    cliente.post("/cuentas")
    assert visto["redactado"] is None
