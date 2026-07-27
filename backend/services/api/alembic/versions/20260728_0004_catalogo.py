"""Catálogo: tabla `productos` (ADR-019). Primera tabla de negocio de Fase 1.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-28

## Las columnas y su porqué (todo viene de ADR-019, firmado)

- Una fila = un ítem vendible. `padre_id` autorreferencia al producto base:
  las variantes son filas más, cada una con su EAN, su precio y su stock.
- `codigo_barras TEXT NULL` con índice único parcial
  `(tenant_id, codigo_barras) WHERE codigo_barras IS NOT NULL`: opcional
  porque el granel no tiene EAN; único porque el escáner (ADR-024) necesita
  que un código resuelva a exactamente un producto.
- Cantidades en NUMERIC (el fruver se vende a 0,350 kg) y dinero en enteros
  de centavos (`precio_venta`, `ultimo_costo`), criterio unificado con
  ADR-018: el dinero nunca se representa en flotante.
- `iva_pct NUMERIC(5,2)` con CHECK contra las tres tarifas vigentes en
  Colombia (0, 5, 19). El IVA es dato del producto, no un módulo fiscal.
- `stock_actual` y `ultimo_costo` se DECLARAN aquí pero el catálogo no los
  mueve: `stock_actual` es una proyección del libro de movimientos de
  inventario y `ultimo_costo` lo actualizan las compras (ADR-020).
- Borrado lógico (`deleted_at`), como en `tenants`: el historial de ventas
  referencia productos que ya no se venden.

## Por qué `vendi_app` conserva los cuatro privilegios (DELETE incluido)

Revocar DELETE (borrado lógico: la API «nunca» borra) obligaría a declarar
`productos` en `PRIVILEGIOS_DE_VENDI_APP`, y ese dict está atado a
`TABLAS_DE_PLATAFORMA` por un test de consistencia: meterla ahí la sacaría
del candado de cobertura RLS, que es la protección que importa. Además hay
precedente firmado: `files` (migración 0001) también es borrado lógico y
conserva los cuatro. La defensa del borrado es la lógica de aplicación —los
servicios marcan `deleted_at` y ningún endpoint emite DELETE físico— más la
RLS, que acota cualquier daño al propio negocio. La purga física la hace el
runner de retención con `vendi_platform`, que no pasa por estos grants.

## Los índices

`ix_productos_tenant_nombre` empieza por `tenant_id` (regla de ADR-013: el
predicado de la policy se resuelve como `Index Cond`) y cubre además el
listado ordenado por nombre del POS, así que `enable_rls` va con
`crear_indice=False` para no crear un `ix_productos_tenant_id` redundante.
El candado `test_rls_coverage.py` lo acepta porque el índice compuesto ya
empieza por `tenant_id`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIDADES = ("unidad", "kg", "g", "lt", "ml")


def upgrade() -> None:
    op.create_table(
        "productos",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # FK a sí misma sin RLS en la comprobación: Postgres NO aplica las
        # policies al verificar llaves foráneas, así que la pertenencia del
        # padre al mismo tenant se valida en la aplicación
        # (`CatalogoService._exigir_padre`), no aquí.
        sa.Column(
            "padre_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("productos.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("codigo_barras", sa.Text(), nullable=True),
        sa.Column("categoria", sa.Text(), nullable=True),
        sa.Column("unidad_medida", sa.String(8), server_default="unidad", nullable=False),
        # Dinero en centavos enteros (ADR-018/ADR-019): jamás flotante.
        sa.Column("precio_venta", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ultimo_costo", sa.Integer(), server_default="0", nullable=False),
        sa.Column("iva_pct", sa.Numeric(5, 2), server_default="0", nullable=False),
        # Cantidades decimales (granel): el fruver se vende a 0,350 kg.
        sa.Column("stock_actual", sa.Numeric(14, 3), server_default="0", nullable=False),
        sa.Column("stock_minimo", sa.Numeric(14, 3), server_default="0", nullable=False),
        sa.CheckConstraint(
            "unidad_medida IN (" + ", ".join(f"'{u}'" for u in UNIDADES) + ")",
            name="ck_productos_unidad_medida",
        ),
        sa.CheckConstraint("iva_pct IN (0, 5, 19)", name="ck_productos_iva_pct"),
        sa.CheckConstraint("precio_venta >= 0", name="ck_productos_precio_no_negativo"),
        sa.CheckConstraint("ultimo_costo >= 0", name="ck_productos_costo_no_negativo"),
    )
    op.create_index("ix_productos_deleted_at", "productos", ["deleted_at"])
    # Empieza por tenant_id: sirve al predicado RLS como Index Cond y al
    # listado del POS ordenado por nombre (consecuencia firmada de ADR-019).
    op.create_index("ix_productos_tenant_nombre", "productos", ["tenant_id", "nombre"])
    # El EAN es único POR NEGOCIO y solo cuando existe: el granel no tiene.
    op.execute(
        "CREATE UNIQUE INDEX ux_productos_ean ON productos (tenant_id, codigo_barras) WHERE codigo_barras IS NOT NULL"
    )
    # crear_indice=False: `ix_productos_tenant_nombre` ya empieza por tenant_id
    # (ver la cabecera). El candado test_rls_coverage lo verifica igual.
    enable_rls(op, "productos", crear_indice=False)

    # Grants: los privilegios por defecto de 01-roles.sh ya conceden SELECT,
    # INSERT, UPDATE y DELETE a vendi_app sobre toda tabla creada por
    # vendi_platform, y es lo que el candado invertido
    # (test_privilegios_de_vendi_app.py) exige para una tabla de negocio. No se
    # toca nada aquí a propósito; la justificación está en la cabecera.


def downgrade() -> None:
    disable_rls(op, "productos", borrar_indice=False)
    op.execute("DROP INDEX IF EXISTS ux_productos_ean")
    op.drop_index("ix_productos_tenant_nombre", table_name="productos")
    op.drop_index("ix_productos_deleted_at", table_name="productos")
    op.drop_table("productos")
