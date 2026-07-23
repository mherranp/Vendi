"""`/metrics` no es alcanzable sin credenciales. Ni en la app, ni por el borde.

El agujero que cierra este archivo: `/metrics` estaba en `RUTAS_PUBLICAS` de
`TenantMiddleware` mientras no había endpoint que montar. Al montarlo, y como el
router `api` de Traefik enruta por `Host` y no por path, la exposición de
Prometheus habría quedado servida en `https://api.<dominio>/metrics` sin
credencial ninguna: el mapa de rutas internas, los contadores de error por
endpoint y —en cuanto haya métricas por negocio— identificadores de negocio.

Dos capas, y las dos se prueban:

1. **La aplicación** exige `Authorization: Bearer <METRICS_TOKEN>` (este
   archivo, tests unitarios).
2. **El borde** responde 403 a `PathPrefix(/metrics)` en el host de la API
   (`test_metrics_por_el_dominio`, marcado `integration`, contra el stack
   levantado y a través de Traefik).
"""

from __future__ import annotations

import os
import subprocess

import pytest
from ayudas import TOKEN_METRICAS, app_de_prueba, settings_de_prueba
from fastapi.testclient import TestClient

BASE_DOMAIN = os.getenv("BASE_DOMAIN", "vendi.co")


def test_sin_credencial_da_401(app_sin_base):
    cliente, _, _ = app_sin_base
    respuesta = cliente.get("/metrics")
    assert respuesta.status_code == 401
    assert respuesta.json()["code"] == "credencial_de_metricas_invalida"


def test_con_un_jwt_de_usuario_tampoco_se_entra(app_sin_base):
    """Un token de sesión no vale: la credencial de métricas es otra cosa.

    Importa porque el camino fácil habría sido aceptar cualquier bearer válido,
    y entonces cualquier usuario de cualquier negocio podría leer la telemetría
    de toda la región.
    """
    from ayudas import usuario_de_plataforma

    cliente, validador, _ = app_sin_base
    validador.registrar("token-de-admin", usuario_de_plataforma())
    respuesta = cliente.get("/metrics", headers={"Authorization": "Bearer token-de-admin"})
    assert respuesta.status_code == 401


def test_con_una_credencial_equivocada_da_401(app_sin_base):
    cliente, _, _ = app_sin_base
    respuesta = cliente.get("/metrics", headers={"Authorization": "Bearer no-es-esa"})
    assert respuesta.status_code == 401


def test_con_la_credencial_correcta_sirve_el_texto_de_prometheus(app_sin_base):
    cliente, _, _ = app_sin_base
    respuesta = cliente.get("/metrics", headers={"Authorization": f"Bearer {TOKEN_METRICAS}"})
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/plain")
    # `python_info` lo publica siempre el cliente de Prometheus: si esto está,
    # el registro se serializó de verdad y no es una respuesta vacía.
    assert "python_info" in respuesta.text


def test_sin_METRICS_TOKEN_configurado_la_ruta_se_cierra_no_se_abre():
    """Falla CERRADO. El modo en que estas protecciones desaparecen sin que
    nadie lo note es «si no hay token, no pido token»: todo sigue funcionando y
    el único síntoma es que ya no protege nada."""
    aplicacion, _, _ = app_de_prueba(settings_de_prueba(metrics_token=""))
    with TestClient(aplicacion, raise_server_exceptions=False) as cliente:
        respuesta = cliente.get("/metrics")
    assert respuesta.status_code == 503
    assert respuesta.json()["code"] == "metricas_no_configuradas"


def test_metrics_no_esta_en_rutas_publicas():
    """El candado sobre la constante, no solo sobre el comportamiento.

    Si alguien devuelve `/metrics` a `RUTAS_PUBLICAS` el endpoint seguiría
    pidiendo su credencial (la comprueba el handler), pero el nombre del
    conjunto estaría mintiendo y el siguiente que lea la lista concluirá que la
    ruta es pública. Los dos conjuntos existen para poder decir la verdad.
    """
    from vendi_core.tenant.middleware import RUTAS_CON_CREDENCIAL_PROPIA, RUTAS_PUBLICAS

    assert "/metrics" not in RUTAS_PUBLICAS
    assert "/metrics" in RUTAS_CON_CREDENCIAL_PROPIA


@pytest.mark.integration
def test_metrics_por_el_dominio_lo_bloquea_traefik():
    """Contra el stack levantado, por el dominio y con el certificado del sistema.

    `--resolve` fija la resolución a 127.0.0.1 sin aflojar nada más: el
    hostname, el SNI, la cabecera `Host`, el enrutado por `Host()` de Traefik y
    la validación completa del certificado siguen siendo los reales. Es
    obligatorio aquí porque `vendi.co` es un dominio registrado por un tercero y
    sin el resolver del sistema el nombre sale a Internet.
    """
    url = f"https://api.{BASE_DOMAIN}/metrics"
    resultado = subprocess.run(
        [
            "curl",
            "-s",
            "--resolve",
            f"api.{BASE_DOMAIN}:443:127.0.0.1",
            "--connect-timeout",
            "3",
            "--max-time",
            "8",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    codigo = resultado.stdout.strip()
    if codigo == "000":
        pytest.fail(f"No se pudo conectar con {url}: ¿está el stack levantado? (docker compose ps)")
    assert codigo == "403", (
        f"{url} devolvió {codigo}: la exposición de Prometheus tiene que quedar "
        "fuera del perímetro. El router `api-metrics-bloqueado` de Traefik es la "
        "primera capa; la credencial de la aplicación es la segunda."
    )
