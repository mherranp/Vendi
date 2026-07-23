import { provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { TranslateService, provideTranslateService } from '@ngx-translate/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Ver `auth/testing`: la fábrica tira del punto de entrada secundario para no
// cerrar un ciclo con el `keycloak-js` que está resolviendo.
vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';

import { ElegirNegocioComponent } from './elegir-negocio.component';

const ORG_A = '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e';
const ORG_B = '2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f';
const AJENA = '3d0a2f60-ab5c-4e4d-9f70-4b8c9d0e1f2a';

/**
 * Monta el selector con un `AuthService` **real** sobre `KeycloakFake`.
 *
 * Aquí el doble a mano era especialmente caro: reimplementaba el filtro de
 * pertenencia de `selectTenant()`, que es la defensa que impide usar esta
 * pantalla para pedir el negocio de otro. Un spec que prueba su propia copia
 * de una regla de seguridad no prueba la regla. Ahora el `false` ante un alias
 * ajeno lo produce `AuthService`, y las organizaciones salen del claim
 * `organization` del token real.
 */
async function montar(organizaciones: string[]): Promise<{
  fixture: ComponentFixture<ElegirNegocioComponent>;
  auth: AuthService;
}> {
  TestBed.resetTestingModule();
  KeycloakFake.reiniciar();
  TestBed.configureTestingModule({
    providers: [
      // `mi-negocio` existe como ruta vacía: sin ella, `navigate()` rechaza y
      // el spec ensucia la suite con una promesa no observada.
      provideRouter([{ path: 'mi-negocio', children: [] }]),
      provideHttpClient(),
      AuthService,
      ...provideTranslateService({ lang: 'es', fallbackLang: 'es' }),
    ],
  });
  TestBed.inject(TranslateService).setTranslation('es', {
    elegir: {
      titulo: '¿Con cuál de tus negocios quieres trabajar?',
      descripcion: 'Elige uno para continuar.',
      sin_negocios: 'Tu cuenta todavía no está asociada a ningún negocio.',
    },
    layout: { cerrar_sesion: 'Cerrar sesión' },
  });

  const auth = TestBed.runInInjectionContext(() => TestBed.inject(AuthService));
  await arrancarSesionFalsa(auth, { organizaciones });
  return { fixture: TestBed.createComponent(ElegirNegocioComponent), auth };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

/** Un turno del bucle de eventos: lo que tarda `navigate()` en resolverse. */
async function asentar(): Promise<void> {
  await new Promise((resolver) => setTimeout(resolver, 0));
}

describe('ElegirNegocioComponent', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('lista los negocios del token', async () => {
    const { fixture } = await montar([ORG_A, ORG_B]);
    fixture.detectChanges();
    const visible = texto(fixture);
    expect(visible).toContain(ORG_A);
    expect(visible).toContain(ORG_B);
  });

  it('elegir uno del token lo fija y navega a Mi negocio', async () => {
    const { fixture, auth } = await montar([ORG_A, ORG_B]);
    fixture.detectChanges();
    // Con dos organizaciones y ninguna elegida, el tenant es `null` a
    // propósito: `AuthService` no adivina con cuál se quiere trabajar.
    expect(auth.tenantId()).toBeNull();

    fixture.componentInstance.elegir(ORG_B);
    await asentar();

    expect(auth.tenantId()).toBe(ORG_B);
    expect(TestBed.inject(Router).url).toBe('/mi-negocio');
  });

  it('un alias que NO está en el token no se selecciona ni navega', async () => {
    // La defensa está en `AuthService.selectTenant`, y ahora es la de verdad:
    // el spec ya no trae su propia copia de la comprobación.
    const { fixture, auth } = await montar([ORG_A]);
    fixture.detectChanges();
    // `selectTenant` deja constancia en consola; se silencia para no ensuciar
    // la salida sin perder el aserto de que rechazó.
    const consola = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    fixture.componentInstance.elegir(AJENA);
    await asentar();

    // Con una sola organización el tenant sigue siendo la propia, nunca la ajena.
    expect(auth.tenantId()).toBe(ORG_A);
    expect(TestBed.inject(Router).url).toBe('/');
    expect(consola).toHaveBeenCalled();
    consola.mockRestore();
  });

  it('sin ninguna organización lo dice y ofrece cerrar sesión', async () => {
    // Usuario recién creado al que nadie ha añadido a un negocio todavía, o
    // token pedido sin `scope=organization:*`. Sin este caso, pantalla muda.
    const { fixture } = await montar([]);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('todavía no está asociada a ningún negocio');
    fixture.componentInstance.cerrarSesion();
    expect(KeycloakFake.ultimaInstancia?.logoutCalls).toBe(1);
  });
});
