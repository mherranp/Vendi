/**
 * Prueba de humo de la superficie pública de `domain`.
 *
 * Verifica que el barril `public-api.ts` se resuelve y se carga sin explotar:
 * atrapa reexportaciones a archivos borrados o renombrados, que es el modo de
 * fallo típico de un barril en un monorepo con librerías.
 *
 * Existe también porque el builder `@angular/build:unit-test` aborta con
 * "No tests found" cuando un proyecto no tiene ni un `.spec.ts`, lo que hacía
 * fallar `npm test` en todo el workspace. Se reemplaza por las pruebas reales
 * de la librería en cuanto esta tenga código.
 */
import * as api from './public-api';

describe('public-api de domain', () => {
  it('debería cargarse sin errores', () => {
    expect(api).toBeDefined();
  });
});
