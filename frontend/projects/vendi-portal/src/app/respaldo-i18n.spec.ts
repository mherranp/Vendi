import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationInitStatus } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { appConfig } from './app.config';
import { InicioComponent } from './features/inicio/inicio.component';

/**
 * QA adversarial: el respaldo i18n PROPIO del portal, ejercitado de verdad.
 *
 * `app.spec.ts` comprueba que el catálogo empotrado EXISTE; esto comprueba que
 * SALVA la página: la landing completa renderizada con los providers reales de
 * producción mientras `/i18n/es.json` falla o llega vacío. Es la superficie
 * pública y anónima: un primer visitante que ve claves crudas (`portal.hero…`)
 * no vuelve.
 */
describe('la landing con /i18n/es.json caído (respaldo empotrado)', () => {
  async function pintarConCatalogoFallido(respuesta: 'error' | 'vacio'): Promise<HTMLElement> {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [...appConfig.providers, provideHttpClientTesting()],
    });
    // Al inyectar se crea el inyector de entorno y corre el inicializador de
    // i18n, que dispara el GET del catálogo: hay que fallarlo ANTES de que se
    // resuelva el arranque.
    const httpMock = TestBed.inject(HttpTestingController);
    const solicitud = httpMock.expectOne('/i18n/es.json');
    if (respuesta === 'error') {
      solicitud.flush('no encontrado', { status: 404, statusText: 'No encontrado' });
    } else {
      solicitud.flush({});
    }
    await TestBed.inject(ApplicationInitStatus).donePromise;

    const fixture = TestBed.createComponent(InicioComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('con 404 del catálogo la página pinta COMPLETA y sin una sola clave cruda', async () => {
    const raiz = await pintarConCatalogoFallido('error');
    expect(raiz.textContent).toContain('Del cuaderno al celular');
    expect(raiz.textContent).toContain('$19.500');
    expect(raiz.textContent).toContain('$40.000');
    expect(raiz.textContent).toContain('1 mes de Pro gratis');
    expect(raiz.textContent).toContain('Hecho para la tienda de barrio');
    expect(raiz.textContent).toContain('Hecho en Colombia');
    // La clave cruda es la firma del fallo: ninguna visible.
    expect(raiz.textContent).not.toContain('portal.');
    expect(raiz.textContent).not.toContain('app.titulo');
  });

  it('con catálogo 200 pero vacío ({}) la fusión cubre igualmente toda la página', async () => {
    const raiz = await pintarConCatalogoFallido('vacio');
    expect(raiz.textContent).toContain('Del cuaderno al celular');
    expect(raiz.textContent).toContain('Precios claros');
    expect(raiz.textContent).not.toContain('portal.');
  });

  it('sin número comercial el CTA de WhatsApp sigue ausente también con el respaldo', async () => {
    const raiz = await pintarConCatalogoFallido('error');
    expect(raiz.querySelector('a[href*="wa.me"]')).toBeNull();
  });
});
