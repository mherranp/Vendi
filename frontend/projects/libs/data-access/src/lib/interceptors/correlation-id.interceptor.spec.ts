import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ApiService } from '../api.service';
import { correlationIdInterceptor } from './correlation-id.interceptor';

const RE_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function montar(): { api: ApiService; http: HttpTestingController } {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withInterceptors([correlationIdInterceptor])),
      provideHttpClientTesting(),
      ApiService,
    ],
  });
  return { api: TestBed.inject(ApiService), http: TestBed.inject(HttpTestingController) };
}

describe('correlationIdInterceptor', () => {
  it('añade un X-Correlation-ID con forma de UUID', () => {
    const { api, http } = montar();
    api.get('/tenants/me').subscribe();
    const req = http.expectOne('/api/v1/tenants/me');
    const id = req.request.headers.get('X-Correlation-ID');
    expect(id).toBeTruthy();
    expect(RE_UUID.test(id ?? '')).toBe(true);
    req.flush({});
    http.verify();
  });

  it('genera un identificador distinto por petición', () => {
    const { api, http } = montar();
    api.get('/a').subscribe();
    api.get('/b').subscribe();
    const primero = http.expectOne('/api/v1/a');
    const segundo = http.expectOne('/api/v1/b');
    expect(primero.request.headers.get('X-Correlation-ID')).not.toBe(
      segundo.request.headers.get('X-Correlation-ID'),
    );
    primero.flush({});
    segundo.flush({});
    http.verify();
  });

  it('respeta el identificador que ya trae la petición (reintento con la misma traza)', () => {
    const { http } = montar();
    // El interceptor trabaja sobre HttpClient; se usa directo para poder fijar
    // la cabecera de entrada, que ApiService no expone.
    const httpClient = TestBed.inject(HttpClient);
    httpClient
      .get('/api/v1/tenants/me', { headers: { 'X-Correlation-ID': 'traza-previa' } })
      .subscribe();
    const req = http.expectOne('/api/v1/tenants/me');
    expect(req.request.headers.get('X-Correlation-ID')).toBe('traza-previa');
    req.flush({});
    http.verify();
  });
});
