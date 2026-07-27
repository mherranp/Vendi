"""El metadata de los modelos de inventario es fiel a la migración 0007.

Sin base de datos (no lleva marcador `integration`): compara nombres de
tabla, índices, checks y FKs contra lo que la migración creó. Si las dos
definiciones se separan, este test es el primero en gritar (D-17 registra
que `alembic check` aún no corre en CI; mientras tanto, ESTE es el candado).
"""

from __future__ import annotations

from app.modules.inventario.models import TIPOS_DE_AJUSTE, AjusteInventario, Compra, CompraItem


def test_las_tablas_son_las_de_la_migracion():
    assert Compra.__tablename__ == "compras"
    assert CompraItem.__tablename__ == "compra_items"
    assert AjusteInventario.__tablename__ == "ajustes_inventario"


def test_cada_tabla_tiene_indice_que_empieza_por_tenant():
    for modelo in (Compra, CompraItem, AjusteInventario):
        for indice in modelo.__table__.indexes:
            if list(indice.columns)[0].name == "tenant_id":
                break
        else:
            raise AssertionError(f"{modelo.__tablename__} no tiene índice que empiece por tenant_id")


def test_los_indices_son_los_de_la_migracion():
    assert {i.name for i in Compra.__table__.indexes} == {"ix_compras_tenant_fecha"}
    assert {i.name for i in CompraItem.__table__.indexes} == {
        "ix_compra_items_tenant_compra",
        "ix_compra_items_tenant_producto",
    }
    assert {i.name for i in AjusteInventario.__table__.indexes} == {"ix_ajustes_tenant_producto"}


def test_los_checks_son_los_de_la_migracion():
    nombres = {
        c.name for t in (Compra.__table__, CompraItem.__table__, AjusteInventario.__table__) for c in t.constraints
    }
    assert {
        "ck_compras_total_no_negativo",
        "ck_compra_items_cantidad_positiva",
        "ck_compra_items_costo_no_negativo",
        "ck_ajustes_tipo",
        "ck_ajustes_forma",
        "ck_ajustes_cantidad_positiva",
        "ck_ajustes_conteo_no_negativo",
    } <= nombres


def test_las_fk_son_restrict():
    compra_fks = {f.column.table.name: f.ondelete for f in CompraItem.__table__.foreign_keys}
    assert compra_fks == {"compras": "RESTRICT", "productos": "RESTRICT"}
    ajuste_fks = {f.column.table.name: f.ondelete for f in AjusteInventario.__table__.foreign_keys}
    assert ajuste_fks == {"productos": "RESTRICT"}


def test_los_tipos_de_ajuste_son_los_del_check():
    assert TIPOS_DE_AJUSTE == ("ajuste", "merma")
