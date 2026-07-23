"""El worker tiene que salir limpio con SIGTERM (tarea 2.1).

Se prueba de dos formas porque cubren cosas distintas:

1. `test_bucle_latido_para_con_el_evento`: unitaria, rápida, sin subprocesos.
2. `test_proceso_sale_con_codigo_0_ante_sigterm`: arranca `python -m worker` de
   verdad y le manda SIGTERM. Es la que demuestra que el manejador de señales
   está registrado en el event loop, cosa que la unitaria no ve.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from worker.__main__ import bucle_latido

RAIZ_WORKER = Path(__file__).resolve().parents[1] / "services" / "worker"


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
    entorno = {
        **os.environ,
        "WORKER_HEARTBEAT_SECONDS": "60",
        "WORKER_HEARTBEAT_FILE": str(tmp_path / "latido"),
    }
    proceso = subprocess.Popen(
        [sys.executable, "-m", "worker"],
        cwd=str(RAIZ_WORKER),
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Darle tiempo a instalar los manejadores antes de señalarlo.
        time.sleep(1.5)
        assert proceso.poll() is None, "el worker murió solo antes del SIGTERM"
        proceso.send_signal(signal.SIGTERM)
        salida = proceso.communicate(timeout=10)[0]
    except subprocess.TimeoutExpired:  # pragma: no cover - solo si hay regresión
        proceso.kill()
        raise AssertionError("el worker no atendió SIGTERM en 10 s") from None
    assert proceso.returncode == 0, f"código de salida {proceso.returncode}; salida:\n{salida}"
    assert "worker detenido limpiamente" in salida
