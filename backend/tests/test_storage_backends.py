"""Backends de almacenamiento: contrato de `StorageBackend` y capa S3-compatible.

`vendi_core.storage` viene de `base_saas.storage`. BaseSaaS cubría la fábrica
(`test_storage_factory.py`, portado aparte) y el resto solo de refilón desde los
routers de ficheros, que en Vendi no existen todavía; el paquete entraba al
repositorio con cero líneas ejecutadas.

Se dobla el cliente de `miniopy_async` en vez de hablar con el MinIO del
compose: lo que se prueba aquí es la traducción entre la API del cliente y el
contrato `StorageBackend`, que es donde vive el error probable (un `length` mal
calculado, un `etag` con comillas, un rango que se pide entero).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vendi_core.storage.base import StorageBackend, StoredObject
from vendi_core.storage.s3compat import S3CompatBackend


class _RespuestaDoblada:
    def __init__(self, datos: bytes):
        self._datos = datos
        self.cerrada = False
        self.liberada = False

    async def read(self) -> bytes:
        return self._datos

    def close(self) -> None:
        self.cerrada = True

    async def release(self) -> None:
        self.liberada = True


def _backend_con_cliente_doblado() -> tuple[S3CompatBackend, MagicMock]:
    backend = S3CompatBackend.__new__(S3CompatBackend)
    cliente = MagicMock()
    backend._client = cliente
    return backend, cliente


# ---------------------------------------------------------------------------
# Contrato de la clase base
# ---------------------------------------------------------------------------


class _BackendMinimo(StorageBackend):
    """Implementación mínima: solo lo abstracto, para ejercer los métodos con
    implementación por defecto de la clase base."""

    def __init__(self, contenido: bytes = b""):
        self.contenido = contenido

    async def ensure_bucket(self, bucket): ...

    async def put(self, bucket, key, data, content_type="application/octet-stream"):
        return StoredObject(bucket=bucket, key=key, size=len(data), content_type=content_type)

    async def get(self, bucket, key):
        return self.contenido

    async def delete(self, bucket, key): ...

    async def get_presigned_url(self, bucket, key, expires_seconds=3600, method="GET"):
        return "https://ejemplo/x"

    async def list_objects(self, bucket, prefix=""):
        return []

    async def stat(self, bucket, key):
        return StoredObject(bucket=bucket, key=key, size=0, content_type="")


def test_no_se_puede_instanciar_un_backend_incompleto():
    """El ABC es lo que impide que un backend nuevo se olvide de `delete` y el
    fallo aparezca el día de la primera purga de retención."""
    with pytest.raises(TypeError):
        StorageBackend()  # type: ignore[abstract]


async def test_el_rango_por_defecto_lee_entero_y_recorta_en_python():
    backend = _BackendMinimo(b"0123456789")
    assert await backend.get_range("b", "k", offset=2, length=3) == b"234"


async def test_un_rango_de_longitud_cero_no_toca_el_backend():
    class _Espia(_BackendMinimo):
        def __init__(self):
            super().__init__(b"x")
            self.lecturas = 0

        async def get(self, bucket, key):
            self.lecturas += 1
            return self.contenido

    espia = _Espia()
    assert await espia.get_range("b", "k", offset=0, length=0) == b""
    assert espia.lecturas == 0


# ---------------------------------------------------------------------------
# Backend S3-compatible
# ---------------------------------------------------------------------------


async def test_put_manda_la_longitud_real_y_devuelve_los_metadatos():
    backend, cliente = _backend_con_cliente_doblado()
    cliente.put_object = AsyncMock()

    objeto = await backend.put("negocio-1", "recibo.pdf", b"12345", content_type="application/pdf")

    assert objeto == StoredObject(bucket="negocio-1", key="recibo.pdf", size=5, content_type="application/pdf")
    _, kwargs = cliente.put_object.call_args
    assert kwargs["length"] == 5
    assert kwargs["content_type"] == "application/pdf"


async def test_get_libera_la_respuesta_siempre():
    """La conexión vuelve al pool en el `finally`: sin eso, una lectura que
    reviente a mitad filtra una conexión por llamada."""
    backend, cliente = _backend_con_cliente_doblado()
    respuesta = _RespuestaDoblada(b"contenido")
    cliente.get_object = AsyncMock(return_value=respuesta)

    assert await backend.get("negocio-1", "a.txt") == b"contenido"
    assert respuesta.cerrada and respuesta.liberada


async def test_get_range_pide_solo_el_trozo_al_almacen():
    """El punto entero de sobrescribir `get_range`: para un objeto de 500 MB del
    que el cliente quiere 1 KB, no se traen los 500 MB."""
    backend, cliente = _backend_con_cliente_doblado()
    respuesta = _RespuestaDoblada(b"1234")
    cliente.get_object = AsyncMock(return_value=respuesta)

    assert await backend.get_range("b", "k", offset=10, length=4) == b"1234"
    _, kwargs = cliente.get_object.call_args
    assert kwargs == {"offset": 10, "length": 4}


async def test_get_range_de_longitud_cero_no_llama_al_almacen():
    backend, cliente = _backend_con_cliente_doblado()
    cliente.get_object = AsyncMock()
    assert await backend.get_range("b", "k", offset=0, length=0) == b""
    cliente.get_object.assert_not_awaited()


async def test_la_url_prefirmada_distingue_get_de_put():
    backend, cliente = _backend_con_cliente_doblado()
    cliente.presigned_get_object = AsyncMock(return_value="https://ejemplo/get")
    cliente.presigned_put_object = AsyncMock(return_value="https://ejemplo/put")

    assert await backend.get_presigned_url("b", "k") == "https://ejemplo/get"
    assert await backend.get_presigned_url("b", "k", method="put") == "https://ejemplo/put"


async def test_stat_quita_las_comillas_del_etag():
    """S3 devuelve el ETag entrecomillado. Guardarlo con comillas rompe
    cualquier comparación posterior."""
    backend, cliente = _backend_con_cliente_doblado()
    momento = datetime.now(UTC)
    cliente.stat_object = AsyncMock(
        return_value=SimpleNamespace(size=42, content_type="image/png", last_modified=momento, etag='"abc123"')
    )

    objeto = await backend.stat("negocio-1", "logo.png")

    assert objeto.etag == "abc123"
    assert objeto.size == 42
    assert objeto.last_modified == momento


async def test_list_objects_rellena_los_huecos_con_valores_seguros():
    backend, cliente = _backend_con_cliente_doblado()
    cliente.list_objects = AsyncMock(
        return_value=[
            SimpleNamespace(object_name="a.txt", size=3, content_type=None, last_modified=None, etag=None),
        ]
    )

    objetos = await backend.list_objects("negocio-1", prefix="a")

    assert objetos == [
        StoredObject(
            bucket="negocio-1",
            key="a.txt",
            size=3,
            content_type="application/octet-stream",
            last_modified=None,
            etag="",
        )
    ]


async def test_ensure_bucket_no_recrea_un_bucket_existente():
    backend, cliente = _backend_con_cliente_doblado()
    cliente.bucket_exists = AsyncMock(return_value=True)
    cliente.make_bucket = AsyncMock()

    await backend.ensure_bucket("negocio-1")

    cliente.make_bucket.assert_not_awaited()


async def test_ensure_bucket_crea_el_bucket_si_falta():
    backend, cliente = _backend_con_cliente_doblado()
    cliente.bucket_exists = AsyncMock(return_value=False)
    cliente.make_bucket = AsyncMock()

    await backend.ensure_bucket("negocio-1")

    cliente.make_bucket.assert_awaited_once_with("negocio-1")


# ---------------------------------------------------------------------------
# ObjectStorage: envoltorio de bucket único
# ---------------------------------------------------------------------------
#
# Es el envoltorio heredado de un solo bucket, exportado en el `__init__` del
# paquete. En Fase 0 no lo usa nadie todavía (los servicios llegan en la Etapa
# 4), pero es API pública del paquete y entraba con cero líneas ejecutadas.


def _object_storage_doblado():
    from vendi_core.storage.minio import ObjectStorage

    cliente = MagicMock()
    return ObjectStorage(cliente, "negocio-1"), cliente


async def test_object_storage_fija_el_bucket_y_devuelve_la_clave():
    almacen, cliente = _object_storage_doblado()
    cliente.put_object = AsyncMock()

    assert await almacen.put("a.txt", b"12345") == "a.txt"

    args, kwargs = cliente.put_object.call_args
    assert args[0] == "negocio-1"
    assert args[1] == "a.txt"
    assert kwargs["length"] == 5


async def test_object_storage_get_libera_la_respuesta():
    almacen, cliente = _object_storage_doblado()
    respuesta = _RespuestaDoblada(b"datos")
    cliente.get_object = AsyncMock(return_value=respuesta)

    assert await almacen.get("a.txt") == b"datos"
    assert respuesta.cerrada and respuesta.liberada


async def test_object_storage_delete_y_url_prefirmada_usan_su_bucket():
    almacen, cliente = _object_storage_doblado()
    cliente.remove_object = AsyncMock()
    cliente.presigned_get_object = AsyncMock(return_value="https://ejemplo/x")

    await almacen.delete("a.txt")
    cliente.remove_object.assert_awaited_once_with("negocio-1", "a.txt")

    assert await almacen.get_presigned_url("a.txt", expires=60) == "https://ejemplo/x"
    args, kwargs = cliente.presigned_get_object.call_args
    assert args[0] == "negocio-1"
    assert kwargs["expires"].total_seconds() == 60


def test_el_atajo_de_compatibilidad_de_middleware_security_reexporta_la_clase():
    """`vendi_core.middleware.security` es un alias del módulo renombrado. Si
    dejara de reexportar, los imports antiguos fallarían en tiempo de arranque
    de la app y no en ningún test."""
    from vendi_core.middleware.security import SecurityHeadersMiddleware as DesdeAlias
    from vendi_core.middleware.security_headers import SecurityHeadersMiddleware as Real

    assert DesdeAlias is Real
