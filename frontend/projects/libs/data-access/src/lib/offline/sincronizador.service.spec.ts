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

/**
 * El drenado lee la cola en Dexie antes de disparar el POST, así que la
 * petición HTTP no existe aún en el mismo tick: hay que ceder el control hasta
 * que llegue (mismo patrón que el spec de DispositivoService). `match` no
 * falla cuando no hay coincidencia, lo que permite sondear tick a tick.
 */
async function esperarPeticion(http: HttpTestingController, url: string) {
  for (let intento = 0; intento < 50; intento += 1) {
    const [encontrada] = http.match(url);
    if (encontrada) {
      return encontrada;
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error(`No llegó la petición a ${url}`);
}

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

async function cobrarUna(ventas: VentasOfflineService): Promise<string> {
  return (
    await ventas.cobrar({
      lineas: LINEA,
      medio_pago: 'efectivo',
      cliente: null,
      fecha_vencimiento: null,
    })
  ).id;
}

async function cobrarTres(ventas: VentasOfflineService): Promise<string[]> {
  const ids: string[] = [];
  for (let n = 0; n < 3; n++) {
    ids.push(
      (
        await ventas.cobrar({
          lineas: LINEA,
          medio_pago: 'efectivo',
          cliente: null,
          fecha_vencimiento: null,
        })
      ).id,
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
    const req = await esperarPeticion(http, '/api/v1/sync/lotes');
    expect(req.request.method).toBe('POST');
    const cuerpo = req.request.body as {
      dispositivo_id: string;
      operaciones: { id: string; secuencia: number }[];
    };
    expect(cuerpo.dispositivo_id).toBe('dispositivo-de-prueba');
    expect(cuerpo.operaciones.map((op) => op.id)).toEqual(ids);
    expect(cuerpo.operaciones.map((op) => op.secuencia)).toEqual([1, 2, 3]);
    req.flush({
      resultados: ids.map((id) => ({
        id,
        tipo: 'venta.crear',
        resultado: 'aceptada',
        motivo: null,
        detalles: null,
      })),
    });
    await promesa;

    expect(await db.cola_sync.count()).toBe(0);
    expect(sync.pendientes()).toBe(0);
  });

  it('aplica el veredicto por operación: aceptada y duplicada salen; rechazada queda como dead-letter', async () => {
    const ids = await cobrarTres(ventas);
    const promesa = sync.sincronizar();
    (await esperarPeticion(http, '/api/v1/sync/lotes')).flush({
      resultados: [
        { id: ids[0], tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
        { id: ids[1], tipo: 'venta.crear', resultado: 'duplicada', motivo: null, detalles: null },
        {
          id: ids[2],
          tipo: 'venta.crear',
          resultado: 'rechazada',
          motivo: 'venta_id_divergente',
          detalles: { campos: ['total_centavos'] },
        },
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
    (await esperarPeticion(http, '/api/v1/sync/lotes')).flush({
      resultados: [
        {
          id: ids[0],
          tipo: 'venta.crear',
          resultado: 'rechazada',
          motivo: 'permiso_ausente',
          detalles: null,
        },
        { id: ids[1], tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
        { id: ids[2], tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
      ],
    });
    await promesa;

    // Nueva venta tras el dead-letter: drena sola, sin arrastrar la rechazada.
    const cuarta = await ventas.cobrar({
      lineas: LINEA,
      medio_pago: 'efectivo',
      cliente: null,
      fecha_vencimiento: null,
    });
    promesa = sync.sincronizar();
    const req = await esperarPeticion(http, '/api/v1/sync/lotes');
    const cuerpo = req.request.body as { operaciones: { id: string }[] };
    expect(cuerpo.operaciones.map((op) => op.id)).toEqual([cuarta.id]);
    req.flush({
      resultados: [
        { id: cuarta.id, tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
      ],
    });
    await promesa;
    expect(sync.pendientes()).toBe(0);
    expect(sync.enError()).toBe(1);
  });

  it('ante un 5xx reprograma TODO el lote con backoff y reintenta al vencerse', async () => {
    // Solo se congela setTimeout/Date: setImmediate queda real porque
    // fake-indexeddb agenda sus operaciones con él (si se congela, Dexie no
    // avanza jamás). El backoff del servicio usa setTimeout, que sí se finge.
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    try {
      const ids = await cobrarTres(ventas);
      const promesa = sync.sincronizar();
      const primer = await vi.waitFor(() => http.expectOne('/api/v1/sync/lotes'));
      primer.flush('Error interno', { status: 500, statusText: 'Error' });
      await promesa;

      const ops = await db.cola_sync.toArray();
      expect(ops.every((op) => op.estado === 'pendiente' && op.intentos === 1)).toBe(true);
      expect(ops.every((op) => op.proximo_intento_en >= Date.now() + ESPERA_BASE_MS)).toBe(true);
      expect(sync.pendientes()).toBe(3);

      // Al vencerse el backoff, el temporizador dispara el reintento solo.
      const avance = vi.advanceTimersByTimeAsync(ESPERA_BASE_MS + 100);
      const req = await vi.waitFor(() => http.expectOne('/api/v1/sync/lotes'));
      req.flush({
        resultados: ids.map((id) => ({
          id,
          tipo: 'venta.crear',
          resultado: 'aceptada',
          motivo: null,
          detalles: null,
        })),
      });
      await avance;
      // La respuesta viaja por microtareas hasta la transacción de Dexie:
      // se espera el drenado en vez de un solo tick, para no correrlo.
      await vi.waitFor(async () => {
        expect(await db.cola_sync.count()).toBe(0);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('un drenado parcial exitoso reprograma el reintento de lo que quedó pendiente (BUG-C)', async () => {
    // Solo se congela setTimeout/Date: fake-indexeddb agenda con setImmediate.
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    try {
      const a = await cobrarUna(ventas);
      const b = await cobrarUna(ventas);
      // B ya intentó 3 veces: su próximo backoff es de 40 s, el de A de 5 s.
      await db.cola_sync.update(b, { intentos: 3 });

      const primer = sync.sincronizar();
      (await vi.waitFor(() => http.expectOne('/api/v1/sync/lotes'))).error(
        new ProgressEvent('error'),
      );
      await primer;
      expect((await db.cola_sync.get(a))?.intentos).toBe(1); // +5 s
      expect((await db.cola_sync.get(b))?.intentos).toBe(4); // +40 s

      // A los 5 s drena A SOLA (B no es elegible): lote parcial exitoso.
      const avance1 = vi.advanceTimersByTimeAsync(ESPERA_BASE_MS + 100);
      const reqA = await vi.waitFor(() => http.expectOne('/api/v1/sync/lotes'));
      expect(
        (reqA.request.body as { operaciones: { id: string }[] }).operaciones.map((op) => op.id),
      ).toEqual([a]);
      reqA.flush({
        resultados: [
          { id: a, tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
        ],
      });
      await avance1;
      // La respuesta viaja por microtareas hasta la transacción de Dexie:
      // se espera el drenado en vez de un solo tick, para no correrlo.
      await vi.waitFor(async () => {
        expect(await db.cola_sync.get(a)).toBeUndefined();
      });
      expect((await db.cola_sync.get(b))?.estado).toBe('pendiente');

      // BUG-C: sin el reintento programado tras el drenado parcial, B no sube
      // sola jamás. Con él, al vencerse SU backoff (40 s) sale sin que nadie
      // la rescate (ni cobro nuevo, ni evento online, ni botón manual).
      const avance2 = vi.advanceTimersByTimeAsync(40_000);
      const reqB = await vi.waitFor(() => http.expectOne('/api/v1/sync/lotes'));
      expect(
        (reqB.request.body as { operaciones: { id: string }[] }).operaciones.map((op) => op.id),
      ).toEqual([b]);
      reqB.flush({
        resultados: [
          { id: b, tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
        ],
      });
      await avance2;
      await vi.waitFor(async () => {
        expect(await db.cola_sync.count()).toBe(0);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('una operación que el servidor OMITE de resultados queda en error, no enviando eterna', async () => {
    const ids = [await cobrarUna(ventas), await cobrarUna(ventas)];
    const promesa = sync.sincronizar();
    // Respuesta fuera de contrato: el servidor solo devuelve UN resultado.
    (await esperarPeticion(http, '/api/v1/sync/lotes')).flush({
      resultados: [
        { id: ids[0], tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
      ],
    });
    await promesa;

    expect(await db.cola_sync.get(ids[0])).toBeUndefined();
    const omitida = await db.cola_sync.get(ids[1]);
    // Dead-letter visible: ni `enviando` congelada ni `pendiente` en bucle.
    expect(omitida?.estado).toBe('error');
    expect(omitida?.ultimo_error).toBe('omitida_en_resultados');
    expect(sync.enError()).toBe(1);
  });

  it('el registro sin red NO entra en bucle caliente: lleva su propio backoff (BUG-D)', async () => {
    // Solo se congela setTimeout/Date: fake-indexeddb agenda con setImmediate.
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    try {
      await cobrarUna(ventas); // pendiente fresca: proximo_intento_en = 0
      const registro = vi
        .spyOn(TestBed.inject(DispositivoService), 'asegurarRegistro')
        .mockRejectedValue(new Error('sin red'));

      await sync.sincronizar();
      expect(registro).toHaveBeenCalledTimes(1);

      // BUG-D: el reintento heredaba el mínimo crudo de la cola (0) y
      // martilleaba el registro 102 veces en 100 ms. Con su propio backoff,
      // en 100 ms NO hay un segundo intento.
      await vi.advanceTimersByTimeAsync(100);
      expect(registro).toHaveBeenCalledTimes(1);

      // Al vencerse el primer backoff (5 s) sí reintenta — una sola vez más.
      await vi.advanceTimersByTimeAsync(ESPERA_BASE_MS + 100);
      await vi.waitFor(() => {
        expect(registro).toHaveBeenCalledTimes(2);
      });

      // Y el backoff CRECE: el tercer intento no llega en otros 5 s, sino en 10.
      await vi.advanceTimersByTimeAsync(ESPERA_BASE_MS + 100);
      expect(registro).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(ESPERA_BASE_MS + 100);
      await vi.waitFor(() => {
        expect(registro).toHaveBeenCalledTimes(3);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('un error de red se trata como el 5xx: nada sale de la cola', async () => {
    const ids = await cobrarTres(ventas);
    const promesa = sync.sincronizar();
    (await esperarPeticion(http, '/api/v1/sync/lotes')).error(new ProgressEvent('error'));
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
    const req = await esperarPeticion(http, '/api/v1/sync/lotes');
    const cuerpo = req.request.body as { operaciones: { id: string }[] };
    expect(cuerpo.operaciones.map((op) => op.id)).toEqual(ids);
    req.flush({
      resultados: ids.map((id) => ({
        id,
        tipo: 'venta.crear',
        resultado: 'aceptada',
        motivo: null,
        detalles: null,
      })),
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
    const req = await esperarPeticion(http2, '/api/v1/sync/lotes');
    expect(
      (req.request.body as { operaciones: { id: string }[] }).operaciones.map((op) => op.id),
    ).toEqual(ids);
    req.flush({
      resultados: ids.map((id) => ({
        id,
        tipo: 'venta.crear',
        resultado: 'aceptada',
        motivo: null,
        detalles: null,
      })),
    });
    await promesa;
    expect(await reabierta.cola_sync.count()).toBe(0);
    http2.verify();
    await reabierta.delete();
  });

  it('el reintento manual adelanta las pendientes sin tocar los dead-letters', async () => {
    await cobrarTres(ventas);
    await db.cola_sync.where('secuencia').equals(1).modify({
      estado: 'error',
      ultimo_error: 'venta_id_divergente',
    });
    await db.cola_sync
      .where('estado')
      .equals('pendiente')
      .modify({
        proximo_intento_en: Date.now() + 3_600_000,
      });

    const promesa = sync.reintentar();
    const req = await esperarPeticion(http, '/api/v1/sync/lotes');
    const cuerpo = req.request.body as { operaciones: { secuencia: number }[] };
    expect(cuerpo.operaciones.map((op) => op.secuencia)).toEqual([2, 3]);
    req.flush({
      resultados: cuerpo.operaciones.map((op) => ({
        id: 'x',
        tipo: 'venta.crear',
        resultado: 'aceptada',
        motivo: null,
        detalles: null,
        ...op,
      })),
    });
    await promesa;
    expect(sync.enError()).toBe(1);
  });
});
