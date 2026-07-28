import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import { API_BASE_URL, CATALOGO_MINIMO_ES, fusionarCatalogos } from 'data-access';
import { Observable, of } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';

// Ver `auth/testing`: la fábrica tira del punto de entrada secundario para no
// cerrar un ciclo con el `keycloak-js` que está resolviendo.
vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';

import catalogoApp from '../../public/i18n/es.json';
import { routes } from './app.routes';

const BASE = 'https://api.vendi.co/api/v1';

// Los repartos de ADR-023, tal cual la siembra del realm.
const ROLES_CAJERO = [
  'cajero',
  'venta:crear',
  'caja:leer',
  'caja:abrir',
  'caja:movimiento',
  'producto:leer',
  'cliente:gestionar',
  'fiado:crear',
  'fiado:abonar',
];
const ROLES_ALMACENISTA = [
  'almacenista',
  'producto:leer',
  'producto:editar',
  'inventario:ajustar',
  'compra:crear',
];

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

/**
 * Candado del candado (ADR-023): la matriz de guards de `app.routes.ts`.
 *
 * El menú se puede equivocar en silencio —oculta, no protege— y las
 * directivas `*vdHasPermission` son cosmética por diseño. La frontera del
 * lado del cliente es esta tabla: si alguien quita un `permisoGuard` de una
 * ruta, estos tests se caen aunque la pantalla siga pareciendo correcta.
 *
 * Se navega de verdad con `RouterTestingHarness` contra las rutas REALES y
 * el `AuthService` REAL sobre `KeycloakFake`: lo que se afirma es lo que el
 * navegador haría con ese token, no una copia de la regla.
 */
describe('app.routes — la matriz de ADR-023 contra URL directa', () => {
  let http: HttpTestingController;

  async function preparar(roles: string[]): Promise<RouterTestingHarness> {
    TestBed.resetTestingModule();
    KeycloakFake.reiniciar();
    TestBed.configureTestingModule({
      providers: [
        provideRouter(routes),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: API_BASE_URL, useValue: BASE },
        AuthService,
        ...provideTranslateService({
          lang: 'es',
          fallbackLang: 'es',
          loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
        }),
      ],
    });
    TestBed.inject(TranslateService).use('es');
    await arrancarSesionFalsa(TestBed.inject(AuthService), { roles });
    http = TestBed.inject(HttpTestingController);
    return RouterTestingHarness.create();
  }

  /** Espera la petición perezosa de la pantalla destino y la responde vacía. */
  async function asentarPeticiones(): Promise<void> {
    for (let intento = 0; intento < 50; intento++) {
      const pendientes = http.match(() => true);
      if (pendientes.length === 0) {
        return;
      }
      for (const peticion of pendientes) {
        // `/tenants/mios` devuelve una lista; el resto, páginas `{items,total}`.
        peticion.flush(
          peticion.request.url.endsWith('/tenants/mios')
            ? []
            : { items: [], total: 0, skip: 0, limit: 10 },
        );
      }
      await new Promise((resolver) => setTimeout(resolver, 0));
    }
  }

  afterEach(() => {
    http.verify();
  });

  it('el almacenista que escribe /cuaderno a mano acaba en /sin-permiso', async () => {
    const harness = await preparar(ROLES_ALMACENISTA);
    await harness.navigateByUrl('/cuaderno');
    expect(TestBed.inject(Router).url).toBe('/sin-permiso');
  });

  it('el almacenista que adivina la URL de un crédito acaba en /sin-permiso', async () => {
    const harness = await preparar(ROLES_ALMACENISTA);
    await harness.navigateByUrl('/cuaderno/creditos/5f1d0e2a-0000-4000-8000-aaaaaaaaaaaa');
    expect(TestBed.inject(Router).url).toBe('/sin-permiso');
  });

  it('el almacenista que escribe /caja a mano acaba en /sin-permiso', async () => {
    const harness = await preparar(ROLES_ALMACENISTA);
    await harness.navigateByUrl('/caja');
    expect(TestBed.inject(Router).url).toBe('/sin-permiso');
  });

  it('el almacenista que escribe /numeros a mano acaba en /sin-permiso', async () => {
    const harness = await preparar(ROLES_ALMACENISTA);
    await harness.navigateByUrl('/numeros');
    expect(TestBed.inject(Router).url).toBe('/sin-permiso');
  });

  it('el cajero que escribe /numeros a mano acaba en /sin-permiso', async () => {
    const harness = await preparar(ROLES_CAJERO);
    await harness.navigateByUrl('/numeros');
    expect(TestBed.inject(Router).url).toBe('/sin-permiso');
  });

  it('el cajero SÍ entra a /cuaderno por URL (ADR-023 le da cliente:gestionar)', async () => {
    const harness = await preparar(ROLES_CAJERO);
    await harness.navigateByUrl('/cuaderno');
    await asentarPeticiones();
    expect(TestBed.inject(Router).url).toBe('/cuaderno');
  });

  it('el almacenista SÍ entra a /catalogo por URL (ADR-023 le da producto:leer)', async () => {
    const harness = await preparar(ROLES_ALMACENISTA);
    await harness.navigateByUrl('/catalogo');
    await asentarPeticiones();
    expect(TestBed.inject(Router).url).toBe('/catalogo');
  });

  it('sin negocio elegido, cualquier sección manda a /elegir-negocio', async () => {
    TestBed.resetTestingModule();
    KeycloakFake.reiniciar();
    TestBed.configureTestingModule({
      providers: [
        provideRouter(routes),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: API_BASE_URL, useValue: BASE },
        AuthService,
        ...provideTranslateService({
          lang: 'es',
          fallbackLang: 'es',
          loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
        }),
      ],
    });
    TestBed.inject(TranslateService).use('es');
    // Dos organizaciones y sin selección: tenantId es null hasta elegir.
    await arrancarSesionFalsa(TestBed.inject(AuthService), {
      roles: ROLES_CAJERO,
      organizaciones: [
        '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e',
        '2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f',
      ],
    });
    http = TestBed.inject(HttpTestingController);
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/caja');
    expect(TestBed.inject(Router).url).toBe('/elegir-negocio');
    // El selector pide /tenants/mios; se responde para que verify() pase.
    await asentarPeticiones();
  });
});
