# ADR-013 — Aislamiento multi-negocio por RLS en schema único

**Fecha:** 2026-07-22 · **Estado:** Firmada (Fase 0)
**Evidencia:** `docs/superpowers/specs/2026-07-22-verificacion-rls.md` (spike 1.2)

## Contexto

Vendi guarda los datos de todos los negocios de una región en la misma base. La
promesa central del producto es que un negocio no ve los datos de otro. Había
tres formas de cumplirla: filtrar en la aplicación, un schema por negocio (lo
que hacía BaseSaaS, de donde se cosechó el código) o Row Level Security.

## Decisión

**RLS en schema único**, con dos roles de base de datos y un GUC de sesión.

- Rol de la API: **`vendi_app`**, **sin `BYPASSRLS`**. Es el que usan los
  handlers. No puede saltarse ninguna policy ni por accidente.
- Rol de plataforma: **`vendi_platform`**, **con `BYPASSRLS`**, owner de las
  tablas. Migraciones, worker y consola de plataforma.
- GUC de negocio: **`vendi.tenant_id`**, siempre con `SET LOCAL` en código de
  petición, nunca con `SET`.

## El idiom de la policy — el del spike, no el del spec

El spec §4.1 traía un SQL que el spike 1.2 corrigió. El bueno es:

```sql
ALTER TABLE "<tabla>" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "<tabla>" FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON "<tabla>"
  USING      (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid);
```

Cada pieza cierra un escenario medido:

- **`FORCE`** aplica la policy también al *owner*. Sin él, `vendi_platform`
  saltaría la policy por ser owner y no por tener `BYPASSRLS`, y se perdería la
  distinción entre las dos cosas (escenario D).
- **`current_setting(..., true)`** — el `true` es `missing_ok`. Sin él, una
  sesión que nunca definió el GUC revienta con `unrecognized configuration
  parameter`, es decir, un HTTP 500, en vez de ver **cero filas** (escenario A).
  Fallar cerrado es ver cero filas, no reventar.
- **`NULLIF(..., '')`** cubre el otro estado posible: el GUC en cadena vacía,
  que es lo que deja el hook de checkout del pool al devolver una conexión.
- **`WITH CHECK` además de `USING`.** `USING` filtra lo que se lee; `WITH CHECK`
  valida lo que se escribe. Sin él, un `INSERT` con `tenant_id` ajeno pasa y un
  `UPDATE ... SET tenant_id = <otro>` **regala la fila a otro negocio**
  (escenarios C y G).
- **Índice que EMPIECE por `tenant_id`.** El planificador usa el predicado de la
  policy como `Index Cond` (escenario F). Sin índice, cada consulta recorre las
  filas de toda la región: no es solo lentitud, es que el coste de un negocio
  depende del tamaño de los demás.

## El reset entre peticiones

Al devolver la conexión al pool se ejecuta `SET vendi.tenant_id = ''`. Es la
razón de que el `NULLIF` esté en el predicado: un GUC vacío tiene que
significar «ningún negocio», no «el negocio cuyo id es la cadena vacía».

## Tablas de plataforma: la excepción, firmada

`audit_events`, `outbox_messages`, `tenants` y `alembic_version` **no llevan
RLS**, porque se consultan cross-negocio por definición (el dispatcher drena la
cola de todos en una pasada; la consola de plataforma audita a todos). La
excepción solo se sostiene si `vendi_app` no las alcanza, y eso es lo que
verifica `backend/tests/test_privilegios_de_vendi_app.py`, un candado
**invertido**: enumera lo permitido y falla ante cualquier tabla del esquema
`public` que conceda algo distinto. La única excepción con privilegio es
`outbox_messages`, con **INSERT y solo INSERT**, más una policy de INSERT que
ata `tenant_id` al GUC — sin eso, el patrón outbox sería inutilizable desde un
handler.

## Alternativas descartadas

- **Filtrar en la aplicación (`WHERE tenant_id = ?`).** Un `WHERE` olvidado es
  una fuga silenciosa, y no hay forma mecánica de comprobar que están todos.
- **Un schema por negocio.** Es lo que hacía BaseSaaS. Con miles de tiendas
  produce miles de schemas: las migraciones se vuelven un bucle frágil, el
  catálogo de Postgres se hincha, y `search_path` es estado de sesión que se
  olvida exactamente igual que un `WHERE`. Además obliga a mantener sincronizado
  el ORM con N copias del esquema — un problema que BaseSaaS documentaba en un
  runbook entero y que aquí simplemente no existe.

## Consecuencias

- **PgBouncer, si algún día se añade: solo `transaction pooling`.** `SET LOCAL`
  es compatible con ese modo porque muere con la transacción. Un `SET` de sesión
  no lo es: en `session pooling` el GUC sobrevive al final de la petición y la
  siguiente, de otro negocio, hereda el valor. Es la razón de que la regla sea
  «siempre `SET LOCAL`, nunca `SET`» y no una preferencia de estilo.
- Añadir una tabla de negocio obliga a llamar a `enable_rls(op, '<tabla>')` en
  su migración. El candado `test_rls_coverage.py` lo delata si se olvida.
- Los dos DSN son campos de configuración distintos y ambos obligatorios: el
  error que el diseño tiene que hacer imposible es usar el de plataforma donde
  tocaba el de la API. El arranque comprueba contra la base que el primero NO
  tiene `BYPASSRLS` y se niega a arrancar si lo tiene.
