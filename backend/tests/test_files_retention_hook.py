"""Hook de pre-purga de `files`: borra el objeto antes de que muera la fila.

`vendi_core.files.retention` viene de `base_saas.files.retention`.

Lo que se fija, y por qué importa: el hook es **permisivo a propósito**. Si el
objeto ya no está en el bucket —lo borró alguien a mano, o el bucket desapareció
en una migración— el hook registra un aviso y deja que la fila se vaya igual. La
alternativa (fallar la política entera) dejaría filas huérfanas para siempre,
apuntando a objetos que no existen, y la retención nunca las limpiaría.
"""

from __future__ import annotations

from unittest.mock import patch

from vendi_core.files.retention import make_storage_cleanup_hook


class _AlmacenamientoDoblado:
    def __init__(self, falla_en: set[tuple[str, str]] | None = None):
        self.borrados: list[tuple[str, str]] = []
        self._falla_en = falla_en or set()

    async def delete(self, bucket: str, key: str) -> None:
        if (bucket, key) in self._falla_en:
            raise RuntimeError("el bucket no responde")
        self.borrados.append((bucket, key))


def _fila(bucket: str, key: str) -> dict:
    return {"id": key, "bucket": bucket, "key": key}


async def test_el_hook_borra_el_objeto_de_cada_fila():
    almacen = _AlmacenamientoDoblado()
    hook = make_storage_cleanup_hook(almacen)

    await hook(None, [_fila("negocio-1", "a.png"), _fila("negocio-1", "b.png")])

    assert almacen.borrados == [("negocio-1", "a.png"), ("negocio-1", "b.png")]


async def test_un_objeto_que_ya_no_esta_no_bloquea_a_los_demas():
    """El caso permisivo: si fallar cortara la pasada, las filas huérfanas se
    quedarían para siempre y la retención no limpiaría nunca."""
    almacen = _AlmacenamientoDoblado(falla_en={("negocio-1", "roto.png")})
    hook = make_storage_cleanup_hook(almacen)

    with patch("vendi_core.files.retention.logger") as logger_doblado:
        await hook(None, [_fila("negocio-1", "roto.png"), _fila("negocio-1", "bueno.png")])

    assert almacen.borrados == [("negocio-1", "bueno.png")]
    assert logger_doblado.warning.called
    evento, *_ = logger_doblado.warning.call_args.args
    assert evento == "files_storage_delete_failed"


async def test_sin_filas_el_hook_no_toca_el_almacenamiento():
    almacen = _AlmacenamientoDoblado()
    await make_storage_cleanup_hook(almacen)(None, [])
    assert almacen.borrados == []
