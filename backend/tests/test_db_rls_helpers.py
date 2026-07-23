"""Helpers DDL de RLS: qué SQL emiten exactamente `enable_rls` y `disable_rls`.

Módulo propio de Vendi (BaseSaaS aislaba por schema y no tenía nada parecido).
Cubrirlo importa porque es el generador del DDL del que depende TODO el
aislamiento: cada tabla de negocio del MVP va a pasar por aquí, y un cambio en
el texto de la policy —perder el `FORCE`, perder el `WITH CHECK`, perder el
`missing_ok` del `current_setting`— no rompe ningún test de negocio: simplemente
deja de aislar.

Se usa un `op` doblado que apunta las sentencias, así que no hace falta Alembic
ni base de datos. Los tres candados de integración
(`test_rls_session.py`, `test_cross_tenant_isolation.py`, `test_rls_coverage.py`)
prueban que el resultado funciona; este prueba que se genera lo que se cree.
"""

from __future__ import annotations

from vendi_core.db.rls import NOMBRE_POLICY, disable_rls, enable_rls


class _OpDoblado:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.indices_creados: list[tuple] = []
        self.indices_borrados: list[tuple] = []

    def execute(self, sentencia: str) -> None:
        self.sql.append(" ".join(sentencia.split()))

    def create_index(self, nombre, tabla, columnas):
        self.indices_creados.append((nombre, tabla, tuple(columnas)))

    def drop_index(self, nombre, table_name):
        self.indices_borrados.append((nombre, table_name))


def test_enable_rls_activa_forzado_y_crea_la_policy():
    op = _OpDoblado()
    enable_rls(op, "ventas")

    assert 'ALTER TABLE "ventas" ENABLE ROW LEVEL SECURITY' in op.sql
    assert 'ALTER TABLE "ventas" FORCE ROW LEVEL SECURITY' in op.sql, (
        "sin FORCE, el owner de la tabla salta la policy por ser owner y se "
        "pierde la distinción entre 'salta porque es plataforma' y 'salta "
        "porque creó la tabla'"
    )
    policy = next(s for s in op.sql if s.startswith("CREATE POLICY"))
    assert NOMBRE_POLICY in policy


def test_la_policy_lleva_using_y_with_check():
    """`USING` filtra lo que se lee; `WITH CHECK` valida lo que se escribe. Sin
    el segundo, un `UPDATE ... SET tenant_id = <otro>` regala la fila a otro
    negocio."""
    op = _OpDoblado()
    enable_rls(op, "ventas")
    policy = next(s for s in op.sql if s.startswith("CREATE POLICY"))

    assert "USING (" in policy
    assert "WITH CHECK (" in policy
    assert policy.count("tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid") == 2


def test_el_predicado_usa_missing_ok_y_nullif():
    """Los dos estados fail-closed: `true` es `missing_ok` (una sesión que nunca
    definió el GUC ve cero filas en vez de reventar con `unrecognized
    configuration parameter`), y `NULLIF` cubre el GUC en `''` que deja el hook
    de checkout del pool."""
    op = _OpDoblado()
    enable_rls(op, "ventas")
    policy = next(s for s in op.sql if s.startswith("CREATE POLICY"))

    assert "current_setting('vendi.tenant_id', true)" in policy
    assert "NULLIF(" in policy


def test_enable_rls_crea_el_indice_por_tenant_por_defecto():
    """Sin un índice que empiece por `tenant_id`, el predicado de la policy deja
    de resolverse como `Index Cond` y cada consulta recorre las filas de toda la
    región."""
    op = _OpDoblado()
    enable_rls(op, "ventas")
    assert op.indices_creados == [("ix_ventas_tenant_id", "ventas", ("tenant_id",))]


def test_se_puede_omitir_el_indice_cuando_ya_hay_uno_compuesto():
    op = _OpDoblado()
    enable_rls(op, "ventas", crear_indice=False)
    assert op.indices_creados == []
    # Lo demás sigue igual: omitir el índice no puede omitir la policy.
    assert any(s.startswith("CREATE POLICY") for s in op.sql)


def test_disable_rls_deshace_exactamente_lo_que_hizo_enable_rls():
    op = _OpDoblado()
    disable_rls(op, "ventas")

    assert f'DROP POLICY IF EXISTS {NOMBRE_POLICY} ON "ventas"' in op.sql
    assert 'ALTER TABLE "ventas" NO FORCE ROW LEVEL SECURITY' in op.sql
    assert 'ALTER TABLE "ventas" DISABLE ROW LEVEL SECURITY' in op.sql
    assert op.indices_borrados == [("ix_ventas_tenant_id", "ventas")]


def test_disable_rls_puede_dejar_el_indice_en_pie():
    op = _OpDoblado()
    disable_rls(op, "ventas", borrar_indice=False)
    assert op.indices_borrados == []


def test_el_nombre_de_la_tabla_va_entrecomillado():
    """Una tabla que colisione con una palabra reservada no puede romper el DDL
    del aislamiento."""
    op = _OpDoblado()
    enable_rls(op, "order")
    assert all('"order"' in s for s in op.sql)
