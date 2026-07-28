import 'fake-indexeddb/auto';
import { HttpRequest, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { VendiDb } from './vendi.db';
import { CatalogoLocalService } from './catalogo-local.service';

/**
 * `refrescarDelta` lee el watermark de `meta` en Dexie antes de disparar el
 * GET, así que la petición HTTP no existe aún en el mismo tick: hay que ceder
 * el control hasta que llegue. `match` no falla cuando no hay coincidencia (a
 * diferencia de `expectOne`), lo que permite sondear tick a tick. Es el mismo
 * patrón del spec de `DispositivoService`.
 */
async function esperarPeticion(
  http: HttpTestingController,
  coincide: (r: HttpRequest<unknown>) => boolean,
) {
  for (let intento = 0; intento < 50; intento += 1) {
    const [encontrada] = http.match(coincide);
    if (encontrada) {
      return encontrada;
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error('No llegó la petición esperada');
}

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
    const req = await esperarPeticion(http, (r) => r.url === '/api/v1/sync/delta');
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
      id: 'p-viejo',
      nombre: 'Viejo',
      categoria: null,
      codigo_barras: null,
      precio_venta: 100,
      unidad_medida: 'unidad',
      stock_actual: '1',
    });

    const promesa = catalogo.refrescarDelta();
    const req = await esperarPeticion(http, (r) => r.url === '/api/v1/sync/delta');
    expect(req.request.params.get('desde')).toBe('2026-07-29T10:00:00Z');
    req.flush({ hasta: '2026-07-29T11:00:00Z', productos: [], eliminados: ['p-viejo'] });
    await promesa;

    expect(await db.productos.get('p-viejo')).toBeUndefined();
    expect((await db.meta.get('delta_hasta'))?.valor).toBe('2026-07-29T11:00:00Z');
  });

  it('busca por nombre sin distinguir mayúsculas y por código de barras exacto', async () => {
    await db.productos.bulkPut([
      {
        id: 'p-1',
        nombre: 'Arroz x kg',
        categoria: 'Granos',
        codigo_barras: '7701234567890',
        precio_venta: 4000,
        unidad_medida: 'kg',
        stock_actual: '25.5',
      },
      {
        id: 'p-2',
        nombre: 'Aceite girasol',
        categoria: null,
        codigo_barras: null,
        precio_venta: 9000,
        unidad_medida: 'unidad',
        stock_actual: '8',
      },
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
        {
          id: 'c-1',
          nombre: 'Don Carlos',
          telefono: '3001234567',
          limite_credito: 50000,
          nota: null,
          saldo_pendiente_total: 12000,
          cupo_excedido: false,
          created_at: null,
        },
      ],
      total: 1,
      skip: 0,
      limit: 200,
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
      {
        id: 'c-2',
        nombre: 'Doña Ana',
        telefono: null,
        limite_credito: null,
        origen: 'servidor',
      },
    ]);
    expect((await catalogo.buscarClientes('carlos')).map((c) => c.id)).toEqual(['c-1']);
    expect((await catalogo.buscarClientes('')).length).toBe(2);
  });
});
