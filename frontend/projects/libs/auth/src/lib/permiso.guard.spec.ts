import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Ver `auth/testing`: la fábrica tira del punto de entrada secundario para no
// cerrar un ciclo con el `keycloak-js` que está resolviendo.
vi.mock('keycloak-js', async () => {
  const mod = await import('../../testing/src/public-api');
  return { default: mod.KeycloakFake };
});

import { AuthService } from './auth.service';
import { permisoGuard } from './permiso.guard';
import { KeycloakFake, arrancarSesionFalsa } from '../../testing/src/public-api';

async function preparar(roles: string[]): Promise<{ auth: AuthService; router: Router }> {
  TestBed.resetTestingModule();
  KeycloakFake.reiniciar();
  TestBed.configureTestingModule({ providers: [provideRouter([]), AuthService] });
  const auth = TestBed.inject(AuthService);
  await arrancarSesionFalsa(auth, { roles });
  return { auth, router: TestBed.inject(Router) };
}

describe('permisoGuard', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('deja pasar cuando el token trae el permiso', async () => {
    await preparar(['dueno', 'caja:leer']);
    const guard = permisoGuard('caja:leer');
    const veredicto = TestBed.runInInjectionContext(() => guard({} as never, {} as never));
    expect(veredicto).toBe(true);
  });

  it('deja pasar con CUALQUIERA de los permisos (semántica OR)', async () => {
    await preparar(['almacenista', 'inventario:ajustar']);
    const guard = permisoGuard('caja:leer', 'inventario:ajustar');
    const veredicto = TestBed.runInInjectionContext(() => guard({} as never, {} as never));
    expect(veredicto).toBe(true);
  });

  it('sin el permiso redirige a /sin-permiso, no al login', async () => {
    const { router } = await preparar(['cajero', 'caja:leer']);
    const guard = permisoGuard('reporte:leer');
    const veredicto = TestBed.runInInjectionContext(() => guard({} as never, {} as never));
    expect(String(veredicto)).toBe(String(router.createUrlTree(['/sin-permiso'])));
    expect(KeycloakFake.ultimaInstancia?.loginCalls ?? 0).toBe(0);
  });

  it('honra el comodín * (un superusuario entra a todas partes)', async () => {
    await preparar(['*']);
    const guard = permisoGuard('reporte:leer');
    const veredicto = TestBed.runInInjectionContext(() => guard({} as never, {} as never));
    expect(veredicto).toBe(true);
  });

  it('sin sesión dispara el login y no deja pasar', async () => {
    TestBed.resetTestingModule();
    KeycloakFake.reiniciar();
    // `init()` que devuelve false = no hay sesión. Se restaura en el finally:
    // un prototype parchado sin restaurar contamina los demás specs del archivo.
    const original = KeycloakFake.prototype.init;
    KeycloakFake.prototype.init = async function (this: KeycloakFake) {
      this.initReturns = false;
      return false;
    };
    try {
      TestBed.configureTestingModule({ providers: [provideRouter([]), AuthService] });
      const auth = TestBed.inject(AuthService);
      await auth.init({
        url: 'https://accounts.vendi.co',
        realm: 'vendi-co',
        clientId: 'vendi-web',
      });

      const guard = permisoGuard('caja:leer');
      const veredicto = TestBed.runInInjectionContext(() => guard({} as never, {} as never));
      expect(veredicto).toBe(false);
      expect(KeycloakFake.ultimaInstancia?.loginCalls).toBeGreaterThan(0);
    } finally {
      KeycloakFake.prototype.init = original;
    }
  });
});
