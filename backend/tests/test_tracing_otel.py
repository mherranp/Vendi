"""Trazado OpenTelemetry: opt-in y coste cero cuando está apagado.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_otel_optin.py` (la
mitad de `configure_tracing`; la mitad de la fusión con `traceparent` está en
`test_middleware_http.py`). Adaptación: `base_saas` → `vendi_core`.

Lo que importa aquí es la semántica de opt-in: sin endpoint OTLP no se instala
`TracerProvider`, no se cablea ningún instrumentador y ni siquiera se importa el
árbol de paquetes de `opentelemetry`. Un fallo en esa rama no se nota —todo
sigue funcionando— salvo en el arranque de cada servicio, cada vez.
"""

from __future__ import annotations

from unittest.mock import patch

from vendi_core.tracing.otel import configure_tracing, otlp_endpoint_from_env


def test_sin_endpoint_no_se_configura_nada():
    assert configure_tracing("svc", otlp_endpoint="") is False
    assert configure_tracing("svc", otlp_endpoint=None) is False


def test_un_endpoint_de_solo_espacios_cuenta_como_vacio():
    """Defensa contra `OTEL_EXPORTER_OTLP_ENDPOINT=" "` colándose por una
    sustitución `${VAR:-}` en un compose."""
    assert configure_tracing("svc", otlp_endpoint="   ") is False


def test_con_endpoint_se_instala_el_proveedor_y_los_instrumentadores():
    from fastapi import FastAPI
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    # Se doblan los instrumentadores para no mutar el estado global de FastAPI
    # y HTTPX en el resto de la suite. Lo que se comprueba es que
    # `configure_tracing` los INTENTA cablear.
    with (
        patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app") as fastapi_doblado,
        patch("opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor.instrument") as httpx_doblado,
    ):
        app = FastAPI()
        ok = configure_tracing(
            service_name="servicio-de-prueba",
            otlp_endpoint="http://localhost:4318/v1/traces",
            app_env="test",
            app=app,
            service_version="9.9.9",
        )

    assert ok is True
    assert isinstance(trace.get_tracer_provider(), TracerProvider)
    fastapi_doblado.assert_called_once_with(app)
    httpx_doblado.assert_called_once()


def test_sin_app_no_se_instrumenta_fastapi():
    """El worker no tiene app de FastAPI y aun así quiere spans de SQLAlchemy
    y HTTPX."""
    with (
        patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app") as fastapi_doblado,
        patch("opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor.instrument"),
    ):
        ok = configure_tracing(
            service_name="worker",
            otlp_endpoint="http://localhost:4318/v1/traces",
            app=None,
        )
    assert ok is True
    fastapi_doblado.assert_not_called()


def test_con_engine_se_instrumenta_el_engine_sincrono_subyacente():
    """El instrumentador de SQLAlchemy engancha el engine síncrono; un
    `AsyncEngine` lo expone en `.sync_engine`."""

    class _EngineFalso:
        sync_engine = object()

    engine = _EngineFalso()
    with (
        patch("opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor.instrument"),
        patch("opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor.instrument") as sa_doblado,
    ):
        ok = configure_tracing(
            service_name="api",
            otlp_endpoint="http://localhost:4318/v1/traces",
            engine=engine,
        )
    assert ok is True
    sa_doblado.assert_called_once_with(engine=engine.sync_engine)


def test_el_endpoint_se_lee_de_la_variable_canonica(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert otlp_endpoint_from_env() == ""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "  http://jaeger:4318/v1/traces  ")
    assert otlp_endpoint_from_env() == "http://jaeger:4318/v1/traces"
