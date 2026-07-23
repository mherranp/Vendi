"""Configuración de logging: salida JSON vs consola y silenciado de ruidosos.

`vendi_core.logging.setup` viene de `base_saas.logging.setup`. BaseSaaS no lo
cubría; se escribe aquí porque el módulo hace tres cosas globales e
irreversibles dentro del proceso (reemplaza los handlers del logger raíz,
reconfigura structlog y baja el nivel de tres loggers), y un fallo en cualquiera
de ellas se manifiesta como "los logs de producción no salen en JSON" — algo que
nadie descubre hasta que hace falta buscar en ellos.

Cada test restaura la configuración global al salir: dejar structlog o el logger
raíz tocados contaminaría al resto de la suite.
"""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from vendi_core.logging.setup import setup_logging


@pytest.fixture(autouse=True)
def restaurar_configuracion_global():
    raiz = logging.getLogger()
    handlers_previos = list(raiz.handlers)
    nivel_previo = raiz.level
    niveles_previos = {n: logging.getLogger(n).level for n in ("uvicorn.access", "sqlalchemy.engine", "httpx")}
    yield
    raiz.handlers.clear()
    for h in handlers_previos:
        raiz.addHandler(h)
    raiz.setLevel(nivel_previo)
    for nombre, nivel in niveles_previos.items():
        logging.getLogger(nombre).setLevel(nivel)
    structlog.reset_defaults()


def test_instala_un_unico_handler_en_el_logger_raiz():
    """Se limpian los handlers previos: sin eso, llamar dos veces (arranque de
    la app + arranque del worker en el mismo proceso) duplica cada línea."""
    raiz = logging.getLogger()
    raiz.addHandler(logging.NullHandler())

    setup_logging()
    assert len(raiz.handlers) == 1

    setup_logging()
    assert len(raiz.handlers) == 1


def test_el_nivel_se_toma_del_argumento_sin_distinguir_mayusculas():
    setup_logging(level="debug")
    assert logging.getLogger().level == logging.DEBUG
    setup_logging(level="WARNING")
    assert logging.getLogger().level == logging.WARNING


def test_un_nivel_invalido_cae_a_info_en_vez_de_reventar():
    """Una errata en una variable de entorno no puede impedir que el proceso
    arranque."""
    setup_logging(level="ruidosisimo")
    assert logging.getLogger().level == logging.INFO


def test_los_loggers_ruidosos_quedan_en_warning():
    setup_logging(level="DEBUG")
    for nombre in ("uvicorn.access", "sqlalchemy.engine", "httpx"):
        assert logging.getLogger(nombre).level == logging.WARNING, nombre


def test_con_json_output_la_linea_es_json_valido(capsys):
    setup_logging(level="INFO", json_output=True)
    structlog.get_logger("prueba").info("evento_de_prueba", negocio="acme", total=7)

    salida = capsys.readouterr().out.strip().splitlines()[-1]
    registro = json.loads(salida)
    assert registro["event"] == "evento_de_prueba"
    assert registro["negocio"] == "acme"
    assert registro["total"] == 7
    assert registro["level"] == "info"


def test_sin_json_output_la_linea_es_legible_y_no_json(capsys):
    setup_logging(level="INFO", json_output=False)
    structlog.get_logger("prueba").info("evento_de_prueba", negocio="acme")

    salida = capsys.readouterr().out
    assert "evento_de_prueba" in salida
    with pytest.raises(json.JSONDecodeError):
        json.loads(salida.strip().splitlines()[-1])
