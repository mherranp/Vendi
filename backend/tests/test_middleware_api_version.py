"""`APIVersionMiddleware`: cabecera de versión y avisos de deprecación.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_api_version_middleware.py`.
Adaptación: `base_saas` → `vendi_core`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vendi_core.middleware.api_version import APIVersionMiddleware


def _cliente(version: str = "v1", deprecadas: dict[str, str] | None = None) -> TestClient:
    app = FastAPI()
    app.add_middleware(APIVersionMiddleware, version=version, deprecated_routes=deprecadas)

    @app.get("/api/v1/sano")
    async def sano() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/usuarios/antiguo")
    async def antiguo() -> dict[str, str]:
        return {"sabor": "antiguo"}

    @app.get("/api/v1/usuarios")
    async def usuarios() -> dict[str, str]:
        return {"sabor": "actual"}

    return TestClient(app)


def test_sella_x_api_version_en_toda_respuesta() -> None:
    respuesta = _cliente(version="v1").get("/api/v1/sano")
    assert respuesta.status_code == 200
    assert respuesta.headers["X-API-Version"] == "v1"


def test_no_pisa_la_cabecera_de_version_que_ponga_el_handler() -> None:
    """El middleware usa `setdefault`: si un router futuro escribe su propia
    versión, la suya manda."""
    app = FastAPI()
    app.add_middleware(APIVersionMiddleware, version="v1")

    @app.get("/api/v2/cosas")
    async def cosas():
        from fastapi.responses import JSONResponse

        return JSONResponse({}, headers={"X-API-Version": "v2"})

    assert TestClient(app).get("/api/v2/cosas").headers["X-API-Version"] == "v2"


def test_sin_deprecacion_no_hay_cabeceras_de_deprecacion() -> None:
    respuesta = _cliente(deprecadas={"/api/v1/usuarios/antiguo": "2027-01-01"}).get("/api/v1/sano")
    assert "Deprecation" not in respuesta.headers
    assert "Sunset" not in respuesta.headers


def test_emite_deprecation_y_sunset_en_el_prefijo_que_coincide() -> None:
    respuesta = _cliente(deprecadas={"/api/v1/usuarios/antiguo": "2027-01-01"}).get("/api/v1/usuarios/antiguo")
    assert respuesta.headers["Deprecation"] == "true"
    # `Sunset` va en HTTP-date (IMF-fixdate), no en ISO.
    assert respuesta.headers["Sunset"] == "Fri, 01 Jan 2027 00:00:00 GMT"


def test_gana_el_prefijo_mas_especifico_cuando_se_solapan() -> None:
    cliente = _cliente(
        deprecadas={
            "/api/v1/usuarios": "2028-06-30",
            "/api/v1/usuarios/antiguo": "2027-01-01",
        }
    )
    assert cliente.get("/api/v1/usuarios/antiguo").headers["Sunset"] == "Fri, 01 Jan 2027 00:00:00 GMT"
    assert cliente.get("/api/v1/usuarios").headers["Sunset"] == "Fri, 30 Jun 2028 00:00:00 GMT"


def test_una_fecha_iso_mal_escrita_falla_al_cablear_y_no_en_produccion() -> None:
    """Pillar la errata al montar la app es mucho más amable que servir una
    cabecera `Sunset` malformada en cada respuesta de producción."""
    app = FastAPI()
    with pytest.raises(ValueError):
        app.add_middleware(APIVersionMiddleware, deprecated_routes={"/api/v1/x": "no-es-una-fecha"})
        TestClient(app).get("/")  # el middleware se construye en diferido; se fuerza
