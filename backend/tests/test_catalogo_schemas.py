"""Validación de entrada del catálogo, sin base de datos.

Lo que se prueba aquí es lo que el 422 le promete al tendero: que un precio
negativo, una tarifa de IVA que no existe o una unidad inventada no llegan
jamás a la base.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.catalogo.schemas import ProductoActualizar, ProductoCrear, ProductoSalida


def test_crear_acepta_un_producto_minimo():
    datos = ProductoCrear(nombre="Arroz 500g", precio_venta=2500)
    assert datos.id is None
    assert datos.unidad_medida == "unidad"
    assert datos.iva_pct == Decimal("0")
    assert datos.codigo_barras is None


def test_crear_acepta_el_uuid_del_cliente():
    """ADR-017: el dispositivo genera el id y el servidor lo acepta como PK."""
    el_id = uuid.uuid4()
    assert ProductoCrear(id=el_id, nombre="Huevo", precio_venta=500).id == el_id


def test_el_precio_no_puede_ser_negativo():
    with pytest.raises(ValidationError):
        ProductoCrear(nombre="Arroz", precio_venta=-1)


def test_el_iva_solo_admite_las_tres_tarifas_de_colombia():
    with pytest.raises(ValidationError):
        ProductoCrear(nombre="Arroz", precio_venta=100, iva_pct=Decimal("8"))
    for tarifa in ("0", "5", "19"):
        assert ProductoCrear(nombre="Arroz", precio_venta=100, iva_pct=Decimal(tarifa)).iva_pct == Decimal(tarifa)


def test_la_unidad_solo_admite_las_cinco_del_adr():
    with pytest.raises(ValidationError):
        ProductoCrear(nombre="Arroz", precio_venta=100, unidad_medida="bulto")
    assert ProductoCrear(nombre="Fruver", precio_venta=100, unidad_medida="kg").unidad_medida == "kg"


def test_el_ean_en_blanco_se_normaliza_a_none():
    """Un EAN vacío no es un EAN: sin esta normalización, el segundo producto
    sin código chocaría con el primero en el índice único (cadena vacía)."""
    assert ProductoCrear(nombre="Arroz", precio_venta=100, codigo_barras="   ").codigo_barras is None
    assert ProductoCrear(nombre="Arroz", precio_venta=100, codigo_barras=" 7701 ").codigo_barras == "7701"


def test_el_nombre_se_limpia_de_espacios():
    assert ProductoCrear(nombre="  Arroz   500g ", precio_venta=100).nombre == "Arroz 500g"


def test_el_nombre_no_puede_quedar_vacio_tras_la_limpieza():
    """`min_length=1` se evalúa antes de la limpieza: un nombre de puros
    espacios pasaba la constraint y quedaba en "" sin CHECK que lo salvara.
    La limpieza va primero y el nombre vacío se rechaza."""
    with pytest.raises(ValidationError):
        ProductoCrear(nombre="   ", precio_venta=100)
    with pytest.raises(ValidationError):
        ProductoCrear(nombre="", precio_venta=100)


def test_actualizar_rechaza_un_nombre_que_queda_vacio():
    """En el PATCH un nombre presente pero vacío tras limpiar es un error,
    no un "no lo toques": para eso está `None`."""
    with pytest.raises(ValidationError):
        ProductoActualizar(nombre="   ")


def test_actualizar_es_todo_opcional_y_none_es_no_tocar():
    datos = ProductoActualizar()
    assert datos.model_dump(exclude_unset=True) == {}
    assert ProductoActualizar(precio_venta=3000).precio_venta == 3000


def test_actualizar_rechaza_los_mismos_valores_invalidos():
    with pytest.raises(ValidationError):
        ProductoActualizar(iva_pct=Decimal("7"))
    with pytest.raises(ValidationError):
        ProductoActualizar(unidad_medida="arroba")


def test_el_nombre_que_no_es_texto_se_rechaza_como_422_no_como_500():
    """El validador de limpieza corre en mode="before", antes de la validación
    de tipo: si intentara limpiar un int/lista/dict reventaría con
    AttributeError y el catch-all lo devolvería como 500. Lo no-texto pasa
    intacto y lo rechaza pydantic con el ValidationError estándar (422)."""
    for invalido in (123, [], {}):
        with pytest.raises(ValidationError):
            ProductoCrear(nombre=invalido, precio_venta=100)
        with pytest.raises(ValidationError):
            ProductoActualizar(nombre=invalido)


def test_el_precio_cabe_en_el_integer_de_la_columna():
    """`precio_venta` es Integer (máx. 2^31-1): sin cota, un valor mayor
    llegaba a la base y el DataError salía como 500 en vez de 422."""
    assert ProductoCrear(nombre="Arroz", precio_venta=2_147_483_647).precio_venta == 2_147_483_647
    with pytest.raises(ValidationError):
        ProductoCrear(nombre="Arroz", precio_venta=2_147_483_648)
    assert ProductoActualizar(precio_venta=2_147_483_647).precio_venta == 2_147_483_647
    with pytest.raises(ValidationError):
        ProductoActualizar(precio_venta=2_147_483_648)


def test_el_stock_minimo_cabe_en_el_numeric_de_la_columna():
    """`stock_minimo` es Numeric(14, 3): el máximo que cabe es
    99_999_999_999.999. Un valor con más de 14 dígitos desbordaba la columna
    y el DataError de Postgres salía como 500."""
    tope = Decimal("99999999999.999")
    assert ProductoCrear(nombre="Arroz", precio_venta=100, stock_minimo=tope).stock_minimo == tope
    with pytest.raises(ValidationError):
        ProductoCrear(nombre="Arroz", precio_venta=100, stock_minimo=Decimal("100000000000"))
    assert ProductoActualizar(stock_minimo=tope).stock_minimo == tope
    with pytest.raises(ValidationError):
        ProductoActualizar(stock_minimo=Decimal("100000000000"))


def test_salida_expone_el_stock_y_el_costo_solo_como_lectura():
    """`stock_actual` y `ultimo_costo` están en la salida (los lee el POS) y
    NO en los schemas de entrada (los mueven inventario y compras, ADR-020)."""
    campos_entrada = set(ProductoCrear.model_fields) | set(ProductoActualizar.model_fields)
    assert "stock_actual" not in campos_entrada
    assert "ultimo_costo" not in campos_entrada
    assert {"stock_actual", "ultimo_costo", "stock_minimo"} <= set(ProductoSalida.model_fields)
