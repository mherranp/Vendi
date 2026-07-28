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
// invoque el script, y carga las builds CJS de ambos paquetes. El orden
// importa: Dexie captura el global indexedDB al evaluarse el módulo, así que
// fake-indexeddb/auto se carga ANTES que dexie.
const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
require('fake-indexeddb/auto');
const Dexie = require('dexie');

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
