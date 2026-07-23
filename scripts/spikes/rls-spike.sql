-- =====================================================================
-- rls-spike.sql — Spike de Row Level Security en PostgreSQL 17
--
-- Verifica los supuestos de ADR-013 (§4.1 del spec de Fase 0):
--   A. El idiom INGENUO (current_setting sin missing_ok) falla con ERROR,
--      no con cero filas → NO falla cerrado.
--   B. El idiom ROBUSTO (NULLIF + missing_ok) devuelve cero filas sin error
--      y el SET LOCAL muere con la transacción.
--   C. WITH CHECK bloquea el INSERT cruzado entre tenants.
--   D. FORCE ROW LEVEL SECURITY aplica al owner; BYPASSRLS lo salta.
--   E. El "reset" de un GUC personalizado: SET a cadena vacía.
--   F. El predicado de la policy usa el índice de tenant_id.
--   G. WITH CHECK bloquea el UPDATE que intenta mover una fila de tenant.
--
-- Ejecutar con:  psql -v ON_ERROR_STOP=0 -f rls-spike.sql
-- (los escenarios A, C y G producen errores ESPERADOS)
--
-- El script es IDEMPOTENTE: se puede ejecutar N veces seguidas contra la
-- misma base sin reventar por objetos existentes.
-- =====================================================================

\set ON_ERROR_STOP 0
\pset pager off

RESET ROLE;

\echo ''
\echo '### 0. Preparación idempotente: roles, tabla y permisos'
\echo ''

-- Los roles se crean solo si no existen (re-ejecutabilidad).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vendi_platform') THEN
    CREATE ROLE vendi_platform LOGIN PASSWORD 'spike' BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vendi_app') THEN
    CREATE ROLE vendi_app LOGIN PASSWORD 'spike';
  END IF;
END
$$;

-- Estado de partida limpio: la tabla se recrea en cada ejecución.
DROP TABLE IF EXISTS ventas;

SELECT rolname, rolbypassrls, rolsuper
  FROM pg_roles
 WHERE rolname IN ('vendi_platform', 'vendi_app')
 ORDER BY rolname;

-- Propiedad del schema como en producción (ver infra/postgres/init/01-roles.sh).
-- HALLAZGO: en PostgreSQL 15+ el rol PUBLIC ya NO tiene CREATE sobre el schema
-- `public` y este pasa a ser propiedad de `pg_database_owner`. Sin este
-- ALTER SCHEMA, `vendi_platform` no puede crear ni una tabla:
--   ERROR: permission denied for schema public
ALTER SCHEMA public OWNER TO vendi_platform;
GRANT USAGE ON SCHEMA public TO vendi_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;   -- explícito aunque ya sea el default

-- Tabla de prueba con el owner de producción: vendi_platform.
SET ROLE vendi_platform;
CREATE TABLE ventas (
  id        serial PRIMARY KEY,
  tenant_id uuid NOT NULL,
  total     numeric
);
GRANT SELECT, INSERT, UPDATE, DELETE ON ventas TO vendi_app;
GRANT USAGE, SELECT ON SEQUENCE ventas_id_seq TO vendi_app;
ALTER TABLE ventas ENABLE ROW LEVEL SECURITY;
ALTER TABLE ventas FORCE ROW LEVEL SECURITY;

\echo ''
\echo '### A. Idiom INGENUO: current_setting sin missing_ok → ERROR, no cero filas'
\echo '###    (ESPERADO: ERROR unrecognized configuration parameter "vendi.tenant_id")'
\echo ''

CREATE POLICY p_naive ON ventas
  USING (tenant_id = current_setting('vendi.tenant_id')::uuid);

INSERT INTO ventas (tenant_id, total)
     VALUES ('11111111-1111-1111-1111-111111111111', 100);

RESET ROLE;
SET ROLE vendi_app;
SELECT * FROM ventas;                      -- ESPERADO: ERROR

RESET ROLE;
SET ROLE vendi_platform;
DROP POLICY p_naive ON ventas;

\echo ''
\echo '### B. Idiom ROBUSTO: NULLIF + missing_ok → cero filas sin error'
\echo ''

CREATE POLICY tenant_isolation ON ventas
  USING      (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid);

RESET ROLE;
SET ROLE vendi_app;

-- B.1 — la variable NUNCA se ha definido en esta sesión: cero filas, sin error.
SELECT count(*) AS b1_guc_nunca_definido_debe_ser_0 FROM ventas;

BEGIN;
  SET LOCAL vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
  SELECT count(*) AS b2_con_guc_debe_ser_1 FROM ventas;
COMMIT;

-- B.3 — el SET LOCAL murió con la transacción.
SELECT count(*) AS b3_tras_commit_debe_ser_0 FROM ventas;

\echo ''
\echo '### C. WITH CHECK cierra el INSERT cruzado (ESPERADO: ERROR row-level security)'
\echo ''

BEGIN;
  SET LOCAL vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
  INSERT INTO ventas (tenant_id, total)
       VALUES ('22222222-2222-2222-2222-222222222222', 50);   -- ESPERADO: ERROR
ROLLBACK;

\echo ''
\echo '### G. WITH CHECK cierra el UPDATE que mueve la fila a otro tenant'
\echo '###    (ESPERADO: ERROR row-level security)'
\echo ''

BEGIN;
  SET LOCAL vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
  UPDATE ventas
     SET tenant_id = '22222222-2222-2222-2222-222222222222';   -- ESPERADO: ERROR
ROLLBACK;

-- G.2 — el UPDATE que respeta el tenant sí pasa.
BEGIN;
  SET LOCAL vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
  UPDATE ventas SET total = 101;
  SELECT count(*) AS g2_update_propio_tenant_debe_ser_1 FROM ventas WHERE total = 101;
COMMIT;

\echo ''
\echo '### D. FORCE aplica al owner sin BYPASSRLS; BYPASSRLS lo salta'
\echo ''

RESET ROLE;
SET ROLE vendi_platform;
SELECT count(*) AS d1_platform_bypassrls_lo_ve_todo FROM ventas;

-- D.2 — misma tabla, mismo owner, pero sin BYPASSRLS: FORCE muerde.
--       Se simula con un rol owner alternativo sin BYPASSRLS.
RESET ROLE;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'spike_owner_sin_bypass') THEN
    CREATE ROLE spike_owner_sin_bypass;
  END IF;
END
$$;
GRANT vendi_platform TO spike_owner_sin_bypass;
ALTER TABLE ventas OWNER TO spike_owner_sin_bypass;
SET ROLE spike_owner_sin_bypass;
SELECT count(*) AS d2_owner_sin_bypassrls_bajo_force_debe_ser_0 FROM ventas;
RESET ROLE;
ALTER TABLE ventas OWNER TO vendi_platform;

\echo ''
\echo '### E. Reset de un GUC personalizado: SET a cadena vacía es lo fiable'
\echo ''

RESET ROLE;
SET ROLE vendi_app;
SET vendi.tenant_id = '11111111-1111-1111-1111-111111111111';   -- fuga simulada a nivel sesión
SELECT count(*) AS e1_fuga_de_sesion_ve_filas FROM ventas;
SET vendi.tenant_id = '';                                       -- lo que hace el hook de checkout
SELECT count(*) AS e2_tras_set_vacio_debe_ser_0 FROM ventas;
SELECT current_setting('vendi.tenant_id', true) AS e3_valor_del_guc_tras_set_vacio;

-- E.4 — ¿y RESET, que es lo que uno escribiría por instinto?
SET vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
RESET vendi.tenant_id;
SELECT count(*) AS e4_tras_reset_debe_ser_0 FROM ventas;
SELECT coalesce(current_setting('vendi.tenant_id', true), '<NULL>') AS e5_valor_tras_reset;

-- Se deja la sesión en estado neutro para el escenario F.
SET vendi.tenant_id = '';

\echo ''
\echo '### F. Plan de consulta: el predicado de la policy usa el índice de tenant_id'
\echo ''

RESET ROLE;
SET ROLE vendi_platform;
INSERT INTO ventas (tenant_id, total)
SELECT '11111111-1111-1111-1111-111111111111', g
  FROM generate_series(1, 5000) g;
INSERT INTO ventas (tenant_id, total)
SELECT '22222222-2222-2222-2222-222222222222', g
  FROM generate_series(1, 5000) g;
CREATE INDEX IF NOT EXISTS ix_ventas_tenant ON ventas (tenant_id);
ANALYZE ventas;

RESET ROLE;
SET ROLE vendi_app;
BEGIN;
  SET LOCAL vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
  EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT * FROM ventas WHERE total > 4990;
COMMIT;

RESET ROLE;
\echo ''
\echo '### Fin de rls-spike.sql'
\echo ''
