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

import { ShellComponent } from './shell.component';

/** Registro de lo que se le pidió pintar al snackbar. */
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
 * Los permisos entran ahora como **roles de realm del token**, que es como
 * viajan de verdad, en vez de por un `hasPermission()` escrito a mano en el
 * spec. Ese doble reimplementaba el comodín `*`, así que afirmaba sobre su
 * propia copia de la regla: si `AuthService.hasPermission()` dejara de honrar
 * el comodín, el spec seguía en verde.
 */
async function preparar(permisos: string[], barra?: SnackBarFalso): Promise<void> {
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
    tenants: { titulo: 'Negocios' },
    layout: { menu: 'Menú', cerrar_sesion: 'Cerrar sesión', cuenta: 'Mi cuenta' },
    comun: { cerrar: 'Cerrar' },
  });

  const auth = TestBed.runInInjectionContext(() => TestBed.inject(AuthService));
  await arrancarSesionFalsa(auth, {
    roles: permisos,
    // La consola de plataforma es de usuarios que no pertenecen a ningún
    // negocio: token sin claim `organization`.
    organizaciones: [],
    perfil: { username: 'ana', firstName: 'Ana', lastName: 'Gómez' },
  });
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

describe('ShellComponent', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('con platform:admin muestra la entrada de Negocios', async () => {
    await preparar(['platform:admin']);
    const fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('Negocios');
  });

  it('sin el permiso, la navegación queda vacía', async () => {
    // Cosmético, no seguridad —de eso se encargan `guardPlataforma` y la API—,
    // pero ofrecer un enlace que va a rebotar es una promesa falsa.
    await preparar(['dueno']);
    const fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance.navegacion()).toEqual([]);
    expect(texto(fixture)).not.toContain('Negocios');
  });

  it('el comodín de plataforma también abre la navegación', async () => {
    // El comodín lo honra `AuthService.hasPermission()` de verdad, leyendo
    // `realm_access.roles` del token.
    await preparar(['*']);
    const fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('Negocios');
  });

  it('pinta el nombre del usuario en la barra', async () => {
    await preparar(['platform:admin']);
    const fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('Ana Gómez');
  });
});

describe('los avisos del shell', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('lo que acumula Notificador acaba en pantalla', async () => {
    // Sin este puente, el mensaje traducido que produce `errorInterceptor`
    // ante un 500 se queda en una señal que nadie lee: la operación falla en
    // silencio. El anfitrión vive en `ui-kit` y la frontera de ADR-011 le
    // impide inyectar `Notificador`, así que el shell se lo pasa por input:
    // este spec prueba esa cadena completa.
    const barra = new SnackBarFalso();
    await preparar(['platform:admin'], barra);
    const fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();

    TestBed.inject(Notificador).error('Tuvimos un problema.');
    fixture.detectChanges();

    expect(barra.abiertos.length).toBe(1);
    expect(barra.abiertos[0].mensaje).toBe('Tuvimos un problema.');
    expect(barra.abiertos[0].accion).toBe('Cerrar');
  });

  it('dos errores idénticos seguidos se ven los dos', async () => {
    // La deduplicación va por `id`, no por texto: si el usuario reintenta y
    // vuelve a fallar, tiene que enterarse de que falló otra vez.
    const barra = new SnackBarFalso();
    await preparar(['platform:admin'], barra);
    const fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();

    const notificador = TestBed.inject(Notificador);
    notificador.error('Mismo error');
    fixture.detectChanges();
    notificador.error('Mismo error');
    fixture.detectChanges();

    expect(barra.abiertos.length).toBe(2);
  });

  it('no repinta el mismo aviso en cada ciclo de detección de cambios', async () => {
    const barra = new SnackBarFalso();
    await preparar(['platform:admin'], barra);
    const fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();

    TestBed.inject(Notificador).info('Una sola vez');
    fixture.detectChanges();
    fixture.detectChanges();
    fixture.detectChanges();

    expect(barra.abiertos.length).toBe(1);
  });
});
