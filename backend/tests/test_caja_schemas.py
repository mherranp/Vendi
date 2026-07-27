"""Schemas de caja y reportes: cotas contra la columna, motivo limpio y
obligatorio, listas cerradas, `extra="forbid"`. Sin base de datos."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.caja.schemas import MovimientoCrear, SesionAbrir, SesionCerrar


def test_la_apertura_valida_minima():
    datos = SesionAbrir.model_validate({})
    assert datos.base_inicial == 0 and datos.id is None


def test_la_base_no_es_negativa_ni_desborda_el_integer():
    with pytest.raises(ValidationError):
        SesionAbrir.model_validate({"base_inicial": -1})
    with pytest.raises(ValidationError):
        SesionAbrir.model_validate({"base_inicial": 2**31})  # DataError → 500 sin la cota (BUG-2)
    assert SesionAbrir.model_validate({"base_inicial": 2**31 - 1}).base_inicial == 2**31 - 1


def test_la_apertura_acepta_el_id_del_cliente():
    el_id = str(uuid.uuid4())
    assert SesionAbrir.model_validate({"id": el_id, "base_inicial": 50000}).id == uuid.UUID(el_id)


def test_el_cierre_exige_conteo_valido():
    with pytest.raises(ValidationError):
        SesionCerrar.model_validate({})  # el conteo es requerido: arquear es contar
    with pytest.raises(ValidationError):
        SesionCerrar.model_validate({"contado": -100})
    with pytest.raises(ValidationError):
        SesionCerrar.model_validate({"contado": 2**31})
    assert SesionCerrar.model_validate({"contado": 0}).contado == 0  # gaveta vacía: legítimo


def test_el_movimiento_exige_id_tipo_categoria_monto_y_motivo():
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({"tipo": "egreso", "categoria": "otro", "monto": 100, "motivo": "x" * 3})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({"id": str(uuid.uuid4()), "categoria": "otro", "monto": 100, "motivo": "x" * 3})


def test_el_monto_es_estrictamente_positivo_y_cabezon():
    base = {"id": str(uuid.uuid4()), "tipo": "ingreso", "categoria": "otro", "motivo": "Venta de la nevera vieja"}
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "monto": 0})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "monto": -500})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "monto": 2**31})


def test_tipo_y_categoria_son_listas_cerradas():
    base = {"id": str(uuid.uuid4()), "monto": 100, "motivo": "Retiro para el banco"}
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "tipo": "transferencia", "categoria": "otro"})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "tipo": "egreso", "categoria": "ropa"})
    ok = MovimientoCrear.model_validate({**base, "tipo": "egreso", "categoria": "retiro_dueno"})
    assert ok.categoria == "retiro_dueno"


def test_el_motivo_se_limpia_antes_de_la_cota_y_no_admite_vacios():
    base = {"id": str(uuid.uuid4()), "tipo": "egreso", "categoria": "servicios", "monto": 12000}
    limpio = MovimientoCrear.model_validate({**base, "motivo": "  Recibo   de\n la  luz  "})
    assert limpio.motivo == "Recibo de la luz"
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "motivo": "   "})  # limpia a "" y choca con min_length
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "motivo": "ab"})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "motivo": "x" * 301})


def test_los_validadores_before_no_asumen_str():
    """Lo que no es str pasa intacto para que pydantic lo rechace como 422
    (BUG-1 del QA del catálogo): nunca un AttributeError → 500."""
    base = {"id": str(uuid.uuid4()), "tipo": "egreso", "categoria": "otro", "monto": 100}
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "motivo": 123})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "motivo": ["lista"]})


def test_extra_forbid_en_las_tres_entradas():
    with pytest.raises(ValidationError):
        SesionAbrir.model_validate({"base_inicial": 0, "tenant_id": str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        SesionCerrar.model_validate({"contado": 0, "tenant_id": str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate(
            {
                "id": str(uuid.uuid4()),
                "tipo": "ingreso",
                "categoria": "otro",
                "monto": 1,
                "motivo": "prueba",
                "tenant_id": str(uuid.uuid4()),
            }
        )
