# ADR-017 — Sincronización offline-first: IndexedDB como verdad local, cola por dispositivo y sync idempotente

**Fecha:** 2026-07-27 · **Estado:** Firmada
**Origen:** `docs/plan-maestro.md` §3 (POS offline-first) y §10 («Sync offline /
conflictos de stock»); `docs/plan-tecnico.md` («la venta NUNCA depende del
internet»); plan de Fase 1, Etapa 1.1-A.

## Contexto

La tienda de barrio vende con internet malo, intermitente o inexistente, y la
fila de clientes no espera a que vuelva la red. El plan técnico ya lo fija en
una frase: la venta nunca depende del internet. Pero en el repo la promesa está
sin cumplir: el README de `data-access` anuncia «IndexedDB como fuente de verdad
offline» y `public-api.ts` repite «Dexie/IndexedDB», y **Dexie no está
instalado ni existe una sola tabla local**. Lo que había que decidir es dónde
vive la verdad local, cómo suben los cambios al servidor y qué garantiza que un
reintento no duplique nada. Es la decisión que condiciona al módulo de ventas,
a la app móvil y a media Etapa 1.4 (QA de conflictos).

## Decisión

**La fuente de verdad en el dispositivo es IndexedDB vía Dexie, y el servidor
es la verdad consolidada; entre ambos va una cola local y un endpoint de sync
idempotente.** Cuatro piezas:

1. **Dexie vive encapsulado en `data-access`.** ADR-011 ya prohíbe importar
   `dexie` en `domain`, `ui-kit`, `auth`, `native` y en las tres apps web;
   `data-access` es el único sitio autorizado y solo `vendi-app` la consume
   (las apps web no venden offline). El spike de Dexie va primero, en
   `scripts/spikes/`, como manda la tradición del repo.
2. **IDs generados en el cliente.** Toda entidad creada en el dispositivo nace
   con un UUIDv4 local que el servidor acepta como clave primaria. Esto es lo
   que hace al sync idempotente de raíz: reenviar la misma operación es un
   no-op porque la fila ya existe, no porque haya que recordar qué se procesó.
3. **Cola local de sincronización.** Una tabla `cola_sync` en IndexedDB: la
   escritura de negocio y el encolado de su operación ocurren en la misma
   transacción de Dexie — el mismo patrón outbox del backend
   (`vendi_core.messaging.outbox`), en espejo. El drenado es FIFO por
   dispositivo con una `secuencia` entera local, reintento con backoff
   exponencial y tope, y dos disparadores: el evento de conectividad y
   Background Sync donde exista. El service worker de la PWA **solo cachea
   assets** (ya firmado en `plan-tecnico.md`): no hay dos lógicas offline.
4. **Endpoints de sync en la API** (módulo `ventas`, Etapa 1.2):
   `POST /api/v1/sync/lotes` recibe un lote ordenado de operaciones y aplica
   cada una como upsert por su ID de cliente, dentro de una transacción por
   lote, respondiendo por operación `aceptada` / `duplicada` /
   `rechazada(motivo)`; y `GET /api/v1/sync/delta?desde=...` baja los cambios
   de datos de referencia al dispositivo. No hay tabla de «ya procesados»: la
   propia fila de dominio, con la PK que le puso el cliente, es la prueba de
   idempotencia. El lote corre con el GUC del tenant y cada fila pasa la policy
   RLS — el `WITH CHECK` de ADR-013 rechaza un `tenant_id` inyectado en el
   payload.

**Conflictos.** *Last-write-wins* por documento, solo para datos de referencia
editables (catálogo, clientes), arbitrado **por orden de recepción en el
servidor, nunca por el reloj del cliente** — el escenario «reloj adelantado /
atrasado» ya está en la lista del QA adversarial de la Etapa 1.4. La edición
descartada queda registrada en auditoría: la pérdida es posible pero visible y
acotada. El stock **no** usa LWW: se reconcilia por deltas (movimientos), cuyo
modelo fija ADR-020. Las ventas no tienen conflicto: son append-only (ADR-018).

## Alternativas descartadas

- **CRDT o versionado vectorial.** El conflicto real es pequeño (una tienda,
  hasta 3 empleados, un puñado de dispositivos) y el coste de implementar y
  probar bien un CRDT es desproporcionado con él. LWW con auditoría deja la
  pérdida acotada, visible y barata.
- **Online-first con caché de respaldo** (pegarle a la API y caer a local si
  falla). Devuelve la dependencia de la red al peor momento posible: el cobro.
  El plan técnico lo descarta de palabra.
- **PouchDB/CouchDB o un protocolo de replicación existente.** Traería un
  servidor y un protocolo que no tenemos, y contradice el contrato REST +
  codegen OpenAPI por el que ya pasa todo el acceso HTTP (ADR-011).
- **Fiar el orden al reloj del dispositivo.** El reloj del cliente es dato (se
  guarda, aparece en el ticket), no árbitro: se manipula con dos toques en
  Android.

## Consecuencias

- Dexie entra como dependencia nueva del workspace — la única librería de
  frontend que añade Fase 1. Hasta que el spike cierre, nada del POS móvil se
  implementa.
- `POST /sync/lotes` es un endpoint que escribe en masa: el riesgo no se
  mitiga relajando RLS sino aplicando cada operación dentro de la sesión del
  tenant, y el candado de privilegios de `vendi_app`
  (`test_privilegios_de_vendi_app.py`) sigue siendo la red.
- LWW acepta que una edición concurrente de catálogo se pierda. Es un precio
  explícito: quien edite el mismo producto desde dos dispositivos sin
  sincronizar verá ganar el último que subió, con rastro en auditoría.
- La topología de exchanges de `plan-tecnico.md` §RabbitMQ mencionaba un
  `sync.jobs` propio; queda subsumida: el dispatcher solo publica en su
  exchange único `events.tenant` (cierre de la deuda D-07 en
  `vendi_core.messaging.outbox`) y los eventos del sync son eventos de dominio
  con routing key `<tenant>.<evento>`, no una cola aparte.
## Tablas, eventos y candado

- **Tablas nuevas:** `dispositivos` (registro de dispositivos del tenant:
  nombre, `ultima_secuencia`, `ultima_sync`) — con `tenant_id`, policy RLS e
  índice que empieza por `tenant_id`, vía `enable_rls(op, ...)`.
- **Eventos de outbox:** ninguno propio de la capa. Los eventos de dominio los
  emite cada módulo al aplicar el lote, **una sola vez por operación
  aceptada**; una operación `duplicada` no re-emite.
- **Candados:** (1) `backend/tests/integration/test_sync_idempotente.py` — el
  mismo lote enviado dos veces deja el mismo número de filas, el mismo stock y
  un solo evento por operación; (2) spec de `data-access` que prueba que la
  cola sobrevive a la recarga de la app y drena en orden; (3) el candado de
  fronteras ESLint (ADR-011) verifica que `dexie` solo aparece en
  `data-access` — se amplía si el conjunto de reglas no lo cubre ya.
