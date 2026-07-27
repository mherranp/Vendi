"""El modelo `Producto` contra el metadata, sin base de datos.

Es el nivel barato de los candados: corre en cada `pytest` y en cada PR. Lo
caro —que la base migrada tenga la policy, los índices y los grants— lo
cubren `test_rls_coverage.py`, `test_privilegios_de_vendi_app.py` y
`test_aislamiento_productos.py`.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint

from app.modules.catalogo.models import Producto
from vendi_core.db.base import Base, verificar_indices_de_tenant


def test_productos_hereda_tenant_model_y_borrado_logico():
    columnas = Producto.__table__.columns
    for nombre in (
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "deleted_at",
        "padre_id",
        "nombre",
        "codigo_barras",
        "categoria",
        "unidad_medida",
        "precio_venta",
        "ultimo_costo",
        "iva_pct",
        "stock_actual",
        "stock_minimo",
    ):
        assert nombre in columnas, f"falta la columna {nombre}"
    assert columnas["tenant_id"].nullable is False
    assert columnas["codigo_barras"].nullable is True, "el EAN es opcional: el granel no tiene (ADR-019)"
    assert columnas["deleted_at"].nullable is True


def test_la_regla_del_indice_de_tenant_se_cumple_con_el_modelo_registrado():
    # Importar el modelo ya lo registró en el metadata; el candado recorre
    # TODAS las tablas declaradas, no solo ésta.
    assert "productos" not in verificar_indices_de_tenant(Base.metadata)


def test_el_indice_unico_del_ean_es_parcial():
    indice = next(i for i in Producto.__table__.indexes if i.name == "ux_productos_ean")
    assert indice.unique is True
    assert [c.name for c in indice.columns] == ["tenant_id", "codigo_barras"]
    assert indice.dialect_options["postgresql"]["where"] is not None, (
        "sin el WHERE la unicidad aplicaría también a los NULL y solo cabría UN producto sin EAN por negocio"
    )


def test_el_indice_de_listado_empieza_por_tenant():
    indice = next(i for i in Producto.__table__.indexes if i.name == "ix_productos_tenant_nombre")
    assert [c.name for c in indice.columns] == ["tenant_id", "nombre"]


def test_los_checks_fijan_unidades_tarifas_y_dinero_no_negativo():
    checks = {c.name for c in Producto.__table__.constraints if isinstance(c, CheckConstraint)}
    assert {
        "ck_productos_unidad_medida",
        "ck_productos_iva_pct",
        "ck_productos_precio_no_negativo",
        "ck_productos_costo_no_negativo",
    } <= checks
