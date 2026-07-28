"""Fiado y clientes: `clientes`, `fiado_creditos` y `fiado_abonos`
(ADR-022, decisiones 1-5 y 9 del plan del módulo).

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-28

## Qué crea

- `clientes` (ADR-009/ADR-022): la entidad mínima — `nombre`, `telefono`
  (formato WhatsApp colombiano, sin validación internacional en MVP), `nota`
  y `limite_credito` opcional. La PK la pone el cliente cuando nace offline
  (mismo patrón que `ventas` y `productos`: es el cierre de D-10 por
  adopción — `ventas.cliente_id` se queda SIN FK a propósito, decisión 4).
- `fiado_creditos` (ADR-022): una fila por venta fiada (`ux_fiado_creditos_venta`:
  UN crédito por venta — la red del doble crédito, decisión 5). `monto_total`
  y `saldo_pendiente` en centavos enteros; el saldo SÍ se materializa y se
  descuenta en la misma transacción de cada abono, con
  `CHECK (saldo_pendiente >= 0)` como red: el desfase es un error, no un dato
  malo. `estado` es de lista cerrada: las tres firmadas (`vigente`,
  `vencido`, `saldado`) más `anulado` (decisión 3: la anulación de la venta
  fiada anula el crédito; append-only, nunca se borra). `fecha_vencimiento`
  nullable: sin fecha no hay recordatorio (ADR-022).
- `fiado_abonos` (ADR-022): cada pago parcial o total. `monto` estrictamente
  positivo (el movimiento inverso NO es un abono negativo: es un egreso de
  caja manual, decisión 3), `metodo_pago` de lista cerrada (`efectivo`,
  `transferencia`, `otro` — ampliarla exige migración: el arqueo distingue
  por ella, decisión 9) y `sesion_caja_id` NULLABLE: la sesión que cobró el
  efectivo (los demás métodos no tocan la gaveta). Los abonos NO se duplican
  como movimientos de caja: el arqueo los suma desde aquí (ADR-021).

## Grants

Los privilegios por defecto conceden los cuatro a `vendi_app` sobre toda
tabla creada por `vendi_platform` — incluidas estas; `fiado_creditos` de
hecho se actualiza (el saldo y el estado). El candado invertido pasa sin
edición, misma decisión que los módulos anteriores.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Las tres firmadas en ADR-022 más `anulado` (decisión 3 del plan).
ESTADOS_DE_CREDITO = ("vigente", "vencido", "saldado", "anulado")
METODOS_DE_PAGO_ABONO = ("efectivo", "transferencia", "otro")


def upgrade() -> None:
    op.create_table(
        "clientes",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("telefono", sa.String(15), nullable=True),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.Column("limite_credito", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "limite_credito IS NULL OR limite_credito >= 0",
            name="ck_clientes_limite_no_negativo",
        ),
    )
    # La lista y la búsqueda del POS filtran por nombre dentro del tenant.
    op.create_index("ix_clientes_tenant_nombre", "clientes", ["tenant_id", "nombre"])
    enable_rls(op, "clientes", crear_indice=False)

    op.create_table(
        "fiado_creditos",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cliente_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clientes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "venta_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("ventas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("monto_total", sa.Integer(), nullable=False),
        sa.Column("saldo_pendiente", sa.Integer(), nullable=False),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=True),
        sa.Column("estado", sa.String(12), nullable=False),
        sa.CheckConstraint("monto_total > 0", name="ck_fiado_creditos_monto_positivo"),
        sa.CheckConstraint("saldo_pendiente >= 0", name="ck_fiado_creditos_saldo_no_negativo"),
        sa.CheckConstraint(
            "saldo_pendiente <= monto_total",
            name="ck_fiado_creditos_saldo_acotado",
        ),
        sa.CheckConstraint(
            "estado IN (" + ", ".join(f"'{e}'" for e in ESTADOS_DE_CREDITO) + ")",
            name="ck_fiado_creditos_estado",
        ),
        sa.UniqueConstraint("venta_id", name="ux_fiado_creditos_venta"),
    )
    # El saldo por cliente es un SUM acotado por la policy (Index Cond).
    op.create_index("ix_fiado_creditos_tenant_cliente", "fiado_creditos", ["tenant_id", "cliente_id"])
    # El cuaderno (pendientes por vencimiento) y el trabajo diario de vencidos.
    op.create_index("ix_fiado_creditos_tenant_estado", "fiado_creditos", ["tenant_id", "estado", "fecha_vencimiento"])
    enable_rls(op, "fiado_creditos", crear_indice=False)

    op.create_table(
        "fiado_abonos",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "credito_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("fiado_creditos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # La sesión que cobró el efectivo (decisión 9): NULL en los métodos
        # que no tocan la gaveta. RESTRICT como todo lo de caja.
        sa.Column(
            "sesion_caja_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("caja_sesiones.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("monto", sa.Integer(), nullable=False),
        sa.Column("metodo_pago", sa.String(16), nullable=False),
        sa.Column("registrado_por", sa.String(120), nullable=False),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.CheckConstraint("monto > 0", name="ck_fiado_abonos_monto_positivo"),
        sa.CheckConstraint(
            "metodo_pago IN (" + ", ".join(f"'{m}'" for m in METODOS_DE_PAGO_ABONO) + ")",
            name="ck_fiado_abonos_metodo",
        ),
    )
    # El historial de pagos del crédito (ADR-009) y el SUM del arqueo por
    # sesión (decisión 9).
    op.create_index("ix_fiado_abonos_tenant_credito", "fiado_abonos", ["tenant_id", "credito_id"])
    op.create_index("ix_fiado_abonos_tenant_sesion", "fiado_abonos", ["tenant_id", "sesion_caja_id"])
    enable_rls(op, "fiado_abonos", crear_indice=False)


def downgrade() -> None:
    disable_rls(op, "fiado_abonos", borrar_indice=False)
    op.drop_index("ix_fiado_abonos_tenant_sesion", table_name="fiado_abonos")
    op.drop_index("ix_fiado_abonos_tenant_credito", table_name="fiado_abonos")
    op.drop_table("fiado_abonos")
    disable_rls(op, "fiado_creditos", borrar_indice=False)
    op.drop_index("ix_fiado_creditos_tenant_estado", table_name="fiado_creditos")
    op.drop_index("ix_fiado_creditos_tenant_cliente", table_name="fiado_creditos")
    op.drop_table("fiado_creditos")
    disable_rls(op, "clientes", borrar_indice=False)
    op.drop_index("ix_clientes_tenant_nombre", table_name="clientes")
    op.drop_table("clientes")
