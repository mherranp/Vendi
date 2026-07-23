"""El worker tiene que salir limpio con SIGTERM.

Se prueba de dos formas porque cubren cosas distintas:

1. `test_bucle_latido_para_con_el_evento`: unitaria, rápida, sin subprocesos.
2. `test_proceso_sale_con_codigo_0_ante_sigterm`: arranca `python -m worker` de
   verdad y le manda SIGTERM. Es la que demuestra que el manejador de señales
   está registrado en el event loop, cosa que la unitaria no ve.

El subproceso arranca **sin RabbitMQ y con un DSN que no conecta**, a propósito:
lo que se mide es el apagado, y un worker que solo sabe apagarse cuando todas
sus dependencias están arriba no sabe apagarse. `create_engine` no abre conexión
hasta la primera consulta, y sin `RABBITMQ_URL` el dispatcher no arranca; así el
proceso queda en el estado que interesa —bucle de latido y planificador
corriendo— sin depender de nada externo.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from worker.__main__ import bucle_latido

RAIZ_WORKER = Path(__file__).resolve().parents[1] / "services" / "worker"


def _puerto_libre() -> int:
    """Puerto efímero para el servidor de métricas del subproceso.

    Fijar 9090 haría que este test fallara cuando el worker del compose ya lo
    tiene ocupado, y ese fallo no diría nada sobre el apagado.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _entorno(tmp_path, **extra) -> dict:
    base = {
        **os.environ,
        "WORKER_HEARTBEAT_FILE": str(tmp_path / "latido"),
        "PLATFORM_DATABASE_URL": "postgresql+asyncpg://nadie:nada@127.0.0.1:1/inexistente",
        "RABBITMQ_URL": "",
        "MINIO_ENDPOINT": "",
        "METRICS_PORT": str(_puerto_libre()),
        "LOG_JSON": "false",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
    }
    base.update(extra)
    return base


async def test_bucle_latido_para_con_el_evento(tmp_path):
    parada = asyncio.Event()
    latido = tmp_path / "latido"
    tarea = asyncio.create_task(bucle_latido(parada, intervalo=5.0, archivo_latido=latido))
    await asyncio.sleep(0.05)
    parada.set()
    # Si el bucle esperase con asyncio.sleep(intervalo) en vez de sobre el
    # evento, este await se comería los 5 segundos y el test daría timeout.
    await asyncio.wait_for(tarea, timeout=1.0)
    # El healthcheck del compose depende de este archivo: si deja de
    # escribirse, el contenedor se marca unhealthy.
    assert latido.exists(), "el bucle no escribió el archivo de latido"


def test_proceso_sale_con_codigo_0_ante_sigterm(tmp_path):
    proceso = subprocess.Popen(
        [sys.executable, "-m", "worker"],
        cwd=str(RAIZ_WORKER),
        env=_entorno(tmp_path, WORKER_HEARTBEAT_SECONDS="60"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Darle tiempo a instalar los manejadores antes de señalarlo.
        time.sleep(2.0)
        assert proceso.poll() is None, "el worker murió solo antes del SIGTERM"
        proceso.send_signal(signal.SIGTERM)
        salida = proceso.communicate(timeout=15)[0]
    except subprocess.TimeoutExpired:  # pragma: no cover - solo si hay regresión
        proceso.kill()
        raise AssertionError("el worker no atendió SIGTERM en 15 s") from None
    assert proceso.returncode == 0, f"código de salida {proceso.returncode}; salida:\n{salida}"
    assert "worker_detenido_limpiamente" in salida, f"salida:\n{salida}"


def test_el_worker_arranca_sin_rabbitmq_y_reintenta_con_backoff(tmp_path):
    """RabbitMQ caído no puede impedir que el worker exista.

    El outbox es durable: los mensajes se quedan en `pending` y se drenan cuando
    el bus vuelva. Lo que NO puede pasar es que el worker muera y deje de latir,
    porque entonces tampoco corren los trabajos programados ni la retención — y
    tampoco puede reintentar en bucle cerrado, que es un crash-loop disfrazado
    con el log lleno de la misma línea.
    """
    proceso = subprocess.Popen(
        [sys.executable, "-m", "worker"],
        cwd=str(RAIZ_WORKER),
        env=_entorno(
            tmp_path,
            WORKER_HEARTBEAT_SECONDS="1",
            # Puerto cerrado a propósito: es el caso "el bus no está".
            RABBITMQ_URL="amqp://vendi:vendi@127.0.0.1:1/",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        time.sleep(5.0)
        assert proceso.poll() is None, "el worker entró en crash-loop porque RabbitMQ no responde"
        assert (tmp_path / "latido").exists(), (
            "sin RabbitMQ el worker dejó de latir: el healthcheck lo daría por muerto"
        )
        proceso.send_signal(signal.SIGTERM)
        salida = proceso.communicate(timeout=15)[0]
    except subprocess.TimeoutExpired:  # pragma: no cover
        proceso.kill()
        raise AssertionError("el worker no atendió SIGTERM con RabbitMQ caído") from None
    assert proceso.returncode == 0, f"código de salida {proceso.returncode}; salida:\n{salida}"
    # Con backoff (1, 2, 4, 8… segundos) caben pocos intentos en cinco
    # segundos. Sin backoff habría centenares de líneas.
    intentos = salida.count("rabbitmq_no_disponible")
    assert 1 <= intentos <= 5, f"reintentos sin backoff ({intentos} en 5 s):\n{salida}"
