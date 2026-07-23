import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';

import { AuthService } from './auth.service';
import { authInterceptor } from './auth.interceptor';

const ORG_A = '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e';

/**
 * Doble de AuthService: el interceptor solo necesita `getToken()` y
 * `tenantId()`. Se evita así arrancar Keycloak en un test de cabeceras.
 */
function montar(token: string, tenantId: string | null) {
  const tenant = signal<string | null>(tenantId);
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withInterceptors([authInterceptor])),
      provideHttpClientTesting(),
      {
        provide: AuthService,
        useValue: { getToken: () => token, tenantId: tenant } as Partial<AuthService>,
      },
    ],
  });
  return {
    http: TestBed.inject(HttpTestingController),
    cliente: TestBed.inject(HttpClient),
    tenant,
  };
}

describe('authInterceptor', () => {
  it('añade Bearer y X-Tenant-Id cuando hay sesión y tenant', () => {
    const { http, cliente } = montar('jwt-abc', ORG_A);
    cliente.get('/api/v1/tenants/me').subscribe();
    const req = http.expectOne('/api/v1/tenants/me');
    expect(req.request.headers.get('Authorization')).toBe('Bearer jwt-abc');
    expect(req.request.headers.get('X-Tenant-Id')).toBe(ORG_A);
    req.flush({});
    http.verify();
  });

  it('sin tenant activo NO manda X-Tenant-Id (no inventa uno)', () => {
    // Caso del usuario con dos negocios que aún no eligió, y del admin de
    // plataforma que no pertenece a ninguno.
    const { http, cliente } = montar('jwt-abc', null);
    cliente.get('/api/v1/platform/tenants').subscribe();
    const req = http.expectOne('/api/v1/platform/tenants');
    expect(req.request.headers.get('Authorization')).toBe('Bearer jwt-abc');
    expect(req.request.headers.has('X-Tenant-Id')).toBe(false);
    req.flush({});
    http.verify();
  });

  it('sin token no toca la petición', () => {
    const { http, cliente } = montar('', ORG_A);
    cliente.get('/api/v1/health').subscribe();
    const req = http.expectOne('/api/v1/health');
    expect(req.request.headers.has('Authorization')).toBe(false);
    expect(req.request.headers.has('X-Tenant-Id')).toBe(false);
    req.flush({});
    http.verify();
  });

  it('refleja el cambio de tenant en la siguiente petición', () => {
    const { http, cliente, tenant } = montar('jwt-abc', null);
    cliente.get('/api/v1/a').subscribe();
    http.expectOne('/api/v1/a').flush({});

    tenant.set(ORG_A);
    cliente.get('/api/v1/b').subscribe();
    const segunda = http.expectOne('/api/v1/b');
    expect(segunda.request.headers.get('X-Tenant-Id')).toBe(ORG_A);
    segunda.flush({});
    http.verify();
  });
});
