import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
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
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Ver `auth/testing`: la fábrica tira del punto de entrada secundario para no
// cerrar un ciclo con el `keycloak-js` que está resolviendo.
vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';

import catalogoApp from '../../../../public/i18n/es.json';
import { routes } from '../../app.routes';
import { ElegirNegocioComponent } from './elegir-negocio.component';

const BASE = 'https://api.vendi.co/api/v1';
const MIOS = `${BASE}/tenants/mios`;
const ME = `${BASE}/tenants/me`;
const ORG_A = '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e';
const ORG_B = '2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f';
const AJENA = '3d0a2f60-ab5c-4e4d-9f70-4b8c9d0e1f2a';

/** El catálogo real de la app sobre el empotrado, igual que en producción. */
class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

interface Preparacion {
  http: HttpTestingController;
  auth: AuthService;
}

/**
 * Prepara el TestBed con un `AuthService` **real** sobre `KeycloakFake` y las
 * rutas reales de la app (patrón de `app.spec.ts`): elegir un negocio navega a
 * `/mi-negocio`, y solo con las rutas de verdad ese viaje se puede afirmar.
 * El componente se monta en cada caso —directo o vía `RouterTestingHarness`—
 * porque es en su constructor donde sale la petición a `/tenants/mios`.
 */
async function preparar(organizaciones: string[]): Promise<Preparacion> {
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

  const auth = TestBed.runInInjectionContext(() => TestBed.inject(AuthService));
  await arrancarSesionFalsa(auth, { organizaciones });
  return { http: TestBed.inject(HttpTestingController), auth };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

/** Un turno del bucle de eventos: lo que tarda `navigate()` en resolverse. */
async function asentar(): Promise<void> {
  await new Promise((resolver) => setTimeout(resolver, 0));
}

/**
 * Espera a que llegue una petición perezosa (la pantalla destino se carga con
 * `loadComponent`, así que su petición no existe en el primer turno). No se
 * usa `fixture.whenStable()`: el `AuthService` real programa el refresco del
 * token con un `timer()` de minutos y la estabilidad no llegaría nunca.
 */
async function esperarPeticion(http: HttpTestingController, url: string) {
  for (let intento = 0; intento < 50; intento++) {
    const coincidencias = http.match(url);
    if (coincidencias.length > 0) {
      return coincidencias[0];
    }
    await asentar();
  }
  throw new Error(`Nunca llegó la petición a ${url}`);
}

describe('ElegirNegocioComponent — con nombres (Etapa 1.3)', () => {
  let p: Preparacion;

  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  afterEach(() => {
    p.http.verify();
  });

  it('pide los negocios del token y los muestra por NOMBRE, con el id como dato secundario', async () => {
    p = await preparar([ORG_A, ORG_B]);
    const fixture = TestBed.createComponent(ElegirNegocioComponent);
    p.http.expectOne(MIOS).flush([
      { id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' },
      { id: ORG_B, nombre: 'Panadería La Espiga', estado: 'activo' },
    ]);
    fixture.detectChanges();
    const visible = texto(fixture);
    expect(visible).toContain('Tienda Don Carlos');
    expect(visible).toContain('Panadería La Espiga');
  });

  it('un negocio del token que el endpoint no devolvió (eliminado) NO se ofrece', async () => {
    p = await preparar([ORG_A, ORG_B]);
    const fixture = TestBed.createComponent(ElegirNegocioComponent);
    p.http.expectOne(MIOS).flush([{ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' }]);
    fixture.detectChanges();
    const visible = texto(fixture);
    expect(visible).not.toContain('Panadería');
    // El alias huérfano tampoco se muestra como UUID: no hay nada que elegir ahí.
    expect(visible).not.toContain(ORG_B);
  });

  it('si el endpoint falla, cae a la lista de alias como antes (degradación honesta)', async () => {
    p = await preparar([ORG_A, ORG_B]);
    const fixture = TestBed.createComponent(ElegirNegocioComponent);
    p.http.expectOne(MIOS).error(new ProgressEvent('error'));
    fixture.detectChanges();
    expect(texto(fixture)).toContain(ORG_A);
  });

  it('elegir llama selectTenant con el id y navega a /mi-negocio', async () => {
    p = await preparar([ORG_A, ORG_B]);
    // Por el harness, no por `createComponent`: elegir navega, y los
    // componentes enrutados solo se instancian si hay un `router-outlet`.
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/elegir-negocio');
    p.http.expectOne(MIOS).flush([{ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' }]);
    harness.detectChanges();

    const boton =
      harness.routeNativeElement?.querySelector<HTMLButtonElement>('button[mat-list-item]');
    expect(boton?.textContent).toContain('Tienda Don Carlos');
    boton?.click();
    expect(p.auth.tenantId()).toBe(ORG_A);

    // La navegación entra a /mi-negocio, que pide su propio dato.
    const peticionMe = await esperarPeticion(p.http, ME);
    peticionMe.flush({ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' });
    expect(TestBed.inject(Router).url).toBe('/mi-negocio');
  });
});

describe('ElegirNegocioComponent — defensas que no cambian', () => {
  let p: Preparacion;

  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  afterEach(() => {
    p.http.verify();
  });

  it('un alias que NO está en el token no se selecciona ni navega', async () => {
    // La defensa vive en `AuthService.selectTenant` (el real): esta pantalla no
    // puede usarse para pedir el negocio de otro, ni escribiendo el id a mano.
    p = await preparar([ORG_A]);
    const fixture = TestBed.createComponent(ElegirNegocioComponent);
    p.http.expectOne(MIOS).flush([{ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' }]);
    fixture.detectChanges();
    // `selectTenant` deja constancia en consola; se silencia para no ensuciar
    // la salida sin perder el aserto de que rechazó.
    const consola = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    fixture.componentInstance.elegir(AJENA);
    await asentar();

    // Con una sola organización el tenant sigue siendo la propia, nunca la ajena.
    expect(p.auth.tenantId()).toBe(ORG_A);
    expect(TestBed.inject(Router).url).toBe('/');
    expect(consola).toHaveBeenCalled();
    consola.mockRestore();
  });

  it('sin ninguna organización lo dice y ofrece cerrar sesión', async () => {
    // Usuario recién creado al que nadie ha añadido a un negocio todavía, o
    // token pedido sin `scope=organization:*`. Sin este caso, pantalla muda.
    p = await preparar([]);
    const fixture = TestBed.createComponent(ElegirNegocioComponent);
    p.http.expectOne(MIOS).flush([]);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('todavía no está asociada a ningún negocio');
    fixture.componentInstance.cerrarSesion();
    expect(KeycloakFake.ultimaInstancia?.logoutCalls).toBe(1);
  });
});
