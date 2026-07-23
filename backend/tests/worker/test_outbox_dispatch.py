"""Ciclo completo del outbox: encolar en PostgreSQL → publicar en RabbitMQ.

Es el test que `test_outbox_dispatcher.py` no puede ser: aquel dobla la sesión y
el publicador para probar la máquina de estados; éste usa el Postgres y el
RabbitMQ del compose, con los roles reales, y mide lo que de verdad llega a una
cola.

## Y es donde se cierra D-05

Medido por el QA de la Etapa 3: la policy `outbox_encolado_del_tenant` solo
acota la **columna** `tenant_id`. Una sesión de `vendi_app` con el GUC del
negocio A podía encolar legalmente una fila con `tenant_id = A` y
`routing_key = '<B>.venta.creada'`, y el dispatcher publicaba esa clave literal:
un consumidor ligado a `<B>.#` recibía un evento originado en A.

La mitigación implementada es la primera de las dos propuestas: el dispatcher
**deriva** la clave de la columna. `test_una_clave_de_enrutado_ajena_no_llega_al_otro_negocio`
es la demostración con dos colas reales.

Los tests van por `127.0.0.1:5672` porque AMQP no es HTTP y Traefik no lo
enruta. Lo que sí va por el dominio —Keycloak, la API— va por el dominio; ver la
nota de `tests/conftest.py`.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import aio_pika
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_platform_session_factory, create_session_factory
from vendi_core.events.service import EVENT_EXCHANGE, DomainEventService
from vendi_core.messaging.outbox import STATUS_PROCESSED, OutboxDispatcher, derivar_clave_de_enrutado
from vendi_core.messaging.publisher import EventPublisher
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _amqp_url() -> str:
    explicito = os.getenv("VENDI_TEST_RABBITMQ_URL", "")
    if explicito:
        return explicito
    usuario = os.getenv("RABBITMQ_USER", "vendi")
    clave = os.getenv("RABBITMQ_PASSWORD", "")
    if not clave:
        pytest.fail(
            "Falta RABBITMQ_PASSWORD (lo trae el .env de la raíz) o VENDI_TEST_RABBITMQ_URL. "
            "Se falla en vez de omitir: un test que desaparece del recuento no prueba nada."
        )
    return f"amqp://{usuario}:{clave}@127.0.0.1:5672/"


@pytest_asyncio.fixture
async def conexion_amqp():
    try:
        conexion = await asyncio.wait_for(aio_pika.connect_robust(_amqp_url()), timeout=10)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"No se pudo conectar con RabbitMQ del compose: {exc}. ¿Está el stack levantado?")
    try:
        yield conexion
    finally:
        await conexion.close()


@pytest_asyncio.fixture
async def cola_por_clave(conexion_amqp):
    """Declara colas efímeras ligadas a un patrón de clave de enrutado.

    Exclusivas y auto-delete: se van con la conexión, así que la suite es
    re-entrante sin limpiar nada a mano.
    """
    canal = await conexion_amqp.channel()
    exchange = await canal.declare_exchange(EVENT_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
    colas: list[aio_pika.abc.AbstractQueue] = []

    async def _declarar(patron: str):
        cola = await canal.declare_queue("", exclusive=True, auto_delete=True)
        await cola.bind(exchange, routing_key=patron)
        colas.append(cola)
        return cola

    try:
        yield _declarar
    finally:
        for cola in colas:
            try:
                await cola.delete(if_unused=False, if_empty=False)
            except Exception:  # noqa: BLE001, S110
                pass
        await canal.close()


@pytest_asyncio.fixture
async def limpiar_outbox(pg_platform_url: str):
    """Borra los mensajes de los negocios de prueba, antes y después."""
    engine = create_async_engine(pg_platform_url)

    async def _borrar():
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM outbox_messages WHERE tenant_id = ANY(:ids)"),
                {"ids": [A, B]},
            )

    await _borrar()
    try:
        yield
    finally:
        await _borrar()
        await engine.dispose()


async def _drenar(pg_platform_url: str, publicador: EventPublisher) -> None:
    engine = create_engine(pg_platform_url)
    try:
        dispatcher = OutboxDispatcher(
            session_factory=create_platform_session_factory(engine),
            publisher=publicador,
            poll_interval=0.05,
        )
        await dispatcher._dispatch_batch()  # noqa: SLF001 - una pasada determinista
    finally:
        await engine.dispose()


async def _recibir(cola, timeout: float = 3.0):
    """Espera un mensaje o devuelve None. Sondeo, no consumidor: el resultado es
    determinista y no depende de que un callback llegue a tiempo."""
    limite = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < limite:
        mensaje = await cola.get(no_ack=True, fail=False)
        if mensaje is not None:
            return mensaje
        await asyncio.sleep(0.05)
    return None


# --- Derivación de la clave (unitario, sin infraestructura) ------------------


@pytest.mark.parametrize(
    ("tenant_id", "guardada", "esperada"),
    [
        (A, f"{A}.venta.creada", f"{A}.venta.creada"),  # camino honesto: no-op
        (A, f"{B}.venta.creada", f"{A}.venta.creada"),  # prefijo ajeno: se corrige
        (A, "venta.creada", f"{A}.venta.creada"),  # sin prefijo: se pone
        (A, "plataforma.tenant.creado", f"{A}.tenant.creado"),
        (None, f"{B}.venta.creada", "plataforma.venta.creada"),
        (None, "plataforma.tenant.creado", "plataforma.tenant.creado"),
    ],
)
def test_la_clave_se_deriva_de_la_columna_tenant_id(tenant_id, guardada, esperada):
    assert derivar_clave_de_enrutado(tenant_id, guardada) == esperada


# --- Ciclo completo contra el compose ----------------------------------------


@pytest.mark.asyncio
async def test_un_evento_encolado_llega_a_la_cola_del_negocio(pg_platform_url, cola_por_clave, limpiar_outbox):
    cola = await cola_por_clave(f"{A}.#")
    engine = create_engine(pg_platform_url)
    try:
        fabrica = create_platform_session_factory(engine)
        async with fabrica() as sesion:
            await DomainEventService.emit(
                sesion,
                tenant_id=A,
                event_name="venta.creada",
                resource_type="venta",
                resource_id="v-1",
                data={"total": 12345},
            )
            await sesion.commit()
    finally:
        await engine.dispose()

    publicador = await EventPublisher.connect(_amqp_url())
    try:
        await _drenar(pg_platform_url, publicador)
    finally:
        await publicador.close()

    mensaje = await _recibir(cola)
    assert mensaje is not None, "el evento no llegó a la cola del negocio"
    assert mensaje.routing_key == f"{A}.venta.creada"


@pytest.mark.asyncio
async def test_una_clave_de_enrutado_ajena_no_llega_al_otro_negocio(
    pg_app_url, pg_platform_url, cola_por_clave, limpiar_outbox
):
    """D-05, con las dos colas reales y el rol de la API de verdad.

    El encolado se hace con `vendi_app` y el GUC del negocio A —o sea, pasando
    la policy— pero con la clave de enrutado y el payload del negocio B. Es
    exactamente lo que un handler equivocado (o malicioso) podría escribir.

    Lo que se afirma: el mensaje sale por `A.#` y **nunca** por `B.#`.
    """
    cola_a = await cola_por_clave(f"{A}.#")
    cola_b = await cola_por_clave(f"{B}.#")

    engine_app = create_engine(pg_app_url)
    marca = current_tenant_id.set(A)
    try:
        async with create_session_factory(engine_app)() as sesion:
            await sesion.execute(
                text(
                    "INSERT INTO outbox_messages (tenant_id, exchange, routing_key, payload) "
                    "VALUES (:t, :x, :k, CAST(:p AS jsonb))"
                ),
                {
                    "t": A,
                    "x": EVENT_EXCHANGE,
                    # Clave de enrutado del negocio B: la policy no la mira.
                    "k": f"{B}.venta.creada",
                    # Y el payload también miente sobre su dueño.
                    "p": f'{{"event": "venta.creada", "tenant_id": "{B}", "data": {{}}}}',
                },
            )
            await sesion.commit()
    finally:
        current_tenant_id.reset(marca)
        await engine_app.dispose()

    publicador = await EventPublisher.connect(_amqp_url())
    try:
        await _drenar(pg_platform_url, publicador)
    finally:
        await publicador.close()

    intruso = await _recibir(cola_b, timeout=1.5)
    assert intruso is None, (
        "un mensaje encolado por el negocio A llegó a la cola del negocio B: "
        "el dispatcher está confiando en la routing_key almacenada (D-05)."
    )

    propio = await _recibir(cola_a)
    assert propio is not None, "el mensaje tampoco llegó a la cola de su propio negocio"
    assert propio.routing_key == f"{A}.venta.creada"
    import json

    cuerpo = json.loads(propio.body)
    assert cuerpo["tenant_id"] == str(A), "el `tenant_id` del payload sigue siendo el ajeno"


@pytest.mark.asyncio
async def test_los_mensajes_publicados_quedan_marcados_processed(pg_platform_url, cola_por_clave, limpiar_outbox):
    """Sin esto el dispatcher republicaría el mismo evento en cada pasada."""
    await cola_por_clave(f"{A}.#")
    engine = create_engine(pg_platform_url)
    try:
        fabrica = create_platform_session_factory(engine)
        async with fabrica() as sesion:
            await DomainEventService.emit(
                sesion,
                tenant_id=A,
                event_name="venta.creada",
                resource_type="venta",
                resource_id="v-2",
            )
            await sesion.commit()
    finally:
        await engine.dispose()

    publicador = await EventPublisher.connect(_amqp_url())
    try:
        await _drenar(pg_platform_url, publicador)
    finally:
        await publicador.close()

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            estados = (
                (
                    await conn.execute(
                        text("SELECT status FROM outbox_messages WHERE tenant_id = :t"),
                        {"t": A},
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()
    assert estados and all(e == STATUS_PROCESSED for e in estados)


@pytest.mark.asyncio
async def test_un_exchange_ajeno_no_se_declara_ni_desvia_el_mensaje(
    pg_app_url, pg_platform_url, conexion_amqp, cola_por_clave, limpiar_outbox
):
    """D-07, el resto de D-05, con dos exchanges reales.

    La policy del outbox acota `tenant_id` y nada más: `vendi_app` puede encolar
    una fila con su propio negocio y el `exchange` que quiera. El dispatcher lo
    usaba literalmente en `declare_exchange`, de modo que un nombre nuevo
    **creaba** el exchange —escritura en la topología del broker desde el rol de
    la API— y uno reservado (`amq.direct`) reventaba la publicación.

    Se afirman las dos mitades:

    1. el mensaje sale igualmente por el exchange bueno, con su clave derivada;
    2. el exchange que pedía la fila **no existe** después. La comprobación es
       un `declare_exchange(..., passive=True)`, que en AMQP es «dime si existe»
       y responde 404 si no: si el dispatcher lo hubiera creado, esa llamada
       tendría éxito y el test fallaría.
    """
    exchange_ajeno = f"vendi.suplantado.{uuid.uuid4().hex[:8]}"
    cola_a = await cola_por_clave(f"{A}.#")

    engine_app = create_engine(pg_app_url)
    marca = current_tenant_id.set(A)
    try:
        async with create_session_factory(engine_app)() as sesion:
            await sesion.execute(
                text(
                    "INSERT INTO outbox_messages (tenant_id, exchange, routing_key, payload) "
                    "VALUES (:t, :x, :k, CAST(:p AS jsonb))"
                ),
                {
                    "t": A,
                    "x": exchange_ajeno,
                    "k": f"{A}.venta.creada",
                    "p": '{"event": "venta.creada", "data": {}}',
                },
            )
            await sesion.commit()
    finally:
        current_tenant_id.reset(marca)
        await engine_app.dispose()

    publicador = await EventPublisher.connect(_amqp_url())
    try:
        await _drenar(pg_platform_url, publicador)
    finally:
        await publicador.close()

    propio = await _recibir(cola_a)
    assert propio is not None, (
        "el mensaje no llegó al exchange configurado: el dispatcher sigue publicando "
        "en el exchange que dice la fila (D-07)."
    )
    assert propio.routing_key == f"{A}.venta.creada"

    # Canal aparte: un `declare` pasivo fallido cierra el canal en el que se
    # hace, y con él se llevaría las colas declaradas arriba.
    canal = await conexion_amqp.channel()
    try:
        with pytest.raises(aio_pika.exceptions.ChannelNotFoundEntity):
            await canal.declare_exchange(exchange_ajeno, passive=True)
    finally:
        if not canal.is_closed:
            await canal.close()
