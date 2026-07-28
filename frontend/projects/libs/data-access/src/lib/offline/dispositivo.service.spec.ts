import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { VendiDb } from './vendi.db';
import { DispositivoService } from './dispositivo.service';

/**
 * El servicio lee/escribe `meta` en Dexie antes de disparar el POST, así que la
 * petición HTTP no existe aún en el mismo tick: hay que ceder el control hasta
 * que llegue. `match` no falla cuando no hay coincidencia (a diferencia de
 * `expectOne`), lo que permite sondear tick a tick.
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
    const req = await esperarPeticion(http, '/api/v1/dispositivos');
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
    (await esperarPeticion(http, '/api/v1/dispositivos')).flush({
      id: 'x',
      nombre: 'Caja 1',
      ultima_secuencia: 3,
      ultima_sync: null,
    });
    await promesa;
    expect((await db.meta.get('ultima_secuencia'))?.valor).toBe(5);
  });

  it('adopta la secuencia del servidor si va por delante', async () => {
    const promesa = servicio.asegurarRegistro();
    (await esperarPeticion(http, '/api/v1/dispositivos')).flush({
      id: 'x',
      nombre: 'Caja 1',
      ultima_secuencia: 7,
      ultima_sync: null,
    });
    await promesa;
    expect((await db.meta.get('ultima_secuencia'))?.valor).toBe(7);
  });

  it('sin red propaga el error y NO marca el dispositivo como registrado', async () => {
    const promesa = servicio.asegurarRegistro();
    (await esperarPeticion(http, '/api/v1/dispositivos')).error(new ProgressEvent('error'));
    await expect(promesa).rejects.toBeTruthy();
    expect(servicio.registrado()).toBe(false);
    expect(await db.meta.get('dispositivo_registrado')).toBeUndefined();
  });
});
