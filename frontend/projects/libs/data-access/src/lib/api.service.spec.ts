import { HttpContext, HttpResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { API_BASE_URL, ApiService } from './api.service';
import { SILENCIAR_AVISO_ERROR } from './interceptors/error.interceptor';

function configurar(baseUrl?: string): { api: ApiService; http: HttpTestingController } {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      ApiService,
      ...(baseUrl ? [{ provide: API_BASE_URL, useValue: baseUrl }] : []),
    ],
  });
  return {
    api: TestBed.inject(ApiService),
    http: TestBed.inject(HttpTestingController),
  };
}

describe('ApiService', () => {
  let http: HttpTestingController;
  let api: ApiService;

  beforeEach(() => {
    ({ api, http } = configurar());
  });

  afterEach(() => {
    http.verify();
  });

  it('usa /api/v1 como base cuando no se provee API_BASE_URL', () => {
    let cuerpo: unknown;
    api.get<{ ok: boolean }>('/health').subscribe((r) => (cuerpo = r));
    const req = http.expectOne('/api/v1/health');
    expect(req.request.method).toBe('GET');
    req.flush({ ok: true });
    expect(cuerpo).toEqual({ ok: true });
  });

  it('respeta el override de API_BASE_URL (el caso real: environment.apiUrl)', () => {
    ({ api, http } = configurar('https://api.vendi.co/api/v1'));
    api.get('/tenants/me').subscribe();
    http.expectOne('https://api.vendi.co/api/v1/tenants/me').flush({});
  });

  it('serializa los parámetros de consulta con HttpParams (numéricos y de texto)', () => {
    api.get('/platform/tenants', { skip: 20, limit: 10, estado: 'activo' }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/v1/platform/tenants');
    expect(req.request.params.get('skip')).toBe('20');
    expect(req.request.params.get('limit')).toBe('10');
    expect(req.request.params.get('estado')).toBe('activo');
    req.flush({ items: [], total: 0, skip: 20, limit: 10 });
  });

  it('post() envía el cuerpo y devuelve la respuesta', () => {
    let recibido: unknown;
    api
      .post<{ id: string }>('/platform/tenants', { nombre: 'Tienda Don Carlos' })
      .subscribe((r) => (recibido = r));
    const req = http.expectOne('/api/v1/platform/tenants');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ nombre: 'Tienda Don Carlos' });
    req.flush({ id: 't_123' });
    expect(recibido).toEqual({ id: 't_123' });
  });

  it('patch() usa la ruta y el método correctos', () => {
    api.patch('/platform/tenants/t_1', { nombre: 'Nuevo nombre' }).subscribe();
    const req = http.expectOne('/api/v1/platform/tenants/t_1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ nombre: 'Nuevo nombre' });
    req.flush({});
  });

  it('put() usa la ruta y el método correctos', () => {
    api.put('/platform/tenants/t_1', { nombre: 'Reemplazado' }).subscribe();
    const req = http.expectOne('/api/v1/platform/tenants/t_1');
    expect(req.request.method).toBe('PUT');
    req.flush({});
  });

  it('delete() usa la ruta y el método correctos', () => {
    api.delete('/platform/tenants/t_1').subscribe();
    const req = http.expectOne('/api/v1/platform/tenants/t_1');
    expect(req.request.method).toBe('DELETE');
    req.flush(new HttpResponse({ status: 204 }));
  });

  it('propaga el HttpContext con SILENCIAR_AVISO_ERROR en GET', () => {
    const ctx = new HttpContext().set(SILENCIAR_AVISO_ERROR, true);
    api.get('/tenant/features', undefined, { context: ctx }).subscribe();
    const req = http.expectOne('/api/v1/tenant/features');
    expect(req.request.context.get(SILENCIAR_AVISO_ERROR)).toBe(true);
    req.flush({});
  });

  it('el contexto por defecto NO trae SILENCIAR_AVISO_ERROR', () => {
    api.get('/tenants/me').subscribe();
    const req = http.expectOne('/api/v1/tenants/me');
    expect(req.request.context.get(SILENCIAR_AVISO_ERROR)).toBe(false);
    req.flush({});
  });
});
