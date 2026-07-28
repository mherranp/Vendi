import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { CATALOGO_DE_RESPALDO } from 'data-access';

import { App } from './app';
import { appConfig } from './app.config';
import { routes } from './app.routes';
import { prepararPruebaI18n } from './testing/i18n-prueba';

describe('App', () => {
  it('debería crearse', () => {
    prepararPruebaI18n();
    expect(TestBed.createComponent(App).componentInstance).toBeTruthy();
  });
});

describe('la landing pública', () => {
  async function pintar(): Promise<HTMLElement> {
    // El router va por `proveedoresExtra`: `prepararPruebaI18n` termina con un
    // `TestBed.inject`, y configurar el módulo después de instanciarlo lanza.
    prepararPruebaI18n([provideRouter(routes)]);
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    return harness.fixture.nativeElement as HTMLElement;
  }

  it('pinta hero, precios y confianza, con los precios de ADR-010 y sin claves crudas', async () => {
    const raiz = await pintar();
    expect(raiz.textContent).toContain('Del cuaderno al celular');
    expect(raiz.textContent).toContain('$19.500');
    expect(raiz.textContent).toContain('$40.000');
    expect(raiz.textContent).toContain('Hecho para la tienda de barrio');
    // El catálogo de prueba es el real: una clave cruda aquí es una clave que
    // falta en es.json.
    expect(raiz.textContent).not.toContain('portal.');
  });

  it('sin número comercial no hay CTA de WhatsApp, y la consola sigue a un clic', async () => {
    const raiz = await pintar();
    expect(raiz.querySelector('a[href*="wa.me"]')).toBeNull();
    // Otro origen: href absoluto, nunca routerLink.
    expect(raiz.querySelector('a[href="https://app.vendi.co"]')).not.toBeNull();
  });

  it('cualquier ruta desconocida cae en la landing, no en blanco', () => {
    const comodin = routes.find((r) => r.path === '**');
    expect(comodin?.redirectTo).toBe('');
  });

  it('hay exactamente UN h1 en toda la página', async () => {
    const raiz = await pintar();
    expect(raiz.querySelectorAll('h1')).toHaveLength(1);
  });

  it('los anclajes de la barra resuelven a secciones que existen (nada de #rotos)', async () => {
    const raiz = await pintar();
    const internos = Array.from(raiz.querySelectorAll<HTMLAnchorElement>('nav a[href^="#"]'));
    expect(internos.length).toBeGreaterThan(0);
    for (const enlace of internos) {
      const destino = enlace.getAttribute('href')?.slice(1) ?? '';
      expect(raiz.querySelector(`#${destino}`), `ancla rota: #${destino}`).not.toBeNull();
    }
  });

  it('todo enlace de la landing tiene destino: ningún botón muerto navegable por teclado', async () => {
    const raiz = await pintar();
    const enlaces = Array.from(raiz.querySelectorAll<HTMLAnchorElement>('a'));
    expect(enlaces.length).toBeGreaterThan(0);
    for (const enlace of enlaces) {
      expect(enlace.getAttribute('href')).toBeTruthy();
    }
    // Los únicos interactivos de la página son enlaces: la tabla de precios es
    // contenido estático legible, sin trampas de foco.
    expect(raiz.querySelectorAll('button, input, select, textarea')).toHaveLength(0);
  });
});

describe('el respaldo i18n del portal', () => {
  it('es el propio catálogo de la landing: si /i18n/es.json falla, nada pinta claves crudas', () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ providers: appConfig.providers });
    const respaldo = TestBed.inject(CATALOGO_DE_RESPALDO);
    expect(typeof respaldo['portal']).toBe('object');
    expect(JSON.stringify(respaldo['portal'])).toContain('Del cuaderno al celular');
  });
});
