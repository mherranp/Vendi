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

/**
 * Prepara la app con un `AuthService` **real** sobre `KeycloakFake`.
 *
 * La sesión es lo único que separa a un administrador de plataforma de un
 * dueño de tienda que se equivocó de dirección, así que probarla contra un
 * `hasPermission()` reimplementado en el propio spec dejaba sin cubrir la
 * comprobación real. Los permisos entran como roles de realm del token, que es
 * como llegan en producción.
 */
async function preparar(opciones: {
  autenticado: boolean;
  permisos: string[];
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
    tenants: { titulo: 'Negocios' },
    sin_acceso: {
      titulo: 'Esta consola no es para tu cuenta',
      descripcion: 'La consola de plataforma es para el equipo de Vendi.',
    },
    layout: { cerrar_sesion: 'Cerrar sesión', menu: 'Menú' },
  });

  const auth = TestBed.runInInjectionContext(() => TestBed.inject(AuthService));
  if (opciones.autenticado) {
    await arrancarSesionFalsa(auth, {
      roles: opciones.permisos,
      // Administrador de plataforma: no pertenece a ningún negocio.
      organizaciones: [],
      perfil: { username: 'ana', firstName: 'Ana', lastName: 'Gómez' },
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
        clientId: 'vendi-admin',
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
    await preparar({ autenticado: true, permisos: ['platform:admin'] });
    const fixture = TestBed.createComponent(App);
    expect(fixture.componentInstance).toBeTruthy();
  });
});

describe('rutas de la consola', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('sin sesión no se entra y se dispara el login', async () => {
    await preparar({ autenticado: false, permisos: [] });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/negocios').catch(() => undefined);
    expect(KeycloakFake.ultimaInstancia?.loginCalls).toBeGreaterThan(0);
    expect(TestBed.inject(Router).url).not.toContain('/negocios');
  });

  it('autenticado SIN platform:admin acaba en /sin-acceso, no en una consola vacía', async () => {
    // La comprobación de fondo de la Tarea 4.5, Paso 2. Enseñar la tabla vacía
    // afirmaría que la plataforma no tiene negocios, que es falso.
    await preparar({ autenticado: true, permisos: ['dueno'] });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/negocios');
    expect(TestBed.inject(Router).url).toBe('/sin-acceso');
    expect((harness.fixture.nativeElement as HTMLElement).textContent).toContain(
      'Esta consola no es para tu cuenta',
    );
  });

  it('la raíz redirige a /negocios para quien sí administra', async () => {
    await preparar({ autenticado: true, permisos: ['platform:admin'] });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    expect(TestBed.inject(Router).url).toBe('/negocios');
  });

  it('el comodín de realm también abre la consola', async () => {
    // Lo resuelve `AuthService.hasPermission()` de verdad, no una copia.
    await preparar({ autenticado: true, permisos: ['*'] });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    expect(TestBed.inject(Router).url).toBe('/negocios');
  });

  it('una ruta inventada aterriza en el 404 de la app, no en pantalla en blanco', async () => {
    await preparar({ autenticado: true, permisos: ['platform:admin'] });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/no-existe');
    expect(TestBed.inject(Router).url).toBe('/no-existe');
    expect(harness.routeDebugElement).toBeTruthy();
  });
});
