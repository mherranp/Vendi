import 'fake-indexeddb/auto';
import { HttpRequest, provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideTranslateService } from '@ngx-translate/core';
import { DispositivoService, SincronizadorService, VendiDb } from 'data-access';
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

/**
 * Espera a que la petición llegue al backend de pruebas y la devuelve.
 *
 * El arranque y el drenado de la cola pasan ANTES por el IndexedDB (promesas
 * de Dexie), así que la petición HTTP no existe todavía en la línea siguiente
 * a `detectChanges()` o a `cobrar()`: hay que ceder el bucle de eventos hasta
 * que salga. Un `expectOne` a pelo fallaría con «found none».
 */
async function esperarPeticion(
  http: HttpTestingController,
  predicado: (r: HttpRequest<unknown>) => boolean,
): Promise<TestRequest> {
  for (let intento = 0; intento < 200; intento++) {
    const [peticion] = http.match(predicado);
    if (peticion) {
      return peticion;
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error('La petición esperada nunca llegó al backend de pruebas.');
}

/** Responde el arranque: delta vacío, clientes vacíos, sin lote (cola vacía). */
async function responderArranque(http: HttpTestingController): Promise<void> {
  (await esperarPeticion(http, (r) => r.url === '/api/v1/sync/delta')).flush({
    hasta: '2026-07-29T10:00:00Z',
    productos: [],
    eliminados: [],
  });
  (await esperarPeticion(http, (r) => r.url === '/api/v1/clientes')).flush({
    items: [],
    total: 0,
    skip: 0,
    limit: 200,
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
    await responderArranque(http);
    await fixture.whenStable();
    return fixture.componentInstance;
  }

  async function sembrarProducto(): Promise<void> {
    await db.productos.put({
      id: 'p-1',
      nombre: 'Arroz x kg',
      categoria: 'Granos',
      codigo_barras: '7701234567890',
      precio_venta: 4000,
      unidad_medida: 'kg',
      stock_actual: '25.5',
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
    (await esperarPeticion(http, (r) => r.url === '/api/v1/sync/lotes')).error(
      new ProgressEvent('error'),
    );

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
    (await esperarPeticion(http, (r) => r.url === '/api/v1/sync/lotes')).error(
      new ProgressEvent('error'),
    );

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
    (await esperarPeticion(http, (r) => r.url === '/api/v1/sync/lotes')).error(
      new ProgressEvent('error'),
    );

    expect(TestBed.inject(SincronizadorService).pendientes()).toBe(1);
  });
});
