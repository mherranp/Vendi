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
        id: 'b',
        tipo: 'venta.crear',
        secuencia: 2,
        datos: {},
        estado: 'pendiente',
        intentos: 0,
        proximo_intento_en: 0,
        ultimo_error: null,
        creada_en: 1,
      },
      {
        id: 'a',
        tipo: 'venta.crear',
        secuencia: 1,
        datos: {},
        estado: 'pendiente',
        intentos: 0,
        proximo_intento_en: 0,
        ultimo_error: null,
        creada_en: 1,
      },
      {
        id: 'c',
        tipo: 'venta.crear',
        secuencia: 3,
        datos: {},
        estado: 'error',
        intentos: 2,
        proximo_intento_en: 0,
        ultimo_error: 'venta_id_divergente',
        creada_en: 1,
      },
    ]);
    const pendientes = await db.cola_sync.where('estado').equals('pendiente').sortBy('secuencia');
    expect(pendientes.map((op) => op.id)).toEqual(['a', 'b']);
  });
});
