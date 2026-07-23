"""Catálogo de negocios: tabla `tenants` (plataforma, sin RLS, fuera del alcance de vendi_app).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-23

## Por qué NO lleva RLS

`tenants` no pertenece a ningún negocio: **es** el negocio. No tiene columna
`tenant_id` que comparar contra el GUC, así que la policy `tenant_isolation` no
tiene ni forma de escribirse. Está declarada en
`vendi_core.db.base.TABLAS_DE_PLATAFORMA` desde la Etapa 3, precisamente para
que el candado de cobertura no cambie de manos entre etapas.

## Por qué se le REVOCA todo a `vendi_app`

`01-roles.sh` deja `ALTER DEFAULT PRIVILEGES ... GRANT SELECT, INSERT, UPDATE,
DELETE ON TABLES TO vendi_app`, de modo que toda tabla nueva creada por
`vendi_platform` nace accesible para el rol de la API. Para una tabla de negocio
eso es lo correcto (RLS la acota). Para ésta sería un agujero directo: sin
policy y con `SELECT`, cualquier handler podría listar **todos los negocios de
la región** —nombres, estados, ids de organización—, que es exactamente el dato
que el producto promete no cruzar.

Así que se revoca entero, igual que `audit_events`. El único camino de lectura
es la sesión de plataforma filtrando en Python por el `tenant_id` que salió del
token (`GET /tenants/me`) o el router `/platform/*`, que exige `platform:admin`.
Lo vigila `test_vendi_app_no_alcanza_las_tablas_de_plataforma`.

## Sobre `nombre`: deliberadamente SIN índice único

Dos "Tienda Don Carlos" en la misma región son dos negocios distintos y ambos
tienen derecho a existir; la identidad es el UUID. La unicidad tampoco puede
venir del IdP: Keycloak **sí** exige `name` único por Organization (medido en
26.6.4 → 409 "A organization with the same name already exists"), y por eso el
`name` de la Organization es el `tenant_id` y no el nombre comercial. Si el
nombre fuera único aquí, el alta de un negocio podría fallar por lo que otro
negocio eligió llamarse, y por los 409 se podrían enumerar los nombres de los
demás.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESTADOS = ("activo", "suspendido", "eliminado")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("estado", sa.String(16), server_default="activo", nullable=False),
        sa.Column("kc_org_id", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "estado IN (" + ", ".join(f"'{e}'" for e in ESTADOS) + ")",
            name="ck_tenants_estado",
        ),
    )
    op.create_index("ix_tenants_deleted_at", "tenants", ["deleted_at"])
    op.create_index("ix_tenants_estado_created_at", "tenants", ["estado", "created_at"])

    # Ver la cabecera: sin esto la tabla nace legible para el rol de la API por
    # los privilegios por defecto de 01-roles.sh.
    op.execute("REVOKE ALL ON tenants FROM vendi_app")


def downgrade() -> None:
    op.drop_index("ix_tenants_estado_created_at", table_name="tenants")
    op.drop_index("ix_tenants_deleted_at", table_name="tenants")
    op.drop_table("tenants")
