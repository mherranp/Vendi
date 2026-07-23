"""Conexión a RabbitMQ con backoff, y el hueco que deja mientras no la hay.

El worker **no puede** morir porque RabbitMQ tarde en levantar: en el compose
los dos arrancan a la vez y en producción un reinicio del bus no debe llevarse
por delante al worker. Pero tampoco puede reintentar en bucle cerrado: eso es un
crash-loop disfrazado, con el log lleno de la misma línea y sin que nadie note
que el sistema lleva horas sin publicar nada.

Así que: reintento con backoff exponencial acotado, un log por intento con el
número de intento y la espera, y una métrica
(`vendi_worker_broker_reconexiones_total`) para poder alertar sobre "lleva N
minutos sin conectar" en vez de tener que leer logs.

Mientras no hay conexión, el dispatcher **no drena**: los mensajes se quedan en
`outbox_messages` con `status='pending'`, que es justo lo que el patrón outbox
existe para garantizar. No se pierde nada; se retrasa.
"""

from __future__ import annotations

import asyncio

import structlog
from prometheus_client import Counter, Gauge

from vendi_core.messaging.publisher import EventPublisher

logger = structlog.get_logger()

broker_reconexiones = Counter(
    "vendi_worker_broker_reconexiones_total",
    "Intentos de (re)conexión del worker con RabbitMQ, por resultado.",
    labelnames=("resultado",),
)

broker_conectado = Gauge(
    "vendi_worker_broker_conectado",
    "1 si el worker tiene conexión con RabbitMQ, 0 si no.",
)


async def conectar_con_backoff(
    url: str,
    parada: asyncio.Event,
    *,
    backoff_max: float = 30.0,
) -> EventPublisher | None:
    """Conecta reintentando hasta lograrlo o hasta que se pida la parada.

    Devuelve `None` si se pidió parar antes de conseguir conexión — el llamante
    tiene que tratarlo como "apagando", no como error.
    """
    espera = 1.0
    intento = 0
    while not parada.is_set():
        intento += 1
        try:
            publicador = await EventPublisher.connect(url)
        except Exception as exc:  # noqa: BLE001
            broker_reconexiones.labels(resultado="fallo").inc()
            broker_conectado.set(0)
            logger.warning(
                "rabbitmq_no_disponible",
                intento=intento,
                espera_s=espera,
                error=str(exc),
            )
            try:
                await asyncio.wait_for(parada.wait(), timeout=espera)
                return None  # se pidió parar durante la espera
            except TimeoutError:
                espera = min(espera * 2, backoff_max)
                continue
        broker_reconexiones.labels(resultado="exito").inc()
        broker_conectado.set(1)
        logger.info("rabbitmq_conectado", intento=intento)
        return publicador
    return None
