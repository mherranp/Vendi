"""Las reglas duras de la entrada del módulo inventario (sin base de datos).

Cotas contra la columna (un overflow es un DataError → 500, no un 422),
cuantización a los 3 decimales de la columna, forma por tipo de ajuste,
motivo obligatorio y `extra="forbid"`. Las lecciones de los dos QA
adversariales, fijadas antes de escribir el schema.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.inventario.schemas import AjusteCrear, CompraCrear, CompraItemEntrada

_PRODUCTO_ID = str(uuid.uuid4())


def _item(**cambios) -> dict:
    cuerpo = {"producto_id": _PRODUCTO_ID, "cantidad": "2", "costo_unitario_centavos": 2500}
    cuerpo.update(cambios)
    return cuerpo


def _compra(**cambios) -> dict:
    cuerpo = {"proveedor_nombre": "Distribuidora La 33", "items": [_item()]}
    cuerpo.update(cambios)
    return cuerpo


def _ajuste(**cambios) -> dict:
    cuerpo = {
        "id": str(uuid.uuid4()),
        "tipo": "ajuste",
        "producto_id": str(uuid.uuid4()),
        "stock_contado": "14",
        "motivo": "Conteo de cierre",
    }
    cuerpo.update(cambios)
    return cuerpo


# --- Compra ---------------------------------------------------------------------


def test_la_compra_feliz_cuantiza_la_cantidad_y_acepta_fecha():
    compra = CompraCrear.model_validate(_compra(fecha=str(date(2026, 7, 20)), items=[_item(cantidad="0.3334")]))
    assert compra.items[0].cantidad == Decimal("0.333")
    assert compra.fecha == date(2026, 7, 20)


def test_la_cantidad_que_cuantiza_a_cero_se_rechaza():
    # BUG-2 del QA de ventas: 0.0004 cabría redondeado a 0.000 por Postgres y
    # reventaba el CHECK como 500. El schema lo corta como dato inválido.
    with pytest.raises(ValidationError):
        CompraItemEntrada.model_validate(_item(cantidad="0.0004"))


def test_la_cantidad_de_cuatro_decimales_se_cuantiza_como_postgres():
    item = CompraItemEntrada.model_validate(_item(cantidad="0.3335"))
    assert item.cantidad == Decimal("0.334")  # ROUND_HALF_UP, el mismo redondeo de la columna


def test_el_costo_no_puede_desbordar_el_integer():
    with pytest.raises(ValidationError):
        CompraItemEntrada.model_validate(_item(costo_unitario_centavos=2**31))
    assert CompraItemEntrada.model_validate(_item(costo_unitario_centavos=2**31 - 1))


def test_la_cantidad_no_puede_desbordar_el_numeric():
    with pytest.raises(ValidationError):
        CompraItemEntrada.model_validate(_item(cantidad="100000000000"))  # 12 dígitos enteros: no cabe en (14,3)


def test_el_proveedor_se_limpia_antes_de_medir():
    compra = CompraCrear.model_validate(_compra(proveedor_nombre="  Distribuidora   La 33  "))
    assert compra.proveedor_nombre == "Distribuidora La 33"
    with pytest.raises(ValidationError):
        CompraCrear.model_validate(_compra(proveedor_nombre="   "))  # limpia a "" y choca con min_length


def test_el_limpiador_no_asume_str():
    with pytest.raises(ValidationError):
        CompraCrear.model_validate(_compra(proveedor_nombre=123))  # 422 de pydantic, no AttributeError


def test_un_producto_repetido_en_dos_lineas_es_422():
    with pytest.raises(ValidationError, match="mismo producto"):
        CompraCrear.model_validate(_compra(items=[_item(), _item()]))  # el helper usa el MISMO producto_id


def test_la_compra_no_acepta_campos_desconocidos():
    with pytest.raises(ValidationError):
        CompraCrear.model_validate(_compra(tenant_id=str(uuid.uuid4()), total_centavos=5))


def test_la_compra_exige_al_menos_un_item():
    with pytest.raises(ValidationError):
        CompraCrear.model_validate(_compra(items=[]))


# --- Ajuste y merma ---------------------------------------------------------------


def test_el_ajuste_exige_id_tipo_conteo_y_motivo():
    ajuste = AjusteCrear.model_validate(_ajuste())
    assert ajuste.stock_contado == Decimal("14")
    for falta in ("id", "stock_contado", "motivo"):
        cuerpo = _ajuste()
        del cuerpo[falta]
        with pytest.raises(ValidationError):
            AjusteCrear.model_validate(cuerpo)


def test_el_ajuste_rechaza_la_cantidad_que_es_de_merma():
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(cantidad="2"))


def test_la_merma_exige_cantidad_y_rechaza_conteo():
    merma = AjusteCrear.model_validate(_ajuste(tipo="merma", cantidad="3", stock_contado=None, motivo="Se dañó"))
    assert merma.cantidad == Decimal("3")
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(tipo="merma", stock_contado=None, motivo="Se dañó"))  # sin cantidad
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(tipo="merma", cantidad="3", motivo="Se dañó"))  # con conteo


def test_el_conteo_cero_es_valido_y_se_cuantiza():
    ajuste = AjusteCrear.model_validate(_ajuste(stock_contado="0.0004"))
    assert ajuste.stock_contado == Decimal("0")  # el conteo cero es legítimo; se guarda cuantizado


def test_el_motivo_se_limpia_y_exige_tres_letras():
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(motivo="  ok "))  # limpia a "ok": menos de 3
    assert AjusteCrear.model_validate(_ajuste(motivo="  Conteo   de cierre  ")).motivo == "Conteo de cierre"


def test_el_ajuste_no_acepta_campos_desconocidos():
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(tenant_id=str(uuid.uuid4())))


def test_el_tipo_solo_admite_ajuste_o_merma():
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(tipo="correccion"))
