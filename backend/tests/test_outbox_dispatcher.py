"""Dispatcher del outbox y publicador de RabbitMQ.

`vendi_core.messaging` viene de `base_saas.messaging`. El encolado desde el rol
de la API se prueba en `test_outbox_transaccional.py`, contra Postgres; aquí se
prueba el drenado, que es la otra mitad del patrón y la que decide si un evento
se publica una vez, se reintenta o se abandona.

Se dobla la sesión y el publicador: lo que se está probando es la máquina de
estados (`pending` → `processed` / `failed`), no SQLAlchemy ni aio_pika.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from vendi_core.messaging.outbox import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROCESSED,
    OutboxDispatcher,
    OutboxMessage,
)
from vendi_core.messaging.publisher import EventPublisher


class _SesionDoblada:
    """Sesión mínima: devuelve un lote fijo en el primer `execute` de SELECT y
    apunta los UPDATE que se emiten después."""

    def __init__(self, mensajes: list[OutboxMessage]):
        self._mensajes = mensajes
        self.updates: list = []
        self.commits = 0

    async def execute(self, sentencia, parametros=None):
        texto = str(sentencia)
        if texto.lstrip().upper().startswith("SELECT"):
            resultado = MagicMock()
            resultado.scalars.return_value.all.return_value = self._mensajes
            return resultado
        self.updates.append(sentencia)
        return MagicMock()

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _fabrica(sesion: _SesionDoblada):
    def _factory():
        return sesion

    return _factory


def _mensaje(**kwargs) -> OutboxMessage:
    tenant_id = kwargs.pop("tenant_id", None) or uuid.uuid4()
    datos = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "exchange": "events.tenant",
        # Clave coherente con la columna: es la que produce `emit` en el camino
        # honesto, y por tanto la que el dispatcher deja intacta. Los mensajes
        # con clave incoherente —el caso de D-05— se prueban en
        # `tests/worker/test_outbox_dispatch.py` contra colas reales.
        "routing_key": f"{tenant_id}.venta.creada",
        "payload": {"total": 1},
        "status": STATUS_PENDING,
        "retry_count": 0,
        "last_error": "",
    }
    datos.update(kwargs)
    return OutboxMessage(**datos)


def _valores(sentencia) -> dict:
    """Extrae el `.values()` de un `update()` de SQLAlchemy.

    SQLAlchemy envuelve los literales en `BindParameter`; se desenvuelven para
    que los asserts hablen de valores y no de nodos del árbol de expresión.
    """
    salida = {}
    for columna, valor in sentencia._values.items():
        salida[columna.name] = getattr(valor, "value", valor)
    return salida


async def test_un_lote_vacio_no_commitea_ni_publica():
    sesion = _SesionDoblada([])
    publicador = AsyncMock()
    await OutboxDispatcher(_fabrica(sesion), publicador)._dispatch_batch()

    publicador.publish.assert_not_awaited()
    assert sesion.commits == 0


async def test_un_mensaje_publicado_pasa_a_processed():
    mensaje = _mensaje()
    sesion = _SesionDoblada([mensaje])
    publicador = AsyncMock()

    await OutboxDispatcher(_fabrica(sesion), publicador)._dispatch_batch()

    publicador.publish.assert_awaited_once_with(mensaje.exchange, mensaje.routing_key, mensaje.payload)
    assert len(sesion.updates) == 1
    assert _valores(sesion.updates[0])["status"] == STATUS_PROCESSED
    assert sesion.commits == 1


async def test_un_fallo_de_publicacion_incrementa_el_reintento_y_lo_deja_pendiente():
    mensaje = _mensaje(retry_count=0)
    sesion = _SesionDoblada([mensaje])
    publicador = AsyncMock()
    publicador.publish.side_effect = RuntimeError("rabbit caído")

    await OutboxDispatcher(_fabrica(sesion), publicador, max_retries=5)._dispatch_batch()

    valores = _valores(sesion.updates[0])
    assert valores["status"] == STATUS_PENDING
    assert valores["retry_count"] == 1
    assert "rabbit caído" in valores["last_error"]


async def test_al_agotar_los_reintentos_el_mensaje_pasa_a_failed():
    """Sin este corte, un mensaje envenenado se republica para siempre y tapa la
    cola de todos los negocios."""
    mensaje = _mensaje(retry_count=4)
    sesion = _SesionDoblada([mensaje])
    publicador = AsyncMock()
    publicador.publish.side_effect = RuntimeError("payload envenenado")

    await OutboxDispatcher(_fabrica(sesion), publicador, max_retries=5)._dispatch_batch()

    valores = _valores(sesion.updates[0])
    assert valores["status"] == STATUS_FAILED
    assert valores["retry_count"] == 5


async def test_el_error_guardado_se_recorta_para_no_desbordar_la_columna():
    """`last_error` es `String(1024)`: un traceback largo sin recortar hace
    fallar el propio UPDATE que registra el fallo."""
    mensaje = _mensaje()
    sesion = _SesionDoblada([mensaje])
    publicador = AsyncMock()
    publicador.publish.side_effect = RuntimeError("x" * 5000)

    await OutboxDispatcher(_fabrica(sesion), publicador)._dispatch_batch()

    assert len(_valores(sesion.updates[0])["last_error"]) == 1000


async def test_un_mensaje_que_falla_no_impide_publicar_los_demas():
    bueno_1, malo, bueno_2 = _mensaje(), _mensaje(), _mensaje()
    sesion = _SesionDoblada([bueno_1, malo, bueno_2])
    publicador = AsyncMock()

    async def _publicar(exchange, routing_key, payload):
        if payload is malo.payload:
            raise RuntimeError("solo este")

    publicador.publish.side_effect = _publicar

    await OutboxDispatcher(_fabrica(sesion), publicador)._dispatch_batch()

    estados = [_valores(u)["status"] for u in sesion.updates]
    assert estados == [STATUS_PROCESSED, STATUS_PENDING, STATUS_PROCESSED]


async def test_el_bucle_para_cuando_se_le_pide():
    sesion = _SesionDoblada([])
    dispatcher = OutboxDispatcher(_fabrica(sesion), AsyncMock(), poll_interval=0.01)
    tarea = asyncio.create_task(dispatcher.run())
    await asyncio.sleep(0.05)
    dispatcher.stop()
    await asyncio.wait_for(tarea, timeout=1.0)


async def test_un_fallo_del_lote_no_mata_el_bucle():
    """Si una excepción del lote tumbara el bucle, la cola dejaría de drenarse
    para toda la región sin que nada lo dijera."""

    class _SesionQueRevienta(_SesionDoblada):
        async def execute(self, sentencia, parametros=None):
            raise RuntimeError("la base no responde")

    dispatcher = OutboxDispatcher(_fabrica(_SesionQueRevienta([])), AsyncMock(), poll_interval=0.01)
    tarea = asyncio.create_task(dispatcher.run())
    await asyncio.sleep(0.05)
    assert not tarea.done()
    dispatcher.stop()
    await asyncio.wait_for(tarea, timeout=1.0)


# ---------------------------------------------------------------------------
# EventPublisher
# ---------------------------------------------------------------------------


async def test_el_publicador_declara_un_exchange_topic_durable_y_publica_json():
    """`durable=True` no es un detalle: con un exchange no durable, reiniciar
    RabbitMQ pierde el enrutado y los eventos se publican al vacío."""
    import aio_pika

    exchange = AsyncMock()
    canal = AsyncMock()
    canal.is_closed = False
    canal.declare_exchange = AsyncMock(return_value=exchange)
    conexion = MagicMock()
    conexion.channel = AsyncMock(return_value=canal)

    publicador = EventPublisher(conexion)
    await publicador.publish("events.tenant", "t1.venta.creada", {"total": 7})

    canal.declare_exchange.assert_awaited_once_with("events.tenant", aio_pika.ExchangeType.TOPIC, durable=True)
    mensaje = exchange.publish.call_args.args[0]
    assert json.loads(mensaje.body) == {"total": 7}
    assert mensaje.content_type == "application/json"
    assert exchange.publish.call_args.kwargs["routing_key"] == "t1.venta.creada"


async def test_el_publicador_reutiliza_el_canal_abierto():
    exchange = AsyncMock()
    canal = AsyncMock()
    canal.is_closed = False
    canal.declare_exchange = AsyncMock(return_value=exchange)
    conexion = MagicMock()
    conexion.channel = AsyncMock(return_value=canal)

    publicador = EventPublisher(conexion)
    await publicador.publish("e", "k", {})
    await publicador.publish("e", "k", {})

    conexion.channel.assert_awaited_once()


async def test_el_publicador_reabre_un_canal_cerrado():
    """Un canal cerrado por el broker tiene que reabrirse solo: si no, el
    dispatcher se queda publicando contra un canal muerto hasta el reinicio."""
    canal_muerto = AsyncMock()
    canal_muerto.is_closed = True
    canal_vivo = AsyncMock()
    canal_vivo.is_closed = False
    canal_vivo.declare_exchange = AsyncMock(return_value=AsyncMock())
    conexion = MagicMock()
    conexion.channel = AsyncMock(return_value=canal_vivo)

    publicador = EventPublisher(conexion)
    publicador._channel = canal_muerto
    await publicador.publish("e", "k", {})

    conexion.channel.assert_awaited_once()
    assert publicador._channel is canal_vivo
    canal_muerto.declare_exchange.assert_not_awaited()


@pytest.mark.parametrize("canal_cerrado", [True, False])
async def test_close_cierra_lo_que_sigue_abierto(canal_cerrado):
    canal = AsyncMock()
    canal.is_closed = canal_cerrado
    conexion = MagicMock()
    conexion.is_closed = False
    conexion.close = AsyncMock()

    publicador = EventPublisher(conexion)
    publicador._channel = canal
    await publicador.close()

    assert canal.close.await_count == (0 if canal_cerrado else 1)
    conexion.close.assert_awaited_once()
