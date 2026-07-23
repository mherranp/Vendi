"""Sobres de respuesta y parámetros de paginación.

`vendi_core.models` viene de `base_saas.models`; BaseSaaS no tenía un test
propio del paquete (se ejercía de refilón desde los routers, que en Vendi
todavía no existen). Se escribe aquí porque los límites de `PageParams` son un
contrato de la API: `limit` sin tope superior es una denegación de servicio
regalada —`?limit=1000000` sobre la tabla de ventas de una región— y `skip`
negativo revienta en el `OFFSET`.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from vendi_core.models import ErrorResponse, PagedList, PageParams, SuccessResponse


def test_los_valores_por_defecto_de_paginacion_son_los_del_contrato():
    p = PageParams()
    assert p.skip == 0
    assert p.limit == 25


def test_el_limite_superior_esta_acotado():
    """Sin tope, `?limit=1000000` es una denegación de servicio regalada."""
    assert PageParams(limit=200).limit == 200
    with pytest.raises(ValidationError):
        PageParams(limit=201)


def test_el_limite_inferior_no_admite_cero_ni_negativos():
    with pytest.raises(ValidationError):
        PageParams(limit=0)
    with pytest.raises(ValidationError):
        PageParams(limit=-1)


def test_skip_no_admite_negativos():
    with pytest.raises(ValidationError):
        PageParams(skip=-1)


class _Cosa(BaseModel):
    nombre: str


def test_el_sobre_paginado_es_generico_y_valida_sus_elementos():
    pagina = PagedList[_Cosa](items=[_Cosa(nombre="a")], total=1, skip=0, limit=25)
    assert pagina.items[0].nombre == "a"
    assert pagina.total == 1

    with pytest.raises(ValidationError):
        PagedList[_Cosa](items=[{"otro_campo": 1}], total=1, skip=0, limit=25)


def test_el_sobre_paginado_lee_de_atributos_no_solo_de_dicts():
    """`from_attributes=True`: los routers le pasan filas del ORM directamente."""

    class _Fila:
        nombre = "desde-orm"

    pagina = PagedList[_Cosa].model_validate(
        {"items": [_Fila()], "total": 1, "skip": 0, "limit": 25},
        from_attributes=True,
    )
    assert pagina.items[0].nombre == "desde-orm"


def test_el_sobre_de_exito_es_exito_por_defecto():
    r = SuccessResponse(data={"id": 1})
    assert r.success is True
    assert r.data == {"id": 1}
    assert r.message is None


def test_el_sobre_de_error_exige_mensaje_y_nunca_dice_exito():
    r = ErrorResponse(message="no encontrado", code="NOT_FOUND")
    assert r.success is False
    assert r.code == "NOT_FOUND"
    with pytest.raises(ValidationError):
        ErrorResponse()  # type: ignore[call-arg]
