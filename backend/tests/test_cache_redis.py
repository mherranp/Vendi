"""`RedisCache`: serialización JSON en get/set y publicación pub/sub.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_cache_publish_json.py`,
ampliado con `get`/`set`/`delete` porque el módulo entero estaba al 0 %.
Adaptación: `base_saas` → `vendi_core`.

No hace falta el Redis del compose: se inyecta un cliente doblado. Lo que se
prueba aquí es la capa de serialización de `vendi_core`, no redis-py.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock

from vendi_core.cache.redis import RedisCache


def _cache_con_cliente_doblado() -> tuple[RedisCache, Mock]:
    cliente = Mock()
    return RedisCache(cliente), cliente


async def test_publish_json_serializa_y_devuelve_el_numero_de_suscriptores():
    cache, cliente = _cache_con_cliente_doblado()
    cliente.publish = AsyncMock(return_value=3)

    n = await cache.publish_json("canal-de-prueba", {"hola": "mundo"})

    assert n == 3
    cliente.publish.assert_awaited_once()
    args, _ = cliente.publish.call_args
    assert args[0] == "canal-de-prueba"
    assert json.loads(args[1]) == {"hola": "mundo"}


async def test_publish_json_sin_suscriptores_devuelve_cero():
    cache, cliente = _cache_con_cliente_doblado()
    cliente.publish = AsyncMock(return_value=0)
    assert await cache.publish_json("canal-vacio", {"evento": "ping"}) == 0


async def test_get_deserializa_json():
    cache, cliente = _cache_con_cliente_doblado()
    cliente.get = AsyncMock(return_value='{"total": 7}')
    assert await cache.get("clave") == {"total": 7}


async def test_get_devuelve_el_texto_crudo_si_no_es_json():
    """Una clave escrita fuera de esta capa no puede reventar la lectura."""
    cache, cliente = _cache_con_cliente_doblado()
    cliente.get = AsyncMock(return_value="no-es-json")
    assert await cache.get("clave") == "no-es-json"


async def test_get_de_una_clave_inexistente_devuelve_none():
    cache, cliente = _cache_con_cliente_doblado()
    cliente.get = AsyncMock(return_value=None)
    assert await cache.get("no-existe") is None


async def test_set_sin_ttl_no_usa_setex():
    cache, cliente = _cache_con_cliente_doblado()
    cliente.set = AsyncMock()
    cliente.setex = AsyncMock()

    await cache.set("clave", {"a": 1})

    cliente.set.assert_awaited_once_with("clave", '{"a": 1}')
    cliente.setex.assert_not_awaited()


async def test_set_con_ttl_usa_setex():
    cache, cliente = _cache_con_cliente_doblado()
    cliente.set = AsyncMock()
    cliente.setex = AsyncMock()

    await cache.set("clave", {"a": 1}, ttl=60)

    cliente.setex.assert_awaited_once_with("clave", 60, '{"a": 1}')
    cliente.set.assert_not_awaited()


async def test_set_de_un_string_no_lo_vuelve_a_serializar():
    """Serializarlo dos veces devolvería `'"hola"'` en la lectura."""
    cache, cliente = _cache_con_cliente_doblado()
    cliente.set = AsyncMock()

    await cache.set("clave", "hola")

    cliente.set.assert_awaited_once_with("clave", "hola")


async def test_delete_delega_en_el_cliente():
    cache, cliente = _cache_con_cliente_doblado()
    cliente.delete = AsyncMock()
    await cache.delete("clave")
    cliente.delete.assert_awaited_once_with("clave")
