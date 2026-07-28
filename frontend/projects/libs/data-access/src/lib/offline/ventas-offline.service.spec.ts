import 'fake-indexeddb/auto';
import { TestBed } from '@angular/core/testing';
import { VendiDb } from './vendi.db';
import { VentasOfflineService } from './ventas-offline.service';

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
    await servicio.cobrar({
      lineas: LINEAS,
      medio_pago: 'efectivo',
      cliente: null,
      fecha_vencimiento: null,
    });
    await servicio.cobrar({
      lineas: LINEAS,
      medio_pago: 'efectivo',
      cliente: null,
      fecha_vencimiento: null,
    });
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
    db.cola_sync.add = (() => Promise.reject(new Error('fallo simulado'))) as never;

    await expect(
      servicio.cobrar({
        lineas: LINEAS,
        medio_pago: 'efectivo',
        cliente: null,
        fecha_vencimiento: null,
      }),
    ).rejects.toThrow('fallo simulado');

    expect(await db.ventas_locales.count()).toBe(0);
    expect(await db.meta.get('consecutivo_local')).toBeUndefined();
  });

  it('el fiado exige cliente: sin él no hay venta ni operación', async () => {
    const { servicio, db } = preparar();
    await expect(
      servicio.cobrar({
        lineas: LINEAS,
        medio_pago: 'fiado',
        cliente: null,
        fecha_vencimiento: null,
      }),
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
    const cliente = await servicio.crearClienteLocal({
      nombre: 'Doña Ana',
      telefono: '3001234567',
    });
    const enCola = await db.cola_sync.get(cliente.id);
    expect(enCola?.datos).toEqual({ nombre: 'Doña Ana', telefono: '3001234567' });
  });

  it('dos cobros en paralelo NO pisan el consecutivo ni la secuencia (QA adversarial)', async () => {
    const { servicio, db } = preparar();
    const entrada = {
      lineas: LINEAS,
      medio_pago: 'efectivo' as const,
      cliente: null,
      fecha_vencimiento: null,
    };

    // Dos toques de cobrar «a la vez»: las transacciones rw de Dexie sobre las
    // mismas tablas se serializan, así que el segundo cobro lee los contadores
    // ya avanzados por el primero.
    const [a, b] = await Promise.all([servicio.cobrar(entrada), servicio.cobrar(entrada)]);

    expect([a.consecutivo_local, b.consecutivo_local].sort()).toEqual([1, 2]);
    expect(await db.ventas_locales.count()).toBe(2);
    const secuencias = (await db.cola_sync.toArray()).map((op) => op.secuencia).sort();
    expect(secuencias).toEqual([1, 2]);
    expect((await db.meta.get('consecutivo_local'))?.valor).toBe(2);
    expect((await db.meta.get('ultima_secuencia'))?.valor).toBe(2);
  });

  it('rechaza nombres de cliente que el servidor rechazaría (min 2)', async () => {
    const { servicio } = preparar();
    await expect(servicio.crearClienteLocal({ nombre: 'A', telefono: null })).rejects.toThrow();
    await expect(servicio.crearClienteLocal({ nombre: '   ', telefono: null })).rejects.toThrow();
  });
});
