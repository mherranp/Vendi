import { provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { provideRouter } from '@angular/router';
import { TranslateService, provideTranslateService } from '@ngx-translate/core';
import { Notificador } from 'data-access';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Ver `auth/testing`: la fábrica tira del punto de entrada secundario para no
// cerrar un ciclo con el `keycloak-js` que está resolviendo.
vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';

import { AvisosComponent } from './avisos.component';
import { ShellComponent } from './shell.component';

class SnackBarFalso {
  readonly abiertos: { mensaje: string; accion?: string }[] = [];
  open(mensaje: string, accion?: string) {
    this.abiertos.push({ mensaje, accion });
    return { dismiss: () => undefined };
  }
}

/**
 * Prepara el shell con un `AuthService` **real** sobre `KeycloakFake`.
 *
 * El doble a mano que había aquí devolvía `displayName` como una señal fija,
 * así que el spec no probaba nada de la cadena real: perfil de Keycloak →
 * `_user` → `displayName`. Con el servicio real, si `cargarPerfil()` deja de
 * poblar el usuario, este spec se cae.
 */
async function preparar(barra?: SnackBarFalso): Promise<{ auth: AuthService }> {
  TestBed.resetTestingModule();
  KeycloakFake.reiniciar();
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      provideHttpClient(),
      AuthService,
      ...(barra ? [{ provide: MatSnackBar, useValue: barra }] : []),
      ...provideTranslateService({ lang: 'es', fallbackLang: 'es' }),
    ],
  });
  TestBed.inject(TranslateService).setTranslation('es', {
    negocio: { titulo: 'Mi negocio' },
    layout: { menu: 'Menú', cerrar_sesion: 'Cerrar sesión', cuenta: 'Mi cuenta' },
    comun: { cerrar: 'Cerrar' },
  });

  const auth = TestBed.runInInjectionContext(() => TestBed.inject(AuthService));
  await arrancarSesionFalsa(auth, {
    perfil: { username: 'dueno', firstName: 'Ana', lastName: 'Gómez' },
  });
  return { auth };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

describe('ShellComponent de vendi-tenant', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('pinta la navegación y el nombre del usuario', async () => {
    await preparar();
    const fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();
    const visible = texto(fixture);
    expect(visible).toContain('Mi negocio');
    // Nombre compuesto por `AuthService.displayName` a partir del perfil real
    // que devolvió `loadUserProfile()`, no por una señal fabricada en el spec.
    expect(visible).toContain('Ana Gómez');
  });

  it('cerrar sesión llega a Keycloak', async () => {
    const { auth } = await preparar();
    const fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();
    fixture.componentInstance.cerrarSesion();
    // Se afirma sobre el adaptador, que es lo que de verdad cierra la sesión.
    expect(KeycloakFake.ultimaInstancia?.logoutCalls).toBe(1);

    // El guard de logout doble de `AuthService` es real y este spec lo cubre:
    // una segunda llamada no debe abrir otra redirección.
    auth.logout();
    expect(KeycloakFake.ultimaInstancia?.logoutCalls).toBe(1);
  });
});

describe('AvisosComponent de vendi-tenant', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('lo que acumula Notificador acaba en pantalla', async () => {
    const barra = new SnackBarFalso();
    await preparar(barra);
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.detectChanges();

    TestBed.inject(Notificador).advertencia('La cuenta del negocio está suspendida.');
    fixture.detectChanges();

    expect(barra.abiertos.length).toBe(1);
    expect(barra.abiertos[0].mensaje).toBe('La cuenta del negocio está suspendida.');
  });
});
