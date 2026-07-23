# Verificación del spike de RLS en PostgreSQL 17

**Tarea:** 1.2 (backend) del plan `2026-07-22-fundacion-fase-0-plan.md`
**Fecha de ejecución:** 2026-07-22
**Entorno:** `postgres:17-alpine` efímero — `PostgreSQL 17.10 on aarch64-unknown-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit`
**Reproducir:** `bash scripts/spikes/rls-spike.sh`

Artefactos:

| Archivo | Qué contiene |
|---|---|
| `scripts/spikes/rls-spike.sh` | Levanta el PG efímero, ejecuta los dos `.sql` y repite el primero para demostrar idempotencia |
| `scripts/spikes/rls-spike.sql` | Escenarios A–G, ejecutados como superusuario con `SET ROLE` |
| `scripts/spikes/rls-spike-app.sql` | Escenarios H–N, ejecutados con una **conexión real** como `vendi_app` |

Por qué dos `.sql`: los permisos de `SET ROLE` se evalúan contra el *session user*, no
contra el rol actual. Una sesión abierta como superusuario puede hacer `SET ROLE` a
cualquier rol, así que los escenarios de escalada de privilegios (H) darían un falso
verde si se probaran con `SET ROLE` desde `postgres`. Hay que conectarse de verdad.

---

## Escenario A — el idiom ingenuo falla con ERROR, no con cero filas

```sql
CREATE POLICY p_naive ON ventas
  USING (tenant_id = current_setting('vendi.tenant_id')::uuid);
```

```
### A. Idiom INGENUO: current_setting sin missing_ok → ERROR, no cero filas
CREATE POLICY
INSERT 0 1
RESET
SET
ERROR:  unrecognized configuration parameter "vendi.tenant_id"
```

Confirmado: sin `missing_ok` la consulta termina en excepción → HTTP 500, no en cero
filas. **No** falla cerrado; falla ruidoso y filtra la existencia del problema al
usuario final.

> **Discrepancia con el plan.** El paso 3 de la tarea 1.2 dice que "el idiom del spec
> (§4.1) tal como está escrito falla con ERROR 500". Es falso: el spec §4.1 ya escribe
> la policy con `NULLIF` + `missing_ok` y ya explica en prosa por qué el idiom ingenuo
> revienta. El escenario A no refuta al spec, lo **corrobora**. No hay corrección que
> redactar para ADR-013 por este motivo.

## Escenario B — el idiom robusto: cero filas sin error

```sql
CREATE POLICY tenant_isolation ON ventas
  USING      (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid);
```

```
 b1_guc_nunca_definido_debe_ser_0    →  0
 b2_con_guc_debe_ser_1               →  1
 b3_tras_commit_debe_ser_0           →  0
```

`b3` es el hallazgo operativo importante: el `SET LOCAL` **muere en el `COMMIT`**, y la
siguiente consulta de la misma sesión ve cero filas *en silencio*. Es exactamente el
motivo por el que el `SET LOCAL` no lo puede emitir el middleware una vez por request:
lo tiene que reinstalar el evento `after_begin` de la sesión en cada transacción nueva
(tarea 3.3).

## Escenario C — `WITH CHECK` cierra el INSERT cruzado

```
BEGIN
SET
ERROR:  new row violates row-level security policy for table "ventas"
ROLLBACK
```

## Escenario G — `WITH CHECK` cierra el UPDATE que mueve la fila de tenant

```
### G. WITH CHECK cierra el UPDATE que mueve la fila a otro tenant
BEGIN
SET
ERROR:  new row violates row-level security policy for table "ventas"
ROLLBACK
BEGIN
SET
UPDATE 1
 g2_update_propio_tenant_debe_ser_1  →  1
COMMIT
```

`UPDATE ventas SET tenant_id = '<otro tenant>'` con el GUC del tenant 1 se bloquea; el
`UPDATE` que no toca `tenant_id` pasa. `USING` por sí solo no habría cubierto esto.

## Escenario D — `FORCE` muerde al owner; `BYPASSRLS` lo salta

```
 d1_platform_bypassrls_lo_ve_todo              →  1
 d2_owner_sin_bypassrls_bajo_force_debe_ser_0  →  0
```

`d2` reasigna el owner de la tabla a un rol **sin** `BYPASSRLS` y demuestra que
`FORCE ROW LEVEL SECURITY` le aplica igual. Consecuencia para las migraciones: Alembic
tiene que correr como `vendi_platform` (owner **y** `BYPASSRLS`), o cualquier backfill
verá cero filas. Esto fija el DSN de `scripts/migrate.sh` en la tarea 2.3.

```
    rolname     | rolbypassrls | rolsuper
----------------+--------------+----------
 vendi_app      | f            | f
 vendi_platform | t            | f
```

Nótese que ninguno de los dos es superusuario: `BYPASSRLS` es un atributo aparte y es
todo lo que `vendi_platform` necesita.

## Escenario E / N — cómo se neutraliza un GUC personalizado

El plan y el spec asumen que `RESET` sobre un GUC personalizado nunca seteado "no está
definido". **Medido en PG 17.10, no es así.** Sesión recién abierta como `vendi_app`:

```
 n1_nunca_definido_es_null    →  t     -- current_setting('vendi.tenant_id', true) IS NULL
RESET
 n2_tras_reset_sigue_null     →  f     -- RESET no falla, y deja el valor en ''
SET
 n3_tras_set_vacio_es_null    →  f     ·  n3_valor  →  ''
SET
RESET
 n4_tras_set_y_reset_es_null  →  f     ·  n4_valor  →  ''
```

Y los tres estados posibles dan cero filas:

```
 k1_guc_neutralizado_debe_ser_0  →  0    (nunca definido)
 e2_tras_set_vacio_debe_ser_0    →  0    (SET a '')
 e4_tras_reset_debe_ser_0        →  0    (RESET tras un SET)
```

Los tres convergen porque `NULLIF(current_setting(...), '')::uuid` produce `NULL` tanto
si el valor es `NULL` como si es `''`, y `tenant_id = NULL` es `NULL` → la fila no pasa
el filtro.

**Decisión (se mantiene la del spec, con mejor argumento):** el hook de checkout ejecuta
`SET vendi.tenant_id = ''`, no `RESET`. La razón no es que `RESET` falle —no falla—,
sino que:

1. `SET ''` deja el GUC en un estado explícito y observable (`''`), idéntico venga la
   conexión de donde venga; `RESET` depende de la semántica de "valor de reset" de un
   placeholder, que es un detalle interno del motor y no está documentado como contrato.
2. Es un solo camino de código, sin ramas según si el GUC existía o no en la sesión.

## Escenario F — el predicado de la policy usa el índice

5.000 filas por tenant, `ANALYZE`, e índice `ix_ventas_tenant (tenant_id)`:

```
 Index Scan using ix_ventas_tenant on ventas (actual time=0.227..0.228 rows=10 loops=1)
   Index Cond: (tenant_id = (NULLIF(current_setting('vendi.tenant_id'::text, true), ''::text))::uuid)
   Filter: (total > '4990'::numeric)
   Rows Removed by Filter: 4991
   Buffers: shared hit=37 read=6
 Planning Time: 0.062 ms
 Execution Time: 0.236 ms
```

El predicado RLS aparece como `Index Cond`, no como filtro post-scan: el planificador lo
trata como cualquier otra condición indexable. **Consecuencia de diseño:** toda tabla de
negocio necesita un índice que empiece por `tenant_id` (solo o compuesto), o cada consulta
degenera en un seq scan de toda la región. Esto entra como regla en `TenantModel` (tarea 3.3).

## Escenarios H, I, J — `vendi_app` no puede escaparse

Conexión real como `vendi_app` (`psql -h 127.0.0.1 -U vendi_app`):

```
### H. vendi_app intenta escalar a vendi_platform
ERROR:  permission denied to set role "vendi_platform"
 h1_sigue_siendo_vendi_app  →  vendi_app

### I. vendi_app intenta desactivar RLS
ERROR:  must be owner of table ventas          -- ALTER TABLE ... DISABLE ROW LEVEL SECURITY
ERROR:  must be owner of table ventas          -- ALTER TABLE ... NO FORCE ROW LEVEL SECURITY
ERROR:  must be owner of relation ventas       -- DROP POLICY tenant_isolation ON ventas

### J. vendi_app intenta crear una tabla en public
ERROR:  permission denied for schema public
```

## Escenario L — aislamiento entre dos tenants con datos reales

```
 l1_t1_debe_ser_5001  →  5001
 l2_t2_debe_ser_5000  →  5000
 l3_fuga_de_sesion    →  5001     (SET de sesión, no SET LOCAL)
 l4_tras_set_vacio_debe_ser_0  →  0
```

## Escenario M — GUC con un valor que no es UUID

```
BEGIN
SET
ERROR:  invalid input syntax for type uuid: "no-es-un-uuid"
ROLLBACK
```

Un valor basura en el GUC produce un error de cast, **no** una fuga. La transacción
aborta. Es fail-closed, pero ruidoso: por eso el middleware valida el alias con
`uuid.UUID(...)` y responde 401 antes de tocar la base (tarea 3.4), en vez de dejar que
el error suba desde el driver.

---

## Hallazgo no previsto: la propiedad del schema `public`

La primera ejecución del spike falló así:

```
SET
ERROR:  permission denied for schema public
LINE 1: CREATE TABLE ventas (
```

Desde **PostgreSQL 15** el rol `PUBLIC` ya no tiene `CREATE` sobre el schema `public`, y
ese schema pertenece a `pg_database_owner`. `vendi_platform`, que en el spike no es el
dueño de la base, no puede crear ni una tabla.

> **Corrección del arquitecto (QA de cierre de Etapa 1).** El error anterior es un
> **artefacto del entorno del spike**, que corre sobre la base `postgres` (propiedad del
> superusuario), no una regla general. En el layout de producción que prescribe la tarea
> 2.2 —`CREATE DATABASE vendi OWNER vendi_platform`— el schema `public` pertenece a
> `pg_database_owner`, del que `vendi_platform` es miembro implícito por ser dueño de la
> base, y crea tablas **sin ningún `ALTER SCHEMA`**. Verificado en `postgres:17-alpine`:
>
> ```
>   current_user  |   dueno_public
> ----------------+-------------------
>  vendi_platform | pg_database_owner
> CREATE TABLE            -- sin ALTER SCHEMA previo
> ERROR:  permission denied for schema public   -- vendi_app sigue sin poder crear
> ```
>
> El `ALTER SCHEMA public OWNER TO vendi_platform` de `01-roles.sh` (tarea 2.2) **se
> conserva** porque hace la propiedad explícita e independiente del orden de creación de
> la base, pero es defensivo, no obligatorio. La razón redactada originalmente aquí
> («sin él no hay DDL posible») era falsa y no debe copiarse a la Etapa 2.

El spike, al correr sobre la base `postgres`, sí necesita reasignar la propiedad:

```sql
ALTER SCHEMA public OWNER TO vendi_platform;
GRANT USAGE ON SCHEMA public TO vendi_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;   -- explícito aunque ya sea el default
```

## Re-ejecutabilidad

`rls-spike.sh` recrea el contenedor en cada corrida, y además ejecuta `rls-spike.sql`
**dos veces seguidas** contra la misma base (se desactiva con `SPIKE_DOBLE_EJECUCION=0`).
El diff de las dos corridas, ignorando tiempos del `EXPLAIN ANALYZE` y `NOTICE`s, es vacío:

```
$ diff <(...primera ejecución...) <(...segunda ejecución...) && echo IDENTICAS
IDENTICAS
```

Idempotencia lograda con: creación de roles dentro de un `DO $$ ... IF NOT EXISTS`,
`DROP TABLE IF EXISTS ventas` al inicio y `CREATE INDEX IF NOT EXISTS`.

---

## Decisiones que fija este spike

1. **Texto exacto de la policy** que emitirá `vendi-core` (y toda migración de Alembic
   para tablas de tenant):

   ```sql
   ALTER TABLE <tabla> ENABLE ROW LEVEL SECURITY;
   ALTER TABLE <tabla> FORCE  ROW LEVEL SECURITY;
   CREATE POLICY tenant_isolation ON <tabla>
     USING      (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
     WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid);
   ```

2. **Propagación:** `SET LOCAL vendi.tenant_id = '<uuid>'` emitido por el evento
   `after_begin` de la sesión, no por el middleware. Motivo medido: escenario B.3.

3. **Neutralización en el checkout del pool:** `SET vendi.tenant_id = ''` (asignación
   explícita). `RESET` también funciona en PG 17, pero se descarta por depender de un
   detalle interno y por obligar a razonar sobre dos estados distintos.

4. **Roles:** `vendi_platform` = owner del schema `public` y de las tablas, con
   `BYPASSRLS`, sin superusuario; es el DSN de Alembic. `vendi_app` = sin `BYPASSRLS`,
   sin ownership, sin `CREATE` en `public`; es el DSN de la API. Verificado que `vendi_app`
   no puede hacer `SET ROLE vendi_platform`, ni desactivar RLS, ni crear tablas.

5. **Índices:** toda tabla con policy `tenant_isolation` lleva un índice cuya primera
   columna es `tenant_id`. El planificador usa el predicado de la policy como `Index Cond`.

6. **Migraciones:** corren con `vendi_platform`. Bajo `FORCE ROW LEVEL SECURITY` cualquier
   otro rol —incluido un owner sin `BYPASSRLS`— vería cero filas en un backfill.

7. **Propiedad del schema:** el init de Postgres crea la base con
   `CREATE DATABASE vendi OWNER vendi_platform`; con eso `vendi_platform` ya puede hacer
   DDL en `public` (es miembro implícito de `pg_database_owner`). El
   `ALTER SCHEMA public OWNER TO vendi_platform` de `01-roles.sh` se mantiene como
   medida **defensiva y explícita**, no como requisito. (Corregido por el arquitecto:
   la redacción original lo declaraba obligatorio a partir de un artefacto del spike,
   que corre sobre la base `postgres`, propiedad del superusuario.)

8. **Valor inválido en el GUC:** produce error de cast, no fuga. El middleware valida el
   alias como UUID antes de sembrarlo.

Sin pendientes.

## Correcciones que la Etapa 3 debe aplicar a ADR-013 / spec §4.1

1. Sustituir la justificación «`RESET` sobre un GUC personalizado nunca seteado no está
   definido» por la medida: **`RESET` sí está definido en PG 17** — no falla ni siquiera
   sobre un GUC jamás seteado y deja el valor en `''`. La decisión de usar
   `SET vendi.tenant_id = ''` en el checkout del pool **se mantiene**, pero por el
   argumento correcto: estado explícito y observable, y un solo camino de código sin
   ramas según el historial de la sesión (escenarios E/N de este informe).
2. No hay corrección que aplicar por el escenario A: el idiom `NULLIF` + `missing_ok`
   del spec §4.1 ya es el correcto; el spike lo corrobora, no lo refuta.
3. Añadir a la regla de `TenantModel` (tarea 3.3): toda tabla con policy
   `tenant_isolation` lleva índice cuya primera columna es `tenant_id` — el predicado
   RLS se resuelve como `Index Cond` (escenario F).
