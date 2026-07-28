import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { VendiDb } from './vendi.db';
import { DispositivoService } from './dispositivo.service';
import { LOTE_MAXIMO, SincronizadorService } from './sincronizador.service';
import { VentasOfflineService } from './ventas-offline.service';

/**
 * QA adversarial sobre el drenado de la cola (ADR-017): los casos que NO son
 * el camino feliz — lotes que desbordan el tope del contrato, drenados
 * concurrentes, reintentos manuales a mitad de vuelo y reenvíos tras morir
 * con `enviando`— con el patrón del spec del SincronizadorService.
 */

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

/** Mismo sondeo tick a tick que el spec del sincronizador: la petición nace tras Dexie. */
async function esperarPeticion(http: HttpTestingController, url: string) {
  for (let intento = 0; intento < 500; intento += 1) {
    const [encontrada] = http.match(url);
    if (encontrada) {
      return encontrada;
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error(`No llegó la petición a ${url}`);
}

function aceptadas(ids: string[]) {
  return {
    resultados: ids.map((id) => ({
      id,
      tipo: 'venta.crear',
      resultado: 'aceptada',
      motivo: null,
      detalles: null,
    })),
  };
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

async function cobrar(ventas: VentasOfflineService): Promise<string> {
  return (
    await ventas.cobrar({
      lineas: LINEA,
      medio_pago: 'efectivo',
      cliente: null,
      fecha_vencimiento: null,
    })
  ).id;
}

describe('SincronizadorService — QA adversarial de la cola', () => {
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

  it('250 operaciones drenan en dos lotes (200 + 50), FIFO y sin repetir ninguna', async () => {
    const ids: string[] = [];
    for (let n = 0; n < LOTE_MAXIMO + 50; n += 1) {
      ids.push(await cobrar(ventas));
    }

    const promesa = sync.sincronizar();

    const primero = await esperarPeticion(http, '/api/v1/sync/lotes');
    const cuerpo1 = primero.request.body as { operaciones: { id: string; secuencia: number }[] };
    expect(cuerpo1.operaciones.length).toBe(LOTE_MAXIMO);
    expect(cuerpo1.operaciones.map((op) => op.id)).toEqual(ids.slice(0, LOTE_MAXIMO));
    expect(cuerpo1.operaciones.map((op) => op.secuencia)).toEqual(
      Array.from({ length: LOTE_MAXIMO }, (_, i) => i + 1),
    );
    primero.flush(aceptadas(ids.slice(0, LOTE_MAXIMO)));

    const segundo = await esperarPeticion(http, '/api/v1/sync/lotes');
    const cuerpo2 = segundo.request.body as { operaciones: { id: string; secuencia: number }[] };
    expect(cuerpo2.operaciones.length).toBe(50);
    expect(cuerpo2.operaciones.map((op) => op.id)).toEqual(ids.slice(LOTE_MAXIMO));
    expect(cuerpo2.operaciones[0].secuencia).toBe(LOTE_MAXIMO + 1);
    segundo.flush(aceptadas(ids.slice(LOTE_MAXIMO)));

    await promesa;
    expect(await db.cola_sync.count()).toBe(0);
    expect(sync.pendientes()).toBe(0);
  });

  it('dos sincronizar() concurrentes NO duplican el envío: un solo POST para la misma cola', async () => {
    const ids = [await cobrar(ventas), await cobrar(ventas), await cobrar(ventas)];

    const primero = sync.sincronizar();
    const segundo = sync.sincronizar(); // el guard de drenado único la hace no-op

    // Solo el primer drenado llega al servidor: la segunda llamada resolvió
    // de inmediato sin tocar la red.
    const req = await esperarPeticion(http, '/api/v1/sync/lotes');
    req.flush(aceptadas(ids));
    await Promise.all([primero, segundo]);

    // Ningún segundo POST, ni siquiera tras ceder el bucle de eventos.
    for (let tick = 0; tick < 20; tick += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    expect(http.match('/api/v1/sync/lotes').length).toBe(0);
    expect(await db.cola_sync.count()).toBe(0);
  });

  it('el reintento manual a mitad de un drenado en vuelo no duplica el lote', async () => {
    const ids = [await cobrar(ventas), await cobrar(ventas)];

    const drenado = sync.sincronizar();
    const enVuelo = await esperarPeticion(http, '/api/v1/sync/lotes');

    // El botón del POS con el lote ya en el aire: el guard frena el segundo
    // drenado y las `enviando` no son `pendiente`, así que nadie las toca.
    const manual = sync.reintentar();
    enVuelo.flush(aceptadas(ids));
    await Promise.all([drenado, manual]);

    expect(http.match('/api/v1/sync/lotes').length).toBe(0);
    expect(await db.cola_sync.count()).toBe(0);
  });

  it('morir con `enviando` a mitad y oír `duplicada` del servidor: salen sin re-aplicar', async () => {
    const ids = [await cobrar(ventas), await cobrar(ventas)];
    // La app murió con el lote en el aire y el servidor SÍ lo aplicó.
    await db.cola_sync.where('estado').equals('pendiente').modify({ estado: 'enviando' });

    await sync.recuperarEnviosInterrumpidos();
    const promesa = sync.sincronizar();
    const req = await esperarPeticion(http, '/api/v1/sync/lotes');
    req.flush({
      resultados: ids.map((id) => ({
        id,
        tipo: 'venta.crear',
        resultado: 'duplicada',
        motivo: null,
        detalles: null,
      })),
    });
    await promesa;

    // Un solo reenvío, cero residuo: la idempotencia por PK absorbió el doble golpe.
    expect(http.match('/api/v1/sync/lotes').length).toBe(0);
    expect(await db.cola_sync.count()).toBe(0);
    expect(sync.pendientes()).toBe(0);
  });

  it('cliente.crear y su venta fiada suben en el mismo lote, en orden y bien ligados', async () => {
    const cliente = await ventas.crearClienteLocal({ nombre: 'Don Carlos', telefono: null });
    const venta = await ventas.cobrar({
      lineas: LINEA,
      medio_pago: 'fiado',
      cliente,
      fecha_vencimiento: null,
    });

    const promesa = sync.sincronizar();
    const req = await esperarPeticion(http, '/api/v1/sync/lotes');
    const cuerpo = req.request.body as {
      operaciones: {
        id: string;
        tipo: string;
        secuencia: number;
        datos: Record<string, unknown>;
      }[];
    };
    expect(cuerpo.operaciones.map((op) => op.tipo)).toEqual(['cliente.crear', 'venta.crear']);
    expect(cuerpo.operaciones[0].id).toBe(cliente.id);
    expect(cuerpo.operaciones[1].datos['cliente_id']).toBe(cliente.id);
    req.flush({
      resultados: [
        {
          id: cliente.id,
          tipo: 'cliente.crear',
          resultado: 'aceptada',
          motivo: null,
          detalles: null,
        },
        { id: venta.id, tipo: 'venta.crear', resultado: 'aceptada', motivo: null, detalles: null },
      ],
    });
    await promesa;

    expect(await db.cola_sync.count()).toBe(0);
  });
});
