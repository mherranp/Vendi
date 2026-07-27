"""Caja: `caja_movimientos`, los CHECK del cierre completo y `ventas.anulada_en`
(ADR-021, decisiones 1, 2 y 7 del plan del módulo).

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-28

## Qué crea y qué NO crea

- `caja_sesiones` NO se recrea: existe completa desde la `0005` (decisión 3
  del plan de ventas) con todas las columnas del arqueo y el índice único
  parcial de sesión abierta. Aquí solo gana dos CHECK: el cierre es completo
  o no es (`cerrada` exige `cerrada_por`, `cerrada_en`, `efectivo_esperado`,
  `efectivo_contado` y `diferencia` no nulas — el arqueo a medias no existe),
  y el conteo físico no es negativo.
- `caja_movimientos` (ADR-021): ingresos y egresos manuales con `tipo`,
  `categoria` de lista cerrada (`arriendo`, `servicios`, `retiro_dueno`,
  `otro` — ampliarla exige migración, a propósito: el P&L agrupa por ella),
  `monto` en centavos enteros estrictamente positivo (el signo lo da el
  tipo), `motivo` obligatorio (decisión 2: la `nota` del ADR como `motivo`,
  la convención del ajuste de inventario) y la sesión a la que pertenecen,
  con FK RESTRICT: ni un movimiento huérfano ni una sesión con movimientos
  se borran físicamente. Las ventas en efectivo y los abonos de fiado NO se
  duplican aquí: el arqueo los suma desde su tabla de origen (ADR-021).
- `ventas.anulada_en` (decisión 7): cuándo se anuló la venta. Sin ella, la
  devolución de efectivo de una venta anulada tras el cierre no podría caer
  en la sesión abierta —como firma ADR-021— sin duplicar la venta como
  movimiento, que el mismo ADR prohíbe. NULL en las anulaciones anteriores
  a esta migración (no hay operación real pre-piloto): el cálculo las
  excluye con `IS NOT NULL`, declarado.

## Grants

Los privilegios por defecto conceden los cuatro a `vendi_app` sobre toda
tabla creada por `vendi_platform` — incluida esta, aunque por modelo sus
filas no se editan ni se borran (misma decisión que las append-only de
ventas e inventario; el candado invertido pasa sin edición).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIPOS_DE_MOVIMIENTO_CAJA = ("ingreso", "egreso")
CATEGORIAS_DE_MOVIMIENTO = ("arriendo", "servicios", "retiro_dueno", "otro")


def upgrade() -> None:
    op.create_table(
        "caja_movimientos",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sesion_caja_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("caja_sesiones.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tipo", sa.String(8), nullable=False),
        sa.Column("categoria", sa.String(24), nullable=False),
        sa.Column("monto", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("registrado_por", sa.String(120), nullable=False),
        sa.CheckConstraint(
            "tipo IN (" + ", ".join(f"'{t}'" for t in TIPOS_DE_MOVIMIENTO_CAJA) + ")",
            name="ck_caja_movimientos_tipo",
        ),
        sa.CheckConstraint(
            "categoria IN (" + ", ".join(f"'{c}'" for c in CATEGORIAS_DE_MOVIMIENTO) + ")",
            name="ck_caja_movimientos_categoria",
        ),
        sa.CheckConstraint("monto > 0", name="ck_caja_movimientos_monto_positivo"),
    )
    # El arqueo suma por sesión; el P&L y el forecast suman por fecha del
    # servidor. Ambos empiezan por tenant_id (predicado RLS como Index Cond).
    op.create_index("ix_caja_movimientos_tenant_sesion", "caja_movimientos", ["tenant_id", "sesion_caja_id"])
    op.create_index("ix_caja_movimientos_tenant_created", "caja_movimientos", ["tenant_id", "created_at"])
    enable_rls(op, "caja_movimientos", crear_indice=False)

    # El arqueo se congela entero o no se congela (ADR-021).
    op.create_check_constraint(
        "ck_caja_sesiones_cierre_completo",
        "caja_sesiones",
        "estado = 'abierta' OR (cerrada_por IS NOT NULL AND cerrada_en IS NOT NULL AND "
        "efectivo_esperado IS NOT NULL AND efectivo_contado IS NOT NULL AND diferencia IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_caja_sesiones_contado_no_negativo",
        "caja_sesiones",
        "efectivo_contado IS NULL OR efectivo_contado >= 0",
    )

    # Cuándo se anuló la venta: la devolución de efectivo cae en la sesión
    # abierta en ese momento (ADR-021, decisión 7 del plan).
    op.add_column("ventas", sa.Column("anulada_en", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ventas", "anulada_en")
    op.drop_constraint("ck_caja_sesiones_contado_no_negativo", "caja_sesiones", type_="check")
    op.drop_constraint("ck_caja_sesiones_cierre_completo", "caja_sesiones", type_="check")
    disable_rls(op, "caja_movimientos", borrar_indice=False)
    op.drop_index("ix_caja_movimientos_tenant_created", table_name="caja_movimientos")
    op.drop_index("ix_caja_movimientos_tenant_sesion", table_name="caja_movimientos")
    op.drop_table("caja_movimientos")
