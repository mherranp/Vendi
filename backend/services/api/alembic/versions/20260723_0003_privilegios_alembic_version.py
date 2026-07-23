"""Cierra `alembic_version` al rol de la API y deja el candado invertido.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-23

## Qué se arregla (deuda D-06)

Medido por el QA de la Etapa 4: `vendi_app` conservaba SELECT/INSERT/UPDATE/
DELETE sobre `alembic_version` —un `UPDATE version_num` dentro de una
transacción funcionó— y ninguno de los dos candados de la Etapa 3 lo veía. El de
tablas de plataforma enumeraba nombres concretos; el de cobertura RLS solo mira
tablas con columna `tenant_id`, y `alembic_version` no la tiene.

No es una tabla cualquiera: es la que decide qué DDL se considera aplicado. Con
UPDATE sobre ella, cualquier handler de la API puede hacer que la siguiente
migración crea que el esquema está en otro punto del que está —o que ya se
aplicó una que no—, y a partir de ahí `alembic upgrade head` es un no-op o una
ejecución fuera de orden. El daño no se ve hasta el despliegue siguiente.

De dónde salía el privilegio: `01-roles.sh` deja
`ALTER DEFAULT PRIVILEGES ... GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO
vendi_app`, y Alembic crea `alembic_version` con el rol de plataforma. La tabla
nace accesible, como cualquier otra. Para una tabla de negocio es lo correcto
—RLS la acota—; para ésta es un agujero, igual que lo era para `tenants`
(migración 0002) y para `audit_events` (migración 0001).

## Por qué el REVOKE va aquí y no en `01-roles.sh`

`01-roles.sh` corre en el `initdb` del contenedor, **antes** de que exista
ninguna tabla: no hay nada que revocar todavía, y una regla de DEFAULT
PRIVILEGES que excluyera esta tabla no se puede escribir (los privilegios por
defecto se declaran por esquema y rol creador, no por nombre de tabla). El sitio
correcto es una migración, que corre después de que Alembic haya creado la
tabla.

## El candado que lo mantiene cerrado

`backend/tests/test_privilegios_de_vendi_app.py` es el candado **invertido** que
pedía la deuda: en vez de enumerar las tablas prohibidas —lista que siempre se
queda corta— enumera las permitidas y falla ante cualquier tabla del esquema
`public` cuyos privilegios para `vendi_app` no cuadren con lo declarado. Una
tabla nueva sin clasificar pone el test rojo aunque nadie se acuerde de tocarlo.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `IF EXISTS` no aplica a REVOKE, pero la tabla siempre existe cuando esta
    # migración corre: la crea el propio Alembic antes de aplicar la primera.
    op.execute("REVOKE ALL ON alembic_version FROM vendi_app")


def downgrade() -> None:
    # Se restituye lo que dejaban los privilegios por defecto de 01-roles.sh,
    # que es el estado del que veníamos. Nadie debería querer volver aquí.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON alembic_version TO vendi_app")
