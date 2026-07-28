import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { TranslateService, provideTranslateService } from '@ngx-translate/core';
import { API_BASE_URL } from 'data-access';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Ver `auth/testing`: la fábrica tira del punto de entrada secundario para no
// cerrar un ciclo con el `keycloak-js` que está resolviendo.
vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';

import { App } from './app';
import { routes } from './app.routes';

const ORG_A = '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e';
const ORG_B = '2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f';

/**
 * Prepara la app con un `AuthService` **real** sobre `KeycloakFake`.
 *
 * Estos casos son los que prueban `authGuard` y `tenantGuard`, y el doble a
 * mano que había aquí traía su propia versión de la regla que los dos guards
 * consultan: "una sola organización se resuelve sola, varias exigen elegir".
 * Probar los guards contra una copia de la regla que deciden es exactamente el
 * agujero que dejó pasar el fallo de "cambiar de negocio". Ahora las
 * organizaciones vienen del claim `organization` del token y `tenantId` lo
 * calcula el servicio real.
 */
async function preparar(opciones: {
  autenticado: boolean;
  organizaciones: string[];
  roles?: string[];
}): Promise<AuthService> {
  TestBed.resetTestingModule();
  KeycloakFake.reiniciar();
  TestBed.configureTestingModule({
    providers: [
      provideRouter(routes),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: 'https://api.vendi.co/api/v1' },
      AuthService,
      ...provideTranslateService({ fallbackLang: 'es', lang: 'es' }),
    ],
  });
  TestBed.inject(TranslateService).setTranslation('es', {
    negocio: { titulo: 'Mi negocio' },
    elegir: { titulo: '¿Con cuál de tus negocios quieres trabajar?' },
    layout: { cerrar_sesion: 'Cerrar sesión', menu: 'Menú' },
    sin_permiso: { titulo: 'No tienes acceso a esta sección' },
  });

  const auth = TestBed.runInInjectionContext(() => TestBed.inject(AuthService));
  if (opciones.autenticado) {
    await arrancarSesionFalsa(auth, {
      organizaciones: opciones.organizaciones,
      roles: opciones.roles,
      perfil: { username: 'dueno', firstName: 'Ana', lastName: 'Gómez' },
    });
  } else {
    // `init()` que devuelve `false` es "el usuario no ha iniciado sesión".
    const original = KeycloakFake.prototype.init;
    KeycloakFake.prototype.init = async function (this: KeycloakFake) {
      this.initReturns = false;
      return false;
    };
    try {
      await auth.init({
        url: 'https://accounts.vendi.co',
        realm: 'vendi-co',
        clientId: 'vendi-web',
      });
    } finally {
      KeycloakFake.prototype.init = original;
    }
  }
  return auth;
}

describe('App', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('debería crearse', async () => {
    await preparar({ autenticado: true, organizaciones: [ORG_A] });
    expect(TestBed.createComponent(App).componentInstance).toBeTruthy();
  });
});

describe('rutas de la consola del negocio', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('sin sesión no se entra y se dispara el login', async () => {
    await preparar({ autenticado: false, organizaciones: [] });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/mi-negocio').catch(() => undefined);
    expect(KeycloakFake.ultimaInstancia?.loginCalls).toBeGreaterThan(0);
  });

  it('con un solo negocio entra directo a Mi negocio, sin preguntar nada', async () => {
    // `AuthService.tenantId` resuelve solo cuando hay exactamente una
    // organización: pedirle al dueño de una sola tienda que "elija" sería
    // ceremonia sin contenido.
    const auth = await preparar({ autenticado: true, organizaciones: [ORG_A] });
    expect(auth.tenantId()).toBe(ORG_A);
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    expect(TestBed.inject(Router).url).toBe('/mi-negocio');
  });

  it('con dos negocios y ninguno elegido, tenantGuard manda al selector', async () => {
    const auth = await preparar({ autenticado: true, organizaciones: [ORG_A, ORG_B] });
    expect(auth.tenantId()).toBeNull();
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/mi-negocio');
    expect(TestBed.inject(Router).url).toBe('/elegir-negocio');
  });

  it('elegido uno, /mi-negocio deja de rebotar', async () => {
    const auth = await preparar({ autenticado: true, organizaciones: [ORG_A, ORG_B] });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/mi-negocio');
    expect(TestBed.inject(Router).url).toBe('/elegir-negocio');

    expect(auth.selectTenant(ORG_B)).toBe(true);
    await harness.navigateByUrl('/mi-negocio');
    expect(TestBed.inject(Router).url).toBe('/mi-negocio');
  });

  it('/elegir-negocio no lleva tenantGuard: protegerla sería un bucle infinito', async () => {
    await preparar({ autenticado: true, organizaciones: [ORG_A, ORG_B] });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/elegir-negocio');
    expect(TestBed.inject(Router).url).toBe('/elegir-negocio');
  });
});

describe('mapa de la consola (Etapa 1.3, pista web)', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('/elegir-negocio NO lleva tenantGuard (sería un bucle de redirección)', () => {
    const shell = routes[0];
    const elegir = shell.children?.find((r) => r.path === 'elegir-negocio');
    expect(elegir?.canActivate ?? []).toEqual([]);
  });

  it('/sin-permiso no lleva guard de permiso (sería el mismo bucle)', () => {
    const shell = routes[0];
    const sinPermiso = shell.children?.find((r) => r.path === 'sin-permiso');
    expect(sinPermiso).toBeTruthy();
    expect(sinPermiso?.canActivate ?? []).toEqual([]);
  });

  it('cada ruta de feature exige tenant; la matriz completa está en la decisión 4 del plan', () => {
    const shell = routes[0];
    const conPermiso = ['caja', 'catalogo', 'inventario', 'cuaderno', 'numeros'];
    for (const camino of conPermiso) {
      const ruta = shell.children?.find((r) => r.path === camino);
      // Las rutas llegan con sus features (Tareas 5-9): este aserto crece con
      // ellas. Si la ruta existe, su guard debe ser [tenantGuard, <uno más>].
      if (ruta) {
        expect(ruta.canActivate?.length).toBe(2);
      }
    }
  });

  it('quien no tiene el permiso cae en /sin-permiso y ve por qué', async () => {
    // Cajero: caja sí, reportes no (ADR-023).
    await preparar({
      autenticado: true,
      organizaciones: [ORG_A],
      roles: ['cajero', 'caja:leer', 'caja:abrir', 'caja:movimiento'],
    });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/sin-permiso');
    expect(TestBed.inject(Router).url).toBe('/sin-permiso');
    expect(harness.routeNativeElement?.textContent).toContain('No tienes acceso a esta sección');
  });
});
