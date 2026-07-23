-- =====================================================================
-- rls-spike-app.sql — Segunda mitad del spike de RLS.
--
-- Estos escenarios NO se pueden probar con SET ROLE desde una sesión de
-- superusuario: los permisos de SET ROLE se evalúan contra el *session
-- user*, no contra el rol actual. Hay que conectarse de verdad como
-- vendi_app. Por eso viven en un archivo aparte que rls-spike.sh ejecuta
-- con `psql -U vendi_app`.
--
-- Escenarios (continúan la numeración de rls-spike.sql):
--   H. vendi_app NO puede escalar a vendi_platform (SET ROLE debe fallar).
--   I. vendi_app NO puede desactivar RLS (no es owner de la tabla).
--   J. vendi_app NO puede crear tablas en public (sin CREATE).
--   K. GUC nunca definido en la sesión → cero filas, sin error.
--   L. GUC definido y luego puesto a '' → cero filas, sin error.
--
-- Precondición: rls-spike.sql ya corrió (deja 5001 filas de T1 y 5000 de T2).
-- =====================================================================

\set ON_ERROR_STOP 0
\pset pager off

\echo ''
\echo '### N. Semántica exacta del GUC personalizado en una sesión RECIÉN abierta'
\echo '###    (decide qué hace el hook de checkout del pool: SET '''' vs RESET)'
\echo ''
SELECT current_user AS conectado_como, session_user AS session_user;

-- N.1 — nunca definido: ¿NULL o cadena vacía?
SELECT current_setting('vendi.tenant_id', true) IS NULL AS n1_nunca_definido_es_null;

-- N.2 — ¿RESET sobre un GUC nunca definido en la sesión falla?
RESET vendi.tenant_id;
SELECT current_setting('vendi.tenant_id', true) IS NULL AS n2_tras_reset_sigue_null;

-- N.3 — SET a cadena vacía: el estado neutro que instala el hook de checkout.
SET vendi.tenant_id = '';
SELECT current_setting('vendi.tenant_id', true) IS NULL AS n3_tras_set_vacio_es_null,
       quote_literal(current_setting('vendi.tenant_id', true)) AS n3_valor;

-- N.4 — tras un SET real, ¿RESET lo devuelve a NULL o a ''?
SET vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
RESET vendi.tenant_id;
SELECT current_setting('vendi.tenant_id', true) IS NULL AS n4_tras_set_y_reset_es_null,
       quote_literal(current_setting('vendi.tenant_id', true)) AS n4_valor;

\echo ''
\echo '### K. GUC neutralizado → cero filas, sin error'
\echo ''
SELECT count(*) AS k1_guc_neutralizado_debe_ser_0 FROM ventas;

\echo ''
\echo '### H. vendi_app intenta escalar a vendi_platform (ESPERADO: ERROR permission denied)'
\echo ''
SET ROLE vendi_platform;                      -- ESPERADO: ERROR
SELECT current_user AS h1_sigue_siendo_vendi_app;

\echo ''
\echo '### I. vendi_app intenta desactivar RLS (ESPERADO: ERROR must be owner)'
\echo ''
ALTER TABLE ventas DISABLE ROW LEVEL SECURITY;   -- ESPERADO: ERROR
ALTER TABLE ventas NO FORCE ROW LEVEL SECURITY;  -- ESPERADO: ERROR
DROP POLICY tenant_isolation ON ventas;          -- ESPERADO: ERROR

\echo ''
\echo '### J. vendi_app intenta crear una tabla en public (ESPERADO: ERROR o éxito a documentar)'
\echo ''
CREATE TABLE fuga_rls (id int);

\echo ''
\echo '### L. Con GUC del tenant 1 → sus filas; tras SET a cadena vacía → cero'
\echo ''
BEGIN;
  SET LOCAL vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
  SELECT count(*) AS l1_t1_debe_ser_5001 FROM ventas;
COMMIT;

BEGIN;
  SET LOCAL vendi.tenant_id = '22222222-2222-2222-2222-222222222222';
  SELECT count(*) AS l2_t2_debe_ser_5000 FROM ventas;
COMMIT;

SET vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
SELECT count(*) AS l3_fuga_de_sesion FROM ventas;
SET vendi.tenant_id = '';
SELECT count(*) AS l4_tras_set_vacio_debe_ser_0 FROM ventas;

\echo ''
\echo '### M. SET LOCAL con un uuid inválido (ESPERADO: ERROR de cast, no fuga)'
\echo ''
BEGIN;
  SET LOCAL vendi.tenant_id = 'no-es-un-uuid';
  SELECT count(*) AS m1_debe_dar_error_de_cast FROM ventas;   -- ESPERADO: ERROR
ROLLBACK;

\echo ''
\echo '### Fin de rls-spike-app.sql'
\echo ''
