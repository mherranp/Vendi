"""Fundación: tablas de plataforma (audit_events, outbox_messages) y `files`.

Revision ID: 0001
Revises:
Create Date: 2026-07-22

## Qué lleva RLS aquí y qué no

- `audit_events` y `outbox_messages` son **tablas de plataforma**: la consulta
  y el drenado son cross-tenant por definición, así que no llevan la policy de
  aislamiento `tenant_isolation` ni entran en el candado de cobertura. Está
  firmado en `vendi_core.db.base.TABLAS_DE_PLATAFORMA` y `test_rls_coverage.py`
  las excluye por nombre.
  - `audit_events`: la consola de plataforma consulta cross-tenant ("qué hizo el
    administrador X en todos los negocios") y el runner de retención la recorre
    entera.
  - `outbox_messages`: el dispatcher drena la cola de todos los negocios en una
    sola pasada. Con la policy de lectura vería cero filas, o habría que abrir
    una transacción por negocio para vaciar una cola.

- **`vendi_app` sí encola en `outbox_messages`, y tiene que poder.** Toda la
  garantía del patrón outbox es que la escritura de negocio y el encolado del
  evento ocurren en la MISMA transacción; la escritura de negocio la hace la
  sesión de tenant (rol `vendi_app`), luego el `INSERT` del outbox también.
  Encolar con la sesión de plataforma sería una segunda transacción y rompería
  la atomicidad, que es lo único que aporta el patrón.
  Por eso `vendi_app` recibe **`INSERT` y nada más**: no `SELECT` (no puede leer
  la cola de nadie), no `UPDATE` (no puede marcar procesado ni reescribir un
  mensaje ajeno), no `DELETE` (no puede vaciar la cola). Drenar sigue siendo
  exclusivo de `vendi_platform`.
  Y para que "sin RLS" no signifique "puede encolar en nombre de otro negocio",
  la tabla lleva una policy **solo de INSERT** (`outbox_encolado_del_tenant`)
  que exige `tenant_id = GUC vendi.tenant_id`. `vendi_platform` la salta por
  `BYPASSRLS` —de ahí que el dispatcher y los eventos de plataforma con
  `tenant_id NULL` sigan funcionando—; `vendi_app` no. Ver
  `tests/test_outbox_transaccional.py`.

- **`audit_events` sigue revocada por completo para `vendi_app`**, y no es una
  omisión simétrica: `AuditService` no recibe una sesión, recibe una
  `session_factory` y abre la suya (`vendi_core/audit/service.py::_write`). La
  auditoría es deliberadamente fire-and-forget y fuera de la transacción del
  llamante —si fuese dentro, un rollback de negocio borraría la prueba de que se
  intentó la operación—, así que se cablea siempre con la fábrica de plataforma.
  El candado que lo defiende es `test_auditoria_no_usa_el_rol_de_la_api`.

- `files` es tabla de negocio (hereda `TenantModel`) y sí lleva `enable_rls`.

Las tablas del MVP (ventas, inventario, cierres de caja) llegan con su propio
módulo; `tenants` llega en la tarea 4.2.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tablas de plataforma: se listan aquí para que el REVOKE de abajo no se
# desincronice de la lista de CREATEs de arriba.
_TABLAS_DE_PLATAFORMA = ("audit_events", "outbox_messages")

# Nombre de la policy de encolado del outbox. No es `tenant_isolation`: no
# aísla lecturas (no hay ninguna para `vendi_app`), solo acota el INSERT.
POLICY_OUTBOX_INSERT = "outbox_encolado_del_tenant"


def upgrade() -> None:
    # `gen_random_uuid()` vive en pgcrypto en PG < 13 y en el core desde PG 13.
    # Con PostgreSQL 17 no hace falta extensión, pero se deja la comprobación
    # explícita para que el fallo, si algún día se ejecuta contra un motor más
    # viejo, diga qué falta en vez de "function does not exist".
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # --- audit_events (plataforma, sin RLS) --------------------------------
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(64), server_default="", nullable=False),
        sa.Column("service_name", sa.String(64), server_default="", nullable=False),
        # Nullable: NULL = evento de plataforma, sin negocio asociado.
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.String(64), server_default="", nullable=False),
        sa.Column("user_email", sa.String(255), server_default="", nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), server_default="", nullable=False),
        sa.Column("resource_id", sa.String(128), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="success", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("changes", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
    )
    op.create_index("ix_audit_events_tenant_timestamp", "audit_events", ["tenant_id", "timestamp"])
    op.create_index("ix_audit_events_user_timestamp", "audit_events", ["user_id", "timestamp"])
    op.create_index("ix_audit_events_resource", "audit_events", ["resource_type", "resource_id"])
    op.create_index("ix_audit_events_correlation", "audit_events", ["correlation_id"])

    # --- outbox_messages (plataforma, sin RLS) -----------------------------
    op.create_table(
        "outbox_messages",
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
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("exchange", sa.String(128), nullable=False),
        sa.Column("routing_key", sa.String(256), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(1024), server_default="", nullable=False),
    )
    # Índice parcial sobre lo único que consulta el dispatcher: los pendientes.
    # Un índice completo sobre `status` sería casi inútil (la inmensa mayoría de
    # las filas acaban en 'processed' y ahí se quedan hasta que las purga
    # retención), y crecería sin parar.
    op.execute("CREATE INDEX ix_outbox_messages_pendientes ON outbox_messages (created_at) WHERE status = 'pending'")

    # --- files (negocio, CON RLS) ------------------------------------------
    op.create_table(
        "files",
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
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("key", sa.String(1024), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column(
            "content_type",
            sa.String(128),
            server_default="application/octet-stream",
            nullable=False,
        ),
        sa.Column("size_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("etag", sa.String(64), server_default="", nullable=False),
        sa.Column("uploaded_by", sa.String(64), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("thumbnails", JSONB, nullable=True),
    )
    op.create_index("ix_files_deleted_at", "files", ["deleted_at"])
    # Crea el índice `ix_files_tenant_id` además de la policy: sin un índice que
    # empiece por tenant_id, el predicado de la policy deja de ser `Index Cond`
    # y cada consulta recorre las filas de toda la región (escenario F del
    # spike de RLS).
    enable_rls(op, "files")

    # --- Privilegios --------------------------------------------------------
    # `vendi_app` los recibe por ALTER DEFAULT PRIVILEGES (01-roles.sh). Se
    # parte de cero sobre las dos tablas de plataforma y se devuelve solo lo
    # imprescindible.
    for tabla in _TABLAS_DE_PLATAFORMA:
        op.execute(f"REVOKE ALL ON {tabla} FROM vendi_app")

    # `audit_events`: nada. `AuditService` abre su propia sesión con la fábrica
    # de plataforma (ver docstring de arriba), así que el rol de la API no
    # necesita —ni debe— alcanzar la tabla: no puede leer lo que hicieron otros
    # negocios ni fabricar una fila de auditoría a mano.

    # `outbox_messages`: solo INSERT. Es lo que hace posible que el encolado
    # viaje en la misma transacción que la escritura de negocio sin regalarle a
    # la API la capacidad de leer ni de drenar la cola.
    op.execute("GRANT INSERT ON outbox_messages TO vendi_app")

    # Y una policy de INSERT que impide encolar en nombre de otro negocio. Sin
    # ella, un `INSERT` con `tenant_id` ajeno pasaría, y el dispatcher publicaría
    # el evento con la clave de enrutado del otro negocio.
    #
    # `FORCE` va porque `vendi_platform` es el owner de la tabla, y sin FORCE el
    # owner salta las policies por serlo. Con FORCE las saltaría igual —tiene
    # `BYPASSRLS`—, pero por el motivo correcto y verificable: el dispatcher y
    # los eventos de plataforma (`tenant_id NULL`) siguen funcionando porque el
    # rol tiene BYPASSRLS, no porque creó la tabla.
    op.execute("ALTER TABLE outbox_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE outbox_messages FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {POLICY_OUTBOX_INSERT} ON outbox_messages
          FOR INSERT TO vendi_app
          WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    disable_rls(op, "files")
    op.drop_index("ix_files_deleted_at", table_name="files")
    op.drop_table("files")
    op.execute(f"DROP POLICY IF EXISTS {POLICY_OUTBOX_INSERT} ON outbox_messages")
    op.execute("ALTER TABLE outbox_messages NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE outbox_messages DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE INSERT ON outbox_messages FROM vendi_app")
    op.execute("DROP INDEX IF EXISTS ix_outbox_messages_pendientes")
    op.drop_table("outbox_messages")
    op.drop_index("ix_audit_events_correlation", table_name="audit_events")
    op.drop_index("ix_audit_events_resource", table_name="audit_events")
    op.drop_index("ix_audit_events_user_timestamp", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_timestamp", table_name="audit_events")
    op.drop_table("audit_events")
