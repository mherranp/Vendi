import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
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

/** Mismo catálogo que sirve la app en producción, fusionado con el empotrado. */
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

describe('vendi-app en Fase 0', () => {
  it('la pantalla única se pinta traducida y sin claves crudas', async () => {
    preparar();
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    const texto = (harness.fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(texto).toContain('Muy pronto en tu bolsillo');
    expect(texto).not.toContain('proximamente.');
    expect(texto).not.toContain('app.titulo');
  });

  it('NO hay ninguna ruta protegida: la auth móvil es el subproyecto 2', () => {
    // Este aserto es el candado de una decisión de alcance, no una perogrullada.
    // Un login "provisional" dentro del WebView de Capacitor no funcionaría con
    // passkeys —el realm es passwordless— y habría que borrarlo entero. Si
    // alguien añade un guard aquí sin traer antes el flujo por navegador del
    // sistema, este test se lo dice.
    const conGuard = routes.filter((r) => r.canActivate || r.canActivateChild);
    expect(conGuard).toEqual([]);
  });

  it('cualquier ruta desconocida cae en la pantalla única, no en blanco', async () => {
    preparar();
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/lo-que-sea');
    expect(TestBed.inject(Router).url).toBe('/');
  });
});
