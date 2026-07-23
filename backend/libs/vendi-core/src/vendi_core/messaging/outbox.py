"""Patrón outbox transaccional.

La escritura de negocio y el encolado del evento ocurren en la MISMA
transacción de base de datos: si la transacción hace rollback, no se publica
ningún evento fantasma. Un dispatcher en segundo plano sondea los mensajes
pendientes y los publica en RabbitMQ.

Cosechado de `base_saas.messaging.outbox` con dos adaptaciones:

1. Se quita `{"schema": "public"}` de `__table_args__`: Vendi es schema único
   regional.
2. `outbox_messages` gana `tenant_id UUID NULL`. Nullable porque los eventos de
   plataforma (alta de negocio, cambios de estado) no pertenecen a ningún
   negocio.

## Privilegios: quién puede hacer qué sobre `outbox_messages`

`outbox_messages` es tabla de PLATAFORMA y **no lleva la policy de aislamiento
`tenant_isolation`**; está en la lista de excepciones del candado
`test_rls_coverage.py`. Razón: el dispatcher drena la cola de TODOS los negocios
en una sola pasada con la sesión de plataforma. Con una policy de lectura por
tenant tendría que abrir una transacción por negocio, o correr sin GUC y ver
cero filas — es decir, no funcionaría.

Pero "tabla de plataforma" no puede significar "fuera del alcance de la API":
`enqueue()` escribe en la sesión del llamante, que en un handler es la de tenant
(rol `vendi_app`). Si `vendi_app` no pudiera insertar aquí, el patrón entero
sería inutilizable — y el encolado con una segunda sesión rompe la atomicidad,
que es lo único que aporta el patrón. Así queda repartido (migración 0001):

- `vendi_app`: **INSERT y nada más**. No SELECT (no lee la cola de nadie), no
  UPDATE (no marca procesado ni reescribe mensajes ajenos), no DELETE.
- `vendi_app` además pasa por la policy `outbox_encolado_del_tenant`, que es
  `FOR INSERT ... WITH CHECK (tenant_id = GUC vendi.tenant_id)`: la API puede
  encolar para su negocio y para ninguno más.
- `vendi_platform`: todo, y salta la policy por `BYPASSRLS`. De ahí que el
  dispatcher drene la cola entera y que los eventos de plataforma
  (`tenant_id NULL`) puedan encolarse.

La columna `tenant_id` sigue siendo material de enrutado y trazabilidad para la
lectura; para la escritura desde la API es también, ahora, columna de control.
"""

import asyncio
import uuid
from datetime import datetime

import structlog
from sqlalchemy import UUID, DateTime, Index, Integer, String, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base
from vendi_core.messaging.publisher import EventPublisher

logger = structlog.get_logger()

STATUS_PENDING = "pending"
STATUS_PROCESSED = "processed"
STATUS_FAILED = "failed"


class OutboxMessage(Base):
    """Mensaje a la espera de publicación. Tabla de plataforma, sin RLS."""

    __tablename__ = "outbox_messages"
    __table_args__ = (
        # Índice PARCIAL sobre lo único que consulta el dispatcher: los
        # pendientes. Un índice completo sobre `status` sería casi inútil —la
        # inmensa mayoría de las filas acaban en 'processed' y ahí se quedan
        # hasta que las purga retención— y crecería sin parar.
        #
        # Está declarado aquí y no solo en la migración porque `alembic check`
        # compara el metadata contra la base: si el índice existe en la base y
        # no en el modelo, el siguiente `--autogenerate` propone **borrarlo**, y
        # se pierde en silencio el único índice del que depende el drenado de
        # la cola. Verificado: `alembic check` fallaba exactamente así.
        Index(
            "ix_outbox_messages_pendientes",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )
    # Sin esto, SQLAlchemy 2 emite `INSERT ... RETURNING created_at` para
    # rellenar el server_default en caliente (`eager_defaults="auto"`), y
    # PostgreSQL exige privilegio SELECT sobre las columnas de un RETURNING.
    # El encolado corre con el rol `vendi_app`, que tiene INSERT y **solo**
    # INSERT sobre esta tabla a propósito: con RETURNING, encolar fallaría con
    # `permission denied for table outbox_messages` aunque el INSERT sea legal.
    # Nadie lee `created_at` en el camino de encolado; quien lo necesita es el
    # dispatcher, que va con la sesión de plataforma y lo lee del SELECT.
    __mapper_args__ = {"eager_defaults": False}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # NULL = evento de plataforma. No es columna de aislamiento (la tabla no
    # lleva RLS); es trazabilidad y material de enrutado.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    exchange: Mapped[str] = mapped_column(String(128), nullable=False)
    routing_key: Mapped[str] = mapped_column(String(256), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_PENDING, server_default=STATUS_PENDING, nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_error: Mapped[str] = mapped_column(String(1024), default="", server_default="", nullable=False)


class OutboxService:
    """Encola mensajes dentro de una sesión de base de datos ya existente."""

    @staticmethod
    async def enqueue(
        session: AsyncSession,
        exchange: str,
        routing_key: str,
        payload: dict,
        tenant_id: uuid.UUID | None = None,
    ) -> OutboxMessage:
        message = OutboxMessage(
            tenant_id=tenant_id,
            exchange=exchange,
            routing_key=routing_key,
            payload=payload,
        )
        session.add(message)
        return message


class OutboxDispatcher:
    """Polls outbox and publishes pending messages. Run as background task."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        publisher: EventPublisher,
        poll_interval: float = 2.0,
        batch_size: int = 100,
        max_retries: int = 5,
    ):
        self._session_factory = session_factory
        self._publisher = publisher
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._stop = asyncio.Event()

    async def run(self) -> None:
        """Main loop. Call once from lifespan startup."""
        while not self._stop.is_set():
            try:
                await self._dispatch_batch()
            except Exception as exc:
                logger.error("outbox_dispatch_loop_error", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()

    async def _dispatch_batch(self) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OutboxMessage)
                .where(OutboxMessage.status == STATUS_PENDING)
                .where(OutboxMessage.retry_count < self._max_retries)
                .order_by(OutboxMessage.created_at)
                .limit(self._batch_size)
            )
            messages = result.scalars().all()
            if not messages:
                return

            for msg in messages:
                try:
                    await self._publisher.publish(msg.exchange, msg.routing_key, msg.payload)
                    await session.execute(
                        update(OutboxMessage)
                        .where(OutboxMessage.id == msg.id)
                        .values(status=STATUS_PROCESSED, processed_at=func.now())
                    )
                except Exception as exc:
                    logger.warning(
                        "outbox_publish_failed",
                        message_id=str(msg.id),
                        exchange=msg.exchange,
                        routing_key=msg.routing_key,
                        error=str(exc),
                    )
                    retry = msg.retry_count + 1
                    new_status = STATUS_FAILED if retry >= self._max_retries else STATUS_PENDING
                    await session.execute(
                        update(OutboxMessage)
                        .where(OutboxMessage.id == msg.id)
                        .values(
                            retry_count=retry,
                            status=new_status,
                            last_error=str(exc)[:1000],
                        )
                    )
            await session.commit()
