"""Bucle principal del worker de Vendi.

Ejecutar con: ``python -m worker``

Tres tareas concurrentes sobre la **sesión de plataforma** y un latido:

1. `OutboxDispatcher` — drena `outbox_messages` hacia RabbitMQ. Cross-tenant por
   definición: vacía la cola de todos los negocios en una pasada, que es
   exactamente por lo que `outbox_messages` no lleva la policy de aislamiento.
2. `JobScheduler` — cron en proceso. Recibe `list_active_tenant_ids` inyectado
   (ver `worker.tenants`): sin él los trabajos con `scope="tenant"` no disparan
   para nadie.
3. `RetentionRunner` — lo dispara el planificador como un trabajo más, en vez de
   correr su propio bucle horario. Un solo reloj en el proceso significa una
   sola cosa que ajustar y una sola fila de auditoría por pasada.

Y el latido, que es lo que mira el healthcheck del compose: comprueba que el
BUCLE avanza, no solo que el proceso existe (un proceso colgado en un `await`
eterno seguiría "vivo" para Docker).

## Contrato de apagado

Ante SIGTERM o SIGINT: se activa el evento de parada, las tres tareas terminan
lo que estén haciendo, se cierran conexión y engine, y el proceso devuelve 0.
Nada de matar tareas a mitad ni de dejar que `docker stop` tenga que recurrir a
SIGKILL a los 10 segundos.

Qué pasa si el worker muere a mitad de un lote del outbox: nada que se pierda.
Los mensajes publicados quedaron marcados `processed` y los demás siguen
`pending`; al reiniciar se retoman. La garantía es **al menos una vez**, no
exactamente una: si el proceso cae entre `publish` y el `UPDATE`, ese mensaje se
publica dos veces. Por eso el sobre de `DomainEventService` lleva un `id` único
por evento — es la clave de idempotencia para el consumidor.

## Por qué el rol es `vendi_platform` y no `vendi_app`

Con `vendi_app` (sin `BYPASSRLS`) el dispatcher vería cero filas en el outbox y
la retención no tendría privilegios sobre las tablas de plataforma. No fallaría:
haría nada, en silencio, porque cero filas no es un error.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from pathlib import Path

import structlog
from prometheus_client import start_http_server

from vendi_core.db.engine import create_engine, dispose_engine
from vendi_core.db.session import create_platform_session_factory
from vendi_core.files.retention import make_storage_cleanup_hook
from vendi_core.jobs.scheduler import JobScheduler
from vendi_core.logging.setup import setup_logging
from vendi_core.messaging.outbox import OutboxDispatcher
from vendi_core.retention.runner import RetentionRunner
from vendi_core.storage.factory import create_storage
from vendi_core.tracing.otel import configure_tracing
from worker.jobs import construir_jobs
from worker.publicador import conectar_con_backoff
from worker.settings import Settings, cargar_settings
from worker.tenants import lector_de_negocios_activos

log = structlog.get_logger("vendi.worker")


def _tocar_latido(ruta: Path) -> None:
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("ok\n", encoding="utf-8")
    except OSError as exc:  # pragma: no cover - solo si el FS es de solo lectura
        # No es motivo para tumbar el worker: se degrada a "sin sonda".
        log.warning("no_se_pudo_escribir_el_latido", ruta=str(ruta), error=str(exc))


async def bucle_latido(parada: asyncio.Event, intervalo: float, archivo_latido: Path) -> None:
    """Toca el archivo de latido cada `intervalo` segundos hasta la parada.

    La espera se hace sobre el evento de parada (no con `asyncio.sleep`) para
    que el apagado sea inmediato en vez de tardar hasta un intervalo completo.
    """
    while not parada.is_set():
        _tocar_latido(archivo_latido)
        try:
            await asyncio.wait_for(parada.wait(), timeout=intervalo)
        except TimeoutError:
            continue


def _instalar_manejadores(parada: asyncio.Event) -> None:
    """Registra SIGTERM/SIGINT en el event loop para que activen la parada.

    `loop.add_signal_handler` no existe en Windows; el fallback con
    `signal.signal` mantiene el script ejecutable ahí para desarrollo, aunque el
    despliegue real sea Linux.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, parada.set)
        except NotImplementedError:  # pragma: no cover - solo Windows
            signal.signal(sig, lambda *_: parada.set())


def _hooks_de_purga(settings: Settings) -> dict:
    """Hook de limpieza de objetos para la política de `files`, si hay almacén.

    Sin él, purgar la fila de un archivo deja el objeto en el bucket para
    siempre: una fuga de almacenamiento que nadie ve porque no hay ninguna fila
    que la señale.
    """
    if not settings.minio_endpoint:
        log.warning(
            "retencion_sin_hook_de_almacenamiento",
            motivo="MINIO_ENDPOINT no configurado; las filas de `files` se purgan pero los objetos quedan",
        )
        return {}
    almacen = create_storage(
        provider=settings.storage_provider,
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.storage_secure,
    )
    return {"files": make_storage_cleanup_hook(almacen)}


async def ejecutar(settings: Settings, parada: asyncio.Event) -> int:
    """Cablea y corre. Separado de `main` para poder ejercerlo desde un test."""
    engine = create_engine(settings.platform_database_url)
    sesion_plataforma = create_platform_session_factory(engine)
    listar_negocios = lector_de_negocios_activos(sesion_plataforma)

    if settings.otel_exporter_otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otel_exporter_otlp_endpoint,
            app_env=settings.app_env,
            engine=engine,
        )

    retencion = RetentionRunner(
        session_factory=sesion_plataforma,
        hour_utc=settings.retention_hour_utc,
        service_name=settings.service_name,
        pre_purge_hooks=_hooks_de_purga(settings),
        # Sin esto, las políticas de tenant se omiten y solo se purgan las
        # tablas de plataforma. Queda en el log como `retention_sin_lista_de_tenants`.
        list_active_tenant_ids=listar_negocios,
    )
    planificador = JobScheduler(
        session_factory=sesion_plataforma,
        engine=engine,
        jobs=construir_jobs(retencion),
        service_name=settings.service_name,
        list_active_tenant_ids=listar_negocios,
    )

    publicador = None
    dispatcher: OutboxDispatcher | None = None
    tareas: list[asyncio.Task] = []
    try:
        tareas.append(
            asyncio.create_task(
                bucle_latido(parada, settings.worker_heartbeat_seconds, Path(settings.worker_heartbeat_file)),
                name="latido",
            )
        )
        tareas.append(asyncio.create_task(planificador.run(parada), name="planificador"))

        if settings.rabbitmq_url:
            publicador = await conectar_con_backoff(
                settings.rabbitmq_url, parada, backoff_max=settings.rabbitmq_backoff_max
            )
        else:
            log.warning("worker_sin_rabbitmq", motivo="RABBITMQ_URL vacío; el outbox no se drena")

        if publicador is not None:
            dispatcher = OutboxDispatcher(
                session_factory=sesion_plataforma,
                publisher=publicador,
                poll_interval=settings.outbox_poll_interval,
                batch_size=settings.outbox_batch_size,
                max_retries=settings.outbox_max_retries,
            )
            tareas.append(asyncio.create_task(dispatcher.run(), name="outbox"))

        log.info("worker_arrancado", tareas=[t.get_name() for t in tareas])
        await parada.wait()
    finally:
        log.info("worker_deteniendose")
        if dispatcher is not None:
            dispatcher.stop()
        for tarea in tareas:
            tarea.cancel()
        # `gather` con `return_exceptions`: una tarea que reviente al cancelarse
        # no puede impedir que se cierren la conexión y el engine.
        await asyncio.gather(*tareas, return_exceptions=True)
        if publicador is not None:
            with contextlib.suppress(Exception):
                await publicador.close()
        await dispose_engine(engine)
        log.info("worker_detenido_limpiamente")
    return 0


async def main() -> int:
    settings = cargar_settings()
    setup_logging(level=settings.log_level, json_output=settings.log_json)
    # Servidor lateral de métricas. Lo raspa Prometheus por `worker:9090` desde
    # dentro de la red del compose; ese puerto no lo enruta Traefik y no sale al
    # exterior, por eso —a diferencia del `/metrics` de la API— no lleva
    # credencial propia.
    try:
        start_http_server(settings.metrics_port)
    except OSError as exc:
        # Puerto ocupado no es motivo para no procesar la cola.
        log.warning("metricas_no_publicadas", puerto=settings.metrics_port, error=str(exc))

    parada = asyncio.Event()
    _instalar_manejadores(parada)
    return await ejecutar(settings, parada)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
