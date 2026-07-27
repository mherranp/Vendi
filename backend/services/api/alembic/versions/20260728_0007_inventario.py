"""Inventario y compras: `compras`, `compra_items` y `ajustes_inventario` (ADR-020/023).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-28

## Las tres tablas y su porqué

- `compras` (ADR-020): el registro simple de una compra a proveedor.
  `proveedor_nombre` es TEXTO LIBRE — la factura es un papel, a veces
  manuscrito, y NO hay tabla de proveedores (YAGNI firmado: sin consumidor
  del historial en el MVP, sería la entidad imaginada que ADR-016 prohíbe).
  `fecha` es el dato de la factura (puede ser de ayer; el orden temporal
  real lo da `created_at`, del servidor). `total_centavos` lo calcula el
  servidor por línea (decisión 7 del plan).
- `compra_items` (ADR-020): las líneas con el costo de ESTA compra. FK a
  `compras` y a `productos` con RESTRICT. Postgres NO aplica RLS al verificar
  llaves foráneas: que el producto sea del propio tenant lo garantiza el
  servicio, que lo lee con FOR UPDATE por la sesión de tenant antes de
  insertar. El índice `(tenant_id, producto_id)` es el insumo de las futuras
  sugerencias de reabastecimiento (ADR-020: se calculan de `compra_items`).
- `ajustes_inventario` (decisión 5 del plan; el ADR no la lista y la
  desviación queda justificada allí): el ajuste de conteo o la merma como
  HECHO, con su `motivo` obligatorio. Su PK es el UUID del cliente: la fila
  es la prueba de idempotencia INCLUSO cuando el delta es cero y no hay
  movimiento que escribir — el agujero que una columna `nota` en el libro no
  podía cerrar. `delta` guarda lo aplicado (0 permitido) y
  `stock_resultante`, el stock tras aplicar, para responder al reintento lo
  mismo que la primera vez. El movimiento del libro (cuando delta ≠ 0)
  lleva `referencia_id = ajustes_inventario.id`, así que la auditoría va del
  libro al ajuste y de ahí al motivo.

## Lo que esta migración NO hace (decisión 6)

No toca `movimientos_inventario`: la 0005 creó `ck_movimientos_tipo` con los
cinco tipos (`venta`, `compra`, `ajuste`, `merma`, y `anulacion` vía 0006) y
el índice único `(tenant_id, tipo, referencia_id, producto_id)` ya deduplica
los movimientos de compra y de ajuste. `test_aislamiento_inventario.py` lo
demuestra insertando los tres tipos nuevos contra la base migrada.

## Grants

Los privilegios por defecto de 01-roles.sh conceden los cuatro a `vendi_app`
sobre toda tabla creada por `vendi_platform`, que es lo que el candado
invertido exige para tablas de negocio (mismo criterio que `productos`,
`ventas` y `files`). No se toca nada aquí a propósito.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columnas_base() -> list[sa.Column]:
    """id (acepta el UUID del cliente; server_default para inserts en SQL),
    tenant_id y los timestamps de `TenantModel`."""
    return [
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "compras",
        *_columnas_base(),
        # Texto libre, no tabla de proveedores (ADR-020, YAGNI firmado). La
        # cota de largo la pone el schema (160), no la columna: es de
        # negocio, no de tipo.
        sa.Column("proveedor_nombre", sa.Text(), nullable=False),
        # El dato de la factura de papel. Sin cota: una factura de ayer se
        # registra hoy. La verdad temporal es `created_at` (servidor).
        sa.Column("fecha", sa.Date(), server_default=sa.func.current_date(), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        # Lo calcula el servidor por línea (decisión 7): nunca viene del cliente.
        sa.Column("total_centavos", sa.Integer(), nullable=False),
        sa.CheckConstraint("total_centavos >= 0", name="ck_compras_total_no_negativo"),
    )
    # Empieza por tenant_id (predicado RLS como Index Cond) y ordena el
    # listado por la fecha de la factura.
    op.create_index("ix_compras_tenant_fecha", "compras", ["tenant_id", "fecha"])
    enable_rls(op, "compras", crear_indice=False)

    op.create_table(
        "compra_items",
        *_columnas_base(),
        sa.Column(
            "compra_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("compras.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "producto_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("productos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("cantidad", sa.Numeric(14, 3), nullable=False),
        # Dinero en centavos enteros, jamás flotante (criterio unificado ADR-018).
        sa.Column("costo_unitario_centavos", sa.Integer(), nullable=False),
        sa.CheckConstraint("cantidad > 0", name="ck_compra_items_cantidad_positiva"),
        sa.CheckConstraint("costo_unitario_centavos >= 0", name="ck_compra_items_costo_no_negativo"),
    )
    op.create_index("ix_compra_items_tenant_compra", "compra_items", ["tenant_id", "compra_id"])
    # El historial de costos por producto: insumo de las sugerencias de
    # reabastecimiento (ADR-020).
    op.create_index("ix_compra_items_tenant_producto", "compra_items", ["tenant_id", "producto_id"])
    enable_rls(op, "compra_items", crear_indice=False)

    op.create_table(
        "ajustes_inventario",
        *_columnas_base(),
        sa.Column(
            "producto_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("productos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tipo", sa.String(8), nullable=False),
        # Forma por tipo (la hace cumplir ck_ajustes_forma): el ajuste es un
        # conteo absoluto (`stock_contado`); la merma, una cantidad que se
        # dañó (`cantidad`).
        sa.Column("stock_contado", sa.Numeric(14, 3), nullable=True),
        sa.Column("cantidad", sa.Numeric(14, 3), nullable=True),
        # Lo aplicado contra el stock del servidor en el momento (ADR-020:
        # el ajuste es online porque su delta se calcula contra ESTE dato).
        # Admite 0: el conteo que cuadra no escribe movimiento, pero la fila
        # queda como prueba de idempotencia (decisión 5).
        sa.Column("delta", sa.Numeric(14, 3), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("aplicado_por", sa.String(120), nullable=False),
        # El stock tras aplicar: es lo que se responde al reintento.
        sa.Column("stock_resultante", sa.Numeric(14, 3), nullable=False),
        sa.CheckConstraint("tipo IN ('ajuste', 'merma')", name="ck_ajustes_tipo"),
        sa.CheckConstraint(
            "(tipo = 'ajuste' AND stock_contado IS NOT NULL AND cantidad IS NULL) OR "
            "(tipo = 'merma' AND cantidad IS NOT NULL AND stock_contado IS NULL)",
            name="ck_ajustes_forma",
        ),
        sa.CheckConstraint("cantidad IS NULL OR cantidad > 0", name="ck_ajustes_cantidad_positiva"),
        sa.CheckConstraint("stock_contado IS NULL OR stock_contado >= 0", name="ck_ajustes_conteo_no_negativo"),
    )
    # El libro de ajustes por producto (auditoría «¿quién movió el arroz?»),
    # empezando por tenant_id para el predicado RLS.
    op.create_index("ix_ajustes_tenant_producto", "ajustes_inventario", ["tenant_id", "producto_id"])
    enable_rls(op, "ajustes_inventario", crear_indice=False)


def downgrade() -> None:
    disable_rls(op, "ajustes_inventario", borrar_indice=False)
    op.drop_index("ix_ajustes_tenant_producto", table_name="ajustes_inventario")
    op.drop_table("ajustes_inventario")
    disable_rls(op, "compra_items", borrar_indice=False)
    op.drop_index("ix_compra_items_tenant_producto", table_name="compra_items")
    op.drop_index("ix_compra_items_tenant_compra", table_name="compra_items")
    op.drop_table("compra_items")
    disable_rls(op, "compras", borrar_indice=False)
    op.drop_index("ix_compras_tenant_fecha", table_name="compras")
    op.drop_table("compras")
