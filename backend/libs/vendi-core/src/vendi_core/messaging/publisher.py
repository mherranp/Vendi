import json

import aio_pika


class EventPublisher:
    """Async RabbitMQ event publisher."""

    def __init__(self, connection: aio_pika.abc.AbstractRobustConnection):
        self._connection = connection
        self._channel: aio_pika.abc.AbstractChannel | None = None

    @classmethod
    async def connect(cls, url: str) -> "EventPublisher":
        connection = await aio_pika.connect_robust(url)
        return cls(connection)

    async def _get_channel(self) -> aio_pika.abc.AbstractChannel:
        if self._channel is None or self._channel.is_closed:
            self._channel = await self._connection.channel()
        return self._channel

    async def publish(self, exchange_name: str, routing_key: str, message: dict) -> None:
        channel = await self._get_channel()
        exchange = await channel.declare_exchange(exchange_name, aio_pika.ExchangeType.TOPIC, durable=True)
        body = json.dumps(message).encode()
        await exchange.publish(
            aio_pika.Message(body=body, content_type="application/json"),
            routing_key=routing_key,
        )

    async def close(self) -> None:
        if self._channel and not self._channel.is_closed:
            await self._channel.close()
        if not self._connection.is_closed:
            await self._connection.close()
