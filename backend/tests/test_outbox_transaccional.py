"""Candado del outbox transaccional visto desde el rol de la API.

Este archivo existe porque el contrato que documentan `messaging/outbox.py` y
`events/service.py` —«la escritura de negocio y el encolado ocurren en la MISMA
transacción»— es una afirmación sobre **privilegios de Postgres**, no sobre
Python: si el rol `vendi_app` no puede insertar en `outbox_messages`, el patrón
no existe, y ningún test de unidad con una sesión falsa lo detectaría.

Lo que se fija aquí:

1. `vendi_app` **puede** encolar desde la sesión de tenant (la del handler).
2. Un `rollback` del llamante no deja mensaje fantasma: es la garantía entera.
3. `vendi_app` **no** puede leer, actualizar ni borrar la cola. Encolar no es
   drenar; drenar es de `vendi_platform`.
4. `vendi_app` **no** puede encolar en nombre de otro negocio (policy
   `outbox_encolado_del_tenant`), ni siquiera con el GUC bien puesto.
5. `vendi_platform` sí ve y drena la cola entera, incluidos los eventos de
   plataforma con `tenant_id NULL`, porque tiene `BYPASSRLS`.
"""

from __future__ import annotations

import uuid

import pytest
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.db.session import create_platform_session_factory, create_session_factory
from vendi_core.events.service import EVENT_EXCHANGE, DomainEventService
from vendi_core.messaging.outbox import STATUS_PENDING, OutboxMessage, OutboxService
from vendi_core.tenant.context import current_tenant_id

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _marca() -> str:
    """Clave de enrutado única por corrida: la suite tiene que ser re-entrante."""
    return f"prueba-{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def limpiar_outbox(pg_platform_url: str):
    """Borra con el rol de plataforma lo que el test haya encolado.

    `vendi_app` no puede borrar (ese es justamente uno de los asserts), así que
    la limpieza tiene que ir por plataforma.
    """
    marcas: list[str] = []
    yield marcas
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            for marca in marcas:
                await conn.execute(
                    text("DELETE FROM outbox_messages WHERE routing_key LIKE :patron"),
                    {"patron": f"%{marca}%"},
                )
    finally:
        await engine.dispose()


async def test_la_api_encola_en_su_propia_transaccion(pg_app_url, pg_platform_url, limpiar_outbox):
    """El caso que el informe de QA reprodujo como fallo: `emit()` con la sesión
    de tenant terminaba en `permission denied for table outbox_messages`."""
    marca = _marca()
    limpiar_outbox.append(marca)
    engine = create_async_engine(pg_app_url)
    token = current_tenant_id.set(T1)
    try:
        factory = create_session_factory(engine)
        async with factory() as sesion:
            event_id = await DomainEventService.emit(
                sesion,
                tenant_id=T1,
                event_name=marca,
                resource_type="venta",
                resource_id=str(uuid.uuid4()),
                data={"total": 1},
            )
            await sesion.commit()
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()

    # Se comprueba con el rol de plataforma, porque `vendi_app` no puede leer.
    plataforma = create_async_engine(pg_platform_url)
    try:
        async with plataforma.connect() as conn:
            fila = (
                await conn.execute(
                    text(
                        "SELECT tenant_id, exchange, routing_key, status, payload "
                        "FROM outbox_messages WHERE routing_key = :rk"
                    ),
                    {"rk": f"{T1}.{marca}"},
                )
            ).one()
    finally:
        await plataforma.dispose()

    assert fila.tenant_id == T1
    assert fila.exchange == EVENT_EXCHANGE
    assert fila.status == STATUS_PENDING
    assert fila.payload["id"] == event_id
    assert fila.payload["event"] == marca


async def test_un_rollback_del_llamante_no_deja_mensaje_fantasma(pg_app_url, pg_platform_url, limpiar_outbox):
    """La atomicidad es TODA la garantía del patrón: sin ella, encolar en el
    outbox no vale más que publicar directamente en RabbitMQ."""
    marca = _marca()
    limpiar_outbox.append(marca)
    engine = create_async_engine(pg_app_url)
    token = current_tenant_id.set(T1)
    try:
        factory = create_session_factory(engine)
        async with factory() as sesion:
            await DomainEventService.emit(
                sesion,
                tenant_id=T1,
                event_name=marca,
                resource_type="venta",
                resource_id=str(uuid.uuid4()),
                data={},
            )
            await sesion.rollback()
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()

    plataforma = create_async_engine(pg_platform_url)
    try:
        async with plataforma.connect() as conn:
            n = await conn.scalar(
                text("SELECT count(*) FROM outbox_messages WHERE routing_key = :rk"),
                {"rk": f"{T1}.{marca}"},
            )
    finally:
        await plataforma.dispose()
    assert n == 0, "el rollback del llamante dejó un evento fantasma en la cola"


async def test_el_encolado_sobrevive_a_un_commit_a_mitad_de_request(pg_app_url, pg_platform_url, limpiar_outbox):
    """`SET LOCAL` muere en el COMMIT. El encolado posterior tiene que seguir
    pasando el `WITH CHECK` de la policy, porque el hook `after_begin` vuelve a
    sembrar el GUC en la transacción nueva. Sin ese hook esto fallaría con
    «new row violates row-level security policy»."""
    marca = _marca()
    limpiar_outbox.append(marca)
    engine = create_async_engine(pg_app_url)
    token = current_tenant_id.set(T1)
    try:
        factory = create_session_factory(engine)
        async with factory() as sesion:
            await DomainEventService.emit(
                sesion,
                tenant_id=T1,
                event_name=f"{marca}-antes",
                resource_type="venta",
                resource_id=str(uuid.uuid4()),
                data={},
            )
            await sesion.commit()  # ← aquí muere el SET LOCAL
            await DomainEventService.emit(
                sesion,
                tenant_id=T1,
                event_name=f"{marca}-despues",
                resource_type="venta",
                resource_id=str(uuid.uuid4()),
                data={},
            )
            await sesion.commit()
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()

    plataforma = create_async_engine(pg_platform_url)
    try:
        async with plataforma.connect() as conn:
            claves = (
                (
                    await conn.execute(
                        text("SELECT routing_key FROM outbox_messages WHERE routing_key LIKE :p ORDER BY routing_key"),
                        {"p": f"%{marca}%"},
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await plataforma.dispose()
    assert claves == [f"{T1}.{marca}-antes", f"{T1}.{marca}-despues"]


async def test_la_api_no_puede_encolar_para_otro_negocio(pg_app_url, limpiar_outbox):
    """La policy `outbox_encolado_del_tenant` es lo que impide que la tabla sin
    aislamiento de lectura se convierta en un canal de escritura cross-tenant."""
    marca = _marca()
    limpiar_outbox.append(marca)
    engine = create_async_engine(pg_app_url)
    token = current_tenant_id.set(T1)  # el GUC dice T1...
    try:
        factory = create_session_factory(engine)
        async with factory() as sesion:
            # ...y el mensaje pretende ser de T2.
            await OutboxService.enqueue(
                sesion,
                exchange=EVENT_EXCHANGE,
                routing_key=f"{T2}.{marca}",
                payload={},
                tenant_id=T2,
            )
            with pytest.raises((DBAPIError, ProgrammingError), match="row-level security policy"):
                await sesion.commit()
            await sesion.rollback()
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


async def test_la_api_no_puede_leer_ni_drenar_la_cola(pg_app_url):
    """Encolar no es drenar. `vendi_app` tiene INSERT y solo INSERT."""
    engine = create_async_engine(pg_app_url)
    sentencias = (
        "SELECT count(*) FROM outbox_messages",
        "UPDATE outbox_messages SET status = 'processed'",
        "DELETE FROM outbox_messages",
    )
    try:
        async with engine.connect() as conn:
            for sql in sentencias:
                with pytest.raises((DBAPIError, ProgrammingError), match="permission denied"):
                    await conn.execute(text(sql))
                await conn.rollback()
    finally:
        await engine.dispose()


async def test_plataforma_encola_eventos_sin_negocio_y_ve_la_cola_entera(pg_platform_url, limpiar_outbox):
    """Los eventos de plataforma llevan `tenant_id NULL` y no pasarían el
    `WITH CHECK`; funcionan porque `vendi_platform` tiene `BYPASSRLS`. Si algún
    día alguien le quita el atributo, este test lo dice."""
    marca = _marca()
    limpiar_outbox.append(marca)
    engine = create_async_engine(pg_platform_url)
    try:
        factory = create_platform_session_factory(engine)
        async with factory() as sesion:
            await DomainEventService.emit(
                sesion,
                tenant_id=None,
                event_name=marca,
                resource_type="tenant",
                resource_id=str(uuid.uuid4()),
                data={},
            )
            await sesion.commit()

        async with factory() as sesion:
            mensajes = (
                await sesion.execute(
                    OutboxMessage.__table__.select().where(OutboxMessage.routing_key.like(f"%{marca}%"))
                )
            ).all()
    finally:
        await engine.dispose()

    assert len(mensajes) == 1
    assert mensajes[0].tenant_id is None
    assert mensajes[0].routing_key == f"plataforma.{marca}"


async def test_la_api_no_alcanza_audit_events_en_ninguna_forma(pg_app_url):
    """Contrapunto deliberado del outbox.

    `audit_events` NO recibe `INSERT` para `vendi_app`, y no es una asimetría
    por olvido: `AuditService` no recibe una sesión, recibe una
    `async_sessionmaker` y abre la suya (`audit/service.py::_write`). La
    auditoría es fire-and-forget **fuera** de la transacción del llamante a
    propósito —si fuese dentro, el rollback de una operación fallida borraría la
    prueba de que se intentó—, así que se cablea con la fábrica de plataforma y
    el rol de la API no necesita alcanzar la tabla.
    """
    import inspect

    from vendi_core.audit.service import AuditService

    firma = inspect.signature(AuditService.log_sync)
    assert "session" not in firma.parameters, (
        "AuditService.log_sync acepta una sesión: si la auditoría pasa a escribirse "
        "en la sesión del llamante, `vendi_app` necesita INSERT sobre audit_events y "
        "esta migración deja de ser correcta."
    )

    engine = create_async_engine(pg_app_url)
    try:
        async with engine.connect() as conn:
            for sql in (
                "SELECT count(*) FROM audit_events",
                "INSERT INTO audit_events (action) VALUES ('x')",
            ):
                with pytest.raises((DBAPIError, ProgrammingError), match="permission denied"):
                    await conn.execute(text(sql))
                await conn.rollback()
    finally:
        await engine.dispose()
