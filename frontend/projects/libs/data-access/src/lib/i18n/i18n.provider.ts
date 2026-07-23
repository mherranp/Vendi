import { HttpClient } from '@angular/common/http';
import {
  EnvironmentProviders,
  Injectable,
  InjectionToken,
  Provider,
  inject,
  provideAppInitializer,
} from '@angular/core';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import { Observable, catchError, firstValueFrom, of, timeout } from 'rxjs';
import { CATALOGO_MINIMO_ES, CatalogoTraducciones } from './catalogo-minimo';

/** Idioma único de Fase 0: Vendi solo opera en Colombia. */
export const IDIOMA_POR_DEFECTO = 'es';

/** Ruta desde la que se sirve el catálogo (assets de la app). */
const PREFIJO_CATALOGO = '/i18n/';
const SUFIJO_CATALOGO = '.json';

/**
 * Tiempo máximo de espera del catálogo antes de arrancar con el mínimo.
 *
 * Sin esto, una red que ni responde ni corta (portal cautivo de un centro
 * comercial, típico en una tienda) deja el bootstrap colgado indefinidamente:
 * el usuario ve la pantalla en blanco igual que si hubiera fallado, pero para
 * siempre.
 */
export const ESPERA_MAXIMA_CATALOGO_MS = 5_000;

/**
 * Catálogo empotrado que se usa cuando el HTTP falla. Se puede sustituir por
 * app: `{ provide: CATALOGO_DE_RESPALDO, useValue: MI_CATALOGO }`.
 */
export const CATALOGO_DE_RESPALDO = new InjectionToken<CatalogoTraducciones>(
  'CATALOGO_DE_RESPALDO',
  { providedIn: 'root', factory: () => CATALOGO_MINIMO_ES },
);

/**
 * Cargador de traducciones que **no puede fallar**.
 *
 * El `TranslateHttpLoader` estándar propaga el error HTTP; combinado con un
 * `APP_INITIALIZER` que espera a `use('es')`, cualquier fallo del catálogo
 * (offline, 404, service worker sin `/i18n/es.json` en caché) aborta el
 * bootstrap de Angular y el usuario ve una pantalla en blanco. Éste cae al
 * catálogo mínimo empotrado en el bundle y deja arrancar la app.
 */
@Injectable()
export class CargadorDeTraduccionesResiliente extends TranslateLoader {
  private readonly http = inject(HttpClient);
  private readonly respaldo = inject(CATALOGO_DE_RESPALDO);

  override getTranslation(idioma: string): Observable<TranslationObject> {
    return this.http.get<TranslationObject>(`${PREFIJO_CATALOGO}${idioma}${SUFIJO_CATALOGO}`).pipe(
      timeout(ESPERA_MAXIMA_CATALOGO_MS),
      catchError(() => of(this.respaldo as TranslationObject)),
    );
  }
}

/**
 * Providers de i18n para las cuatro apps.
 *
 * Sustituye al bloque que la Tarea 2.4 duplicó en los cuatro `app.config.ts`,
 * que era fail-hard. Garantiza tres cosas:
 *
 *  1. La app **siempre** arranca: ni el cargador ni el inicializador propagan
 *     errores.
 *  2. Nunca se pinta una clave cruda: si el catálogo remoto no llega, están los
 *     textos esenciales empotrados; si llega incompleto, `traducir()` cae al
 *     mínimo.
 *  3. Español fijo, sin negociar con el navegador: pedir `en.json` (que no
 *     existe) pintaría claves crudas.
 *
 * @param respaldo catálogo empotrado alternativo (por defecto, el mínimo)
 */
export function proveerI18nVendi(
  respaldo?: CatalogoTraducciones,
): (Provider | EnvironmentProviders)[] {
  return [
    ...(respaldo ? [{ provide: CATALOGO_DE_RESPALDO, useValue: respaldo }] : []),
    ...provideTranslateService({
      // `fallbackLang`/`lang` sustituyen a `defaultLanguage`, deprecado en
      // @ngx-translate/core 17.
      fallbackLang: IDIOMA_POR_DEFECTO,
      lang: IDIOMA_POR_DEFECTO,
      loader: { provide: TranslateLoader, useClass: CargadorDeTraduccionesResiliente },
    }),
    provideAppInitializer(() => {
      const traductor = inject(TranslateService);
      // Se espera al catálogo para que el primer render no pinte `app.titulo`,
      // pero el `catch` es la diferencia entre "arranca con textos mínimos" y
      // "pantalla en blanco". El cargador ya no rechaza; el catch cubre el
      // resto de modos de fallo (store no inicializado, JSON corrupto).
      return firstValueFrom(traductor.use(IDIOMA_POR_DEFECTO)).catch(() => undefined);
    }),
  ];
}
