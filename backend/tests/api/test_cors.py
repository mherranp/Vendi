"""CORS: un solo dueño, una sola lista de cabeceras, y nada de comodines.

Tres cosas distintas se prueban aquí, y conviene no confundirlas:

1. **Por defecto la aplicación NO gestiona CORS.** Lo termina Traefik. Si los
   dos lo hicieran, la respuesta saldría con `Access-Control-Allow-Origin`
   duplicada y el navegador la rechaza entera: las cuatro SPAs caerían con
   «CORS error» y sin un solo log en el backend.

2. **Cuando sí lo gestiona** (topologías sin ese borde delante), las cabeceras
   permitidas son una lista explícita. `["*"]` con `allow_credentials=True` es
   una combinación inválida: la especificación de Fetch obliga a comparar el
   `*` literalmente en peticiones con credenciales, así que el preflight de
   cualquier petición con `Authorization` fallaría.

3. **Las dos orillas del borde declaran la misma lista.** El test lee el
   template de Traefik y lo compara con la constante de Python. Es el único
   modo de que no se separen: son dos archivos, en dos lenguajes, que nadie
   edita a la vez.
"""

from __future__ import annotations

import re
from pathlib import Path

from ayudas import app_de_prueba, settings_de_prueba
from fastapi.testclient import TestClient

from app.factory import CABECERAS_CORS

RAIZ = Path(__file__).resolve().parents[3]
TEMPLATE_TRAEFIK = RAIZ / "infra" / "traefik" / "templates" / "dynamic.yml.tpl"


def _cabeceras_declaradas_en_traefik() -> list[str]:
    """Extrae `accessControlAllowHeaders` del template, sin dependencias YAML."""
    texto = TEMPLATE_TRAEFIK.read_text(encoding="utf-8")
    bloque = re.search(
        r"^(\s+)accessControlAllowHeaders:\s*\n((?:\1\s+-\s+.+\n)+)",
        texto,
        flags=re.MULTILINE,
    )
    assert bloque, f"no encontré accessControlAllowHeaders en {TEMPLATE_TRAEFIK}"
    return [linea.strip().lstrip("- ").strip().strip('"') for linea in bloque.group(2).splitlines() if linea.strip()]


def test_traefik_no_declara_el_comodin_de_cabeceras():
    cabeceras = _cabeceras_declaradas_en_traefik()
    assert "*" not in cabeceras, (
        "`accessControlAllowHeaders: ['*']` junto a `accessControlAllowCredentials: true` "
        "es inválido: con credenciales el `*` se compara literalmente y el preflight de "
        "toda petición con Authorization se rechaza en el navegador."
    )
    assert "Authorization" in cabeceras, "sin Authorization no hay petición autenticada que pase el preflight"


def test_las_dos_orillas_del_borde_declaran_la_misma_lista():
    assert sorted(_cabeceras_declaradas_en_traefik()) == sorted(CABECERAS_CORS), (
        "La lista de cabeceras de Traefik y la de app/factory.py han divergido. "
        "Son la misma superficie vista desde los dos lados del borde: cuando el "
        "despliegue no tiene Traefik delante, la que manda es la de Python."
    )


def test_sin_origenes_configurados_la_app_no_pone_cabeceras_de_cors():
    app, _, _ = app_de_prueba()
    respuesta = TestClient(app).get("/health", headers={"Origin": "https://app.vendi.co"})
    assert respuesta.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in respuesta.headers}


def test_con_origenes_configurados_el_preflight_acepta_authorization_y_no_devuelve_comodin():
    app, _, _ = app_de_prueba(settings_de_prueba(cors_origins="https://app.vendi.co"))
    respuesta = TestClient(app).options(
        "/health",
        headers={
            "Origin": "https://app.vendi.co",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-tenant-id",
        },
    )
    assert respuesta.status_code == 200
    permitidas = respuesta.headers["access-control-allow-headers"]
    assert "*" not in permitidas
    assert "Authorization" in permitidas
    assert "X-Tenant-Id" in permitidas
    assert respuesta.headers["access-control-allow-credentials"] == "true"
