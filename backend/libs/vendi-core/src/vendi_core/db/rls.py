"""Helper DDL de Row Level Security para las migraciones de Alembic.

El texto SQL de la policy no se inventa aquí: es literalmente el que fijó el
spike 1.2 en `docs/superpowers/specs/2026-07-22-verificacion-rls.md`, decisión 1.
Toda tabla de negocio (las que heredan `TenantModel`) DEBE pasar por
`enable_rls` en su migración.

Las tres piezas y por qué cada una:

- `ENABLE ROW LEVEL SECURITY` activa las policies para los roles normales.
- `FORCE ROW LEVEL SECURITY` las aplica **también al owner de la tabla**. Sin
  `FORCE`, `vendi_platform` —owner— saltaría la policy por ser owner, no por
  tener `BYPASSRLS`, y perderíamos la distinción entre "salta porque es
  plataforma" y "salta porque creó la tabla" (escenario D del spike).
- `NULLIF(current_setting('vendi.tenant_id', true), '')::uuid` es el idiom
  fail-closed. El `true` es `missing_ok`: sin él, una sesión que nunca definió
  el GUC revienta con `unrecognized configuration parameter` —un HTTP 500— en
  vez de ver cero filas (escenario A). El `NULLIF` cubre el otro estado, el GUC
  en `''` que deja el hook de checkout del pool.
- `WITH CHECK` además de `USING`: `USING` filtra lo que se lee; `WITH CHECK`
  valida lo que se escribe. Sin él, un INSERT con `tenant_id` ajeno pasa, y un
  `UPDATE ... SET tenant_id = <otro>` **regala la fila a otro negocio**
  (escenarios C y G).
- El índice sobre `tenant_id` no es opcional: el planificador usa el predicado
  de la policy como `Index Cond` (escenario F). Sin índice, cada consulta
  recorre las filas de toda la región.
"""

from __future__ import annotations

NOMBRE_POLICY = "tenant_isolation"

_PREDICADO = "tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid"

POLICY_SQL = f"""
CREATE POLICY {NOMBRE_POLICY} ON {{table}}
  USING      ({_PREDICADO})
  WITH CHECK ({_PREDICADO})
"""


def enable_rls(op, table: str, *, crear_indice: bool = True) -> None:
    """Activa RLS forzado + policy de aislamiento sobre `table`.

    Args:
        op: el módulo `op` de Alembic (se pasa como argumento para que este
            helper no importe Alembic y siga siendo testeable sin él).
        table: nombre de la tabla, sin comillas.
        crear_indice: crea `ix_{table}_tenant_id`. Ponlo en `False` **solo** si
            la migración ya declara un índice compuesto que empieza por
            `tenant_id` (p. ej. `(tenant_id, creado_en)`), que sirve igual para
            el `Index Cond`. Si lo pones en `False` sin ese índice, el candado
            `test_rls_coverage.py` falla — y hace bien.
    """
    tabla_citada = f'"{table}"'
    op.execute(f"ALTER TABLE {tabla_citada} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {tabla_citada} FORCE ROW LEVEL SECURITY")
    op.execute(POLICY_SQL.format(table=tabla_citada))
    if crear_indice:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def disable_rls(op, table: str, *, borrar_indice: bool = True) -> None:
    """Deshace `enable_rls`. Para el `downgrade()` de las migraciones."""
    tabla_citada = f'"{table}"'
    op.execute(f"DROP POLICY IF EXISTS {NOMBRE_POLICY} ON {tabla_citada}")
    op.execute(f"ALTER TABLE {tabla_citada} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {tabla_citada} DISABLE ROW LEVEL SECURITY")
    if borrar_indice:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
