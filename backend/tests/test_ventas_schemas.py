"""Validación de entrada del sync de ventas, sin base de datos.

Las cotas NO son cosméticas: un entero que desborda su columna sale como
`DataError` de Postgres → 500, no 422 (BUG-2 del QA del catálogo). Todo lo
que entra lleva cota contra su tipo de columna, y los validadores
`mode="before"` no asumen `str` (BUG-1).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.catalogo.schemas import TOPE_PRECIO, TOPE_STOCK
from app.modules.ventas.schemas import (
    LoteSync,
    OperacionSync,
    VentaAnularSync,
    VentaCrearSync,
    VentaItemSync,
)

AHORA = datetime.now(UTC)


def _item(**campos) -> dict:
    return {"producto_id": str(uuid.uuid4()), "cantidad": "1", "precio_unitario_centavos": 2500, **campos}


def _venta(**campos) -> dict:
    return {
        "consecutivo_local": 1,
        "medio_pago": "efectivo",
        "total_centavos": 2500,
        "creada_en_cliente": AHORA.isoformat(),
        "items": [_item()],
        **campos,
    }


def test_una_venta_minima_valida():
    datos = VentaCrearSync.model_validate(_venta())
    assert datos.estado == "completada"
    assert datos.cliente_id is None
    assert datos.items[0].cantidad == Decimal("1")


def test_el_total_no_puede_desbordar_el_int32_de_la_columna():
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(total_centavos=TOPE_PRECIO + 1))
    assert VentaCrearSync.model_validate(_venta(total_centavos=TOPE_PRECIO)).total_centavos == TOPE_PRECIO


def test_la_cantidad_es_positiva_y_cabe_en_numeric_14_3():
    with pytest.raises(ValidationError):
        VentaItemSync.model_validate(_item(cantidad="0"))
    with pytest.raises(ValidationError):
        VentaItemSync.model_validate(_item(cantidad=str(TOPE_STOCK + 1)))
    # El granel: 0,350 kg es una cantidad legítima.
    assert VentaItemSync.model_validate(_item(cantidad="0.350")).cantidad == Decimal("0.350")


def test_el_precio_unitario_no_desborda():
    with pytest.raises(ValidationError):
        VentaItemSync.model_validate(_item(precio_unitario_centavos=-1))
    with pytest.raises(ValidationError):
        VentaItemSync.model_validate(_item(precio_unitario_centavos=TOPE_PRECIO + 1))


def test_el_medio_de_pago_es_uno_de_los_del_mvp():
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(medio_pago="tarjeta"))
    assert VentaCrearSync.model_validate(_venta(medio_pago="fiado", cliente_id=str(uuid.uuid4()))).medio_pago == "fiado"


def test_creada_en_cliente_debe_traer_zona_horaria():
    """El reloj del cliente es dato (se acepta 1970 o 2099, ADR-017), pero un
    timestamp naive no dice nada: sin offset no hay ticket interpretable."""
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(creada_en_cliente="2026-07-28T10:00:00"))
    lejano = VentaCrearSync.model_validate(_venta(creada_en_cliente="2099-01-01T00:00:00+00:00"))
    assert lejano.creada_en_cliente.year == 2099, "el reloj manipulado se guarda como DATO; no se rechaza"


def test_una_venta_sin_items_no_es_una_venta():
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(items=[]))


def test_campos_desconocidos_se_rechazan():
    """`extra="forbid"`: un `tenant_id` inyectado en el payload no se ignora,
    se rechaza — la defensa en profundidad del WITH CHECK de ADR-017."""
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(tenant_id=str(uuid.uuid4())))


def test_el_consecutivo_y_la_secuencia_son_positivos_y_acotados():
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(consecutivo_local=0))
    with pytest.raises(ValidationError):
        OperacionSync(id=uuid.uuid4(), tipo="venta.crear", secuencia=0, datos=_venta())
    # secuencia es BIGINT en columna: la cota es 2^63-1.
    with pytest.raises(ValidationError):
        OperacionSync(id=uuid.uuid4(), tipo="venta.crear", secuencia=2**63, datos=_venta())


def test_el_lote_tiene_tope_de_200_operaciones():
    operacion = {"id": str(uuid.uuid4()), "tipo": "venta.crear", "secuencia": 1, "datos": _venta()}
    with pytest.raises(ValidationError):
        LoteSync(dispositivo_id=uuid.uuid4(), operaciones=[operacion] * 201)
    lote = LoteSync(dispositivo_id=uuid.uuid4(), operaciones=[operacion])
    assert lote.operaciones[0].tipo == "venta.crear"
    assert isinstance(lote.operaciones[0].datos, dict), "datos se valida por operación en el servicio (decisión 6)"


def test_el_tipo_es_texto_libre_acotado():
    """Un tipo desconocido es `rechazada` por operación, no 422 del lote
    (decisión 6): el schema solo acota el largo."""
    operacion = OperacionSync(id=uuid.uuid4(), tipo="venta.futurista", secuencia=1, datos={})
    assert operacion.tipo == "venta.futurista"


def test_anular_solo_necesita_la_venta():
    datos = VentaAnularSync.model_validate({"venta_id": str(uuid.uuid4())})
    assert datos.venta_id is not None
    with pytest.raises(ValidationError):
        VentaAnularSync.model_validate({})
