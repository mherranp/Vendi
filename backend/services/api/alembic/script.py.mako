"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Recordatorio: toda tabla de negocio (las que heredan `TenantModel`) DEBE pasar
por `vendi_core.db.rls.enable_rls(op, "<tabla>")` en su `upgrade()`, y por
`disable_rls` en el `downgrade()`. Si se olvida, el test candado
`tests/test_rls_coverage.py` falla — y hace bien: una tabla de negocio sin
policy es visible para todos los negocios de la región.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
