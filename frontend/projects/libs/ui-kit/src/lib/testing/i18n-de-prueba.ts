import { Provider } from '@angular/core';
import { TranslateLoader, TranslationObject, provideTranslateService } from '@ngx-translate/core';
import { CATALOGO_MINIMO_ES } from 'data-access';
import { Observable, of } from 'rxjs';

/**
 * Utilidades de prueba de `ui-kit`. **No forman parte del paquete publicado**:
 * `tsconfig.lib.json` excluye este directorio.
 */

/**
 * Catálogo de los specs de componentes: **es** el catálogo de respaldo que la
 * app empotra en el bundle (`CATALOGO_MINIMO_ES` de `data-access`), no una copia.
 *
 * Que sean el mismo objeto es deliberado y es la corrección de un defecto. Antes
 * había dos catálogos: aquí uno completo, y en producción uno recortado a
 * `app`/`comun`/`layout`/`errores`. Resultado: la suite verde y, en el único
 * escenario que el respaldo existe para cubrir —catálogo HTTP inaccesible, PWA
 * instalada sin red—, la app arrancando con `ui.404.titulo`,
 * `ui.archivos.buscar` o `ui.validacion.requerido` pintados en pantalla. Los
 * componentes usan el pipe `| translate` directo, que devuelve la clave cruda
 * cuando no la encuentra; no pasan por `traducir()`, que sí sabe caer al
 * respaldo.
 *
 * Compartiendo la constante, cada spec de `ui-kit` ejerce exactamente la rama de
 * respaldo de `CargadorDeTraduccionesResiliente`: si alguien añade una clave a
 * una plantilla y no la añade al catálogo empotrado, la suite lo caza aquí en
 * vez de que lo cace un tendero sin conexión.
 *
 * La excepción de frontera que permite este import está documentada en
 * `projects/libs/ui-kit/eslint.config.js`.
 */
export const CATALOGO_DE_PRUEBA: TranslationObject = CATALOGO_MINIMO_ES as TranslationObject;

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    // Copia superficial por nivel: ngx-translate escribe sobre el objeto que
    // recibe, y el catálogo empotrado es una constante compartida.
    return of(structuredClone(CATALOGO_DE_PRUEBA));
  }
}

/** Providers de i18n síncronos para los specs de componentes. */
export function proveerTraduccionDePrueba(): Provider[] {
  return provideTranslateService({
    lang: 'es',
    fallbackLang: 'es',
    loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
  }) as Provider[];
}
