"""Bucle principal del worker de Vendi.

Ejecutar con: ``python -m worker``

Contrato de apagado (importa para el compose y para Kubernetes el día que
llegue): ante SIGTERM o SIGINT el bucle termina la iteración en curso, sale del
`while` y el proceso devuelve código 0. Nada de matar tareas a mitad ni de
dejar que `docker stop` tenga que recurrir a SIGKILL a los 10 segundos.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("vendi.worker")

# Segundos entre latidos. Configurable para que los tests no esperen 30 s.
INTERVALO_LATIDO = float(os.environ.get("WORKER_HEARTBEAT_SECONDS", "30"))

# Archivo que se toca en cada latido. Es lo que mira el healthcheck del
# compose: comprueba que el BUCLE avanza, no solo que el proceso existe (un
# proceso colgado en un await eterno seguiría "vivo" para Docker).
ARCHIVO_LATIDO = Path(os.environ.get("WORKER_HEARTBEAT_FILE", "/tmp/vendi-worker-latido"))


def _tocar_latido(ruta: Path) -> None:
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("ok\n", encoding="utf-8")
    except OSError as exc:  # pragma: no cover - solo si el FS es de solo lectura
        # No es motivo para tumbar el worker: se degrada a "sin sonda".
        log.warning("no se pudo escribir el archivo de latido %s: %s", ruta, exc)


async def bucle_latido(
    parada: asyncio.Event,
    intervalo: float = INTERVALO_LATIDO,
    archivo_latido: Path = ARCHIVO_LATIDO,
) -> None:
    """Loguea un latido cada `intervalo` segundos hasta que se pide la parada.

    La espera se hace sobre el evento de parada (no con `asyncio.sleep`) para
    que el apagado sea inmediato en vez de tardar hasta un intervalo completo.
    """
    while not parada.is_set():
        log.info("latido del worker (aún sin dispatcher ni scheduler: llegan en la tarea 4.3)")
        _tocar_latido(archivo_latido)
        try:
            await asyncio.wait_for(parada.wait(), timeout=intervalo)
        except TimeoutError:
            # Se agotó el intervalo sin señal de parada: toca otro latido.
            continue


def _instalar_manejadores(parada: asyncio.Event) -> None:
    """Registra SIGTERM/SIGINT en el event loop para que activen la parada.

    `loop.add_signal_handler` no existe en Windows; el fallback con
    `signal.signal` mantiene el script ejecutable ahí para desarrollo, aunque
    el despliegue real sea Linux.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, parada.set)
        except NotImplementedError:  # pragma: no cover - solo Windows
            signal.signal(sig, lambda *_: parada.set())


async def main() -> int:
    parada = asyncio.Event()
    _instalar_manejadores(parada)
    log.info(
        "worker arrancado (intervalo de latido: %ss, archivo: %s)",
        INTERVALO_LATIDO,
        ARCHIVO_LATIDO,
    )
    await bucle_latido(parada)
    log.info("worker detenido limpiamente")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
