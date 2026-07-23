import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Router, UrlTree, provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Ver `auth/testing`: la fábrica tira del punto de entrada secundario para no
// cerrar un ciclo con el `keycloak-js` que está resolviendo.
vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';

import { PERMISO_PLATAFORMA, guardPlataforma } from './plataforma.guard';

/**
 * Deja listo un `AuthService` **real** y ejecuta el guard.
 *
 * El doble a mano que había aquí traía su propia implementación del comodín
 * `*`. Es justo la regla que decide quién entra en la consola de plataforma:
 * probarla contra una copia del spec dejaba sin cubrir la del código que se
 * despliega. Ahora los permisos entran como roles de realm del token, que es
 * como llegan en producción.
 */
async function ejecutar(opciones: {
  autenticado: boolean;
  permisos: string[];
}): Promise<boolean | UrlTree> {
  TestBed.resetTestingModule();
  KeycloakFake.reiniciar();
  TestBed.configureTestingModule({
    providers: [provideRouter([]), provideHttpClient(), AuthService],
  });

  const auth = TestBed.runInInjectionContext(() => TestBed.inject(AuthService));
  if (opciones.autenticado) {
    await arrancarSesionFalsa(auth, { roles: opciones.permisos, organizaciones: [] });
  } else {
    // `init()` que devuelve `false` es "el usuario no ha iniciado sesión": el
    // mismo camino que recorre el adaptador real con `check-sso` sin sesión.
    KeycloakFake.siguienteToken = undefined;
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

  return TestBed.runInInjectionContext(
    () =>
      guardPlataforma(
        // El guard no lee ninguno de los dos argumentos.
        null as never,
        null as never,
      ) as boolean | UrlTree,
  );
}

describe('guardPlataforma', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('sin sesión manda al login y no deja pasar', async () => {
    expect(await ejecutar({ autenticado: false, permisos: [] })).toBe(false);
    expect(KeycloakFake.ultimaInstancia?.loginCalls).toBe(1);
  });

  it('con sesión y con el permiso deja pasar', async () => {
    expect(await ejecutar({ autenticado: true, permisos: [PERMISO_PLATAFORMA] })).toBe(true);
  });

  it('con sesión y SIN el permiso redirige a /sin-acceso', async () => {
    // El requisito del plan es explícito: "no una consola vacía". Una tabla sin
    // filas afirmaría algo falso sobre los datos de la plataforma.
    const resultado = await ejecutar({ autenticado: true, permisos: ['dueno'] });
    expect(resultado).toBeInstanceOf(UrlTree);
    expect(TestBed.inject(Router).serializeUrl(resultado as UrlTree)).toBe('/sin-acceso');
  });

  it('el comodín de plataforma abre la consola', async () => {
    // `hasPermission()` honra `*`; `hasAnyRole()` no. Usar el segundo dejaría
    // fuera a un superusuario del realm.
    expect(await ejecutar({ autenticado: true, permisos: ['*'] })).toBe(true);
  });

  it('un rol parecido no cuela', async () => {
    expect(await ejecutar({ autenticado: true, permisos: ['platform:lector'] })).toBeInstanceOf(
      UrlTree,
    );
  });
});
