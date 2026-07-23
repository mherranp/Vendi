import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import {
  API_BASE_URL,
  CATALOGO_MINIMO_ES,
  Notificador,
  errorInterceptor,
  fusionarCatalogos,
} from 'data-access';
import { Observable, of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Se sustituye keycloak-js por el doble compartido ANTES de que `AuthService`
// se cargue. La fábrica no puede depender de imports de nivel superior porque
// vitest eleva `vi.mock` al principio del archivo, y tiene que tirar de
// `auth/testing` —no del barril `auth`— para no cerrar un ciclo con el propio
// `keycloak-js` que está resolviendo.
vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';

import catalogoApp from '../../../../public/i18n/es.json';
import { MiNegocioComponent } from './mi-negocio.component';

const BASE = 'https://api.vendi.co/api/v1';
const ME = `${BASE}/tenants/me`;
const ORG_A = '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e';
const ORG_B = '2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f';

/** El catálogo real de la app sobre el empotrado, igual que en producción. */
class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

interface Montaje {
  fixture: ComponentFixture<MiNegocioComponent>;
  http: HttpTestingController;
  notificador: Notificador;
  auth: AuthService;
  router: Router;
}

/**
 * Monta la pantalla con un `AuthService` **real** alimentado por `KeycloakFake`.
 *
 * Antes aquí había un doble de `AuthService` escrito a mano que modelaba
 * `limpiarSeleccionDeTenant()` como un contador. Con eso, el caso de "cambiar
 * de negocio" pasaba en verde mientras la funcionalidad real estaba rota: el
 * componente soltaba la selección y no navegaba a ninguna parte. Usando el
 * servicio real, lo que se afirma es el efecto observable —`tenantId()` y la
 * URL— y no la existencia de una llamada.
 */
async function montar(organizaciones: string[] = [ORG_A]): Promise<Montaje> {
  TestBed.resetTestingModule();
  KeycloakFake.reiniciar();
  TestBed.configureTestingModule({
    providers: [
      // Las rutas reales que toca esta pantalla: sin `elegir-negocio` el
      // `navigate()` de "cambiar de negocio" rechazaría y el spec no podría
      // distinguir "no navegó" de "navegó a una ruta que no existe".
      provideRouter([
        { path: 'mi-negocio', children: [] },
        { path: 'elegir-negocio', children: [] },
      ]),
      provideHttpClient(withInterceptors([errorInterceptor])),
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
  await arrancarSesionFalsa(auth, {
    organizaciones,
    perfil: { username: 'dueno', firstName: 'Ana', lastName: 'Gómez' },
  });
  // Con más de un negocio, `tenantId` es `null` hasta que se elige: es
  // exactamente lo que hace el selector antes de llegar a esta pantalla.
  if (organizaciones.length > 1) {
    auth.selectTenant(organizaciones[0]);
  }

  return {
    fixture: TestBed.createComponent(MiNegocioComponent),
    http: TestBed.inject(HttpTestingController),
    notificador: TestBed.inject(Notificador),
    auth,
    router: TestBed.inject(Router),
  };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

/**
 * Deja correr un turno del bucle de eventos para que el router termine.
 *
 * No se usa `fixture.whenStable()` a propósito: `AuthService` real programa el
 * refresco del token con un `timer()` de hasta 5 minutos, que es un macrotask
 * pendiente, y `whenStable()` se quedaría esperándolo. Aquí solo hace falta
 * que se resuelva la promesa de `navigate()`.
 */
async function asentar(): Promise<void> {
  await new Promise((resolver) => setTimeout(resolver, 0));
}

describe('MiNegocioComponent', () => {
  let m: Montaje;

  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  afterEach(() => {
    m.http.verify();
  });

  it('pide GET /tenants/me SIN identificador en la URL', async () => {
    // Éste es el aserto de aislamiento del lado del cliente: no hay ningún id
    // que un usuario pueda manipular para pedir el negocio de otro. El tenant
    // lo resuelve el backend del claim del token.
    m = await montar();
    m.fixture.detectChanges();
    const req = m.http.expectOne(ME);
    expect(req.request.method).toBe('GET');
    expect(req.request.params.keys().length).toBe(0);
    req.flush({ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' });
  });

  it('el tenant que enseña sale del claim del token, no de la respuesta', async () => {
    // Con el servicio real esto deja de ser una constante del spec: es
    // `aliasDeOrganizaciones()` leyendo el claim `organization` tal y como lo
    // emite el realm `vendi-co` (lista de alias, `alias = str(tenant_id)`).
    m = await montar();
    expect(m.auth.tenantId()).toBe(ORG_A);
    m.fixture.detectChanges();
    m.http.expectOne(ME).flush({ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' });
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain(ORG_A);
  });

  it('pinta el nombre, el estado traducido y los dos identificadores', async () => {
    m = await montar();
    m.fixture.detectChanges();
    m.http.expectOne(ME).flush({ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' });
    m.fixture.detectChanges();

    const visible = texto(m.fixture);
    expect(visible).toContain('Tienda Don Carlos');
    expect(visible).toContain('Activo');
    // El de la API y el resuelto del claim: verlos juntos convierte una
    // incoherencia silenciosa en algo observable.
    expect(visible).toContain(ORG_A);
    expect(visible).toContain('Identificador en tu sesión');
  });

  it('un negocio suspendido lo dice con todas las letras', async () => {
    m = await montar();
    m.fixture.detectChanges();
    m.http.expectOne(ME).flush({ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'suspendido' });
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain('La cuenta del negocio está suspendida');
  });

  it('con un solo negocio NO ofrece cambiar de negocio', async () => {
    m = await montar([ORG_A]);
    m.fixture.detectChanges();
    m.http.expectOne(ME).flush({ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' });
    m.fixture.detectChanges();
    expect(texto(m.fixture)).not.toContain('Cambiar de negocio');
  });

  it('con dos negocios lo ofrece, y al usarlo suelta la selección Y navega al selector', async () => {
    m = await montar([ORG_A, ORG_B]);
    m.fixture.detectChanges();
    m.http.expectOne(ME).flush({ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' });
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain('Cambiar de negocio');
    expect(m.auth.tenantId()).toBe(ORG_A);

    m.fixture.componentInstance.cambiarDeNegocio();
    await asentar();

    // Efecto real sobre el servicio real: con dos organizaciones y sin
    // selección, `tenantId` vuelve a ser `null`.
    expect(m.auth.tenantId()).toBeNull();
    // Y, sobre todo, el usuario acaba en el selector. Sin esto se quedaba en
    // esta misma pantalla mirando datos de un negocio que ya no está elegido,
    // porque los guards solo corren al navegar.
    expect(m.router.url).toBe('/elegir-negocio');
  });

  it('un 403 de tenant suspendido deja mensaje en español y salida, no spinner', async () => {
    m = await montar();
    m.fixture.detectChanges();
    m.http.expectOne(ME).flush(
      {
        message: 'La cuenta del negocio está suspendida. Contáctanos para reactivarla.',
        code: 'tenant_suspendido',
      },
      { status: 403, statusText: 'Forbidden' },
    );
    m.fixture.detectChanges();

    // El interceptor prefiere el mensaje del backend en los 4xx recuperables:
    // es quien conoce la regla violada y ya lo manda en español.
    expect(m.notificador.ultimo()?.mensaje).toContain('suspendida');
    expect(m.fixture.componentInstance.cargando()).toBe(false);
    expect(texto(m.fixture)).toContain('Reintentar');
  });

  it('reintentar vuelve a pedir el negocio', async () => {
    m = await montar();
    m.fixture.detectChanges();
    m.http.expectOne(ME).error(new ProgressEvent('error'));
    m.fixture.detectChanges();
    expect(m.fixture.componentInstance.fallo()).toBe(true);

    m.fixture.componentInstance.cargar();
    m.http.expectOne(ME).flush({ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' });
    expect(m.fixture.componentInstance.fallo()).toBe(false);
  });

  it('un estado desconocido se enseña tal cual y en neutro', async () => {
    m = await montar();
    m.fixture.detectChanges();
    m.http.expectOne(ME).flush({ id: ORG_A, nombre: 'X', estado: 'en_mora' });
    m.fixture.detectChanges();
    expect(m.fixture.componentInstance.varianteDeEstado('en_mora')).toBe('neutro');
    expect(texto(m.fixture)).toContain('en_mora');
  });
});
