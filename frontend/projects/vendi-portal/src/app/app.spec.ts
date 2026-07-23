import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import { CATALOGO_MINIMO_ES, fusionarCatalogos } from 'data-access';
import { Observable, of } from 'rxjs';

import catalogoApp from '../../public/i18n/es.json';
import { App } from './app';
import { routes } from './app.routes';

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

function preparar(): void {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideRouter(routes),
      provideHttpClient(),
      provideHttpClientTesting(),
      ...provideTranslateService({
        lang: 'es',
        fallbackLang: 'es',
        loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
      }),
    ],
  });
  TestBed.inject(TranslateService).use('es');
}

describe('App', () => {
  it('debería crearse', () => {
    preparar();
    expect(TestBed.createComponent(App).componentInstance).toBeTruthy();
  });
});

describe('portal público', () => {
  it('pinta el lema traducido y el enlace a la consola del negocio', async () => {
    preparar();
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    const raiz = harness.fixture.nativeElement as HTMLElement;
    expect(raiz.textContent).toContain('El punto de venta para las tiendas de barrio');
    expect(raiz.textContent).not.toContain('portal.');

    const enlace = raiz.querySelector('a');
    // Otro origen: tiene que ser un href absoluto, no un routerLink.
    expect(enlace?.getAttribute('href')).toBe('https://app.vendi.co');
  });
});
