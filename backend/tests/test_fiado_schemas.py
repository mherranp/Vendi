"""Las reglas de los schemas del fiado (cotas, limpieza, teléfono, listas)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.catalogo.schemas import TOPE_PRECIO
from app.modules.fiado.schemas import (
    AbonoCrear,
    AbonoSync,
    ClienteCrear,
    ClienteCrearSync,
    ClienteEditar,
    CreditoReprogramar,
)


def _cliente(**cambios) -> dict:
    return {"nombre": "Don Carlos", "telefono": "300 123 4567", **cambios}


def test_cliente_crear_valido_y_limpieza():
    c = ClienteCrear.model_validate(_cliente(nombre="  Don   Carlos  "))
    assert c.nombre == "Don Carlos"
    assert c.telefono == "3001234567"  # espacios fuera; solo dígitos
    assert c.id is None and c.limite_credito is None and c.nota is None


def test_el_telefono_admite_indicativo_y_rechaza_lo_que_no_es_whatsapp():
    assert ClienteCrear.model_validate(_cliente(telefono="+57 3001234567")).telefono == "573001234567"
    for malo in ("12345", "3001234567890123456", "trescientos", "300-123-45-67x"):
        with pytest.raises(ValidationError):
            ClienteCrear.model_validate(_cliente(telefono=malo))


def test_el_telefono_es_opcional():
    assert ClienteCrear.model_validate({"nombre": "La vecina"}).telefono is None


def test_el_limite_lleva_cota_y_no_es_negativo():
    with pytest.raises(ValidationError):
        ClienteCrear.model_validate(_cliente(limite_credito=-1))
    with pytest.raises(ValidationError):
        ClienteCrear.model_validate(_cliente(limite_credito=TOPE_PRECIO + 1))
    assert ClienteCrear.model_validate(_cliente(limite_credito=0)).limite_credito == 0  # cero: no fiarle más


def test_los_campos_desconocidos_se_rechazan():
    with pytest.raises(ValidationError):
        ClienteCrear.model_validate(_cliente(tenant_id=str(uuid.uuid4())))
    with pytest.raises(ValidationError):
        AbonoCrear.model_validate(
            {"id": str(uuid.uuid4()), "monto": 100, "metodo_pago": "efectivo", "tenant_id": str(uuid.uuid4())}
        )


def test_el_nombre_no_son_puros_espacios():
    with pytest.raises(ValidationError):
        ClienteCrear.model_validate({"nombre": "    "})


def test_cliente_editar_todo_opcional_y_limite_borrable():
    assert ClienteEditar.model_validate({}).model_dump(exclude_unset=True) == {}
    # null explícito: quitar el cupo (vuelve a «sin tope»).
    assert ClienteEditar.model_validate({"limite_credito": None}).limite_credito is None
    with pytest.raises(ValidationError):
        ClienteEditar.model_validate({"nombre": "x"})


def test_abono_exige_id_monto_positivo_y_metodo_de_la_lista():
    with pytest.raises(ValidationError):
        AbonoCrear.model_validate({"monto": 100, "metodo_pago": "efectivo"})  # sin id (la ancla)
    for malo in (0, -100, TOPE_PRECIO + 1):
        with pytest.raises(ValidationError):
            AbonoCrear.model_validate({"id": str(uuid.uuid4()), "monto": malo, "metodo_pago": "efectivo"})
    with pytest.raises(ValidationError):
        AbonoCrear.model_validate({"id": str(uuid.uuid4()), "monto": 100, "metodo_pago": "nequi"})
    ok = AbonoCrear.model_validate({"id": str(uuid.uuid4()), "monto": 100, "metodo_pago": "transferencia"})
    assert ok.nota is None


def test_la_nota_se_limpia_y_es_opcional():
    ok = AbonoCrear.model_validate(
        {"id": str(uuid.uuid4()), "monto": 100, "metodo_pago": "otro", "nota": "  dejó   el  destajo  "}
    )
    assert ok.nota == "dejó el destajo"


def test_reprogramar_admite_fecha_o_null():
    assert CreditoReprogramar.model_validate({"fecha_vencimiento": "2026-08-15"}).fecha_vencimiento is not None
    assert CreditoReprogramar.model_validate({"fecha_vencimiento": None}).fecha_vencimiento is None
    # El campo es REQUERIDO: un body `{}` no es «sin fecha», es un payload
    # ambiguo — 422. Dejar el fiado sin recordatorio exige el `null`
    # explícito (un gesto deliberado, nunca el default de un campo ausente).
    with pytest.raises(ValidationError):
        CreditoReprogramar.model_validate({})


def test_cliente_sync_es_el_contrato_del_lote():
    ok = ClienteCrearSync.model_validate({"nombre": "Don Carlos", "telefono": "3001234567"})
    assert ok.limite_credito is None
    with pytest.raises(ValidationError):
        ClienteCrearSync.model_validate({"nombre": "X"})


def _abono_sync(**cambios) -> dict:
    base = {
        "cliente_id": str(uuid.uuid4()),
        "credito_id": str(uuid.uuid4()),
        "monto": 13000,
        "metodo_pago": "efectivo",
    }
    base.update(cambios)
    return base


def test_abono_sync_exige_cliente_credito_monto_y_metodo():
    """El contrato de `fiado.abonar` (cierre de D-27): el `cliente_id` es
    REQUERIDO como ancla y `sesion_caja_id` no viaja — lo resuelve el
    servidor (`extra="forbid"`)."""
    ok = AbonoSync.model_validate(_abono_sync())
    assert ok.monto == 13000 and ok.metodo_pago == "efectivo" and ok.nota is None
    for falta in ("cliente_id", "credito_id", "monto", "metodo_pago"):
        datos = _abono_sync()
        del datos[falta]
        with pytest.raises(ValidationError):
            AbonoSync.model_validate(datos)
    with pytest.raises(ValidationError):
        AbonoSync.model_validate(_abono_sync(sesion_caja_id=str(uuid.uuid4())))


def test_abono_sync_lleva_las_cotas_del_abono_online():
    for malo in (0, -1, TOPE_PRECIO + 1):
        with pytest.raises(ValidationError):
            AbonoSync.model_validate(_abono_sync(monto=malo))
    with pytest.raises(ValidationError):
        AbonoSync.model_validate(_abono_sync(metodo_pago="nequi"))
    ok = AbonoSync.model_validate(_abono_sync(nota="  dejó   el  destajo  "))
    assert ok.nota == "dejó el destajo"
    # El validador `before` de la nota NO asume str (BUG-1 del catálogo): un
    # tipo erróneo lo rechaza pydantic, no un AttributeError.
    with pytest.raises(ValidationError):
        AbonoSync.model_validate(_abono_sync(nota=123))
