"""Ventas y sync offline: `dispositivos`, `caja_sesiones`, `ventas`,
`ventas_items` y `movimientos_inventario` (ADR-017/018/020/021).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-28

## Las cinco tablas y su porqué

- `dispositivos` (ADR-017): registro de los dispositivos del tenant que
  sincronizan. `ultima_secuencia` es la mayor `secuencia` de cola aplicada;
  `ultima_sync`, la marca del último lote. Ambas son observabilidad, no
  árbitro: la idempotencia la da la PK de cada fila de dominio.
- `caja_sesiones` (ADR-021, creada aquí por la decisión 3 del plan del
  módulo): una sesión de caja abierta por tienda, garantizada por el índice
  único parcial `(tenant_id) WHERE estado = 'abierta'`. El sync la usa para
  resolver la referencia de cada venta (abierta del tenant o implícita); el
  arqueo y `caja_movimientos` llegan con el módulo de caja.
- `ventas` (ADR-018): hecho append-only. PK = UUIDv4 del dispositivo;
  `consecutivo_local` único por `(tenant_id, dispositivo_id)` — es el número
  del ticket; doble verdad temporal (`creada_en_cliente` es dato del ticket,
  `recibida_en` es la verdad del servidor); `medio_pago` es texto libre
  acotado por la aplicación (efectivo/fiado hoy; «otros medios registrados
  como dato», ADR-018). `cliente_id` no lleva FK: la tabla `clientes` es del
  módulo de fiado (decisión 8). La única mutación permitida es
  `completada → anulada`.
- `ventas_items` (ADR-018): líneas con el precio CONGELADO en el momento de
  la venta. FK a `ventas` y a `productos` con RESTRICT: ni una venta ni un
  producto con historial se borran físicamente (el borrado del catálogo es
  lógico). Postgres NO aplica RLS al verificar llaves foráneas: que el
  producto sea del propio tenant lo garantiza el servicio, que lo lee por la
  sesión de tenant antes de insertar.
- `movimientos_inventario` (ADR-020, creada aquí por la decisión 1): el libro
  de stock. `cantidad` NUMERIC con signo (la venta descuenta, la anulación
  repone); `referencia_id` es el UUID de la venta (o de la operación de
  anulación) que lo causó. El índice único
  `(tenant_id, tipo, referencia_id, producto_id)` es la segunda red de
  idempotencia: incluye `producto_id` porque una venta tiene varios ítems y
  cada uno es un movimiento con la misma referencia (decisión 2).

## Grants

Los privilegios por defecto de 01-roles.sh conceden los cuatro a `vendi_app`
sobre toda tabla creada por `vendi_platform`, que es lo que el candado
invertido exige para tablas de negocio — incluidas las append-only (decisión
11 del plan, mismo criterio que `productos` y `files`). No se toca nada aquí
a propósito.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEDIOS_DE_PAGO = ("efectivo", "fiado")
TIPOS_DE_MOVIMIENTO = ("venta", "compra", "ajuste", "merma")


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
        "dispositivos",
        *_columnas_base(),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("ultima_secuencia", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("ultima_sync", sa.DateTime(timezone=True), nullable=True),
    )
    enable_rls(op, "dispositivos")  # crea ix_dispositivos_tenant_id

    op.create_table(
        "caja_sesiones",
        *_columnas_base(),
        sa.Column("abierta_por", sa.String(120), nullable=False),
        sa.Column("abierta_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("base_inicial", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cerrada_por", sa.String(120), nullable=True),
        sa.Column("cerrada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("efectivo_esperado", sa.Integer(), nullable=True),
        sa.Column("efectivo_contado", sa.Integer(), nullable=True),
        sa.Column("diferencia", sa.Integer(), nullable=True),
        sa.Column("estado", sa.String(16), server_default="abierta", nullable=False),
        sa.CheckConstraint("estado IN ('abierta', 'cerrada')", name="ck_caja_sesiones_estado"),
        sa.CheckConstraint("base_inicial >= 0", name="ck_caja_sesiones_base_no_negativa"),
    )
    # Una sesión ABIERTA por tienda (ADR-021): la regla la hace cumplir la
    # base. Empieza por tenant_id, así que sirve de índice del predicado RLS.
    op.execute("CREATE UNIQUE INDEX ux_caja_sesion_abierta ON caja_sesiones (tenant_id) WHERE estado = 'abierta'")
    enable_rls(op, "caja_sesiones", crear_indice=False)

    op.create_table(
        "ventas",
        *_columnas_base(),
        sa.Column(
            "dispositivo_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("dispositivos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # NOT NULL por la decisión 13 del plan: el sync siempre resuelve a la
        # sesión abierta del tenant o abre una implícita (ADR-018).
        sa.Column(
            "sesion_caja_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("caja_sesiones.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("consecutivo_local", sa.Integer(), nullable=False),
        sa.Column("estado", sa.String(16), server_default="completada", nullable=False),
        # Texto libre acotado por la aplicación: «efectivo | fiado | otros
        # medios registrados como dato» (ADR-018). Sin CHECK para que añadir
        # un medio no sea una migración.
        sa.Column("medio_pago", sa.String(24), nullable=False),
        sa.Column("total_centavos", sa.Integer(), nullable=False),
        # Sin FK: `clientes` es del módulo de fiado (decisión 8 del plan).
        sa.Column("cliente_id", sa.UUID(as_uuid=True), nullable=True),
        # La marca del reloj del dispositivo: dato del ticket, NO orden
        # (puede mentir; la verdad temporal es `recibida_en`, del servidor).
        sa.Column("creada_en_cliente", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recibida_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("secuencia_dispositivo", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("estado IN ('completada', 'anulada')", name="ck_ventas_estado"),
        sa.CheckConstraint("consecutivo_local > 0", name="ck_ventas_consecutivo_positivo"),
        sa.CheckConstraint("total_centavos >= 0", name="ck_ventas_total_no_negativo"),
        sa.CheckConstraint("secuencia_dispositivo > 0", name="ck_ventas_secuencia_positiva"),
    )
    # El número del ticket es único por negocio Y dispositivo (multi-caja,
    # ADR-018): dos cajas repiten números sin colisionar.
    op.create_index(
        "ux_ventas_consecutivo",
        "ventas",
        ["tenant_id", "dispositivo_id", "consecutivo_local"],
        unique=True,
    )
    # Empieza por tenant_id (predicado RLS como Index Cond) y ordena los
    # reportes y el P&L, que suman por la marca del SERVIDOR (ADR-018).
    op.create_index("ix_ventas_tenant_recibida", "ventas", ["tenant_id", "recibida_en"])
    enable_rls(op, "ventas", crear_indice=False)

    op.create_table(
        "ventas_items",
        *_columnas_base(),
        sa.Column(
            "venta_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("ventas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "producto_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("productos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("cantidad", sa.Numeric(14, 3), nullable=False),
        sa.Column("precio_unitario_centavos", sa.Integer(), nullable=False),
        sa.CheckConstraint("cantidad > 0", name="ck_ventas_items_cantidad_positiva"),
        sa.CheckConstraint("precio_unitario_centavos >= 0", name="ck_ventas_items_precio_no_negativo"),
    )
    op.create_index("ix_ventas_items_tenant_venta", "ventas_items", ["tenant_id", "venta_id"])
    enable_rls(op, "ventas_items", crear_indice=False)

    op.create_table(
        "movimientos_inventario",
        *_columnas_base(),
        sa.Column("tipo", sa.String(16), nullable=False),
        sa.Column("cantidad", sa.Numeric(14, 3), nullable=False),
        sa.Column("referencia_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "producto_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("productos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tipo IN (" + ", ".join(f"'{t}'" for t in TIPOS_DE_MOVIMIENTO) + ")",
            name="ck_movimientos_tipo",
        ),
        sa.CheckConstraint("cantidad <> 0", name="ck_movimientos_cantidad_no_cero"),
    )
    # La idempotencia del sync con constraint, no con lógica (ADR-020); con
    # `producto_id` porque una venta tiene varios ítems (decisión 2 del plan).
    op.create_index(
        "ux_movimientos_origen",
        "movimientos_inventario",
        ["tenant_id", "tipo", "referencia_id", "producto_id"],
        unique=True,
    )
    # El libro por producto (auditoría «¿por qué tengo menos arroz?»).
    op.create_index("ix_movimientos_tenant_producto", "movimientos_inventario", ["tenant_id", "producto_id"])
    enable_rls(op, "movimientos_inventario", crear_indice=False)


def downgrade() -> None:
    disable_rls(op, "movimientos_inventario", borrar_indice=False)
    op.drop_index("ix_movimientos_tenant_producto", table_name="movimientos_inventario")
    op.drop_index("ux_movimientos_origen", table_name="movimientos_inventario")
    op.drop_table("movimientos_inventario")
    disable_rls(op, "ventas_items", borrar_indice=False)
    op.drop_index("ix_ventas_items_tenant_venta", table_name="ventas_items")
    op.drop_table("ventas_items")
    disable_rls(op, "ventas", borrar_indice=False)
    op.drop_index("ix_ventas_tenant_recibida", table_name="ventas")
    op.drop_index("ux_ventas_consecutivo", table_name="ventas")
    op.drop_table("ventas")
    disable_rls(op, "caja_sesiones", borrar_indice=False)
    op.execute("DROP INDEX IF EXISTS ux_caja_sesion_abierta")
    op.drop_table("caja_sesiones")
    disable_rls(op, "dispositivos")
    op.drop_table("dispositivos")
