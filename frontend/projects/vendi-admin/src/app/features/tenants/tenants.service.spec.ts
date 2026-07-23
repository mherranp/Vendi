import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { API_BASE_URL, SILENCIAR_AVISO_ERROR } from 'data-access';
import { PagedList, TenantDeApi } from 'domain';

import { MAXIMO_NOMBRE, TenantsService } from './tenants.service';

/**
 * Éste es el spec que hace de **contrato** con la pista backend.
 *
 * Mientras `docs/api/openapi-fase0.json` no exista, lo único que impide que el
 * frontend y la API se desalineen es que las cinco firmas de la sección
 * "Interfaces" de la Tarea 4.2 estén fijadas en algún sitio ejecutable. Están
 * aquí: URL, método y cuerpo, uno a uno. Si el backend publica otra cosa, este
 * archivo es el que hay que cambiar —y ese cambio es la conversación que toca
 * tener.
 */

const BASE = 'https://api.vendi.co/api/v1';
const ID = '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e';

function configurar(): { servicio: TenantsService; http: HttpTestingController } {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
    ],
  });
  return {
    servicio: TestBed.inject(TenantsService),
    http: TestBed.inject(HttpTestingController),
  };
}

describe('TenantsService — contrato con la API', () => {
  let servicio: TenantsService;
  let http: HttpTestingController;

  beforeEach(() => {
    ({ servicio, http } = configurar());
  });

  afterEach(() => {
    http.verify();
  });

  it('lista con GET /platform/tenants?skip&limit', () => {
    let pagina: PagedList<TenantDeApi> | undefined;
    servicio.listar(20, 10).subscribe((p) => (pagina = p));

    const req = http.expectOne((r) => r.url === `${BASE}/platform/tenants`);
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('skip')).toBe('20');
    expect(req.request.params.get('limit')).toBe('10');
    // Explícito, no por omisión: quién ve los negocios dados de baja no puede
    // depender del valor por defecto de un parámetro del backend.
    expect(req.request.params.get('incluir_eliminados')).toBe('false');

    req.flush({
      items: [{ id: ID, nombre: 'Tienda Don Carlos', estado: 'activo' }],
      total: 201,
      skip: 20,
      limit: 10,
    });

    expect(pagina?.items.length).toBe(1);
    expect(pagina?.total).toBe(201);
  });

  it('crea con POST /platform/tenants {nombre} y recorta espacios', () => {
    servicio.crear('  Tienda Don Carlos  ').subscribe();
    const req = http.expectOne(`${BASE}/platform/tenants`);
    expect(req.request.method).toBe('POST');
    // Recortar en el cliente evita dos negocios que se ven idénticos en la
    // lista y solo se distinguen por un espacio final.
    expect(req.request.body).toEqual({ nombre: 'Tienda Don Carlos' });
    req.flush(
      { id: ID, nombre: 'Tienda Don Carlos', estado: 'activo' },
      { status: 201, statusText: 'Created' },
    );
  });

  it('renombra con PATCH /platform/tenants/{id} {nombre}', () => {
    servicio.actualizar(ID, { nombre: 'Otro nombre' }).subscribe();
    const req = http.expectOne(`${BASE}/platform/tenants/${ID}`);
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ nombre: 'Otro nombre' });
    req.flush({ id: ID, nombre: 'Otro nombre', estado: 'activo' });
  });

  it('suspende con PATCH /platform/tenants/{id} {estado}', () => {
    servicio.actualizar(ID, { estado: 'suspendido' }).subscribe();
    const req = http.expectOne(`${BASE}/platform/tenants/${ID}`);
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ estado: 'suspendido' });
    req.flush({ id: ID, nombre: 'X', estado: 'suspendido' });
  });

  it('da de baja con DELETE /platform/tenants/{id}', () => {
    servicio.eliminar(ID).subscribe();
    const req = http.expectOne(`${BASE}/platform/tenants/${ID}`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });
  });

  it('pide los eliminados solo cuando se le pide', () => {
    servicio.listar(0, 10, true).subscribe();
    const req = http.expectOne((r) => r.url === `${BASE}/platform/tenants`);
    expect(req.request.params.get('incluir_eliminados')).toBe('true');
    req.flush({ items: [], total: 0, skip: 0, limit: 10 });
  });

  it('el sondeo silencioso marca el contexto que calla al aviso global', () => {
    servicio.listarEnSilencio(0, 10).subscribe();
    const req = http.expectOne((r) => r.url === `${BASE}/platform/tenants`);
    expect(req.request.context.get(SILENCIAR_AVISO_ERROR)).toBe(true);
    req.flush({ items: [], total: 0, skip: 0, limit: 10 });
  });
});

describe('TenantsService — respuestas hostiles', () => {
  let servicio: TenantsService;
  let http: HttpTestingController;

  beforeEach(() => {
    ({ servicio, http } = configurar());
  });

  afterEach(() => {
    http.verify();
  });

  it('una página sin items no rompe la tabla: se degrada a vacía', () => {
    // Ocurre de verdad con un 200 de un proxy, o si el endpoint cambia de
    // forma. Sin esta red, la tabla hace `undefined.length` y la pantalla
    // muere entera.
    let pagina: PagedList<TenantDeApi> | undefined;
    servicio.listar(0, 10).subscribe((p) => (pagina = p));
    http.expectOne((r) => r.url === `${BASE}/platform/tenants`).flush({});
    expect(pagina).toEqual({ items: [], total: 0, skip: 0, limit: 10 });
  });

  it('cero negocios es una respuesta legítima, no un error', () => {
    let pagina: PagedList<TenantDeApi> | undefined;
    servicio.listar(0, 10).subscribe((p) => (pagina = p));
    http
      .expectOne((r) => r.url === `${BASE}/platform/tenants`)
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    expect(pagina?.total).toBe(0);
  });

  it('conserva un estado que este frontend no conoce en vez de inventarse uno', () => {
    // El día que el backend añada `en_mora`, la consola tiene que enseñarlo
    // tal cual. Estrecharlo a `EstadoTenant` con un cast diría que es
    // "activo".
    let pagina: PagedList<TenantDeApi> | undefined;
    servicio.listar(0, 10).subscribe((p) => (pagina = p));
    http
      .expectOne((r) => r.url === `${BASE}/platform/tenants`)
      .flush({ items: [{ id: ID, nombre: 'X', estado: 'en_mora' }], total: 1, skip: 0, limit: 10 });
    expect(pagina?.items[0].estado).toBe('en_mora');
  });

  it('un total ausente cae al número de filas recibidas', () => {
    let pagina: PagedList<TenantDeApi> | undefined;
    servicio.listar(0, 10).subscribe((p) => (pagina = p));
    http
      .expectOne((r) => r.url === `${BASE}/platform/tenants`)
      .flush({ items: [{ id: ID, nombre: 'X', estado: 'activo' }] });
    expect(pagina?.total).toBe(1);
  });
});

describe('MAXIMO_NOMBRE', () => {
  it('deja margen frente al varchar(255) de Keycloak', () => {
    // El alta crea una Organization con este nombre. Pasarse del límite de
    // Keycloak reventaba con un 500 de JDBC (hallazgo de la Etapa 3), que es
    // un error que el usuario no puede entender ni corregir.
    expect(MAXIMO_NOMBRE).toBeLessThan(255);
    expect(MAXIMO_NOMBRE).toBeGreaterThan(50);
  });
});
