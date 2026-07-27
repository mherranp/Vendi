"""`anulacion` como tipo de movimiento del libro (fix BUG-3 del QA de ventas).

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-27

Los movimientos de reposición de stock de una anulación pasan de
`tipo='venta'` a `tipo='anulacion'`. Con el tipo de la venta, una anulación
cuyo id de operación coincide con el id de la venta (patrón «la anulación
DE la venta V») chocaba contra los movimientos originales en
`ux_movimientos_origen` (tenant_id, tipo, referencia_id, producto_id) y el
`IntegrityError` se mistraducía a `duplicada`: la venta seguía
`completada`, el stock sin reponer y el cliente marcaba la operación como
confirmada.

El CHECK `ck_movimientos_tipo` se recrea con el valor nuevo; el índice
único no se toca — sigue deduplicando el reintento por (tipo,
referencia_id=operacion.id, producto_id), ahora sin falso positivo contra
los movimientos de la venta.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Copias locales e inmutables (mismo criterio que la 0005): la migración
#: no importa del modelo para que el historial no cambie cuando el modelo
#: cambie.
_TIPOS_ANTES = ("venta", "compra", "ajuste", "merma")
_TIPOS_DESPUES = ("venta", "compra", "ajuste", "merma", "anulacion")


def _check(tipos: tuple[str, ...]) -> str:
    return "tipo IN (" + ", ".join(f"'{t}'" for t in tipos) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_movimientos_tipo", "movimientos_inventario", type_="check")
    op.create_check_constraint("ck_movimientos_tipo", "movimientos_inventario", _check(_TIPOS_DESPUES))


def downgrade() -> None:
    op.drop_constraint("ck_movimientos_tipo", "movimientos_inventario", type_="check")
    op.create_check_constraint("ck_movimientos_tipo", "movimientos_inventario", _check(_TIPOS_ANTES))
