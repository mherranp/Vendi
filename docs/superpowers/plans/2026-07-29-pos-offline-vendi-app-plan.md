# POS offline-first en `vendi-app` — IndexedDB con Dexie, cola de sync por dispositivo y punto de venta (Fase 1, Etapa 1.3, pista móvil) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar el POS offline-first del MVP en `vendi-app` —la venta NUNCA depende del internet— con: el spike de Dexie primero (tradición `scripts/spikes/`, candado de ADR-017), la fundación offline encapsulada en `data-access` (único sitio legal para Dexie según ADR-011/ADR-017): la base `VendiDb` (esquema v1: `productos`, `clientes`, `ventas_locales`, `cola_sync`, `meta`), el outbox local (escritura de negocio + encolado + contadores en UNA transacción Dexie, espejo del outbox del backend), el motor de drenado FIFO por `secuencia` con backoff exponencial y dead-letter para las `rechazada`, el registro del dispositivo (`POST /api/v1/dispositivos` con UUID local persistido y reconciliación de `ultima_secuencia`), el descargador del delta al IndexedDB (`GET /api/v1/sync/delta` con watermark `hasta` y tumbas), la aritmética del ticket en `domain` (dinero en centavos enteros, granel en mili-unidades, redondeo half-up por línea — TS puro, sin framework), y el POS en `vendi-app`: catálogo local con búsqueda, ticket con cantidades granel de 3 decimales, cobro en efectivo y fiado (fiado solo con cliente, con `cliente.crear` encolado FIFO antes que la venta), `consecutivo_local` monotónico por dispositivo, estado de la cola visible y reintento manual. La autenticación reusa `AuthService`/`authGuard`/`tenantGuard` de la lib `auth` con el flujo web (passkey en el navegador); el canal del piloto es la PWA instalada. La auth nativa por navegador del sistema queda FUERA, registrada como deuda D-29. Incluye el retiro oficial del spec-candado de `app.spec.ts` y de la pantalla «próximamente» (este plan ES el subproyecto 2, en su alcance honesto), la extensión de la frontera ESLint de `vendi-app` con `dexie` (candado 3 de ADR-017) y el gate: los 9 proyectos del workspace verdes en test y lint, build de producción de `vendi-app` verde, codegen sin deriva (el backend no se toca) y `android.yml` intacto.

**Architecture:** Se mantiene la arquitectura firmada del workspace Angular (ADR-011): `domain` es TS puro (la aritmética del ticket vive ahí), `data-access` es la única capa con persistencia (Dexie/IndexedDB) y HTTP (`ApiService` + interceptores + cliente generado), `auth` es la sesión (Keycloak passwordless, guards, `authInterceptor` con Bearer + `X-Tenant-Id`), `native` es la única fachada de plataforma, y `vendi-app` consume todo por las superficies públicas. IndexedDB es la fuente de verdad local y el servidor la verdad consolidada (ADR-017); la venta es append-only con identidad y número propios (ADR-018): `id` UUIDv4 del dispositivo como PK, `consecutivo_local` por dispositivo, dinero en centavos, doble verdad temporal (`creada_en_cliente` es dato; `recibida_en` manda en el servidor). El service worker de la PWA solo cachea assets (ya firmado): no hay dos lógicas offline. El contrato OpenAPI está congelado y NO cambia en este plan: el frontend se adapta a `POST /api/v1/sync/lotes` (lote ≤200 operaciones, resultado por operación `aceptada`/`duplicada`/`rechazada`), `GET /api/v1/sync/delta` (productos + tumbas, sin clientes — D-28), `POST /api/v1/dispositivos` y `GET /api/v1/clientes` (asimilación online de clientes).

**Tech Stack:** Angular 21 (standalone, signals, control flow `@if`/`@for`) · TypeScript 5.9 · Dexie 4 (única dependencia nueva del workspace en Fase 1, ADR-017) · Vitest sobre jsdom (`@angular/build:unit-test`) + `fake-indexeddb` para IndexedDB en tests · RxJS 7 · Angular Material 21 · ngx-translate 17 · keycloak-js 26 · openapi-typescript (cliente generado, solo tipos).

**Spec fuente:**
- `docs/adr/adr-017-sincronizacion-offline-first.md` (Dexie encapsulado en `data-access`, ids del cliente como PK, cola local con outbox en espejo, FIFO con `secuencia` + backoff, endpoints de sync, LWW por orden de recepción solo para referencia, candados: cola que sobrevive recarga y drena en orden, frontera ESLint de `dexie`, spike primero)
- `docs/adr/adr-018-modelo-de-ventas-offline.md` (venta append-only, `consecutivo_local`, multi-caja, fiado sin red permitido, dinero en enteros, `creada_en_cliente` dato no árbitro, el servidor resuelve la sesión de caja)
- `docs/adr/adr-011-fronteras-workspace-angular.md` + `frontend/eslint.fronteras.js` (fronteras mecánicas: `dexie` ya prohibido en `domain`, `ui-kit`, `auth`, `native` y las tres apps web; `vendi-app` aún NO lo prohíbe — este plan lo añade)
- `docs/adr/adr-009-fiado-y-clientes.md` (el fiado es el modo normal de vender; se lleva por persona)
- Contrato congelado `docs/api/openapi-fase0.json`: `POST /api/v1/sync/lotes` (`LoteSync`/`OperacionSync`/`RespuestaLote`/`ResultadoOperacion`), `GET /api/v1/sync/delta` (`DeltaSalida`), `POST /api/v1/dispositivos` (`DispositivoRegistrar`/`DispositivoSalida`), `GET /api/v1/clientes` (`ClienteConSaldo`), `GET /api/v1/productos` (`ProductoSalida`)
- Schemas del sync que NO están en el OpenAPI (el campo `datos` es objeto libre): `backend/services/api/app/modules/ventas/schemas.py` (`VentaCrearSync` línea 104, `VentaItemSync` línea 88: `cantidad` Decimal que se cuantiza a 3 decimales, `precio_unitario_centavos` congelado del dispositivo) y `backend/services/api/app/modules/fiado/schemas.py:78` (`ClienteCrearSync`: `extra="forbid"`, `nombre` min 2, `telefono`/`nota`/`limite_credito` opcionales)
- `docs/deuda-tecnica.md` (D-27 abonos offline — abierta, este plan NO depende de ella; D-28 sin delta de clientes — abierta, este plan la rodea con asimilación online)
- `docs/superpowers/plans/2026-07-27-fase1-mvp-colombia-plan.md` §Etapa 1.3 (pista móvil: spike de Dexie + cola PRIMERO, luego POS; el E2E Playwright del flujo de dinero es gate posterior con el stack, NO de este plan)
- Plantillas a imitar: `frontend/projects/vendi-tenant/src/app/` (patrón de features reales, `nucleo/sesion.ts`, `elegir-negocio`), `frontend/projects/libs/data-access/src/lib/api.service.ts` y sus specs (`HttpTestingController`), `frontend/projects/libs/auth/testing/` (`KeycloakFake`, `arrancarSesionFalsa`), `scripts/spikes/` (tradición de spikes)

## Global Constraints

- Todo artefacto en español riguroso (código, docstrings, commits, claves i18n, mensajes de error). Sin tildes ni eñes en identificadores técnicos que viajen en tokens, URLs, JSON o claves de traducción.
- Las fronteras de ADR-011/ADR-017 son mecánicas y no se negocian: `dexie` solo se importa en `data-access`; `@capacitor/*` solo en `native`; `domain` sigue siendo TS puro (sin Angular, sin RxJS, sin Dexie). El candado nuevo de `vendi-app` (Tarea 9) lo hace cumplir también ahí.
- TDD en cada tarea: primero el test que falla (con la salida del fallo esperada), luego la implementación completa, luego el test en verde, luego el commit. Prohibido «similar a», «agregar validación», TODO o código elidido.
- Dinero SIEMPRE en centavos enteros; cantidades SIEMPRE en mili-unidades enteras (1 kg = 1000). Nunca un flotante para dinero ni para masa: el único punto donde un `number` fraccionario existe es el input del tendero, y se convierte a enteros en el borde (`miliDeCantidad`).
- El contrato OpenAPI NO cambia: el backend está entregado y congelado. Si el codegen deriva al ejecutarlo, es un bug del frontend y se corrige el frontend, nunca se edita `docs/api/openapi-fase0.json`.
- Los ids los genera el dispositivo con `crypto.randomUUID()` (UUIDv4, ADR-017). El reloj del cliente es dato, no árbitro: `creada_en_cliente` se guarda y se muestra, pero nada en el dispositivo ordena ni decide por él.
- La cola NUNCA se purga sin veredicto del servidor: una operación solo sale de `cola_sync` con `aceptada` o `duplicada`; la `rechazada` queda como dead-letter visible (`estado: 'error'` + motivo). «Borrar para que suba» está prohibido.
- La escritura de negocio, el encolado y el avance de contadores (`consecutivo_local`, `ultima_secuencia`) ocurren en UNA transacción Dexie (patrón outbox en espejo, ADR-017). Ningún camino escribe la venta sin encolar ni encola sin contador.
- Toda cadena visible va por `translate` con las claves nuevas en `frontend/projects/vendi-app/public/i18n/es.json`; ninguna cadena cruda en plantillas (el candado de i18n del repo ya existe en Fase 0).
- Tests de IndexedDB con `fake-indexeddb/auto` importado ANTES que `dexie` en cada spec que abre base de datos, y una base con nombre único por spec (o `db.delete()` en `afterEach`): nada de estado compartido entre pruebas. La «recarga» se simula cerrando la instancia y abriendo otra con el mismo nombre.
- Los commits son por tarea, mensajes en español estilo oración. Nunca `git push` sin confirmación humana.
- Un ADR no se edita para cambiar de opinión: lo que este plan decide más allá de los ADRs queda listado en la sección siguiente, con su justificación.

## Decisiones de diseño tomadas en este plan (más allá de los ADRs)

1. **La auth nativa por navegador del sistema queda FUERA de esta entrega; la app del piloto es la PWA.** El plan maestro de la Etapa 1.3 pide «auth por navegador del sistema (`@capacitor/browser`, esquema `co.vendi.app://`)». Hacerlo bien exige la fachada en `native`, el manejo del deep-link de retorno (`appUrlOpen`), el flujo OIDC manual fuera de keycloak-js (que navega con `window.location` y no sirve para volver a la app), la asociación de asset links para passkeys y —sobre todo— pruebas en dispositivo real que no son TDD-able en CI. Es un subproyecto propio, no una tarea más. Lo que SÍ entra: `AuthService`, `authGuard` y `tenantGuard` tal cual están, con el flujo web (passkey en el navegador), que funciona en `ng serve` y en la **PWA instalada** — que en Chrome Android tiene passkeys, service worker de assets e IndexedDB, o sea, todo lo que el POS offline necesita. El AAB nativo sigue siendo artefacto de CI (`android.yml` intacto) pero no es el canal del piloto. Se registra como deuda **D-29** con vencimiento antes del piloto nativo. Tensión declarada con el plan maestro, no escondida.
2. **Esquema Dexie v1, exacto:** `productos: 'id, nombre, codigo_barras, categoria'`, `clientes: 'id, nombre'`, `ventas_locales: 'id, consecutivo_local, creada_en_cliente, estado'`, `cola_sync: 'id, secuencia, estado'`, `meta: 'clave'`. Sin tabla de sesiones de caja: el contrato `VentaCrearSync` no lleva `sesion_caja_id` porque el servidor la resuelve (la abre implícita si no hay — ADR-018, «turno offline» ya delegado). Sin tabla de «ya procesados» en el cliente: la fila borrada tras `aceptada`/`duplicada` es la prueba, y la venta queda en `ventas_locales` para el historial. `meta` guarda `dispositivo_id`, `nombre_dispositivo`, `dispositivo_registrado`, `ultima_secuencia`, `consecutivo_local` y `delta_hasta` — dos contadores distintos a propósito: el consecutivo es el número que ve el tendero en el ticket; la secuencia es el orden FIFO de la cola (incluye `cliente.crear`, que no tiene número de venta).
3. **IndexedDB en Vitest con `fake-indexeddb/auto` por spec.** jsdom (el entorno del builder `@angular/build:unit-test`) no implementa IndexedDB; `fake-indexeddb` es la emulación estándar que Dexie soporta y la que el ecosistema usa para exactamente esto. La «recarga» de los candados de ADR-017 se simula cerrando la instancia de Dexie y abriendo otra con el mismo nombre dentro del mismo spec: la base persiste en el proceso. Declarado honestamente: `fake-indexeddb` emula IndexedDB, no ES IndexedDB — la verificación en navegador real queda para la Etapa 1.4 (QA adversarial con la PWA y el stack), y se dice así en la superficie de ataque.
4. **Fiado offline con alcance honesto: solo con cliente conocido por el dispositivo.** Dos fuentes: (a) clientes creados EN el dispositivo, que suben por la cola como operación `cliente.crear` (el backend ya la soporta — decisión 2 del plan de fiado — y el FIFO por `secuencia` garantiza que precede a la venta fiada que lo referencia: la dependencia es estructural, no convención); (b) clientes del servidor asimilados ONLINE por `GET /api/v1/clientes` (no hay delta de clientes — D-28 abierta —, así que la asimilación ocurre cuando hay red, en el mismo gesto que el delta del catálogo). Si el dispositivo no tiene clientes, el botón «fiar» exige crear o buscar uno; fiar sin cliente está bloqueado en servicio y en UI (el cuaderno se lleva por persona, ADR-009). La `fecha_vencimiento` NO se captura en esta entrega (viaja `null`): el crédito nace sin fecha y se reprograma desde la consola web; ADR-022 declara que sin fecha no hay recordatorio, y eso es coherente con un POS que no puede prometer fechas sin reloj confiable. El aviso de `cupo_excedido` que el servidor devuelve en `detalles` de la operación aceptada NO se muestra en el POS en esta entrega: vive en el cuaderno web; se declara en riesgos.
5. **La `rechazada` es dead-letter visible y NO bloquea el FIFO.** El servidor aplica cada operación con su SAVEPOINT y devuelve veredicto por operación; una `rechazada` (p. ej. `venta_id_divergente`, `permiso_ausente`, datos inválidos) es un veredicto final: retransmitirla no la cambia. Se queda en `cola_sync` con `estado: 'error'` y el motivo estable, cuenta en el badge de la barra del POS y el drenado sigue con las demás (el lote ya las aplica independientemente). La resolución humana del dead-letter (corregir el dato o purgar con criterio) es gesto posterior — runbook de la Etapa 1.5 —; lo inaceptable sería esconderla o reintentarla en bucle.
6. **Aritmética del ticket en `domain`, con la regla fijada aquí porque el servidor NO recalcula.** El contrato congela `precio_unitario_centavos` del dispositivo y acepta `total_centavos` sin recomputarlo: la exactitud es responsabilidad del cliente, así que vive en `domain` (TS puro, pruebas exhaustivas sin framework). Regla firmada en este plan: cantidades en mili-unidades enteras; **total de línea = redondeo half-up al centavo de `precio × cantidad`** (`Math.round(precio_centavos × cantidad_mili / 1000)` — half-up exacto para positivos); **total del ticket = suma de los totales de línea ya redondeados** (la línea es lo que el tendero ve y lo que cuadra con el ticket). El `cantidad` del payload viaja como **string** de 3 decimales (`"1.500"`), el formato exacto que el backend cuantiza: un número JSON arrastraría binario (0.1+0.2) hacia el validador Decimal.
7. **El backoff es por lote y ante fallo de transporte, nunca por operación.** Ante error de red o 5xx, TODAS las operaciones del lote vuelven a `pendiente` con `intentos+1` y `proximo_intento_en = ahora + min(5s × 2^(intentos−1), 5min)`: el resultado de las ya enviadas es desconocido, y la idempotencia del servidor (misma PK → `duplicada`, sin re-emitir evento) hace el reenvío seguro por construcción. No hay backoff por operación individual porque el servidor responde 200 con veredictos por operación: el transporte falla entero o no falla. Disparadores del drenado: evento `online`, tras cada cobro, el temporizador del backoff y el botón manual. **Background Sync API fuera**: solo Chromium la soporta, exige permisos y el temporizador + el evento `online` cubren el caso real de una tienda.
8. **Las operaciones `enviando` huérfanas vuelven a `pendiente` al arrancar.** Si la app muere a mitad del drenado (el tendero cierra la PWA, se apaga el teléfono), las operaciones marcadas `enviando` quedarían mudas para siempre. Al iniciar, el sincronizador las devuelve a `pendiente` antes del primer drenado; el reenvío es seguro por idempotencia (decisión 7). Es el mismo criterio del outbox del backend: el estado transitorio no es verdad, la cola sí.
9. **El registro del dispositivo precede al primer lote y reconcilia la secuencia.** `asegurarRegistro()` persiste `dispositivo_id` (UUIDv4 local) la primera vez, llama `POST /api/v1/dispositivos` y guarda `ultima_secuencia = max(local, servidor)`: si el servidor ya conoce el dispositivo (re-registro tras reinstalar conservando la base), el contador local no retrocede jamás. Un **409 de registro es irrecuperable sin intervención** (id en conflicto con otro dispositivo del sistema): se propaga, el sync se pospone con backoff y el caso queda en la superficie de QA — inventar una curación automática de identidad de dispositivo es peor que el bloqueo visible.
10. **El spec-candado se retira porque este plan ES el subproyecto 2 en su alcance honesto.** El candado de `app.spec.ts` («NO hay ninguna ruta protegida») existe para que nadie improvisara un login dentro del WebView que los passkeys no sobreviven. Nadie lo improvisa: la decisión 1 deja la auth nativa fuera y pone la PWA como canal, con guards reales (`authGuard` + `tenantGuard`) que funcionan en el navegador. El candado se reemplaza por su inverso: un spec que afirma que la ruta del POS lleva `authGuard` y `tenantGuard`, y que `/elegir-negocio` no lleva `tenantGuard` (sería un bucle de redirección). Quien quite los guards rompe el test, que es exactamente el trabajo de un candado.
11. **`proveerSesion` se copia de `vendi-tenant`; la deduplicación es de la pista web.** El plan maestro encarga a la pista web de la Etapa 1.3 «deduplicar `nucleo/sesion.ts` hacia libs». Esta pista copia el archivo tal cual a `vendi-app/src/app/nucleo/sesion.ts` (con `check-sso` y el `catch` que no aborta el bootstrap: un POS que no arranca sin IdP no es offline-first) y deja la deduplicación a quien la tiene asignada — hacerla aquí tocaría las cuatro apps y la pista web pisaría el cambio. Los interceptores se cablean en el mismo orden que `vendi-tenant`: `[errorInterceptor, correlationIdInterceptor, authInterceptor]`.
12. **Sin anulación de ventas y sin escáner en esta entrega.** El contrato soporta `venta.anular` y la ruta `GET /productos/por-codigo/{codigo}` alimenta el escáner de ADR-024, pero ninguno entra al alcance: la anulación exige su propia UI de historial con criterio (venta sincronizada vs. no sincronizada, ADR-018) y el escáner exige hardware y otra tanda de pruebas. Ambos quedan declarados para la entrega siguiente de la pista móvil; la búsqueda del POS ya resuelve por `codigo_barras` exacto contra el catálogo local, así que un lector que «teclea» el código funciona sin trabajo extra.

---

## Tarea 1: Dependencias (Dexie + fake-indexeddb) y spike de Dexie

**Files:**
- Create: `scripts/spikes/dexie-spike.mjs`
- Modify: `frontend/package.json` + `frontend/package-lock.json` (vía `npm install`, nunca a mano)

**Interfaces:**
- Consume: la tradición de `scripts/spikes/` (cada riesgo nuevo se mide antes de construir sobre él; ADR-017: «hasta que el spike cierre, nada del POS móvil se implementa»).
- Produce: `dexie` en `dependencies` y `fake-indexeddb` en `devDependencies` del workspace, y la evidencia de que las cuatro propiedades en las que descansa ADR-017 funcionan: transacción atómica multi-tabla, orden FIFO por índice, persistencia tras cerrar y consulta por estado.

- [ ] **Paso 1: instalar las dependencias.**

```bash
cd frontend
npm install dexie@^4
npm install --save-dev fake-indexeddb@^6
npm ls dexie fake-indexeddb
# Esperado: dexie@4.x.x y fake-indexeddb@6.x.x sin errores de árbol
```

- [ ] **Paso 2: escribir el spike.** Crear `scripts/spikes/dexie-spike.mjs`:

```js
/**
 * Spike de Dexie (ADR-017): la base del POS offline-first.
 *
 * Mide, ANTES de construir nada encima, las cuatro propiedades en las que
 * descansa la cola de sincronización:
 *
 *   1. La escritura de negocio y el encolado confirman o revientan JUNTOS
 *      (transacción multi-tabla: el outbox local en espejo del backend).
 *   2. El drenado lee en orden FIFO por `secuencia`.
 *   3. La base sobrevive al cierre (la «recarga» del candado de ADR-017).
 *   4. Las pendientes se consultan por `estado` sin barrer la tabla.
 *
 * IndexedDB la emula `fake-indexeddb` (Node no la trae): el spike mide la
 * semántica de Dexie, que es la que el diseño usa. La verificación en
 * navegador real es de la Etapa 1.4.
 *
 * Ejecución (desde la raíz del repo):  node scripts/spikes/dexie-spike.mjs
 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

// Las dependencias viven en frontend/node_modules (único package.json del
// workspace). createRequire resuelve desde allí sin importar desde dónde se
// invoque el script, y carga las builds CJS de ambos paquetes.
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const Dexie = require('dexie');
require('fake-indexeddb/auto');

const NOMBRE_BD = `spike-dexie-${process.pid}`;

class DbSpike extends Dexie {
  constructor(nombre) {
    super(nombre);
    this.version(1).stores({
      ventas_locales: 'id, consecutivo_local',
      cola_sync: 'id, secuencia, estado',
      meta: 'clave',
    });
  }
}

function paso(mensaje) {
  console.log(`PASS ${mensaje}`);
}

// --- 1. Transacción atómica: negocio + cola + contador ----------------------
const db = new DbSpike(NOMBRE_BD);
await db.open();
await db.transaction('rw', [db.ventas_locales, db.cola_sync, db.meta], async () => {
  await db.ventas_locales.add({ id: 'venta-1', consecutivo_local: 1 });
  await db.cola_sync.add({ id: 'venta-1', secuencia: 1, estado: 'pendiente' });
  await db.meta.put({ clave: 'consecutivo_local', valor: 1 });
});
assert.equal(await db.ventas_locales.count(), 1);
assert.equal(await db.cola_sync.count(), 1);
assert.equal((await db.meta.get('consecutivo_local'))?.valor, 1);
paso('1a. la escritura de negocio y el encolado confirman juntos');

try {
  await db.transaction('rw', [db.ventas_locales, db.cola_sync, db.meta], async () => {
    await db.ventas_locales.add({ id: 'venta-2', consecutivo_local: 2 });
    throw new Error('fallo simulado a mitad del cobro');
  });
  assert.fail('la transacción con fallo debió reventar');
} catch {
  // esperado
}
assert.equal(await db.ventas_locales.get('venta-2'), undefined);
assert.equal(await db.cola_sync.count(), 1);
paso('1b. un fallo a mitad deja la base intacta (rollback completo)');

// --- 2. FIFO por secuencia ---------------------------------------------------
await db.cola_sync.bulkAdd([
  { id: 'venta-3', secuencia: 3, estado: 'pendiente' },
  { id: 'venta-4', secuencia: 4, estado: 'pendiente' },
  { id: 'venta-2b', secuencia: 2, estado: 'pendiente' },
]);
const orden = (await db.cola_sync.orderBy('secuencia').toArray()).map((op) => op.secuencia);
assert.deepEqual(orden, [1, 2, 3, 4]);
paso('2. el drenado lee FIFO por secuencia, aunque se inserte desordenado');

// --- 3. Sobrevive al cierre (la «recarga») -----------------------------------
await db.close();
const reabierta = new DbSpike(NOMBRE_BD);
await reabierta.open();
assert.equal(await reabierta.cola_sync.count(), 4);
assert.equal((await reabierta.meta.get('consecutivo_local'))?.valor, 1);
paso('3. la cola y los contadores sobreviven al cierre de la base');

// --- 4. Pendientes por estado -------------------------------------------------
await reabierta.cola_sync.update('venta-1', { estado: 'enviando' });
const pendientes = await reabierta.cola_sync
  .where('estado')
  .equals('pendiente')
  .sortBy('secuencia');
assert.deepEqual(
  pendientes.map((op) => op.secuencia),
  [2, 3, 4],
);
paso('4. las pendientes se consultan por estado y salen en orden');

await reabierta.delete();
console.log('Spike de Dexie: las cuatro propiedades de ADR-017 quedan medidas.');
```

- [ ] **Paso 3: ejecutar el spike.**

```bash
node scripts/spikes/dexie-spike.mjs
# Esperado:
# PASS 1a. la escritura de negocio y el encolado confirman juntos
# PASS 1b. un fallo a mitad deja la base intacta (rollback completo)
# PASS 2. el drenado lee FIFO por secuencia, aunque se inserte desordenado
# PASS 3. la cola y los contadores sobreviven al cierre de la base
# PASS 4. las pendientes se consultan por estado y salen en orden
# Spike de Dexie: las cuatro propiedades de ADR-017 quedan medidas.
```

- [ ] **Paso 4: commit**

```bash
git add frontend/package.json frontend/package-lock.json scripts/spikes/dexie-spike.mjs
git commit -m "Dexie y fake-indexeddb en el workspace, con el spike que mide las cuatro propiedades de la cola offline"
```

**Criterios de aceptación:** el spike pasa las seis líneas PASS; `dexie` está en `dependencies` y `fake-indexeddb` en `devDependencies`; ningún proyecto del workspace importa todavía `dexie` (eso empieza en la Tarea 2, dentro de `data-access`).

---

## Tarea 2: `VendiDb` — el esquema local v1 en `data-access`

**Files:**
- Create: `frontend/projects/libs/data-access/src/lib/offline/modelos-locales.ts`
- Create: `frontend/projects/libs/data-access/src/lib/offline/vendi.db.ts`
- Create: `frontend/projects/libs/data-access/src/lib/offline/vendi.db.spec.ts` (primero: el test que falla)
- Modify: `frontend/projects/libs/data-access/src/public-api.ts`

**Interfaces:**
- Consume: `dexie` (Tarea 1); la frontera de `data-access`, que ya permite `dexie` (su grupo prohibido es `['ui-kit', 'auth', '@capacitor/*']`).
- Produce: la base `VendiDb` inyectable con el esquema v1 de la decisión 2 y los tipos locales que consumen las tareas 4-8.

- [ ] **Paso 1: escribir el spec que falla.** Crear `frontend/projects/libs/data-access/src/lib/offline/vendi.db.spec.ts`:

```ts
// `fake-indexeddb` registra el global `indexedDB` que jsdom no implementa;
// tiene que cargarse ANTES de abrir cualquier base. La «recarga» se simula
// cerrando la instancia y abriendo otra con el mismo nombre: la base persiste
// en el proceso del worker de Vitest.
import 'fake-indexeddb/auto';
import { VendiDb } from './vendi.db';

describe('VendiDb (esquema local v1, ADR-017/ADR-018)', () => {
  let db: VendiDb;

  beforeEach(() => {
    db = new VendiDb(`test-${crypto.randomUUID()}`);
  });

  afterEach(async () => {
    await db.delete();
  });

  it('crea las cinco tablas del esquema v1', () => {
    expect(db.tables.map((t) => t.name).sort()).toEqual([
      'clientes',
      'cola_sync',
      'meta',
      'productos',
      'ventas_locales',
    ]);
  });

  it('persiste tras cerrar y reabrir (la recarga del candado de ADR-017)', async () => {
    await db.meta.put({ clave: 'consecutivo_local', valor: 7 });
    const nombre = db.name;
    await db.close();

    const reabierta = new VendiDb(nombre);
    await reabierta.open();
    expect((await reabierta.meta.get('consecutivo_local'))?.valor).toBe(7);
    await reabierta.delete();
  });

  it('consulta la cola por estado y la ordena por secuencia', async () => {
    await db.cola_sync.bulkAdd([
      {
        id: 'b', tipo: 'venta.crear', secuencia: 2, datos: {},
        estado: 'pendiente', intentos: 0, proximo_intento_en: 0,
        ultimo_error: null, creada_en: 1,
      },
      {
        id: 'a', tipo: 'venta.crear', secuencia: 1, datos: {},
        estado: 'pendiente', intentos: 0, proximo_intento_en: 0,
        ultimo_error: null, creada_en: 1,
      },
      {
        id: 'c', tipo: 'venta.crear', secuencia: 3, datos: {},
        estado: 'error', intentos: 2, proximo_intento_en: 0,
        ultimo_error: 'venta_id_divergente', creada_en: 1,
      },
    ]);
    const pendientes = await db.cola_sync
      .where('estado')
      .equals('pendiente')
      .sortBy('secuencia');
    expect(pendientes.map((op) => op.id)).toEqual(['a', 'b']);
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test data-access --watch=false
# Esperado: 3 fallos — Cannot find module './vendi.db' (o TS2307 equivalente)
```

- [ ] **Paso 2: escribir los modelos locales.** Crear `frontend/projects/libs/data-access/src/lib/offline/modelos-locales.ts`:

```ts
/**
 * Tipos de la verdad local del dispositivo (ADR-017/ADR-018).
 *
 * Son los contratos internos de `data-access`: lo que el POS lee y escribe en
 * IndexedDB. No son los contratos de la API —los del lote de sync se arman en
 * el momento de encolar— aunque se parezcan a propósito.
 */

/** Estados de una operación en la cola de sincronización. */
export type EstadoOperacion = 'pendiente' | 'enviando' | 'error';

/**
 * Operaciones que el dispositivo sabe encolar. `venta.anular` entra cuando la
 * UI de anulación llegue (decisión 12 del plan); el tipo se deja cerrado a
 * propósito: añadir una operación es una decisión, no un string suelto.
 */
export type TipoOperacion = 'venta.crear' | 'cliente.crear';

/** Producto del catálogo local (lo que baja el delta de ADR-017). */
export interface ProductoLocal {
  id: string;
  nombre: string;
  categoria: string | null;
  codigo_barras: string | null;
  /** Centavos enteros (ADR-018). */
  precio_venta: number;
  unidad_medida: string;
  /** Decimal de la API como string (granel); es dato de exhibición, no se opera. */
  stock_actual: string;
}

/**
 * Cliente conocido por el dispositivo. `origen: 'local'` lo creó este
 * dispositivo (sube como `cliente.crear`); `'servidor'` se asimiló online por
 * `GET /clientes` (no hay delta de clientes — D-28).
 */
export interface ClienteLocal {
  id: string;
  nombre: string;
  telefono: string | null;
  limite_credito: number | null;
  origen: 'local' | 'servidor';
}

/** Línea de una venta local: el precio y el nombre se congelan en la venta. */
export interface LineaVentaLocal {
  producto_id: string;
  /** Desnormalizado: el ticket no cambia aunque el catálogo cambie después. */
  nombre: string;
  /** Mili-unidades enteras: 1500 = 1,5 kg (granel de 3 decimales). */
  cantidad_mili: number;
  precio_unitario_centavos: number;
  total_linea_centavos: number;
}

/** La venta append-only tal como la creó el dispositivo (ADR-018). */
export interface VentaLocal {
  id: string;
  /** El número que ve el tendero; monotónico por dispositivo. */
  consecutivo_local: number;
  estado: 'completada' | 'anulada';
  medio_pago: 'efectivo' | 'fiado';
  total_centavos: number;
  cliente_id: string | null;
  /** Desnormalizado: el historial se lee sin red y sin joins. */
  cliente_nombre: string | null;
  /** `YYYY-MM-DD` o null; solo fiado. */
  fecha_vencimiento: string | null;
  /** ISO 8601 con zona; marca del reloj del dispositivo: dato, no árbitro. */
  creada_en_cliente: string;
  items: LineaVentaLocal[];
}

/**
 * Operación encolada para el lote de sync. `id` ES la PK de la entidad que
 * creó (la venta o el cliente): la idempotencia del servidor es por esa PK
 * (ADR-017). `datos` lleva el shape exacto del schema del módulo dueño de la
 * operación (`VentaCrearSync`, `ClienteCrearSync`).
 */
export interface OperacionEnCola {
  id: string;
  tipo: TipoOperacion;
  /** Orden FIFO por dispositivo; monotónica, sin huecos garantizados. */
  secuencia: number;
  datos: Record<string, unknown>;
  estado: EstadoOperacion;
  intentos: number;
  /** Epoch ms a partir del cual se puede reintentar; 0 = ya. */
  proximo_intento_en: number;
  /** Motivo estable del servidor cuando `estado` es `error` (dead-letter). */
  ultimo_error: string | null;
  creada_en: number;
}

/** Claves de la tabla `meta` (configuración y contadores del dispositivo). */
export type ClaveMeta =
  | 'dispositivo_id'
  | 'nombre_dispositivo'
  | 'dispositivo_registrado'
  | 'ultima_secuencia'
  | 'consecutivo_local'
  | 'delta_hasta';

export interface EntradaMeta {
  clave: ClaveMeta;
  valor: string | number | boolean;
}
```

- [ ] **Paso 3: escribir `VendiDb`.** Crear `frontend/projects/libs/data-access/src/lib/offline/vendi.db.ts`:

```ts
import { Injectable } from '@angular/core';
import Dexie, { Table } from 'dexie';
import type {
  ClienteLocal,
  EntradaMeta,
  OperacionEnCola,
  ProductoLocal,
  VentaLocal,
} from './modelos-locales';

/**
 * La base local del dispositivo: IndexedDB vía Dexie (ADR-017).
 *
 * Es el ÚNICO sitio del workspace donde `dexie` aparece (la frontera ESLint de
 * ADR-011 lo hace cumplir en todos los demás proyectos; `vendi-app` la gana en
 * la Tarea 9 de este plan). El esquema es la decisión 2 del plan:
 *
 *  - `productos` y `clientes`: datos de referencia (LWW por orden de recepción
 *    en el servidor; los clientes llegan online, D-28).
 *  - `ventas_locales`: la verdad local de las ventas, append-only.
 *  - `cola_sync`: el outbox local; la escritura de negocio y el encolado van en
 *    la misma transacción (eso lo garantizan los servicios, no este archivo).
 *  - `meta`: identidad del dispositivo, contadores y watermark del delta.
 *
 * Es inyectable (`providedIn: 'root'`) para que los specs puedan sustituirla
 * por una instancia con nombre propio sobre `fake-indexeddb`; el constructor
 * admite el nombre por esa misma razón.
 */
@Injectable({ providedIn: 'root' })
export class VendiDb extends Dexie {
  productos!: Table<ProductoLocal, string>;
  clientes!: Table<ClienteLocal, string>;
  ventas_locales!: Table<VentaLocal, string>;
  cola_sync!: Table<OperacionEnCola, string>;
  meta!: Table<EntradaMeta, string>;

  constructor(nombre = 'vendi-offline') {
    super(nombre);
    this.version(1).stores({
      productos: 'id, nombre, codigo_barras, categoria',
      clientes: 'id, nombre',
      ventas_locales: 'id, consecutivo_local, creada_en_cliente, estado',
      cola_sync: 'id, secuencia, estado',
      meta: 'clave',
    });
  }
}
```

- [ ] **Paso 4: exportar por la superficie pública.** En `frontend/projects/libs/data-access/src/public-api.ts`, añadir tras la sección de servicios:

```ts
// --- Offline (ADR-017/ADR-018): IndexedDB como verdad local ----------------
export { VendiDb } from './lib/offline/vendi.db';
export type {
  ClaveMeta,
  ClienteLocal,
  EntradaMeta,
  EstadoOperacion,
  LineaVentaLocal,
  OperacionEnCola,
  ProductoLocal,
  TipoOperacion,
  VentaLocal,
} from './lib/offline/modelos-locales';
```

- [ ] **Paso 5: verificar en verde.**

```bash
cd frontend && npm run build:libs && npx ng test data-access --watch=false
# Esperado: verde, con los 3 specs nuevos de VendiDb
npx ng lint data-access
# Esperado: sin errores (dexie es legal en data-access; la frontera no lo toca)
```

- [ ] **Paso 6: commit**

```bash
git add frontend/projects/libs/data-access
git commit -m "VendiDb: esquema local v1 del POS offline (productos, clientes, ventas, cola y meta) encapsulado en data-access"
```

**Criterios de aceptación:** los 3 specs de `VendiDb` pasan; el spec de persistencia tras reabrir (el candado de ADR-017) pasa; `npx ng lint data-access` verde con `dexie` importado dentro de la librería; la superficie pública exporta `VendiDb` y los tipos.

---

## Tarea 3: Aritmética del ticket en `domain` — centavos y granel sin flotantes

**Files:**
- Create: `frontend/projects/libs/domain/src/lib/reglas/dinero.ts`
- Create: `frontend/projects/libs/domain/src/lib/reglas/dinero.spec.ts` (primero: el test que falla)
- Modify: `frontend/projects/libs/domain/src/public-api.ts`

**Interfaces:**
- Consume: nada (domain es TS puro; su frontera prohíbe Angular, RxJS, Dexie).
- Produce: `MILI_POR_UNIDAD`, `LineaTicket`, `miliDeCantidad`, `textoDeCantidad`, `totalLineaCentavos`, `totalTicketCentavos`, `formatearPesos` — la regla de la decisión 6, que el POS y `VentasOfflineService` usan.

- [ ] **Paso 1: escribir el spec que falla.** Crear `frontend/projects/libs/domain/src/lib/reglas/dinero.spec.ts`:

```ts
import {
  MILI_POR_UNIDAD,
  LineaTicket,
  formatearPesos,
  miliDeCantidad,
  textoDeCantidad,
  totalLineaCentavos,
  totalTicketCentavos,
} from './dinero';

/**
 * La aritmética del dinero del POS. El servidor NO recalcula el total (el
 * contrato congela lo que manda el dispositivo), así que estas funciones son
 * la regla — y por eso esta tabla de casos es larga a propósito.
 */
describe('dinero (ADR-018: enteros, nunca flotantes)', () => {
  it('convierte cantidades del tendero a mili-unidades enteras', () => {
    expect(miliDeCantidad(1)).toBe(MILI_POR_UNIDAD);
    expect(miliDeCantidad(1.5)).toBe(1500);
    expect(miliDeCantidad(0.333)).toBe(333);
    expect(miliDeCantidad(2.75)).toBe(2750);
  });

  it('rechaza cantidades que no son vendibles', () => {
    expect(() => miliDeCantidad(0)).toThrow();
    expect(() => miliDeCantidad(-1)).toThrow();
    expect(() => miliDeCantidad(Number.NaN)).toThrow();
    expect(() => miliDeCantidad(Number.POSITIVE_INFINITY)).toThrow();
  });

  it('serializa la cantidad como string de 3 decimales (lo que el backend cuantiza)', () => {
    expect(textoDeCantidad(1500)).toBe('1.500');
    expect(textoDeCantidad(333)).toBe('0.333');
    expect(textoDeCantidad(25)).toBe('0.025');
  });

  it('total de línea exacto en centavos, con redondeo half-up', () => {
    // 3 unidades de $50,00
    expect(totalLineaCentavos(5000, 3000)).toBe(15000);
    // 0,333 kg a $10,00/kg = 333 centavos exactos
    expect(totalLineaCentavos(1000, 333)).toBe(333);
    // 2,5 kg a $19,99/kg = 4997,5 → 4998 (half-up, nunca hacia abajo)
    expect(totalLineaCentavos(1999, 2500)).toBe(4998);
    // 100 g a $10,07/kg = 100,7 → 101
    expect(totalLineaCentavos(1007, 100)).toBe(101);
  });

  it('no arrastra el error binario de los flotantes (el caso 0.1 + 0.2)', () => {
    // Tres líneas de 0,1 kg a $10,07/kg: cada una redondea a 101 y el total
    // es 303 — determinista, sin la deriva de 0.30000000000000004.
    const lineas: LineaTicket[] = [0, 1, 2].map((n) => ({
      producto_id: `p-${n}`,
      nombre: 'Arroz',
      cantidad_mili: 100,
      precio_unitario_centavos: 1007,
    }));
    expect(totalTicketCentavos(lineas)).toBe(303);
  });

  it('el total del ticket es la suma de las líneas YA redondeadas', () => {
    const lineas: LineaTicket[] = [
      { producto_id: 'a', nombre: 'A', cantidad_mili: 2500, precio_unitario_centavos: 1999 },
      { producto_id: 'b', nombre: 'B', cantidad_mili: 1000, precio_unitario_centavos: 5000 },
    ];
    expect(totalTicketCentavos(lineas)).toBe(4998 + 5000);
  });

  it('aguanta valores grandes sin perder enteros', () => {
    // $9.999.999,99 el kilo, 999,999 kg: por debajo de 2^53, exacto.
    expect(totalLineaCentavos(999_999_999, 999_999)).toBe(999_998_999_000);
  });

  it('formatea pesos colombianos sin decimales', () => {
    expect(formatearPesos(125000)).toContain('1.250');
    expect(formatearPesos(0)).toContain('0');
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test domain --watch=false
# Esperado: fallos — Cannot find module './dinero'
```

- [ ] **Paso 2: escribir la implementación.** Crear `frontend/projects/libs/domain/src/lib/reglas/dinero.ts`:

```ts
/**
 * Aritmética del dinero y del granel del POS (ADR-018).
 *
 * Dos reglas duras:
 *
 *  - El dinero son centavos ENTEROS. Ningún flotante toca un precio, un total
 *    o un saldo.
 *  - Las cantidades son mili-unidades ENTERAS (1 kg = 1000), porque el granel
 *    se vende con 3 decimales (el backend cuantiza `cantidad` a 3) y la masa
 *    tampoco es un flotante.
 *
 * El único sitio donde existe un número fraccionario es el input del tendero,
 * y se convierte en el borde (`miliDeCantidad`).
 *
 * La regla de redondeo la fija el plan del POS (decisión 6) y no la mueve
 * nadie sin revisarla: el servidor NO recalcula el total —acepta el que manda
 * el dispositivo—, así que la consistencia entre el ticket del tendero y la
 * caja del negocio depende de que esta función sea determinista.
 */

/** Factor de la unidad de cantidad: 1 unidad = 1000 mili-unidades. */
export const MILI_POR_UNIDAD = 1000;

/** Línea del ticket en memoria: enteros por todas partes. */
export interface LineaTicket {
  producto_id: string;
  nombre: string;
  cantidad_mili: number;
  precio_unitario_centavos: number;
}

/**
 * Convierte la cantidad que tecleó el tendero a mili-unidades enteras.
 *
 * Lanza sobre lo no vendible (cero, negativos, NaN, infinito): quien llama
 * decide si ignora la tecla o avisa, pero ninguna de esas cantidades llega al
 * ticket. Más de 3 decimales se truncan al mili (el tendero no pesa
 * microgramos; el backend cuantiza igual).
 */
export function miliDeCantidad(cantidad: number): number {
  if (!Number.isFinite(cantidad) || cantidad <= 0) {
    throw new Error(`Cantidad no vendible: ${cantidad}`);
  }
  return Math.round(cantidad * MILI_POR_UNIDAD);
}

/**
 * Serializa la cantidad para el payload del sync: string de 3 decimales, el
 * formato exacto que el backend cuantiza (`Decimal`). Un número JSON
 * arrastraría binario (0.1 + 0.2) hacia el validador.
 */
export function textoDeCantidad(cantidadMili: number): string {
  return (cantidadMili / MILI_POR_UNIDAD).toFixed(3);
}

/**
 * Total de una línea en centavos, redondeo half-up al centavo.
 *
 * `Math.round` es half-up exacto para positivos (los precios y cantidades de
 * una venta siempre lo son). La línea es la unidad que ve el tendero: el
 * ticket cuadra línea a línea y el total es su suma.
 */
export function totalLineaCentavos(
  precioUnitarioCentavos: number,
  cantidadMili: number,
): number {
  return Math.round((precioUnitarioCentavos * cantidadMili) / MILI_POR_UNIDAD);
}

/** Total del ticket: suma de los totales de línea YA redondeados. */
export function totalTicketCentavos(lineas: readonly LineaTicket[]): number {
  return lineas.reduce(
    (total, linea) =>
      total + totalLineaCentavos(linea.precio_unitario_centavos, linea.cantidad_mili),
    0,
  );
}

/** Pesos colombianos para mostrar: enteros, con separador de miles. */
export function formatearPesos(centavos: number): string {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    maximumFractionDigits: 0,
  }).format(centavos / 100);
}
```

- [ ] **Paso 3: exportar por la superficie pública de `domain`.** En `frontend/projects/libs/domain/src/public-api.ts`, añadir al final:

```ts
export type { LineaTicket } from './lib/reglas/dinero';
export {
  MILI_POR_UNIDAD,
  formatearPesos,
  miliDeCantidad,
  textoDeCantidad,
  totalLineaCentavos,
  totalTicketCentavos,
} from './lib/reglas/dinero';
```

- [ ] **Paso 4: verificar en verde.**

```bash
cd frontend && npm run build:libs && npx ng test domain --watch=false
# Esperado: verde, con los 8 specs nuevos de dinero
npx ng lint domain
# Esperado: sin errores (domain sigue puro: sin Angular, sin RxJS, sin dexie)
```

- [ ] **Paso 5: commit**

```bash
git add frontend/projects/libs/domain
git commit -m "Aritmética del ticket en domain: centavos enteros, granel en mili-unidades y redondeo half-up por línea"
```

**Criterios de aceptación:** los 8 specs pasan, incluidos el half-up en `.5`, el caso `0.1 + 0.2` sin deriva y el valor grande exacto; `domain` sigue sin importar nada de framework (lint verde).

---

## Tarea 4: El outbox local — `VentasOfflineService` (cobro y alta de cliente en una transacción)

**Files:**
- Create: `frontend/projects/libs/data-access/src/lib/offline/ventas-offline.service.ts`
- Create: `frontend/projects/libs/data-access/src/lib/offline/ventas-offline.service.spec.ts` (primero: el test que falla)
- Modify: `frontend/projects/libs/data-access/src/public-api.ts`

**Interfaces:**
- Consume: `VendiDb` y tipos (Tarea 2); aritmética de `domain` (Tarea 3). Los shapes del payload: `VentaCrearSync` (`backend/services/api/app/modules/ventas/schemas.py:104`) y `ClienteCrearSync` (`backend/services/api/app/modules/fiado/schemas.py:78`, `extra="forbid"`, `nombre` min 2).
- Produce: `VentasOfflineService.cobrar()`, `.crearClienteLocal()`, `.historial()` — el corazón del offline: cobra sin red y deja la operación encolada atómicamente.

- [ ] **Paso 1: escribir el spec que falla.** Crear `frontend/projects/libs/data-access/src/lib/offline/ventas-offline.service.spec.ts`:

```ts
import 'fake-indexeddb/auto';
import { TestBed } from '@angular/core/testing';
import { VendiDb } from './vendi.db';
import { VentasOfflineService } from './ventas-offline.service';
import type { ClienteLocal } from './modelos-locales';

const LINEAS = [
  { producto_id: 'p-1', nombre: 'Arroz x kg', cantidad_mili: 1500, precio_unitario_centavos: 4000 },
  { producto_id: 'p-2', nombre: 'Panela', cantidad_mili: 1000, precio_unitario_centavos: 2500 },
];

function preparar(): { servicio: VentasOfflineService; db: VendiDb } {
  const db = new VendiDb(`test-${crypto.randomUUID()}`);
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [{ provide: VendiDb, useValue: db }],
  });
  return { servicio: TestBed.inject(VentasOfflineService), db };
}

describe('VentasOfflineService (outbox local, ADR-017/ADR-018)', () => {
  afterEach(async () => {
    await TestBed.inject(VendiDb).delete();
  });

  it('cobra sin red: venta + operación encolada + contadores, en una transacción', async () => {
    const { servicio, db } = preparar();
    const venta = await servicio.cobrar({
      lineas: LINEAS,
      medio_pago: 'efectivo',
      cliente: null,
      fecha_vencimiento: null,
    });

    expect(venta.consecutivo_local).toBe(1);
    expect(venta.total_centavos).toBe(8500); // 6000 + 2500, exacto
    expect(await db.ventas_locales.count()).toBe(1);

    const enCola = await db.cola_sync.get(venta.id);
    expect(enCola).toBeDefined();
    expect(enCola?.tipo).toBe('venta.crear');
    expect(enCola?.secuencia).toBe(1);
    expect(enCola?.estado).toBe('pendiente');
  });

  it('el payload encolado tiene el shape exacto de VentaCrearSync', async () => {
    const { servicio, db } = preparar();
    const venta = await servicio.cobrar({
      lineas: LINEAS,
      medio_pago: 'efectivo',
      cliente: null,
      fecha_vencimiento: null,
    });
    const enCola = await db.cola_sync.get(venta.id);

    expect(enCola?.datos).toEqual({
      consecutivo_local: 1,
      estado: 'completada',
      medio_pago: 'efectivo',
      total_centavos: 8500,
      cliente_id: null,
      fecha_vencimiento: null,
      creada_en_cliente: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/),
      items: [
        { producto_id: 'p-1', cantidad: '1.500', precio_unitario_centavos: 4000 },
        { producto_id: 'p-2', cantidad: '1.000', precio_unitario_centavos: 2500 },
      ],
    });
  });

  it('el consecutivo y la secuencia son monótonos y sobreviven a la recarga', async () => {
    const { servicio, db } = preparar();
    await servicio.cobrar({ lineas: LINEAS, medio_pago: 'efectivo', cliente: null, fecha_vencimiento: null });
    await servicio.cobrar({ lineas: LINEAS, medio_pago: 'efectivo', cliente: null, fecha_vencimiento: null });
    const nombre = db.name;
    await db.close();

    const reabierta = new VendiDb(nombre);
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ providers: [{ provide: VendiDb, useValue: reabierta }] });
    const servicio2 = TestBed.inject(VentasOfflineService);
    const tercera = await servicio2.cobrar({
      lineas: LINEAS,
      medio_pago: 'efectivo',
      cliente: null,
      fecha_vencimiento: null,
    });

    expect(tercera.consecutivo_local).toBe(3);
    expect((await reabierta.cola_sync.get(tercera.id))?.secuencia).toBe(3);
    await reabierta.delete();
  });

  it('un fallo a mitad de la transacción no deja ni venta ni cola ni contador', async () => {
    const { servicio, db } = preparar();
    const original = db.cola_sync.add.bind(db.cola_sync);
    db.cola_sync.add = ((...args: unknown[]) => {
      void original;
      return Promise.reject(new Error('fallo simulado'));
    }) as never;

    await expect(
      servicio.cobrar({ lineas: LINEAS, medio_pago: 'efectivo', cliente: null, fecha_vencimiento: null }),
    ).rejects.toThrow('fallo simulado');

    expect(await db.ventas_locales.count()).toBe(0);
    expect(await db.meta.get('consecutivo_local')).toBeUndefined();
  });

  it('el fiado exige cliente: sin él no hay venta ni operación', async () => {
    const { servicio, db } = preparar();
    await expect(
      servicio.cobrar({ lineas: LINEAS, medio_pago: 'fiado', cliente: null, fecha_vencimiento: null }),
    ).rejects.toThrow(/cliente/);
    expect(await db.ventas_locales.count()).toBe(0);
    expect(await db.cola_sync.count()).toBe(0);
  });

  it('el fiado con cliente local encola la venta con su referencia', async () => {
    const { servicio, db } = preparar();
    const cliente = await servicio.crearClienteLocal({ nombre: 'Don Carlos', telefono: null });
    const venta = await servicio.cobrar({
      lineas: LINEAS,
      medio_pago: 'fiado',
      cliente,
      fecha_vencimiento: null,
    });

    const enCola = await db.cola_sync.get(venta.id);
    expect(enCola?.datos['medio_pago']).toBe('fiado');
    expect(enCola?.datos['cliente_id']).toBe(cliente.id);
    // El cliente.crear va ANTES que la venta en la cola (FIFO estructural).
    const clienteEnCola = await db.cola_sync.get(cliente.id);
    expect(clienteEnCola?.tipo).toBe('cliente.crear');
    expect(clienteEnCola!.secuencia).toBeLessThan(enCola!.secuencia);
  });

  it('cliente.crear lleva solo los campos de ClienteCrearSync (extra=forbid)', async () => {
    const { servicio, db } = preparar();
    const cliente = await servicio.crearClienteLocal({ nombre: 'Doña Ana', telefono: '3001234567' });
    const enCola = await db.cola_sync.get(cliente.id);
    expect(enCola?.datos).toEqual({ nombre: 'Doña Ana', telefono: '3001234567' });
  });

  it('rechaza nombres de cliente que el servidor rechazaría (min 2)', async () => {
    const { servicio } = preparar();
    await expect(servicio.crearClienteLocal({ nombre: 'A', telefono: null })).rejects.toThrow();
    await expect(servicio.crearClienteLocal({ nombre: '   ', telefono: null })).rejects.toThrow();
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test data-access --watch=false
# Esperado: fallos — Cannot find module './ventas-offline.service'
```

- [ ] **Paso 2: escribir la implementación.** Crear `frontend/projects/libs/data-access/src/lib/offline/ventas-offline.service.ts`:

```ts
import { Injectable, inject } from '@angular/core';
import {
  LineaTicket,
  textoDeCantidad,
  totalLineaCentavos,
  totalTicketCentavos,
} from 'domain';
import type { ClaveMeta, ClienteLocal, OperacionEnCola, VentaLocal } from './modelos-locales';
import { VendiDb } from './vendi.db';

/** Entrada del cobro: lo que la UI del POS ya validó visualmente. */
export interface EntradaCobro {
  lineas: readonly LineaTicket[];
  medio_pago: 'efectivo' | 'fiado';
  cliente: ClienteLocal | null;
  /** `YYYY-MM-DD`; solo fiado. Esta entrega siempre la manda en null (decisión 4). */
  fecha_vencimiento: string | null;
}

/**
 * El outbox local del POS (ADR-017 en espejo del backend).
 *
 * Cobra SIN RED: la venta, su operación en `cola_sync` y el avance de los dos
 * contadores (`consecutivo_local` —el número del ticket— y `ultima_secuencia`
 * —el orden FIFO de la cola, que también cuentan los `cliente.crear`—)
 * confirman o revientan JUNTOS en una transacción Dexie. No existe ningún
 * camino que escriba la venta sin encolarla.
 *
 * La venta es append-only (ADR-018): nace `completada` con el id que el
 * dispositivo le puso (ese id ES la PK en el servidor y el `id` de la
 * operación del lote: la idempotencia es estructural).
 */
@Injectable({ providedIn: 'root' })
export class VentasOfflineService {
  private readonly db = inject(VendiDb);

  async cobrar(entrada: EntradaCobro): Promise<VentaLocal> {
    if (entrada.lineas.length === 0) {
      throw new Error('El ticket no tiene líneas.');
    }
    if (entrada.medio_pago === 'fiado' && !entrada.cliente) {
      // El cuaderno se lleva por persona (ADR-009): fiado sin cliente no existe.
      throw new Error('El fiado exige un cliente.');
    }
    if (entrada.medio_pago === 'efectivo' && entrada.fecha_vencimiento) {
      throw new Error('La fecha de vencimiento solo aplica al fiado.');
    }
    const ahora = new Date();

    return this.db.transaction(
      'rw',
      [this.db.ventas_locales, this.db.cola_sync, this.db.meta],
      async () => {
        const consecutivo = (await this.numeroMeta('consecutivo_local')) + 1;
        const secuencia = (await this.numeroMeta('ultima_secuencia')) + 1;
        const venta: VentaLocal = {
          id: crypto.randomUUID(),
          consecutivo_local: consecutivo,
          estado: 'completada',
          medio_pago: entrada.medio_pago,
          total_centavos: totalTicketCentavos(entrada.lineas),
          cliente_id: entrada.cliente?.id ?? null,
          cliente_nombre: entrada.cliente?.nombre ?? null,
          fecha_vencimiento: entrada.fecha_vencimiento,
          creada_en_cliente: ahora.toISOString(),
          items: entrada.lineas.map((linea) => ({
            producto_id: linea.producto_id,
            nombre: linea.nombre,
            cantidad_mili: linea.cantidad_mili,
            precio_unitario_centavos: linea.precio_unitario_centavos,
            total_linea_centavos: totalLineaCentavos(
              linea.precio_unitario_centavos,
              linea.cantidad_mili,
            ),
          })),
        };
        // Shape EXACTO de VentaCrearSync (ventas/schemas.py): la cantidad es
        // string de 3 decimales, el formato que el backend cuantiza.
        const datos: Record<string, unknown> = {
          consecutivo_local: venta.consecutivo_local,
          estado: venta.estado,
          medio_pago: venta.medio_pago,
          total_centavos: venta.total_centavos,
          cliente_id: venta.cliente_id,
          fecha_vencimiento: venta.fecha_vencimiento,
          creada_en_cliente: venta.creada_en_cliente,
          items: venta.items.map((item) => ({
            producto_id: item.producto_id,
            cantidad: textoDeCantidad(item.cantidad_mili),
            precio_unitario_centavos: item.precio_unitario_centavos,
          })),
        };
        await this.db.ventas_locales.add(venta);
        await this.db.cola_sync.add(this.operacion(venta.id, 'venta.crear', secuencia, datos, ahora));
        await this.ponerMeta('consecutivo_local', consecutivo);
        await this.ponerMeta('ultima_secuencia', secuencia);
        return venta;
      },
    );
  }

  /**
   * Alta de cliente en el dispositivo: la venta fiada sin red lo referencia y
   * el servidor lo adopta como PK (operación `cliente.crear`, cierre de D-10
   * por adopción). El FIFO por `secuencia` garantiza que esta operación sube
   * ANTES que la venta que fía: la dependencia es estructural.
   */
  async crearClienteLocal(entrada: { nombre: string; telefono: string | null }): Promise<ClienteLocal> {
    const nombre = entrada.nombre.trim();
    if (nombre.length < 2) {
      // Mismo piso que ClienteCrearSync (min 2): rechazar aquí evita una
      // `rechazada` segura en el servidor y una venta fiada huérfana detrás.
      throw new Error('El nombre del cliente necesita al menos 2 letras.');
    }
    const ahora = new Date();
    return this.db.transaction(
      'rw',
      [this.db.clientes, this.db.cola_sync, this.db.meta],
      async () => {
        const secuencia = (await this.numeroMeta('ultima_secuencia')) + 1;
        const cliente: ClienteLocal = {
          id: crypto.randomUUID(),
          nombre,
          telefono: entrada.telefono,
          limite_credito: null,
          origen: 'local',
        };
        await this.db.clientes.add(cliente);
        // ClienteCrearSync tiene extra="forbid": solo estos dos campos viajan.
        await this.db.cola_sync.add(
          this.operacion(
            cliente.id,
            'cliente.crear',
            secuencia,
            { nombre: cliente.nombre, telefono: cliente.telefono },
            ahora,
          ),
        );
        await this.ponerMeta('ultima_secuencia', secuencia);
        return cliente;
      },
    );
  }

  /** El historial local, del más reciente al más antiguo. */
  historial(limite = 50): Promise<VentaLocal[]> {
    return this.db.ventas_locales
      .orderBy('consecutivo_local')
      .reverse()
      .limit(limite)
      .toArray();
  }

  private operacion(
    id: string,
    tipo: OperacionEnCola['tipo'],
    secuencia: number,
    datos: Record<string, unknown>,
    ahora: Date,
  ): OperacionEnCola {
    return {
      id,
      tipo,
      secuencia,
      datos,
      estado: 'pendiente',
      intentos: 0,
      proximo_intento_en: 0,
      ultimo_error: null,
      creada_en: ahora.getTime(),
    };
  }

  private async numeroMeta(clave: 'consecutivo_local' | 'ultima_secuencia'): Promise<number> {
    const entrada = await this.db.meta.get(clave);
    return typeof entrada?.valor === 'number' ? entrada.valor : 0;
  }

  private async ponerMeta(clave: ClaveMeta, valor: string | number | boolean): Promise<void> {
    await this.db.meta.put({ clave, valor });
  }
}
```

- [ ] **Paso 3: exportar por la superficie pública.** En `frontend/projects/libs/data-access/src/public-api.ts`, tras el bloque de `VendiDb`:

```ts
export { VentasOfflineService } from './lib/offline/ventas-offline.service';
export type { EntradaCobro } from './lib/offline/ventas-offline.service';
```

- [ ] **Paso 4: verificar en verde.**

```bash
cd frontend && npm run build:libs && npx ng test data-access --watch=false
# Esperado: verde, con los 8 specs nuevos del outbox local
npx ng lint data-access
# Esperado: sin errores
```

- [ ] **Paso 5: commit**

```bash
git add frontend/projects/libs/data-access
git commit -m "Outbox local del POS: cobro offline con venta, cola y contadores en una sola transacción Dexie"
```

**Criterios de aceptación:** el cobro sin red deja venta + operación + contadores atómicamente; el payload encolado coincide campo a campo con `VentaCrearSync` (incluida la cantidad como string `"1.500"`); el consecutivo y la secuencia son monótonos y sobreviven a la recarga; el fiado sin cliente no escribe nada; `cliente.crear` lleva solo `{nombre, telefono}` y queda ANTES que la venta en la cola.

---

## Tarea 5: Registro del dispositivo — `DispositivoService`

**Files:**
- Create: `frontend/projects/libs/data-access/src/lib/offline/dispositivo.service.ts`
- Create: `frontend/projects/libs/data-access/src/lib/offline/dispositivo.service.spec.ts` (primero: el test que falla)
- Modify: `frontend/projects/libs/data-access/src/public-api.ts`

**Interfaces:**
- Consume: `VendiDb` (Tarea 2); `ApiService` + `SILENCIAR_AVISO_ERROR`; el contrato `POST /api/v1/dispositivos` (`DispositivoRegistrar`/`DispositivoSalida`, ya en el cliente generado).
- Produce: `DispositivoService.asegurarRegistro()` y las señales `dispositivoId`/`registrado` que consume el sincronizador (Tarea 6).

- [ ] **Paso 1: escribir el spec que falla.** Crear `frontend/projects/libs/data-access/src/lib/offline/dispositivo.service.spec.ts`:

```ts
import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { VendiDb } from './vendi.db';
import { DispositivoService } from './dispositivo.service';

describe('DispositivoService (registro, ADR-017)', () => {
  let db: VendiDb;
  let http: HttpTestingController;
  let servicio: DispositivoService;

  beforeEach(() => {
    db = new VendiDb(`test-${crypto.randomUUID()}`);
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: VendiDb, useValue: db },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    servicio = TestBed.inject(DispositivoService);
  });

  afterEach(async () => {
    http.verify();
    await db.delete();
  });

  it('genera el UUID la primera vez, lo persiste y lo registra en el servidor', async () => {
    const promesa = servicio.asegurarRegistro();
    const req = http.expectOne('/api/v1/dispositivos');
    expect(req.request.method).toBe('POST');
    const cuerpo = req.request.body as { id: string; nombre: string };
    expect(cuerpo.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(cuerpo.nombre).toBe('Caja 1');
    req.flush({ id: cuerpo.id, nombre: cuerpo.nombre, ultima_secuencia: 0, ultima_sync: null });

    const id = await promesa;
    expect(id).toBe(cuerpo.id);
    expect((await db.meta.get('dispositivo_id'))?.valor).toBe(id);
    expect(servicio.registrado()).toBe(true);
  });

  it('no genera un id nuevo tras la recarga: reusa el persistido', async () => {
    await db.meta.put({ clave: 'dispositivo_id', valor: 'id-persistido' });
    await db.meta.put({ clave: 'dispositivo_registrado', valor: 'si' });

    const id = await servicio.asegurarRegistro();
    expect(id).toBe('id-persistido');
    http.expectNone('/api/v1/dispositivos');
  });

  it('reconcilia la secuencia: jamás retrocede (max local, servidor)', async () => {
    await db.meta.put({ clave: 'ultima_secuencia', valor: 5 });
    const promesa = servicio.asegurarRegistro();
    http.expectOne('/api/v1/dispositivos').flush({
      id: 'x', nombre: 'Caja 1', ultima_secuencia: 3, ultima_sync: null,
    });
    await promesa;
    expect((await db.meta.get('ultima_secuencia'))?.valor).toBe(5);
  });

  it('adopta la secuencia del servidor si va por delante', async () => {
    const promesa = servicio.asegurarRegistro();
    http.expectOne('/api/v1/dispositivos').flush({
      id: 'x', nombre: 'Caja 1', ultima_secuencia: 7, ultima_sync: null,
    });
    await promesa;
    expect((await db.meta.get('ultima_secuencia'))?.valor).toBe(7);
  });

  it('sin red propaga el error y NO marca el dispositivo como registrado', async () => {
    const promesa = servicio.asegurarRegistro();
    http.expectOne('/api/v1/dispositivos').error(new ProgressEvent('error'));
    await expect(promesa).rejects.toBeTruthy();
    expect(servicio.registrado()).toBe(false);
    expect(await db.meta.get('dispositivo_registrado')).toBeUndefined();
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test data-access --watch=false
# Esperado: fallos — Cannot find module './dispositivo.service'
```

- [ ] **Paso 2: escribir la implementación.** Crear `frontend/projects/libs/data-access/src/lib/offline/dispositivo.service.ts`:

```ts
import { HttpContext } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { lastValueFrom } from 'rxjs';
import type { paths } from '../api-client';
import { ApiService } from '../api.service';
import { SILENCIAR_AVISO_ERROR } from '../interceptors/error.interceptor';
import type { ClaveMeta } from './modelos-locales';
import { VendiDb } from './vendi.db';

type DispositivoSalida =
  paths['/api/v1/dispositivos']['post']['responses']['201']['content']['application/json'];

/**
 * Registro del dispositivo (ADR-017).
 *
 * El dispositivo nace con un UUIDv4 local que el servidor adopta como PK:
 * re-registrar con el mismo id devuelve el existente. La `ultima_secuencia`
 * se reconcilia con `max(local, servidor)`: el contador FIFO del dispositivo
 * jamás retrocede (decisión 9 del plan).
 *
 * Un fallo de red propaga y NO marca el registro: el sincronizador lo
 * reintenta con el mismo backoff que los lotes. Un 409 (id en conflicto) es
 * irrecuperable sin intervención y también propaga — inventar una curación
 * automática de identidad es peor que el bloqueo visible.
 */
@Injectable({ providedIn: 'root' })
export class DispositivoService {
  private readonly db = inject(VendiDb);
  private readonly api = inject(ApiService);

  private readonly _dispositivoId = signal<string | null>(null);
  readonly dispositivoId = this._dispositivoId.asReadonly();
  private readonly _registrado = signal(false);
  readonly registrado = this._registrado.asReadonly();

  async asegurarRegistro(): Promise<string> {
    let id = await this.leerMeta('dispositivo_id');
    if (!id) {
      id = crypto.randomUUID();
      await this.db.meta.put({ clave: 'dispositivo_id', valor: id });
    }
    this._dispositivoId.set(id);

    if (await this.leerMeta('dispositivo_registrado')) {
      this._registrado.set(true);
      return id;
    }

    let nombre = await this.leerMeta('nombre_dispositivo');
    if (!nombre) {
      nombre = 'Caja 1';
      await this.db.meta.put({ clave: 'nombre_dispositivo', valor: nombre });
    }

    const salida = await lastValueFrom(
      this.api.post<DispositivoSalida>(
        '/dispositivos',
        { id, nombre },
        { context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true) },
      ),
    );

    const secuenciaLocal = await this.numeroMeta();
    await this.db.meta.put({
      clave: 'ultima_secuencia',
      valor: Math.max(secuenciaLocal, salida.ultima_secuencia),
    });
    await this.db.meta.put({ clave: 'dispositivo_registrado', valor: 'si' });
    this._registrado.set(true);
    return id;
  }

  private async leerMeta(clave: ClaveMeta): Promise<string | null> {
    const entrada = await this.db.meta.get(clave);
    return typeof entrada?.valor === 'string' ? entrada.valor : null;
  }

  private async numeroMeta(): Promise<number> {
    const entrada = await this.db.meta.get('ultima_secuencia');
    return typeof entrada?.valor === 'number' ? entrada.valor : 0;
  }
}
```

- [ ] **Paso 3: exportar por la superficie pública.** En `public-api.ts`, tras `VentasOfflineService`:

```ts
export { DispositivoService } from './lib/offline/dispositivo.service';
```

- [ ] **Paso 4: verificar en verde.**

```bash
cd frontend && npm run build:libs && npx ng test data-access --watch=false
# Esperado: verde, con los 5 specs nuevos del registro
```

- [ ] **Paso 5: commit**

```bash
git add frontend/projects/libs/data-access
git commit -m "Registro del dispositivo con UUID local persistido y reconciliación de ultima_secuencia"
```

**Criterios de aceptación:** el UUID se genera una vez y sobrevive a la recarga; el POST lleva `{id, nombre}`; la secuencia se reconcilia con `max(local, servidor)` en ambos sentidos; un fallo de red no deja el dispositivo marcado como registrado.

---

## Tarea 6: El motor de drenado — `SincronizadorService` (FIFO, veredictos por operación, backoff)

**Files:**
- Create: `frontend/projects/libs/data-access/src/lib/offline/sincronizador.service.ts`
- Create: `frontend/projects/libs/data-access/src/lib/offline/sincronizador.service.spec.ts` (primero: el test que falla)
- Modify: `frontend/projects/libs/data-access/src/public-api.ts`

**Interfaces:**
- Consume: `VendiDb` (Tarea 2), `VentasOfflineService` (Tarea 4, para sembrar la cola en los specs), `DispositivoService` (Tarea 5); el contrato `POST /api/v1/sync/lotes` (`LoteSync`, `RespuestaLote`, `ResultadoOperacion`, máx 200 por lote).
- Produce: `SincronizadorService` con `sincronizar()`, `reintentar()`, `recuperarEnviosInterrumpidos()`, `escucharConectividad()`, `notificarVentaCobrada()` y las señales `pendientes`/`enError`/`sincronizando` que pinta el POS.

- [ ] **Paso 1: escribir el spec que falla.** Crear `frontend/projects/libs/data-access/src/lib/offline/sincronizador.service.spec.ts`:

```ts
import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { VendiDb } from './vendi.db';
import { DispositivoService } from './dispositivo.service';
import { SincronizadorService, ESPERA_BASE_MS } from './sincronizador.service';
import { VentasOfflineService } from './ventas-offline.service';

/** El registro del dispositivo tiene su propio spec; aquí va fijo. */
class DispositivoFalso {
  readonly dispositivoId = signal('dispositivo-de-prueba');
  readonly registrado = signal(true);
  async asegurarRegistro(): Promise<string> {
    return 'dispositivo-de-prueba';
  }
}

const LINEA = [
  { producto_id: 'p-1', nombre: 'Arroz', cantidad_mili: 1000, precio_unitario_centavos: 4000 },
];

function preparar(): {
  db: VendiDb;
  http: HttpTestingController;
  sync: SincronizadorService;
  ventas: VentasOfflineService;
} {
  const db = new VendiDb(`test-${crypto.randomUUID()}`);
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: VendiDb, useValue: db },
      { provide: DispositivoService, useClass: DispositivoFalso },
    ],
  });
  return {
    db,
    http: TestBed.inject(HttpTestingController),
    sync: TestBed.inject(SincronizadorService),
    ventas: TestBed.inject(VentasOfflineService),
  };
}

async function cobrarTres(ventas: VentasOfflineService): Promise<string[]> {
  const ids: string[] = [];
  for (let n = 0; n < 3; n++) {
    ids.push(
      (await ventas.cobrar({
        lineas: LINEA, medio_pago: 'efectivo', cliente: null, fecha_vencimiento: null,
      })).id,
    );
  }
  return ids;
}

describe('SincronizadorService (drenado FIFO, ADR-017)', () => {
  let db: VendiDb;
  let http: HttpTestingController;
  let sync: SincronizadorService;
  let ventas: VentasOfflineService;

  beforeEach(() => {
    ({ db, http, sync, ventas } = preparar());
  });

  afterEach(async () => {
    http.verify();
    await db.delete();
  });

  it('drena en orden FIFO: el lote sale ordenado por secuencia', async () => {
    const ids = await cobrarTres(ventas);
    const promesa = sync.sincronizar();
    const req = http.expectOne('/api/v1/sync/lotes');
    expect(req.request.method).toBe('POST');
    const cuerpo = req.request.body as {
      dispositivo_id: string;
      operaciones: { id: string; secuencia: number }[];
    };
    expect(cuerpo.dispositivo_id).toBe('dispositivo-de-prueba');
    expect(cuerpo.operaciones.map((op) => op.id)).toEqual(ids);
    expect(cuerpo.operaciones.map((op) => op.secuencia)).toEqual([1, 2, 3]);
    req.flush({
      resultados: ids.map((id) => ({ id, tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null })),
    });
    await promesa;

    expect(await db.cola_sync.count()).toBe(0);
    expect(sync.pendientes()).toBe(0);
  });

  it('aplica el veredicto por operación: aceptada y duplicada salen; rechazada queda como dead-letter', async () => {
    const ids = await cobrarTres(ventas);
    const promesa = sync.sincronizar();
    http.expectOne('/api/v1/sync/lotes').flush({
      resultados: [
        { id: ids[0], tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
        { id: ids[1], tipo: 'venta.crear', resultado: 'duplicada', motivo: null, detalles: null },
        { id: ids[2], tipo: 'venta.crear', resultado: 'rechazada', motivo: 'venta_id_divergente', detalles: { campos: ['total_centavos'] } },
      ],
    });
    await promesa;

    expect(await db.cola_sync.get(ids[0])).toBeUndefined();
    expect(await db.cola_sync.get(ids[1])).toBeUndefined();
    const muerta = await db.cola_sync.get(ids[2]);
    expect(muerta?.estado).toBe('error');
    expect(muerta?.ultimo_error).toBe('venta_id_divergente');
    expect(sync.enError()).toBe(1);
    expect(sync.pendientes()).toBe(0);
  });

  it('la rechazada NO bloquea el FIFO: la venta siguiente drena en el próximo lote', async () => {
    const ids = await cobrarTres(ventas);
    let promesa = sync.sincronizar();
    http.expectOne('/api/v1/sync/lotes').flush({
      resultados: [
        { id: ids[0], tipo: 'venta.crear', resultado: 'rechazada', motivo: 'permiso_ausente', detalles: null },
        { id: ids[1], tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
        { id: ids[2], tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
      ],
    });
    await promesa;

    // Nueva venta tras el dead-letter: drena sola, sin arrastrar la rechazada.
    const cuarta = await ventas.cobrar({
      lineas: LINEA, medio_pago: 'efectivo', cliente: null, fecha_vencimiento: null,
    });
    promesa = sync.sincronizar();
    const req = http.expectOne('/api/v1/sync/lotes');
    const cuerpo = req.request.body as { operaciones: { id: string }[] };
    expect(cuerpo.operaciones.map((op) => op.id)).toEqual([cuarta.id]);
    req.flush({
      resultados: [{ id: cuarta.id, tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null }],
    });
    await promesa;
    expect(sync.pendientes()).toBe(0);
    expect(sync.enError()).toBe(1);
  });

  it('ante un 5xx reprograma TODO el lote con backoff y reintenta al vencerse', async () => {
    vi.useFakeTimers();
    try {
      const ids = await cobrarTres(ventas);
      let promesa = sync.sincronizar();
      http.expectOne('/api/v1/sync/lotes').flush('Error interno', { status: 500, statusText: 'Error' });
      await promesa;

      const ops = await db.cola_sync.toArray();
      expect(ops.every((op) => op.estado === 'pendiente' && op.intentos === 1)).toBe(true);
      expect(ops.every((op) => op.proximo_intento_en >= Date.now() + ESPERA_BASE_MS)).toBe(true);
      expect(sync.pendientes()).toBe(3);

      // Al vencerse el backoff, el temporizador dispara el reintento solo.
      const avance = vi.advanceTimersByTimeAsync(ESPERA_BASE_MS + 100);
      const req = await vi.waitFor(() => http.expectOne('/api/v1/sync/lotes'));
      req.flush({
        resultados: ids.map((id) => ({ id, tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null })),
      });
      await avance;
      expect(await db.cola_sync.count()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('un error de red se trata como el 5xx: nada sale de la cola', async () => {
    const ids = await cobrarTres(ventas);
    const promesa = sync.sincronizar();
    http.expectOne('/api/v1/sync/lotes').error(new ProgressEvent('error'));
    await promesa;

    expect(await db.cola_sync.count()).toBe(3);
    expect((await db.cola_sync.get(ids[0]))?.estado).toBe('pendiente');
    expect((await db.cola_sync.get(ids[0]))?.intentos).toBe(1);
  });

  it('las operaciones enviando huérfanas vuelven a pendiente al arrancar', async () => {
    const ids = await cobrarTres(ventas);
    await db.cola_sync.update(ids[1], { estado: 'enviando' });

    await sync.recuperarEnviosInterrumpidos();
    expect((await db.cola_sync.get(ids[1]))?.estado).toBe('pendiente');

    // Y drenan con normalidad, en orden.
    const promesa = sync.sincronizar();
    const req = http.expectOne('/api/v1/sync/lotes');
    const cuerpo = req.request.body as { operaciones: { id: string }[] };
    expect(cuerpo.operaciones.map((op) => op.id)).toEqual(ids);
    req.flush({
      resultados: ids.map((id) => ({ id, tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null })),
    });
    await promesa;
  });

  it('la cola drena tras la recarga (candado de ADR-017: sobrevive a la app)', async () => {
    const ids = await cobrarTres(ventas);
    const nombre = db.name;
    await db.close();

    const reabierta = new VendiDb(nombre);
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: VendiDb, useValue: reabierta },
        { provide: DispositivoService, useClass: DispositivoFalso },
      ],
    });
    const http2 = TestBed.inject(HttpTestingController);
    const sync2 = TestBed.inject(SincronizadorService);

    const promesa = sync2.sincronizar();
    const req = http2.expectOne('/api/v1/sync/lotes');
    expect((req.request.body as { operaciones: { id: string }[] }).operaciones.map((op) => op.id)).toEqual(ids);
    req.flush({
      resultados: ids.map((id) => ({ id, tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null })),
    });
    await promesa;
    expect(await reabierta.cola_sync.count()).toBe(0);
    http2.verify();
    await reabierta.delete();
  });

  it('el reintento manual adelanta las pendientes sin tocar los dead-letters', async () => {
    await cobrarTres(ventas);
    await db.cola_sync.where('secuencia').equals(1).modify({
      estado: 'error', ultimo_error: 'venta_id_divergente',
    });
    await db.cola_sync.where('estado').equals('pendiente').modify({
      proximo_intento_en: Date.now() + 3_600_000,
    });

    const promesa = sync.reintentar();
    const req = http.expectOne('/api/v1/sync/lotes');
    const cuerpo = req.request.body as { operaciones: { secuencia: number }[] };
    expect(cuerpo.operaciones.map((op) => op.secuencia)).toEqual([2, 3]);
    req.flush({
      resultados: cuerpo.operaciones.map((op) => ({
        id: 'x', tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null, ...op,
      })),
    });
    await promesa;
    expect(sync.enError()).toBe(1);
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test data-access --watch=false
# Esperado: fallos — Cannot find module './sincronizador.service'
```

- [ ] **Paso 2: escribir la implementación.** Crear `frontend/projects/libs/data-access/src/lib/offline/sincronizador.service.ts`:

```ts
import { HttpContext } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { lastValueFrom } from 'rxjs';
import type { paths } from '../api-client';
import { ApiService } from '../api.service';
import { SILENCIAR_AVISO_ERROR } from '../interceptors/error.interceptor';
import { DispositivoService } from './dispositivo.service';
import type { OperacionEnCola } from './modelos-locales';
import { VendiDb } from './vendi.db';

type LoteSync =
  paths['/api/v1/sync/lotes']['post']['requestBody']['content']['application/json'];
type RespuestaLote =
  paths['/api/v1/sync/lotes']['post']['responses']['200']['content']['application/json'];

/** Tope del contrato: el lote acepta entre 1 y 200 operaciones. */
export const LOTE_MAXIMO = 200;
/** Backoff exponencial con tope (decisión 7 del plan): 5s, 10s, 20s, …, 5min. */
export const ESPERA_BASE_MS = 5_000;
export const ESPERA_MAXIMA_MS = 300_000;

export function esperaDeReintento(intentos: number): number {
  return Math.min(ESPERA_BASE_MS * 2 ** Math.max(0, intentos - 1), ESPERA_MAXIMA_MS);
}

/**
 * El motor de drenado de la cola (ADR-017).
 *
 * Reglas duras:
 *
 *  - FIFO por `secuencia`: el lote sale ordenado, porque la dependencia entre
 *    operaciones (`cliente.crear` antes que la venta fiada) es estructural.
 *  - La cola NUNCA se purga sin veredicto: una operación sale solo con
 *    `aceptada` o `duplicada`. La `rechazada` es dead-letter visible
 *    (decisión 5): queda en `error` con su motivo y no bloquea a las demás.
 *  - El backoff es por lote y ante fallo de transporte (red o 5xx): todas las
 *    operaciones del lote vuelven a `pendiente` con `intentos+1`. El reenvío
 *    es seguro porque el servidor es idempotente por PK (la re-aplicación
 *    responde `duplicada` y no re-emite eventos).
 *  - Los avisos globales de error se silencian en estas llamadas: la tienda
 *    no necesita un aviso por cada reintento de fondo; el estado lo da el
 *    contador de pendientes.
 */
@Injectable({ providedIn: 'root' })
export class SincronizadorService {
  private readonly db = inject(VendiDb);
  private readonly api = inject(ApiService);
  private readonly dispositivos = inject(DispositivoService);

  private readonly _pendientes = signal(0);
  readonly pendientes = this._pendientes.asReadonly();
  private readonly _enError = signal(0);
  readonly enError = this._enError.asReadonly();
  private readonly _sincronizando = signal(false);
  readonly sincronizando = this._sincronizando.asReadonly();

  private drenajeEnVuelo = false;
  private temporizador: ReturnType<typeof setTimeout> | null = null;
  private escuchando = false;

  /** Dispara el drenado al volver la red. Idempotente (un solo listener). */
  escucharConectividad(): void {
    if (this.escuchando) {
      return;
    }
    this.escuchando = true;
    window.addEventListener('online', () => void this.sincronizar());
  }

  /** Cuenta pendientes y dead-letters para la barra del POS. */
  async refrescarContadores(): Promise<void> {
    this._pendientes.set(await this.db.cola_sync.where('estado').equals('pendiente').count());
    this._enError.set(await this.db.cola_sync.where('estado').equals('error').count());
  }

  /**
   * Las `enviando` huérfanas vuelven a `pendiente` (decisión 8): si la app
   * murió a mitad del drenado, el estado transitorio no es verdad — la cola
   * sí, y el reenvío es idempotente.
   */
  async recuperarEnviosInterrumpidos(): Promise<void> {
    await this.db.cola_sync.where('estado').equals('enviando').modify({ estado: 'pendiente' });
  }

  async sincronizar(): Promise<void> {
    if (this.drenajeEnVuelo) {
      return;
    }
    this.drenajeEnVuelo = true;
    this._sincronizando.set(true);
    try {
      const dispositivoId = await this.dispositivos.asegurarRegistro();
      let quedanPorDrenar = true;
      while (quedanPorDrenar) {
        quedanPorDrenar = await this.drenarLote(dispositivoId);
      }
    } catch (error) {
      // Sin red (en el registro o en el lote): se pospone con backoff y se
      // sigue vendiendo. La cola es la verdad; el aviso lo da el contador.
      console.warn('El drenado de la cola se pospone.', error);
      this.programarReintento();
    } finally {
      this.drenajeEnVuelo = false;
      this._sincronizando.set(false);
      await this.refrescarContadores();
    }
  }

  /** @returns `true` si pudo quedar otro lote detrás (este salió lleno). */
  private async drenarLote(dispositivoId: string): Promise<boolean> {
    const ahora = Date.now();
    const lote = (
      await this.db.cola_sync.where('estado').equals('pendiente').sortBy('secuencia')
    )
      .filter((op) => op.proximo_intento_en <= ahora)
      .slice(0, LOTE_MAXIMO);
    if (lote.length === 0) {
      this.programarReintento();
      return false;
    }

    await this.db.cola_sync
      .where('id')
      .anyOf(lote.map((op) => op.id))
      .modify({ estado: 'enviando' });

    const cuerpo: LoteSync = {
      dispositivo_id: dispositivoId,
      operaciones: lote.map(({ id, tipo, secuencia, datos }) => ({ id, tipo, secuencia, datos })),
    };

    try {
      const respuesta = await lastValueFrom(
        this.api.post<RespuestaLote>('/sync/lotes', cuerpo, {
          context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true),
        }),
      );
      await this.aplicarVeredictos(respuesta, lote);
    } catch (error) {
      await this.reprogramar(lote);
      throw error;
    }
    return lote.length === LOTE_MAXIMO;
  }

  private async aplicarVeredictos(
    respuesta: RespuestaLote,
    lote: OperacionEnCola[],
  ): Promise<void> {
    const porId = new Map(lote.map((op) => [op.id, op]));
    await this.db.transaction('rw', this.db.cola_sync, async () => {
      for (const resultado of respuesta.resultados) {
        const operacion = porId.get(resultado.id);
        if (!operacion) {
          // El servidor no inventa ids; si lo hiciera, no tocamos nada.
          continue;
        }
        if (resultado.resultado === 'aceptada' || resultado.resultado === 'duplicada') {
          await this.db.cola_sync.delete(operacion.id);
        } else {
          await this.db.cola_sync.update(operacion.id, {
            estado: 'error',
            ultimo_error: resultado.motivo ?? 'rechazada_sin_motivo',
          });
        }
      }
    });
  }

  private async reprogramar(lote: OperacionEnCola[]): Promise<void> {
    const ahora = Date.now();
    await this.db.transaction('rw', this.db.cola_sync, async () => {
      for (const operacion of lote) {
        const intentos = operacion.intentos + 1;
        await this.db.cola_sync.update(operacion.id, {
          estado: 'pendiente',
          intentos,
          proximo_intento_en: ahora + esperaDeReintento(intentos),
        });
      }
    });
  }

  /** Programa el próximo drenado para la pendiente más próxima, si la hay. */
  private programarReintento(): void {
    if (this.temporizador) {
      return;
    }
    void this.proximaPendiente().then((instante) => {
      if (instante === null) {
        return;
      }
      this.temporizador = setTimeout(
        () => {
          this.temporizador = null;
          void this.sincronizar();
        },
        Math.max(0, instante - Date.now()),
      );
    });
  }

  private async proximaPendiente(): Promise<number | null> {
    const pendientes = await this.db.cola_sync.where('estado').equals('pendiente').toArray();
    if (pendientes.length === 0) {
      return null;
    }
    return Math.min(...pendientes.map((op) => op.proximo_intento_en));
  }

  /** El botón manual del POS: adelanta las pendientes. Los dead-letters NO se reintentan (decisión 5). */
  async reintentar(): Promise<void> {
    await this.db.cola_sync
      .where('estado')
      .equals('pendiente')
      .modify({ proximo_intento_en: Date.now() });
    await this.sincronizar();
  }

  /** Lo llama el POS tras cada cobro: intento inmediato (si hay red, sube ya). */
  notificarVentaCobrada(): void {
    void this.refrescarContadores();
    void this.sincronizar();
  }
}
```

- [ ] **Paso 3: exportar por la superficie pública.** En `public-api.ts`, tras `DispositivoService`:

```ts
export {
  ESPERA_BASE_MS,
  ESPERA_MAXIMA_MS,
  LOTE_MAXIMO,
  SincronizadorService,
  esperaDeReintento,
} from './lib/offline/sincronizador.service';
```

- [ ] **Paso 4: verificar en verde.**

```bash
cd frontend && npm run build:libs && npx ng test data-access --watch=false
# Esperado: verde, con los 8 specs nuevos del motor de drenado
npx ng lint data-access
# Esperado: sin errores
```

- [ ] **Paso 5: commit**

```bash
git add frontend/projects/libs/data-access
git commit -m "Motor de drenado de la cola: FIFO por secuencia, veredictos por operación, backoff por lote y dead-letters visibles"
```

**Criterios de aceptación:** el lote sale ordenado por `secuencia` con el `dispositivo_id` del registro; `aceptada`/`duplicada` salen de la cola y `rechazada` queda como dead-letter con motivo sin bloquear el FIFO; el 5xx y el error de red reprograman todo el lote con backoff (verificado con fake timers); las `enviando` huérfanas vuelven a `pendiente`; el candado «la cola sobrevive a la recarga y drena en orden» pasa; el reintento manual adelanta pendientes sin tocar dead-letters.

---

## Tarea 7: El catálogo local — `CatalogoLocalService` (delta al IndexedDB, tumbas, clientes online)

**Files:**
- Create: `frontend/projects/libs/data-access/src/lib/offline/catalogo-local.service.ts`
- Create: `frontend/projects/libs/data-access/src/lib/offline/catalogo-local.service.spec.ts` (primero: el test que falla)
- Modify: `frontend/projects/libs/data-access/src/public-api.ts`

**Interfaces:**
- Consume: `VendiDb` (Tarea 2); `GET /api/v1/sync/delta` (`DeltaSalida`: `hasta`, `productos: ProductoSalida[]`, `eliminados: uuid[]`); `GET /api/v1/clientes` (`PagedList` de `ClienteConSaldo`).
- Produce: `CatalogoLocalService.refrescarDelta()`, `.buscar()`, `.contar()`, `.cargarClientes()`, `.buscarClientes()` — la lectura local del POS.

- [ ] **Paso 1: escribir el spec que falla.** Crear `frontend/projects/libs/data-access/src/lib/offline/catalogo-local.service.spec.ts`:

```ts
import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { VendiDb } from './vendi.db';
import { CatalogoLocalService } from './catalogo-local.service';

const PRODUCTO_API = {
  id: 'p-1',
  nombre: 'Arroz x kg',
  categoria: 'Granos',
  codigo_barras: '7701234567890',
  precio_venta: 4000,
  unidad_medida: 'kg',
  stock_actual: '25.500',
};

describe('CatalogoLocalService (delta al IndexedDB, ADR-017)', () => {
  let db: VendiDb;
  let http: HttpTestingController;
  let catalogo: CatalogoLocalService;

  beforeEach(() => {
    db = new VendiDb(`test-${crypto.randomUUID()}`);
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: VendiDb, useValue: db },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    catalogo = TestBed.inject(CatalogoLocalService);
  });

  afterEach(async () => {
    http.verify();
    await db.delete();
  });

  it('la primera descarga pide desde la marca inicial y siembra el catálogo', async () => {
    const promesa = catalogo.refrescarDelta();
    const req = http.expectOne((r) => r.url === '/api/v1/sync/delta');
    expect(req.request.params.get('desde')).toBe('1970-01-01T00:00:00.000Z');
    req.flush({ hasta: '2026-07-29T10:00:00Z', productos: [PRODUCTO_API], eliminados: [] });
    const resultado = await promesa;

    expect(resultado).toEqual({ recibidos: 1, eliminados: 0 });
    const guardado = await db.productos.get('p-1');
    expect(guardado?.precio_venta).toBe(4000);
    expect(guardado?.stock_actual).toBe('25.500');
    expect((await db.meta.get('delta_hasta'))?.valor).toBe('2026-07-29T10:00:00Z');
  });

  it('la siguiente descarga usa el watermark guardado y aplica tumbas', async () => {
    await db.meta.put({ clave: 'delta_hasta', valor: '2026-07-29T10:00:00Z' });
    await db.productos.put({
      id: 'p-viejo', nombre: 'Viejo', categoria: null, codigo_barras: null,
      precio_venta: 100, unidad_medida: 'unidad', stock_actual: '1',
    });

    const promesa = catalogo.refrescarDelta();
    const req = http.expectOne((r) => r.url === '/api/v1/sync/delta');
    expect(req.request.params.get('desde')).toBe('2026-07-29T10:00:00Z');
    req.flush({ hasta: '2026-07-29T11:00:00Z', productos: [], eliminados: ['p-viejo'] });
    await promesa;

    expect(await db.productos.get('p-viejo')).toBeUndefined();
    expect((await db.meta.get('delta_hasta'))?.valor).toBe('2026-07-29T11:00:00Z');
  });

  it('busca por nombre sin distinguir mayúsculas y por código de barras exacto', async () => {
    await db.productos.bulkPut([
      { id: 'p-1', nombre: 'Arroz x kg', categoria: 'Granos', codigo_barras: '7701234567890', precio_venta: 4000, unidad_medida: 'kg', stock_actual: '25.5' },
      { id: 'p-2', nombre: 'Aceite girasol', categoria: null, codigo_barras: null, precio_venta: 9000, unidad_medida: 'unidad', stock_actual: '8' },
    ]);

    expect((await catalogo.buscar('arroz')).map((p) => p.id)).toEqual(['p-1']);
    expect((await catalogo.buscar('ARROZ')).map((p) => p.id)).toEqual(['p-1']);
    expect((await catalogo.buscar('7701234567890')).map((p) => p.id)).toEqual(['p-1']);
    expect((await catalogo.buscar('')).length).toBe(2);
  });

  it('asimila los clientes del servidor cuando hay red (rodeo de D-28)', async () => {
    const promesa = catalogo.cargarClientes();
    const req = http.expectOne((r) => r.url === '/api/v1/clientes');
    expect(req.request.params.get('limit')).toBe('200');
    req.flush({
      items: [
        { id: 'c-1', nombre: 'Don Carlos', telefono: '3001234567', limite_credito: 50000, nota: null, saldo_pendiente_total: 12000, cupo_excedido: false, created_at: null },
      ],
      total: 1, skip: 0, limit: 200,
    });
    const cargados = await promesa;

    expect(cargados).toBe(1);
    const cliente = await db.clientes.get('c-1');
    expect(cliente?.origen).toBe('servidor');
    expect(cliente?.limite_credito).toBe(50000);
  });

  it('busca clientes locales por nombre', async () => {
    await db.clientes.bulkPut([
      { id: 'c-1', nombre: 'Don Carlos', telefono: null, limite_credito: null, origen: 'local' },
      { id: 'c-2', nombre: 'Doña Ana', telefono: null, limite_credito: null, origen: 'servidor' },
    ]);
    expect((await catalogo.buscarClientes('carlos')).map((c) => c.id)).toEqual(['c-1']);
    expect((await catalogo.buscarClientes('')).length).toBe(2);
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test data-access --watch=false
# Esperado: fallos — Cannot find module './catalogo-local.service'
```

- [ ] **Paso 2: escribir la implementación.** Crear `frontend/projects/libs/data-access/src/lib/offline/catalogo-local.service.ts`:

```ts
import { HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { lastValueFrom } from 'rxjs';
import type { paths } from '../api-client';
import { ApiService } from '../api.service';
import { SILENCIAR_AVISO_ERROR } from '../interceptors/error.interceptor';
import type { ClienteLocal, ProductoLocal } from './modelos-locales';
import { VendiDb } from './vendi.db';

type DeltaSalida =
  paths['/api/v1/sync/delta']['get']['responses']['200']['content']['application/json'];
type PaginaClientes =
  paths['/api/v1/clientes']['get']['responses']['200']['content']['application/json'];

/**
 * Marca inicial del delta: «desde el principio de los tiempos». El servidor
 * responde con todo el catálogo vivo y su marca `hasta`.
 */
const MARCA_INICIAL = '1970-01-01T00:00:00.000Z';

const LIMITE_BUSQUEDA = 20;

/**
 * El catálogo local del POS (ADR-017).
 *
 * El delta baja los cambios del servidor al IndexedDB: productos vivos
 * (upsert — el LWW lo arbitra el orden de recepción en el servidor, nunca el
 * reloj del dispositivo) y tumbas (borrados). El watermark `hasta` del
 * servidor se guarda en `meta` y se devuelve como próximo `desde`: es marca
 * del SERVIDOR, no del reloj local.
 *
 * Los clientes NO tienen delta (D-28): se asimilan online por
 * `GET /clientes` en el mismo gesto de refresco. Offline, el dispositivo ve
 * los que él mismo creó (decisión 4 del plan).
 */
@Injectable({ providedIn: 'root' })
export class CatalogoLocalService {
  private readonly db = inject(VendiDb);
  private readonly api = inject(ApiService);

  /** Baja el delta al IndexedDB y avanza el watermark, en una transacción. */
  async refrescarDelta(): Promise<{ recibidos: number; eliminados: number }> {
    const desde = (await this.leerWatermark()) ?? MARCA_INICIAL;
    const delta = await lastValueFrom(
      this.api.get<DeltaSalida>(
        '/sync/delta',
        { desde },
        { context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true) },
      ),
    );
    await this.db.transaction('rw', [this.db.productos, this.db.meta], async () => {
      await this.db.productos.bulkPut(delta.productos.map(mapearProducto));
      await this.db.productos.bulkDelete(delta.eliminados);
      await this.db.meta.put({ clave: 'delta_hasta', valor: delta.hasta });
    });
    return { recibidos: delta.productos.length, eliminados: delta.eliminados.length };
  }

  /**
   * Búsqueda del POS: subcadena de nombre (sin distinguir mayúsculas) o
   * código de barras EXACTO — un lector de código «teclea» el código entero.
   * Todo local: sin red no hay búsqueda contra la API que valga.
   */
  buscar(consulta: string): Promise<ProductoLocal[]> {
    const limpia = consulta.trim();
    if (limpia.length === 0) {
      return this.db.productos.orderBy('nombre').limit(LIMITE_BUSQUEDA).toArray();
    }
    const minusculas = limpia.toLowerCase();
    return this.db.productos
      .filter(
        (producto) =>
          producto.nombre.toLowerCase().includes(minusculas) ||
          producto.codigo_barras === limpia,
      )
      .limit(LIMITE_BUSQUEDA)
      .toArray();
  }

  contar(): Promise<number> {
    return this.db.productos.count();
  }

  /** Asimila los clientes del servidor (rodeo de D-28; solo con red). */
  async cargarClientes(): Promise<number> {
    const pagina = await lastValueFrom(
      this.api.get<PaginaClientes>(
        '/clientes',
        { limit: 200 },
        { context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true) },
      ),
    );
    const asimilados: ClienteLocal[] = pagina.items.map((cliente) => ({
      id: cliente.id,
      nombre: cliente.nombre,
      telefono: cliente.telefono ?? null,
      limite_credito: cliente.limite_credito ?? null,
      origen: 'servidor',
    }));
    await this.db.clientes.bulkPut(asimilados);
    return asimilados.length;
  }

  buscarClientes(consulta: string): Promise<ClienteLocal[]> {
    const limpia = consulta.trim().toLowerCase();
    if (limpia.length === 0) {
      return this.db.clientes.orderBy('nombre').limit(LIMITE_BUSQUEDA).toArray();
    }
    return this.db.clientes
      .filter((cliente) => cliente.nombre.toLowerCase().includes(limpia))
      .limit(LIMITE_BUSQUEDA)
      .toArray();
  }

  private async leerWatermark(): Promise<string | null> {
    const entrada = await this.db.meta.get('delta_hasta');
    return typeof entrada?.valor === 'string' ? entrada.valor : null;
  }
}

function mapearProducto(producto: DeltaSalida['productos'][number]): ProductoLocal {
  return {
    id: producto.id,
    nombre: producto.nombre,
    categoria: producto.categoria ?? null,
    codigo_barras: producto.codigo_barras ?? null,
    precio_venta: producto.precio_venta,
    unidad_medida: producto.unidad_medida,
    stock_actual: producto.stock_actual,
  };
}
```

- [ ] **Paso 3: exportar por la superficie pública.** En `public-api.ts`, tras el sincronizador:

```ts
export { CatalogoLocalService } from './lib/offline/catalogo-local.service';
```

- [ ] **Paso 4: verificar en verde.**

```bash
cd frontend && npm run build:libs && npx ng test data-access --watch=false
# Esperado: verde, con los 5 specs nuevos del catálogo local
```

- [ ] **Paso 5: commit**

```bash
git add frontend/projects/libs/data-access
git commit -m "Catálogo local: delta al IndexedDB con watermark y tumbas, búsqueda offline y asimilación online de clientes"
```

**Criterios de aceptación:** la primera descarga pide `desde` la marca inicial y siembra; la siguiente reusa el watermark y aplica tumbas; la búsqueda resuelve por subcadena de nombre y por código de barras exacto, todo local; los clientes del servidor se asimilan con `origen: 'servidor'`.

---

## Tarea 8: El POS en `vendi-app` — catálogo local, ticket, cobro y estado de la cola

**Files:**
- Create: `frontend/projects/vendi-app/src/app/nucleo/sesion.ts` (copia de la de `vendi-tenant`, decisión 11)
- Create: `frontend/projects/vendi-app/src/app/features/pos/pos.component.ts`
- Create: `frontend/projects/vendi-app/src/app/features/pos/pos.component.html`
- Create: `frontend/projects/vendi-app/src/app/features/pos/pos.component.scss`
- Create: `frontend/projects/vendi-app/src/app/features/pos/pos.component.spec.ts` (primero: el test que falla)
- Create: `frontend/projects/vendi-app/src/app/features/elegir-negocio/elegir-negocio.component.ts` (y `.html`/`.scss`, copia adaptada de la de `vendi-tenant`)
- Modify: `frontend/projects/vendi-app/src/app/app.routes.ts`
- Modify: `frontend/projects/vendi-app/src/app/app.config.ts`
- Modify: `frontend/projects/vendi-app/public/i18n/es.json`

**Interfaces:**
- Consume: `VentasOfflineService`, `CatalogoLocalService`, `SincronizadorService`, `Notificador` (Tareas 4-7); aritmética de `domain` (Tarea 3); `AuthService`, `authGuard`, `tenantGuard`, `authInterceptor` de `auth`; `proveerSesion` y `ElegirNegocioComponent` de `vendi-tenant` como plantilla.
- Produce: la ruta `/` del POS protegida por `authGuard` + `tenantGuard`, la venta offline funcionando en el navegador/PWA, y el estado de la cola visible con reintento manual.

- [ ] **Paso 1: cablear la sesión y los interceptores.** Crear `frontend/projects/vendi-app/src/app/nucleo/sesion.ts` como COPIA EXACTA de `frontend/projects/vendi-tenant/src/app/nucleo/sesion.ts` (mismo `check-sso`, mismo `catch` que no aborta el bootstrap: un POS que no arranca sin IdP no es offline-first; la deduplicación hacia libs es de la pista web, decisión 11).

En `frontend/projects/vendi-app/src/app/app.config.ts`, reemplazar los providers de HTTP por:

```ts
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { authInterceptor } from 'auth';
import {
  API_BASE_URL,
  correlationIdInterceptor,
  errorInterceptor,
  proveerI18nVendi,
} from 'data-access';
import { proveerSesion } from './nucleo/sesion';
```

```ts
    // Mismo orden que vendi-tenant: errorInterceptor envuelve al resto.
    provideHttpClient(
      withInterceptors([errorInterceptor, correlationIdInterceptor, authInterceptor]),
    ),
    { provide: API_BASE_URL, useValue: environment.apiUrl },
    ...proveerI18nVendi(),
    // Sesión de Keycloak con el flujo WEB (passkey en el navegador). La auth
    // nativa por navegador del sistema es la deuda D-29; el canal del piloto
    // es la PWA instalada (decisión 1 del plan).
    proveerSesion({
      url: environment.keycloakUrl,
      realm: environment.realm,
      clientId: environment.clientId,
    }),
```

(el bloque de `provideServiceWorker` queda EXACTAMENTE como está: el SW solo cachea assets y no corre en el WebView nativo.)

- [ ] **Paso 2: las rutas.** Reemplazar `frontend/projects/vendi-app/src/app/app.routes.ts`:

```ts
import { Routes } from '@angular/router';
import { authGuard, tenantGuard } from 'auth';

/**
 * Rutas del POS (Etapa 1.3): la pantalla de venta ES la app.
 *
 * `authGuard` y `tenantGuard` llegan con este subproyecto (el spec-candado
 * que los prohibía se retira en la Tarea 9, con su nota). El flujo de login
 * es el web: en el navegador y en la PWA instalada funciona el passkey; la
 * auth nativa es la deuda D-29.
 *
 * `/elegir-negocio` NO lleva `tenantGuard`: es adonde `tenantGuard` manda a
 * quien no ha elegido, y protegerla con él sería un bucle de redirección
 * (mismo criterio que en vendi-tenant).
 */
export const routes: Routes = [
  {
    path: '',
    canActivate: [authGuard, tenantGuard],
    loadComponent: () => import('./features/pos/pos.component').then((m) => m.PosComponent),
  },
  {
    path: 'elegir-negocio',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/elegir-negocio/elegir-negocio.component').then(
        (m) => m.ElegirNegocioComponent,
      ),
  },
  { path: '**', redirectTo: '' },
];
```

- [ ] **Paso 3: el selector de negocio.** Copiar `frontend/projects/vendi-tenant/src/app/features/elegir-negocio/elegir-negocio.component.{ts,html,scss}` a `frontend/projects/vendi-app/src/app/features/elegir-negocio/`, con DOS cambios: en `elegir()`, navegar a `['/']` en vez de `['/mi-negocio']` (y ajustar el comentario y el mensaje de error), y el bloque de i18n nuevo del Paso 6.

- [ ] **Paso 4: el spec del POS que falla.** Crear `frontend/projects/vendi-app/src/app/features/pos/pos.component.spec.ts`:

```ts
import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideTranslateService } from '@ngx-translate/core';
import {
  CatalogoLocalService,
  DispositivoService,
  SincronizadorService,
  VendiDb,
  VentasOfflineService,
} from 'data-access';
import { PosComponent } from './pos.component';

class DispositivoFalso {
  readonly dispositivoId = signal('dispositivo-de-prueba');
  readonly registrado = signal(true);
  async asegurarRegistro(): Promise<string> {
    return 'dispositivo-de-prueba';
  }
}

function preparar(): { db: VendiDb; http: HttpTestingController } {
  const db = new VendiDb(`test-${crypto.randomUUID()}`);
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideTranslateService({ lang: 'es', fallbackLang: 'es' }),
      { provide: VendiDb, useValue: db },
      { provide: DispositivoService, useClass: DispositivoFalso },
    ],
  });
  return { db, http: TestBed.inject(HttpTestingController) };
}

/** Responde el arranque: delta vacío, clientes vacíos, sin lote (cola vacía). */
function responderArranque(http: HttpTestingController): void {
  http.expectOne((r) => r.url === '/api/v1/sync/delta').flush({
    hasta: '2026-07-29T10:00:00Z', productos: [], eliminados: [],
  });
  http.expectOne((r) => r.url === '/api/v1/clientes').flush({
    items: [], total: 0, skip: 0, limit: 200,
  });
}

describe('PosComponent (el POS offline)', () => {
  let db: VendiDb;
  let http: HttpTestingController;

  beforeEach(() => {
    ({ db, http } = preparar());
  });

  afterEach(async () => {
    http.verify();
    await db.delete();
  });

  async function crearComponente(): Promise<PosComponent> {
    const fixture = TestBed.createComponent(PosComponent);
    fixture.detectChanges();
    // Las peticiones del arranque se emiten en ngOnInit: se responden ANTES de
    // esperar la estabilidad, o whenStable() espera una respuesta que nadie da.
    responderArranque(http);
    await fixture.whenStable();
    return fixture.componentInstance;
  }

  async function sembrarProducto(): Promise<void> {
    await db.productos.put({
      id: 'p-1', nombre: 'Arroz x kg', categoria: 'Granos',
      codigo_barras: '7701234567890', precio_venta: 4000,
      unidad_medida: 'kg', stock_actual: '25.5',
    });
  }

  it('agrega productos al ticket y calcula el total en centavos exactos', async () => {
    const componente = await crearComponente();
    await sembrarProducto();
    await componente.buscar('arroz');

    componente.agregar(componente.resultados()[0]);
    componente.agregar(componente.resultados()[0]);

    expect(componente.lineas().length).toBe(1);
    expect(componente.lineas()[0].cantidad_mili).toBe(2000);
    expect(componente.total()).toBe(8000);
  });

  it('el granel se edita con coma o punto y se cobra exacto', async () => {
    const componente = await crearComponente();
    await sembrarProducto();
    await componente.buscar('arroz');
    componente.agregar(componente.resultados()[0]);

    componente.fijarCantidad('p-1', '0,333');
    expect(componente.lineas()[0].cantidad_mili).toBe(333);
    expect(componente.total()).toBe(1332); // 4000 × 0,333 = 1332 exactos

    componente.fijarCantidad('p-1', '2.5');
    expect(componente.lineas()[0].cantidad_mili).toBe(2500);
    expect(componente.total()).toBe(10000);
  });

  it('cobra sin red: la venta y su operación quedan en la base local', async () => {
    const componente = await crearComponente();
    await sembrarProducto();
    await componente.buscar('arroz');
    componente.agregar(componente.resultados()[0]);

    await componente.cobrar();
    // El intento de sync inmediato sale sin red:
    http.expectOne('/api/v1/sync/lotes').error(new ProgressEvent('error'));

    expect(await db.ventas_locales.count()).toBe(1);
    expect(await db.cola_sync.count()).toBe(1);
    expect(componente.lineas().length).toBe(0);
    expect(componente.ultimaVenta()?.consecutivo_local).toBe(1);
  });

  it('el fiado sin cliente NO cobra y no deja nada en la cola', async () => {
    const componente = await crearComponente();
    await sembrarProducto();
    await componente.buscar('arroz');
    componente.agregar(componente.resultados()[0]);
    componente.elegirMedioPago('fiado');

    await componente.cobrar();

    expect(await db.ventas_locales.count()).toBe(0);
    expect(await db.cola_sync.count()).toBe(0);
    expect(componente.lineas().length).toBe(1); // el ticket sigue ahí
  });

  it('el fiado con cliente local sube con cliente.crear ANTES en la cola', async () => {
    const componente = await crearComponente();
    await sembrarProducto();
    await componente.buscar('arroz');
    componente.agregar(componente.resultados()[0]);
    componente.elegirMedioPago('fiado');

    await componente.buscarCliente('carlos');
    await componente.crearCliente();
    componente.elegirCliente(componente.clientes()[0]);

    await componente.cobrar();
    http.expectOne('/api/v1/sync/lotes').error(new ProgressEvent('error'));

    const cola = await db.cola_sync.orderBy('secuencia').toArray();
    expect(cola.map((op) => op.tipo)).toEqual(['cliente.crear', 'venta.crear']);
    expect(cola[1].datos['medio_pago']).toBe('fiado');
    expect(cola[1].datos['cliente_id']).toBe(cola[0].id);
  });

  it('el contador de pendientes refleja la cola', async () => {
    const componente = await crearComponente();
    await sembrarProducto();
    await componente.buscar('arroz');
    componente.agregar(componente.resultados()[0]);

    await componente.cobrar();
    http.expectOne('/api/v1/sync/lotes').error(new ProgressEvent('error'));

    expect(TestBed.inject(SincronizadorService).pendientes()).toBe(1);
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test vendi-app --watch=false
# Esperado: fallos — Cannot find module './pos.component'
```

- [ ] **Paso 5: el componente del POS.** Crear `frontend/projects/vendi-app/src/app/features/pos/pos.component.ts`:

```ts
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import {
  CatalogoLocalService,
  ClienteLocal,
  Notificador,
  ProductoLocal,
  SincronizadorService,
  VentaLocal,
  VentasOfflineService,
} from 'data-access';
import {
  LineaTicket,
  MILI_POR_UNIDAD,
  formatearPesos,
  miliDeCantidad,
  totalLineaCentavos,
  totalTicketCentavos,
} from 'domain';

/**
 * El punto de venta: la pantalla por la que existe esta app.
 *
 * Todo lo que hace el tendero aquí funciona SIN RED: el catálogo se lee del
 * IndexedDB (lo siembra el delta), el cobro escribe en la base local y encola
 * en la misma transacción (el outbox de `VentasOfflineService`), y el estado
 * de la cola se ve siempre arriba: «N por sincronizar» es la promesa visible
 * de que nada se pierde. La red solo se nota en que el contador baja solo.
 */
@Component({
  selector: 'vd-pos',
  imports: [TranslateModule, FormsModule, MatButtonModule, MatIconModule],
  templateUrl: './pos.component.html',
  styleUrl: './pos.component.scss',
})
export class PosComponent implements OnInit {
  private readonly catalogo = inject(CatalogoLocalService);
  private readonly ventas = inject(VentasOfflineService);
  private readonly sincronizador = inject(SincronizadorService);
  private readonly notificador = inject(Notificador);
  private readonly traductor = inject(TranslateService);

  readonly consulta = signal('');
  readonly resultados = signal<ProductoLocal[]>([]);
  readonly lineas = signal<LineaTicket[]>([]);
  readonly total = computed(() => totalTicketCentavos(this.lineas()));

  readonly pendientes = this.sincronizador.pendientes;
  readonly enError = this.sincronizador.enError;
  readonly sincronizando = this.sincronizador.sincronizando;

  readonly catalogoVacio = signal(false);
  readonly medioPago = signal<'efectivo' | 'fiado'>('efectivo');
  readonly consultaCliente = signal('');
  readonly clientes = signal<ClienteLocal[]>([]);
  readonly cliente = signal<ClienteLocal | null>(null);
  readonly ultimaVenta = signal<VentaLocal | null>(null);
  readonly cobrando = signal(false);

  readonly formatear = formatearPesos;

  /** Total de línea con la misma regla del dominio: nunca la fórmula cruda en plantilla. */
  totalDeLinea(linea: LineaTicket): string {
    return formatearPesos(totalLineaCentavos(linea.precio_unitario_centavos, linea.cantidad_mili));
  }

  async ngOnInit(): Promise<void> {
    this.sincronizador.escucharConectividad();
    await this.sincronizador.recuperarEnviosInterrumpidos();
    await this.refrescarDatos();
  }

  /** El delta y los clientes bajan si hay red; si no, se trabaja con lo local. */
  private async refrescarDatos(): Promise<void> {
    try {
      await this.catalogo.refrescarDelta();
      await this.catalogo.cargarClientes();
    } catch {
      // Sin red: el catálogo y los clientes locales son la verdad de hoy.
    }
    this.catalogoVacio.set((await this.catalogo.contar()) === 0);
    await this.buscar('');
    await this.sincronizador.sincronizar();
  }

  async buscar(consulta: string): Promise<void> {
    this.consulta.set(consulta);
    this.resultados.set(await this.catalogo.buscar(consulta));
  }

  agregar(producto: ProductoLocal): void {
    this.lineas.update((lineas) => {
      const existente = lineas.find((l) => l.producto_id === producto.id);
      if (existente) {
        return lineas.map((l) =>
          l.producto_id === producto.id
            ? { ...l, cantidad_mili: l.cantidad_mili + MILI_POR_UNIDAD }
            : l,
        );
      }
      return [
        ...lineas,
        {
          producto_id: producto.id,
          nombre: producto.nombre,
          cantidad_mili: MILI_POR_UNIDAD,
          precio_unitario_centavos: producto.precio_venta,
        },
      ];
    });
  }

  /** Acepta coma o punto (el teclado de la tienda tiene las dos). */
  fijarCantidad(productoId: string, valor: string): void {
    const cantidad = Number(valor.replace(',', '.'));
    if (!Number.isFinite(cantidad) || cantidad <= 0) {
      return;
    }
    const mili = miliDeCantidad(cantidad);
    this.lineas.update((lineas) =>
      lineas.map((l) => (l.producto_id === productoId ? { ...l, cantidad_mili: mili } : l)),
    );
  }

  quitar(productoId: string): void {
    this.lineas.update((lineas) => lineas.filter((l) => l.producto_id !== productoId));
  }

  elegirMedioPago(medio: 'efectivo' | 'fiado'): void {
    this.medioPago.set(medio);
  }

  async buscarCliente(consulta: string): Promise<void> {
    this.consultaCliente.set(consulta);
    this.clientes.set(await this.catalogo.buscarClientes(consulta));
  }

  elegirCliente(cliente: ClienteLocal): void {
    this.cliente.set(cliente);
  }

  /** Alta en el mostrador: el cliente nace local y sube por la cola (FIFO). */
  async crearCliente(): Promise<void> {
    const nombre = this.consultaCliente().trim();
    if (nombre.length < 2) {
      return;
    }
    const cliente = await this.ventas.crearClienteLocal({ nombre, telefono: null });
    this.cliente.set(cliente);
    await this.buscarCliente('');
  }

  async cobrar(): Promise<void> {
    if (this.lineas().length === 0 || this.cobrando()) {
      return;
    }
    if (this.medioPago() === 'fiado' && !this.cliente()) {
      this.notificador.advertencia(this.traductor.instant('pos.fiado_sin_cliente'));
      return;
    }
    this.cobrando.set(true);
    try {
      const venta = await this.ventas.cobrar({
        lineas: this.lineas(),
        medio_pago: this.medioPago(),
        cliente: this.cliente(),
        fecha_vencimiento: null,
      });
      this.ultimaVenta.set(venta);
      this.lineas.set([]);
      this.cliente.set(null);
      this.medioPago.set('efectivo');
      this.notificador.exito(
        this.traductor.instant('pos.cobrada', { numero: venta.consecutivo_local }),
      );
      this.sincronizador.notificarVentaCobrada();
    } finally {
      this.cobrando.set(false);
    }
  }

  async reintentar(): Promise<void> {
    await this.sincronizador.reintentar();
  }
}
```

- [ ] **Paso 6: la plantilla.** Crear `frontend/projects/vendi-app/src/app/features/pos/pos.component.html`:

```html
<main class="pos">
  <header class="pos__barra">
    <h1 class="pos__titulo">{{ 'app.titulo' | translate }}</h1>
    <span class="pos__cola" [class.pos__cola--sucia]="pendientes() > 0">
      @if (sincronizando()) {
        {{ 'pos.sincronizando' | translate }}
      } @else {
        {{ 'pos.pendientes' | translate: { cantidad: pendientes() } }}
      }
    </span>
    @if (enError() > 0) {
      <span class="pos__errores">
        {{ 'pos.operaciones_en_error' | translate: { cantidad: enError() } }}
      </span>
    }
    <button mat-stroked-button type="button" (click)="reintentar()">
      {{ 'comun.reintentar' | translate }}
    </button>
  </header>

  @if (catalogoVacio()) {
    <p class="pos__aviso">{{ 'pos.catalogo_vacio' | translate }}</p>
  }

  <section class="pos__busqueda" aria-labelledby="buscar-producto">
    <label id="buscar-producto" for="consulta">{{ 'comun.buscar' | translate }}</label>
    <input
      id="consulta"
      type="search"
      [ngModel]="consulta()"
      (ngModelChange)="buscar($event)"
      [placeholder]="'pos.buscar_placeholder' | translate"
    />
    <ul class="pos__resultados">
      @for (producto of resultados(); track producto.id) {
        <li>
          <button type="button" class="pos__producto" (click)="agregar(producto)">
            <span>{{ producto.nombre }}</span>
            <span>{{ formatear(producto.precio_venta) }} / {{ producto.unidad_medida }}</span>
          </button>
        </li>
      }
    </ul>
  </section>

  <section class="pos__ticket" aria-labelledby="ticket-titulo">
    <h2 id="ticket-titulo">{{ 'pos.ticket' | translate }}</h2>
    @if (lineas().length === 0) {
      <p>{{ 'pos.ticket_vacio' | translate }}</p>
    }
    <ul>
      @for (linea of lineas(); track linea.producto_id) {
        <li class="pos__linea">
          <span class="pos__linea-nombre">{{ linea.nombre }}</span>
          <input
            type="text"
            inputmode="decimal"
            class="pos__linea-cantidad"
            [ngModel]="linea.cantidad_mili / 1000"
            (ngModelChange)="fijarCantidad(linea.producto_id, $event)"
            [attr.aria-label]="'pos.cantidad' | translate"
          />
          <span class="pos__linea-total">{{ totalDeLinea(linea) }}</span>
          <button
            mat-icon-button
            type="button"
            (click)="quitar(linea.producto_id)"
            [attr.aria-label]="'comun.eliminar' | translate"
          >
            <mat-icon>delete</mat-icon>
          </button>
        </li>
      }
    </ul>
    <p class="pos__total">{{ 'pos.total' | translate }}: {{ formatear(total()) }}</p>
  </section>

  <section class="pos__cobro" aria-labelledby="cobro-titulo">
    <h2 id="cobro-titulo">{{ 'pos.cobro' | translate }}</h2>
    <div class="pos__medios" role="group" [attr.aria-label]="'pos.medio_pago' | translate">
      <button
        mat-stroked-button
        type="button"
        [class.pos__medio--activo]="medioPago() === 'efectivo'"
        (click)="elegirMedioPago('efectivo')"
      >
        {{ 'pos.efectivo' | translate }}
      </button>
      <button
        mat-stroked-button
        type="button"
        [class.pos__medio--activo]="medioPago() === 'fiado'"
        (click)="elegirMedioPago('fiado')"
      >
        {{ 'pos.fiado' | translate }}
      </button>
    </div>

    @if (medioPago() === 'fiado') {
      <div class="pos__cliente">
        @if (cliente(); as elegido) {
          <p>{{ 'pos.fiado_a' | translate: { nombre: elegido.nombre } }}</p>
        } @else {
          <input
            type="search"
            [ngModel]="consultaCliente()"
            (ngModelChange)="buscarCliente($event)"
            [placeholder]="'pos.cliente_placeholder' | translate"
          />
          <ul>
            @for (opcion of clientes(); track opcion.id) {
              <li>
                <button type="button" (click)="elegirCliente(opcion)">{{ opcion.nombre }}</button>
              </li>
            }
          </ul>
          <button mat-stroked-button type="button" (click)="crearCliente()">
            {{ 'pos.cliente_nuevo' | translate }}
          </button>
        }
      </div>
    }

    <button
      mat-flat-button
      type="button"
      class="pos__cobrar"
      [disabled]="lineas().length === 0 || cobrando()"
      (click)="cobrar()"
    >
      {{ 'pos.cobrar' | translate: { total: formatear(total()) } }}
    </button>
  </section>

  @if (ultimaVenta(); as venta) {
    <p class="pos__ultima">
      {{ 'pos.ultima_venta' | translate: { numero: venta.consecutivo_local } }}
    </p>
  }
</main>
```

- [ ] **Paso 7: los estilos.** Crear `frontend/projects/vendi-app/src/app/features/pos/pos.component.scss` con un layout mínimo de una columna pensado para pantalla de teléfono (barra pegajosa arriba, resultados y ticket en flujo, botón de cobro grande al final). Sin diseño elaborado: es la entrega funcional; la capa visual llega con la pista de UX.

- [ ] **Paso 8: las claves de i18n.** En `frontend/projects/vendi-app/public/i18n/es.json`, añadir (y en el Paso 3 de la Tarea 9 se quita `proximamente`):

```json
  "pos": {
    "buscar_placeholder": "Buscar por nombre o código…",
    "ticket": "Ticket",
    "ticket_vacio": "Toca un producto para empezar la venta",
    "cantidad": "Cantidad",
    "total": "Total",
    "cobro": "Cobro",
    "medio_pago": "Medio de pago",
    "efectivo": "Efectivo",
    "fiado": "Fiado",
    "fiado_a": "Fiado a {{nombre}}",
    "fiado_sin_cliente": "Para fiar, elige o crea primero el cliente",
    "cliente_placeholder": "Buscar o escribir el nombre del cliente…",
    "cliente_nuevo": "Crear cliente con este nombre",
    "cobrar": "Cobrar {{total}}",
    "cobrada": "Venta #{{numero}} registrada",
    "ultima_venta": "Última venta: #{{numero}}",
    "pendientes": "{{cantidad}} por sincronizar",
    "sincronizando": "Sincronizando…",
    "operaciones_en_error": "{{cantidad}} con error (requieren revisión)",
    "catalogo_vacio": "El catálogo está vacío. Conéctate una vez para descargarlo."
  },
  "elegir_negocio": {
    "titulo": "¿Con qué negocio trabajas?",
    "cerrar_sesion": "Cerrar sesión"
  }
```

(verificar contra el html copiado de `vendi-tenant` las claves exactas que usa `elegir-negocio` y trasladar esas, no inventar otras.)

- [ ] **Paso 9: verificar en verde.**

```bash
cd frontend && npm run build:libs && npx ng test vendi-app --watch=false
# Esperado: verde, con los 6 specs nuevos del POS
npx ng lint vendi-app
# Esperado: sin errores
npx ng build vendi-app
# Esperado: build de desarrollo verde
```

- [ ] **Paso 10: commit**

```bash
git add frontend/projects/vendi-app
git commit -m "POS offline en vendi-app: catálogo local, ticket con granel, cobro efectivo/fiado y estado de la cola visible"
```

**Criterios de aceptación:** los 6 specs del POS pasan; el granel se cobra exacto con coma y con punto; el fiado sin cliente no escribe nada; el fiado con cliente local encola `cliente.crear` antes que la venta; el contador de pendientes refleja la cola; `vendi-app` compila y pasa lint con guards en las rutas.

---

## Tarea 9: Retiro oficial del spec-candado y de «próximamente», y la frontera `dexie` en `vendi-app`

**Files:**
- Delete: `frontend/projects/vendi-app/src/app/features/proximamente/` (3 archivos)
- Modify: `frontend/projects/vendi-app/src/app/app.spec.ts` (el candado se reemplaza por su inverso)
- Modify: `frontend/projects/vendi-app/public/i18n/es.json` (fuera el bloque `proximamente`)
- Modify: `frontend/projects/vendi-app/eslint.config.js` (el grupo prohibido gana `dexie`)

**Interfaces:**
- Consume: las rutas nuevas de la Tarea 8; el helper `fronteraDeCapa` de `frontend/eslint.fronteras.js`; el candado 3 de ADR-017 («el candado de fronteras ESLint verifica que `dexie` solo aparece en `data-access` — se amplía si el conjunto de reglas no lo cubre ya»: `vendi-app` era el único proyecto sin `dexie` en su grupo).
- Produce: el candado invertido (los guards son obligatorios), la frontera cerrada y la pantalla de Fase 0 retirada.

**Por qué ahora (la nota del retiro):** el candado de `app.spec.ts` («NO hay ninguna ruta protegida: la auth móvil es el subproyecto 2») existía para que nadie improvisara un login dentro del WebView que los passkeys no sobreviven. Este plan ES el subproyecto 2 en su alcance honesto (decisiones 1 y 10): llega con guards reales que funcionan en el navegador y en la PWA, sin improvisar nada en el WebView — la auth nativa queda registrada como D-29, no escondida en un login provisional. El candado cumplió y se retira; en su lugar queda el inverso, que protege lo nuevo.

- [ ] **Paso 1: el spec nuevo (candado invertido).** Reemplazar `frontend/projects/vendi-app/src/app/app.spec.ts`:

```ts
import { TestBed } from '@angular/core/testing';
import { authGuard, tenantGuard } from 'auth';
import { App } from './app';
import { routes } from './app.routes';

describe('App', () => {
  it('debería crearse', () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    expect(TestBed.createComponent(App).componentInstance).toBeTruthy();
  });
});

describe('vendi-app con POS (Etapa 1.3, subproyecto 2)', () => {
  // Este spec es el INVERSO del candado de Fase 0. Aquel prohibía guards para
  // que nadie improvisara un login dentro del WebView (los passkeys no
  // funcionan ahí). El subproyecto 2 llegó con el flujo WEB (passkey en el
  // navegador/PWA; la auth nativa es la deuda D-29), y ahora el candado
  // protege lo contrario: la ruta del POS exige sesión y tenant, y quien los
  // quite rompe este test.
  it('la ruta del POS exige sesión y tenant', () => {
    const pos = routes.find((r) => r.path === '');
    expect(pos?.canActivate).toEqual([authGuard, tenantGuard]);
  });

  it('/elegir-negocio NO lleva tenantGuard (sería un bucle de redirección)', () => {
    const elegir = routes.find((r) => r.path === 'elegir-negocio');
    expect(elegir?.canActivate).toEqual([authGuard]);
  });

  it('cualquier ruta desconocida cae en el POS, no en blanco', () => {
    const comodin = routes.find((r) => r.path === '**');
    expect(comodin?.redirectTo).toBe('');
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test vendi-app --watch=false
# Esperado: verde con el candado invertido (y los specs del POS de la Tarea 8)
```

- [ ] **Paso 2: retirar la pantalla «próximamente».** Borrar `frontend/projects/vendi-app/src/app/features/proximamente/` y, en `frontend/projects/vendi-app/public/i18n/es.json`, quitar el bloque `"proximamente"` completo. Verificar que ninguna cadena suya sobrevive:

```bash
grep -rn "proximamente" frontend/projects/vendi-app/src frontend/projects/vendi-app/public || echo "limpio"
# Esperado: limpio
```

- [ ] **Paso 3: la frontera `dexie` en `vendi-app`.** En `frontend/projects/vendi-app/eslint.config.js`, tocar SOLO los dos primeros argumentos de la llamada a `fronteraDeCapa` (el tercero — el array de selectores de ADR-004 — queda intacto, sin moverle una coma):

```js
    rules: fronteraDeCapa(
      ['@capacitor/*', 'dexie'],
      'ADR-011/ADR-017: `native` es el único punto autorizado a importar @capacitor/* y `data-access` el único autorizado a importar dexie — IndexedDB es la verdad local y la app la consume por los servicios offline de data-access (VendiDb, VentasOfflineService, SincronizadorService, CatalogoLocalService), nunca por el motor a pelo.',
```

- [ ] **Paso 4: probar la frontera (sonda obligatoria).** Añadir temporalmente `import Dexie from 'dexie';` al principio de `frontend/projects/vendi-app/src/app/features/pos/pos.component.ts` y comprobar que el lint lo rechaza con el mensaje de la frontera; revertir:

```bash
cd frontend && npx ng lint vendi-app
# Esperado: error no-restricted-imports con el mensaje ADR-011/ADR-017
# (revertir la línea de la sonda tras verificarlo)
npx ng lint vendi-app
# Esperado: sin errores
grep -rn "from 'dexie'" frontend/projects --include="*.ts" | grep -v "libs/data-access" || echo "dexie solo en data-access"
# Esperado: dexie solo en data-access
```

- [ ] **Paso 5: verificar el workspace completo.**

```bash
cd frontend && npm run build:libs && npx ng test --watch=false
# Esperado: verde en los 9 proyectos
npx ng lint
# Esperado: sin errores en los 9 proyectos
npm run format:check
# Esperado: sin diferencias (si prettier marca los archivos nuevos: npm run format)
```

- [ ] **Paso 6: commit**

```bash
git add frontend/projects/vendi-app
git commit -m "Spec-candado retirado con el subproyecto 2: guards obligatorios en el POS, pantalla próximamente fuera y dexie vedado en vendi-app"
```

**Criterios de aceptación:** el candado invertido pasa y falla si se quita un guard (probarlo una vez quitando `tenantGuard` de la ruta y viendo el rojo, y restaurar); `proximamente` no deja rastro; la sonda de `dexie` rompe el lint con el mensaje de la frontera; los 9 proyectos verdes en test y lint.

---

## Tarea 10: Cierre — gate de la Etapa 1.3 (pista móvil), `docs/estado.md` y deuda D-29

**Files:**
- Modify: `docs/estado.md` (sección nueva del POS offline, con fecha de corte y evidencia comando+salida)
- Modify: `docs/deuda-tecnica.md` (D-29 nueva; D-27 y D-28 quedan como están — este plan no las cierra ni depende de ellas)

**NO se toca:** `.github/workflows/android.yml` (sigue construyendo el AAB igual), `docs/api/openapi-fase0.json` (el contrato está congelado y este plan no añade rutas), el backend entero.

- [ ] **Paso 1: ejecutar el gate completo de la pista móvil:**

```bash
cd frontend
npm ci --no-audit --no-fund
npm run build:libs
npx ng test --watch=false
# Esperado: verde en los 9 proyectos; los specs nuevos de offline corren (data-access, domain, vendi-app)
npx ng lint
# Esperado: sin errores en los 9 proyectos (fronteras incluidas)
npm run format:check
# Esperado: sin diferencias
npx ng build vendi-app --configuration production
# Esperado: build de producción verde
grep -rE "localhost:[0-9]{4}|environment\.development" dist/vendi-app/browser || echo "sin URLs de desarrollo"
# Esperado: sin URLs de desarrollo (el candado que android.yml aplica al AAB)
cd ..
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git diff --exit-code
# Esperado: salida 0 — el contrato no se tocó y el cliente generado no deriva
```

Gate de la pista (del plan maestro §Etapa 1.3), a verificar ítem a ítem:
- [ ] `ng test` verde en los 9 proyectos con los specs nuevos por feature (offline en `data-access`, dinero en `domain`, POS en `vendi-app`).
- [ ] Los candados firmados de ADR-017: la cola sobrevive a la recarga y drena en orden (Tarea 6, specs 7 y 1); la frontera ESLint verifica que `dexie` solo aparece en `data-access` (Tarea 9, sonda incluida); el spike de Dexie corrió primero (Tarea 1).
- [ ] Los candados de ADR-018: dinero en enteros con aritmética exacta (Tarea 3), `consecutivo_local` monotónico por dispositivo que sobrevive a la recarga (Tarea 4).
- [ ] El E2E Playwright del flujo de dinero queda para el gate posterior con el stack levantado (decisión del encargo: NO es de esta entrega).
- [ ] Budgets de bundle no relajados; `android.yml` sin cambios.

- [ ] **Paso 2: actualizar `docs/estado.md`.** Añadir una sección «POS offline-first en vendi-app (Fase 1, Etapa 1.3, pista móvil)» con: fecha de corte, qué se entregó (Dexie encapsulado en `data-access` con el esquema v1; el outbox local atómico; el motor de drenado FIFO con backoff y dead-letters; el registro del dispositivo; el delta al IndexedDB con tumbas; la aritmética exacta del ticket; el POS con cobro efectivo/fiado, fiado solo con cliente y `cliente.crear` FIFO; el spec-candado retirado y reemplazado por su inverso; la frontera `dexie` cerrada en `vendi-app`), el alcance honesto (auth nativa fuera → D-29; canal del piloto = PWA; sin anulación, sin escáner, sin `fecha_vencimiento` en el fiado), y **al lado de cada afirmación el comando que la demuestra** con su salida pegada (regla del documento: no promete nada que un comando no demuestre).

- [ ] **Paso 3: registrar D-29 en `docs/deuda-tecnica.md`.**

```markdown
| D-29 | La auth nativa de vendi-app (login por navegador del sistema: @capacitor/browser + esquema co.vendi.app:// + asset links para passkeys) no existe: la app autentica con el flujo WEB y el canal del piloto es la PWA instalada; el AAB nativo sigue siendo artefacto de CI | Fase 1 (antes del piloto nativo) | frontend |
```

Con el detalle del formato del documento: qué es (el plan maestro pedía auth por navegador del sistema en la Etapa 1.3; se entregó el POS completo con el flujo web y se dejó lo nativo para su propio subproyecto), por qué se aceptó (el flujo nativo exige deep-links, asset links y pruebas en dispositivo que no son TDD-ables en CI; la PWA cubre passkey + assets + IndexedDB), riesgo si se olvida (el AAB instalado no puede iniciar sesión: el login redirige dentro del WebView y el passkey falla; nadie debe repartir el AAB del CI como «la app»), vencimiento (antes del piloto nativo / publicación — depende de B-3), candados mientras tanto (el spec de `app.routes` fija los guards; la sección de `estado.md` declara la PWA como canal).

- [ ] **Paso 4: commit de cierre**

```bash
git add docs/estado.md docs/deuda-tecnica.md
git commit -m "Pista móvil de la Etapa 1.3 cerrada: POS offline-first en vendi-app con evidencia en estado y D-29 registrada"
```

---

## Superficie de ataque para QA — POS offline-first (cola, drenado, dinero, fiado, auth)

Para el agente de QA adversarial de la Etapa 1.4 (agente distinto del implementador; su KPI son hallazgos). Los escenarios marcados (firmado) ya tienen test que los fija: verificarlos, no «redescubrirlos»; el hallazgo sería que el test miente. Todo lo que diga «con el stack» exige el backend levantado: son candidatos naturales del E2E del flujo de dinero.

- **La cola:** matar la PWA a mitad del drenado (las `enviando` vuelven a `pendiente` al arrancar — firmado; provocarlo de verdad cerrando la pestaña a mitad de un POST con el stack); dos cobros en el mismo milisegundo (consecutivo y secuencia no se pisan: una sola transacción — intentar provocar la carrera con dos clicks sincronizados; el botón se deshabilita con `cobrando`, verificar que no hay atajo por teclado); 201 operaciones pendientes (lotes de 200 + 1 — verificar con el stack que el segundo lote sale); la cola sobrevive a la recarga (firmado en fake-indexeddb; repetir en Chrome real recargando la PWA offline); reloj del dispositivo adelantado/atrasado (`creada_en_cliente` miente y el servidor lo acepta como dato: la venta no se rompe ni se reordena — con el stack, verificar que `recibida_en` es la verdad y que el backoff no se dispara a años por un reloj loco: `Date.now()` manipulado); borrar el IndexedDB con la cola llena (las ventas locales se pierden — es el límite físico del diseño, no un bug: verificar que el mensaje de «por sincronizar» desaparece y que el servidor nunca las recibe; documentar).
- **El drenado:** respuestas mixtas `aceptada`/`duplicada`/`rechazada` en un lote (firmado); la `rechazada` no bloquea el FIFO (firmado); timeout tras POST que el servidor SÍ procesó (el reenvío vuelve `duplicada` y no duplica venta ni stock ni evento — con el stack, cortando el proxy a mitad de respuesta); 5xx con backoff creciente 5s→10s→20s (firmado con fake timers; verificar el tope de 5 min); token expirado a mitad del drenado (401: ¿cae al backoff como error de transporte? el interceptor no renueva y el refresco de `AuthService` no corre en segundo plano — fijar el comportamiento real y, si el sync queda mudo hasta recargar, registrarlo); `X-Tenant-Id` y `Bearer` presentes en lotes/delta/dispositivos (firmado por el interceptor; verificar con el stack y dos tenants que cada dispositivo solo drena en el suyo); dos pestañas de la PWA a la vez (DOS instancias de Dexie sobre la misma base, dos drenajes concurrentes: ¿doble envío del mismo lote? el servidor responde `duplicada` y no pasa nada — verificar con el stack; si las dos pestañas cobran a la vez, ¿se pisan el consecutivo? IndexedDB serializa las transacciones `rw`, pero entre pestañas no hay garantía de lectura-escritura atómica del contador: PROVOCARLO y, si se pisa, registrarlo como hallazgo con su vencimiento — una tienda = una pestaña es la operación esperada, pero el diseño no lo impone).
- **El dinero y el granel:** 0,333 kg a $10,00/kg (333 exactos — firmado); 2,5 kg a $19,99 (4998 half-up — firmado); cantidad con coma (`0,333` — firmado); cantidad 0, negativa, vacía, con letras (la UI la ignora — verificar que no queda línea a 0); precio 0 (venta de total 0: el backend la acepta — verificar con el stack); totales grandes (firmado hasta ~10^12); el total del ticket es suma de líneas redondeadas, no redondeo del total (firmado: la discrepancia de un centavo entre las dos reglas es el hallazgo si alguien la «corrige»).
- **El consecutivo:** monotónico por dispositivo y sobrevive a la recarga (firmado); dos dispositivos del mismo negocio repiten número (por diseño, ADR-018: el identificador público es dispositivo+consecutivo — verificar con el stack que ambas ventas coexisten y que el reporte no las confunde); la UI muestra solo el número, sin dispositivo (alcance declarado: en multi-caja el tendero distingue por caja física; si el piloto lo pide, vendrá con su decisión).
- **El catálogo:** delta con tumbas (firmado); watermark persistente y reutilizado (firmado); producto editado en el servidor llega al dispositivo en el siguiente refresco (LWW por orden de recepción — con el stack); el mismo producto editado en dos frentes (servidor y… solo servidor: la app no edita catálogo; el conflicto LWW de verdad es de la Etapa 1.4 entre web y delta); primer arranque sin red con catálogo vacío (mensaje honesto y ningún crash — firmado el estado, verificar la UX real); producto con `precio_venta` 0 o nombre de 160 caracteres en la búsqueda (no rompe el render — verificar).
- **El fiado:** fiar a cliente creado en el mostrador antes de sincronizar nada (`cliente.crear` precede a la venta en el lote — firmado; con el stack verificar que el crédito nace en el servidor); fiar sin cliente (bloqueado en UI y en servicio — firmado); cliente creado en OTRA caja llega solo online por `GET /clientes` (rodeo de D-28 — con el stack: caja A crea offline, caja B sin red NO lo ve, con red lo asimila); venta fiada sin su `cliente.crear` (rechazada o auto-alta placeholder según el backend — con el stack, provocándola por REST); `cupo_excedido` del servidor viaja en `detalles` de la aceptada y el POS NO lo muestra (alcance declarado: vive en el cuaderno web — verificar que la consola lo muestra y anotar la tensión); fiado sin `fecha_vencimiento` (nace sin recordatorio, ADR-022 — con el stack verificar que el trabajo diario no lo toca).
- **Auth y PWA:** passkey en Chrome Android con la PWA instalada (el canal del piloto — verificación manual con el stack); token expirado con la app offline (las ventas se encolan igual — la venta no depende del internet — y el sync espera al próximo login: verificar y fijar); dueño con dos negocios (selector — firmado el guard; verificar que cada tenant drena su propio catálogo y cola: ¡la base local NO se particiona por tenant! Cambiar de tenant con la misma base mezcla catálogos — HALLAZGO PROBABLE: fijar el comportamiento real y, si la cola del tenant A se drena con el token del tenant B, el servidor rechaza por permiso/RLS y queda dead-letter: documentar la curación); el AAB nativo del CI no puede loguear (D-29 declarada — verificar que NADIE lo reparte como app del piloto).
- **Fronteras:** `import ... from 'dexie'` fuera de `data-access` (lint rojo — firmado con sonda en `vendi-app`); `import('dexie')` dinámico (lo cubre el `no-restricted-syntax` del helper — verificar con sonda); `require('dexie')` (ídem); el build de las tres apps web no arrastra Dexie al bundle (revisar el análisis de chunks: si `dexie` aparece en el bundle de `vendi-portal`, algo rompió el tree-shaking — verificar).

---

## Self-Review

- **Cobertura del spec:** ADR-017 (Dexie encapsulado en `data-access`, spike primero, ids del dispositivo, cola con outbox en espejo, FIFO por secuencia con backoff, delta con watermark, candados de recarga+orden y de frontera ESLint) → Tareas 1, 2, 4, 5, 6, 7, 9. ADR-018 (venta append-only con id del dispositivo, `consecutivo_local` monotónico, dinero en enteros, granel de 3 decimales, fiado sin red, multi-caja, reloj del cliente como dato, sesión resuelta por el servidor) → Tareas 3, 4 + decisiones 2 y 6. ADR-011 (fronteras mecánicas; `dexie` vedado fuera de `data-access` en los 9 proyectos) → Tarea 9 + verificación global. ADR-009 (el fiado se lleva por persona) → Tarea 4 (fiado sin cliente no escribe) + Tarea 8. Plan maestro §Etapa 1.3 pista móvil (spike + cola primero, POS después, candado retirado con el subproyecto 2, gate de 9 proyectos) → Tareas 1-10. Encargo (los 6 puntos: fundación offline, registro, POS, retiro del candado, tests de los 5 candados, sin E2E obligatorio pero 9 proyectos verdes y `android.yml` intacto) → Tareas 2-7, 5, 8, 9, 3/4/6/7 y 10 respectivamente. D-27 (abonos offline) → NO se depende de ella: los abonos no entran al POS de esta entrega. D-28 (sin delta de clientes) → rodeada por diseño en Tarea 7 + decisión 4.
- **Placeholders:** ninguno. Todo paso lleva código completo, comando exacto y salida esperada; los dos únicos «copiar de» (Paso 1 y Paso 3 de la Tarea 8: `nucleo/sesion.ts` y `elegir-negocio`) nombran el archivo fuente exacto y los cambios exactos a aplicar. Los conteos de specs son los escritos (3 de `VendiDb`, 8 de dinero, 8 del outbox, 5 del registro, 8 del drenado, 5 del catálogo, 6 del POS, 4 del candado invertido); si el ejecutor añade casos, ajusta el número (los comandos de gate son de suite, no de conteo).
- **Consistencia de tipos/contratos:** los shapes encolados se verificaron contra el backend real: `VentaCrearSync` (`ventas/schemas.py:104`: `consecutivo_local`, `estado`, `medio_pago`, `total_centavos`, `cliente_id`, `fecha_vencimiento`, `creada_en_cliente`, `items[{producto_id, cantidad, precio_unitario_centavos}]`) y `ClienteCrearSync` (`fiado/schemas.py:78`, `extra="forbid"`, `nombre` min 2) coinciden campo a campo con los `datos` de las Tareas 4 y 6 y con los asertos de sus specs; los tipos de los contratos salen del cliente generado (`paths[...]`) y no se redeclaran; `OperacionSync.id` = PK de la entidad en ambos tipos de operación; el estado `enviando` se recupera al arrancar (Tarea 6 y `ngOnInit` del POS, Tarea 8) — los dos puntos de entrada están cubiertos; el `desde` del delta y el `hasta` watermark usan el formato `date-time` del contrato (la marca inicial `1970-01-01T00:00:00.000Z` es ISO 8601 válida); el límite del lote (200) es el `maxItems` del schema; los motivos estables usados en specs (`venta_id_divergente`, `permiso_ausente`) existen en el backend.
- **Riesgos conocidos y declarados:** (1) la auth nativa no existe — D-29 con vencimiento piloto nativo; el AAB del CI no es repartible como app; (2) `fake-indexeddb` emula IndexedDB, no ES IndexedDB — los candados de recarga pasan sobre la emulación y la verificación en navegador real queda explícitamente en la superficie de QA; (3) la base local NO se particiona por tenant: un dueño con dos negocios comparte catálogo y cola en el mismo IndexedDB — queda en la superficie de QA como hallazgo probable con su curación documentada (la RLS del servidor es la red final: drenar con el tenant equivocado produce dead-letters, no fugas); (4) dos pestañas de la PWA no coordinan el consecutivo — en la superficie de QA, con la operación esperada (una pestaña por caja) declarada; (5) el `cupo_excedido` no se muestra en el POS (vive en el cuaderno web) — declarado en decisión 4 y superficie; (6) el fiado nace sin `fecha_vencimiento` en esta entrega (sin recordatorio, ADR-022 lo permite) — declarado; (7) un 409 de registro de dispositivo bloquea el sync hasta intervención humana — decisión 9, sin autocuración a propósito; (8) borrar el IndexedDB pierde las ventas no sincronizadas — límite físico del diseño offline-first, en la superficie de QA para documentación al piloto.
