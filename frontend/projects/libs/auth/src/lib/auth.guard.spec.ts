import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, RouterStateSnapshot, UrlTree } from '@angular/router';
import { provideRouter } from '@angular/router';

import { AuthService } from './auth.service';
import { authGuard, roleGuard, tenantGuard } from './auth.guard';

const ORG_A = '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e';

interface AuthFalso {
  authenticated: () => boolean;
  tenantId: () => string | null;
  hasAnyRole: (...roles: string[]) => boolean;
  login: () => void;
  loginCalls: number;
}

function montar(opciones: {
  autenticado: boolean;
  tenantId?: string | null;
  roles?: string[];
}): AuthFalso {
  const roles = signal(opciones.roles ?? []);
  const falso: AuthFalso = {
    authenticated: () => opciones.autenticado,
    tenantId: () => opciones.tenantId ?? null,
    hasAnyRole: (...pedidos: string[]) => pedidos.some((r) => roles().includes(r)),
    login: () => {
      falso.loginCalls += 1;
    },
    loginCalls: 0,
  };
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [provideRouter([]), { provide: AuthService, useValue: falso }],
  });
  return falso;
}

const RUTA = {} as ActivatedRouteSnapshot;
const ESTADO = {} as RouterStateSnapshot;

function ejecutar(guard: ReturnType<typeof roleGuard>) {
  return TestBed.runInInjectionContext(() => guard(RUTA, ESTADO));
}

describe('authGuard', () => {
  it('deja pasar con sesión', () => {
    montar({ autenticado: true });
    expect(ejecutar(authGuard)).toBe(true);
  });

  it('sin sesión manda al login y bloquea', () => {
    const auth = montar({ autenticado: false });
    expect(ejecutar(authGuard)).toBe(false);
    expect(auth.loginCalls).toBe(1);
  });
});

describe('roleGuard', () => {
  it('deja pasar si tiene alguno de los roles', () => {
    montar({ autenticado: true, roles: ['dueno'] });
    expect(ejecutar(roleGuard('dueno', 'cajero'))).toBe(true);
  });

  it('sin el rol redirige a /sin-permiso en vez de dejar la ruta a medias', () => {
    montar({ autenticado: true, roles: ['cajero'] });
    const resultado = ejecutar(roleGuard('dueno'));
    expect(resultado).toBeInstanceOf(UrlTree);
    expect(String(resultado)).toBe('/sin-permiso');
  });

  it('sin sesión manda al login', () => {
    const auth = montar({ autenticado: false, roles: ['dueno'] });
    expect(ejecutar(roleGuard('dueno'))).toBe(false);
    expect(auth.loginCalls).toBe(1);
  });
});

describe('tenantGuard', () => {
  it('deja pasar cuando hay tenant activo', () => {
    montar({ autenticado: true, tenantId: ORG_A });
    expect(ejecutar(tenantGuard)).toBe(true);
  });

  it('sin tenant manda a elegir negocio', () => {
    montar({ autenticado: true, tenantId: null });
    const resultado = ejecutar(tenantGuard);
    expect(resultado).toBeInstanceOf(UrlTree);
    expect(String(resultado)).toBe('/elegir-negocio');
  });

  it('sin sesión manda al login', () => {
    const auth = montar({ autenticado: false });
    expect(ejecutar(tenantGuard)).toBe(false);
    expect(auth.loginCalls).toBe(1);
  });
});
