import json
from collections.abc import Awaitable
from typing import Any, cast

import redis.asyncio as aioredis


class RedisCache:
    """Async Redis cache wrapper."""

    def __init__(self, client: aioredis.Redis):
        self._client = client

    @classmethod
    async def connect(cls, url: str) -> "RedisCache":
        client = aioredis.from_url(url, decode_responses=True)
        # redis-py's async stubs declare ping() as Awaitable[bool] | bool,
        # which mypy refuses to await directly. In the asyncio client it
        # always returns a coroutine at runtime, so the cast is safe.
        await cast(Awaitable[Any], client.ping())
        return cls(client)

    async def get(self, key: str) -> Any | None:
        value = await self._client.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        serialized = json.dumps(value) if not isinstance(value, str) else value
        if ttl:
            await self._client.setex(key, ttl, serialized)
        else:
            await self._client.set(key, serialized)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def publish_json(self, channel: str, payload: dict) -> int:
        """Publish a JSON-serialized payload to a Redis pub/sub channel.

        Returns the number of subscribers that received the message.
        Used by mail-worker / scrapper-worker to push real-time notifications
        to the realtime-service hub.
        """
        return await self._client.publish(channel, json.dumps(payload))

    async def close(self) -> None:
        await self._client.aclose()
