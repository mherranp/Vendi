"""Los modelos del módulo ventas contra el metadata, sin base de datos.

Es el nivel barato de los candados: corre en cada `pytest` y en cada PR. Lo
caro —que la base migrada tenga las policies, los índices y los grants— lo
cubren `test_rls_coverage.py`, `test_privilegios_de_vendi_app.py` y
`test_aislamiento_ventas.py`.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint

from app.modules.ventas.models import CajaSesion, MovimientoInventario, Venta, VentaItem
from vendi_core.db.base import Base, verificar_indices_de_tenant


def test_ventas_tiene_las_columnas_de_adr_018():
    columnas = Venta.__table__.columns
    for nombre in (
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "dispositivo_id",
        "sesion_caja_id",
        "consecutivo_local",
        "estado",
        "medio_pago",
        "total_centavos",
        "cliente_id",
        "creada_en_cliente",
        "recibida_en",
        "secuencia_dispositivo",
    ):
        assert nombre in columnas, f"falta la columna {nombre}"
    assert columnas["cliente_id"].nullable is True, "cliente_id es NULL salvo fiado (ADR-018)"
    assert columnas["sesion_caja_id"].nullable is False, "el sync siempre resuelve la sesión (decisión 13)"
    assert "deleted_at" not in columnas, "la venta es append-only: no hay borrado, hay anulación"


def test_ventas_items_congela_el_precio():
    columnas = VentaItem.__table__.columns
    for nombre in ("id", "tenant_id", "venta_id", "producto_id", "cantidad", "precio_unitario_centavos"):
        assert nombre in columnas, f"falta la columna {nombre}"


def test_movimientos_es_el_libro_con_referencia_de_origen():
    columnas = MovimientoInventario.__table__.columns
    for nombre in ("id", "tenant_id", "tipo", "cantidad", "referencia_id", "producto_id"):
        assert nombre in columnas, f"falta la columna {nombre}"
    assert "deleted_at" not in columnas, "un movimiento jamás se edita ni se borra (ADR-020)"


def test_la_regla_del_indice_de_tenant_se_cumple_con_los_modelos_registrados():
    for tabla in ("ventas", "ventas_items", "dispositivos", "caja_sesiones", "movimientos_inventario"):
        assert tabla not in verificar_indices_de_tenant(Base.metadata)


def test_los_indices_unicos_del_modelo():
    consecutivo = next(i for i in Venta.__table__.indexes if i.name == "ux_ventas_consecutivo")
    assert consecutivo.unique is True
    assert [c.name for c in consecutivo.columns] == ["tenant_id", "dispositivo_id", "consecutivo_local"]

    origen = next(i for i in MovimientoInventario.__table__.indexes if i.name == "ux_movimientos_origen")
    assert origen.unique is True
    assert [c.name for c in origen.columns] == ["tenant_id", "tipo", "referencia_id", "producto_id"], (
        "sin producto_id, la segunda línea de un ticket chocaría con la primera (decisión 2 del plan)"
    )

    abierta = next(i for i in CajaSesion.__table__.indexes if i.name == "ux_caja_sesion_abierta")
    assert abierta.unique is True
    assert [c.name for c in abierta.columns] == ["tenant_id"]
    assert abierta.dialect_options["postgresql"]["where"] is not None, (
        "sin el WHERE solo cabría UNA sesión por negocio en toda su historia"
    )


def test_los_checks_fijan_estados_cantidades_y_dinero():
    def nombres(modelo):
        return {c.name for c in modelo.__table__.constraints if isinstance(c, CheckConstraint)}

    assert {
        "ck_ventas_estado",
        "ck_ventas_consecutivo_positivo",
        "ck_ventas_total_no_negativo",
        "ck_ventas_secuencia_positiva",
    } <= nombres(Venta)
    assert {"ck_ventas_items_cantidad_positiva", "ck_ventas_items_precio_no_negativo"} <= nombres(VentaItem)
    assert {"ck_movimientos_tipo", "ck_movimientos_cantidad_no_cero"} <= nombres(MovimientoInventario)
    assert {"ck_caja_sesiones_estado", "ck_caja_sesiones_base_no_negativa"} <= nombres(CajaSesion)
