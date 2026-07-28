"""La metadata de los modelos del fiado contra el contrato de la 0009."""

from __future__ import annotations

from sqlalchemy import CheckConstraint

from app.modules.fiado.models import ESTADOS_DE_CREDITO, METODOS_DE_PAGO_ABONO, Cliente, FiadoAbono, FiadoCredito


def test_las_tres_tablas_tienen_su_nombre_y_tenant():
    assert Cliente.__tablename__ == "clientes"
    assert FiadoCredito.__tablename__ == "fiado_creditos"
    assert FiadoAbono.__tablename__ == "fiado_abonos"
    for modelo in (Cliente, FiadoCredito, FiadoAbono):
        assert "tenant_id" in modelo.__table__.columns


def test_las_listas_cerradas_son_las_de_la_migracion():
    assert ESTADOS_DE_CREDITO == ("vigente", "vencido", "saldado", "anulado")
    assert METODOS_DE_PAGO_ABONO == ("efectivo", "transferencia", "otro")


def test_el_credito_lleva_los_checks_del_saldo_y_la_unicidad_por_venta():
    tabla = FiadoCredito.__table__
    checks = {c.name for c in tabla.constraints if isinstance(c, CheckConstraint)}
    assert {
        "ck_fiado_creditos_monto_positivo",
        "ck_fiado_creditos_saldo_no_negativo",
        "ck_fiado_creditos_saldo_acotado",
        "ck_fiado_creditos_estado",
    } <= checks
    unicos = {u.name for c in tabla.constraints for u in [c] if c.__class__.__name__ == "UniqueConstraint"}
    assert "ux_fiado_creditos_venta" in unicos
    columnas = tabla.columns
    assert columnas["saldo_pendiente"].nullable is False
    assert columnas["fecha_vencimiento"].nullable is True  # sin fecha = sin recordatorio (ADR-022)
    fks = {fk.target_fullname for fk in tabla.foreign_keys}
    assert fks == {"clientes.id", "ventas.id"}


def test_el_abono_referencia_credito_y_opcionalmente_sesion():
    tabla = FiadoAbono.__table__
    checks = {c.name for c in tabla.constraints if isinstance(c, CheckConstraint)}
    assert {"ck_fiado_abonos_monto_positivo", "ck_fiado_abonos_metodo"} <= checks
    assert tabla.columns["sesion_caja_id"].nullable is True  # NULL fuera del efectivo (decisión 9)
    fks = {fk.target_fullname for fk in tabla.foreign_keys}
    assert fks == {"fiado_creditos.id", "caja_sesiones.id"}


def test_los_indices_empiezan_por_tenant_id():
    esperados = {
        "clientes": {"ix_clientes_tenant_nombre"},
        "fiado_creditos": {"ix_fiado_creditos_tenant_cliente", "ix_fiado_creditos_tenant_estado"},
        "fiado_abonos": {"ix_fiado_abonos_tenant_credito", "ix_fiado_abonos_tenant_sesion"},
    }
    for modelo in (Cliente, FiadoCredito, FiadoAbono):
        indices = {i.name: i for i in modelo.__table__.indexes}
        assert esperados[modelo.__tablename__] <= set(indices)
        for nombre in esperados[modelo.__tablename__]:
            assert indices[nombre].columns.values()[0].name == "tenant_id"
