import { TestBed } from '@angular/core/testing';
import { authGuard, tenantGuard } from 'auth';
import { App } from './app';
import { routes } from './app.routes';

describe('App', () => {
  it('debería crearse', () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    expect(TestBed.createComponent(App).componentInstance).toBeTruthy();
  });
});

describe('vendi-app con POS (Etapa 1.3, subproyecto 2)', () => {
  // Este spec es el INVERSO del candado de Fase 0. Aquel prohibía guards para
  // que nadie improvisara un login dentro del WebView (los passkeys no
  // funcionan ahí). El subproyecto 2 llegó con el flujo WEB (passkey en el
  // navegador/PWA; la auth nativa es la deuda D-29), y ahora el candado
  // protege lo contrario: la ruta del POS exige sesión y tenant, y quien los
  // quite rompe este test.
  it('la ruta del POS exige sesión y tenant', () => {
    const pos = routes.find((r) => r.path === '');
    expect(pos?.canActivate).toEqual([authGuard, tenantGuard]);
  });

  it('/elegir-negocio NO lleva tenantGuard (sería un bucle de redirección)', () => {
    const elegir = routes.find((r) => r.path === 'elegir-negocio');
    expect(elegir?.canActivate).toEqual([authGuard]);
  });

  it('cualquier ruta desconocida cae en el POS, no en blanco', () => {
    const comodin = routes.find((r) => r.path === '**');
    expect(comodin?.redirectTo).toBe('');
  });
});
