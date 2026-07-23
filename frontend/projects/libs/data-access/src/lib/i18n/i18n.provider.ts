import { HttpClient, HttpContext } from '@angular/common/http';
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
import { Observable, catchError, firstValueFrom, map, of, timeout } from 'rxjs';
import { CATALOGO_MINIMO_ES, CatalogoTraducciones } from './catalogo-minimo';
import { SILENCIAR_AVISO_ERROR } from '../interceptors/error.interceptor';

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
    return this.http
      .get<TranslationObject>(`${PREFIJO_CATALOGO}${idioma}${SUFIJO_CATALOGO}`, {
        // El fallo de esta petición está contemplado y se resuelve solo con el
        // catálogo empotrado: sacarle un aviso de error al usuario sería ruido
        // por algo que la app acaba de arreglar por su cuenta.
        context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true),
      })
      .pipe(
        timeout(ESPERA_MAXIMA_CATALOGO_MS),
        // **Fusión, no sustitución.** El catálogo remoto es el de la app y solo
        // trae lo suyo; el empotrado es el inventario completo de lo que
        // `ui-kit` y los shells pueden pintar. Antes se devolvía el remoto tal
        // cual y bastaba con que un `es.json` no tuviera `comun.reintentar`
        // —el caso real de las cuatro apps— para que el pipe `| translate`
        // pintara la clave cruda: ngx-translate no cae al respaldo, solo
        // `traducir()` lo hace, y las plantillas usan el pipe.
        //
        // Fusionando, el respaldo cubre por debajo TODO lo que el remoto omita,
        // y el remoto sigue mandando donde sí define la clave (así cada app
        // conserva su propio `app.titulo`).
        map(
          (remoto) =>
            fusionarCatalogos(
              this.respaldo,
              remoto as unknown as CatalogoTraducciones,
            ) as TranslationObject,
        ),
        catchError(() => of(structuredClone(this.respaldo) as TranslationObject)),
      );
  }
}

/**
 * Fusión profunda de dos catálogos: lo del segundo gana clave a clave.
 *
 * No muta ninguno de los dos. Importa porque ngx-translate escribe sobre el
 * objeto que recibe, y el catálogo de respaldo es una constante compartida por
 * toda la aplicación: devolverlo sin copiar dejaría que una traducción cargada
 * después lo contaminara para siempre.
 */
export function fusionarCatalogos(
  base: CatalogoTraducciones,
  encima: CatalogoTraducciones,
): CatalogoTraducciones {
  const resultado: CatalogoTraducciones = { ...base };
  for (const [clave, valor] of Object.entries(encima ?? {})) {
    if (valor === undefined || valor === null) {
      continue;
    }
    const previo = resultado[clave];
    if (esObjeto(valor)) {
      resultado[clave] = fusionarCatalogos(esObjeto(previo) ? previo : {}, valor);
    } else {
      resultado[clave] = String(valor);
    }
  }
  return resultado;
}

function esObjeto(valor: unknown): valor is CatalogoTraducciones {
  return typeof valor === 'object' && valor !== null && !Array.isArray(valor);
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
