import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Provider } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import { CATALOGO_MINIMO_ES, fusionarCatalogos } from 'data-access';
import { Observable, of } from 'rxjs';

import catalogoApp from '../../../public/i18n/es.json';

/**
 * El catálogo de la app fusionado sobre el mínimo, exactamente como hace el
 * cargador resiliente en producción: si un spec ve una clave cruda
 * (`portal.algo`), es que la clave no existe en `es.json` — el aserto
 * `not.toContain('portal.')` de la página la caza.
 */
class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

/**
 * TestBed base de los specs del portal: i18n real con el catálogo de la app,
 * más los providers extra que pida el spec (p. ej. el número comercial de
 * WhatsApp). `TestBed.resetTestingModule()` primero: cada spec arranca limpio.
 */
export function prepararPruebaI18n(proveedoresExtra: Provider[] = []): void {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      ...provideTranslateService({
        lang: 'es',
        fallbackLang: 'es',
        loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
      }),
      ...proveedoresExtra,
    ],
  });
  TestBed.inject(TranslateService).use('es');
}
