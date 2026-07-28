import { EnvironmentProviders, inject, provideAppInitializer } from '@angular/core';
import { AuthService, ConfiguracionAuth } from './auth.service';

/**
 * Arranca la sesión de Keycloak antes de que se pinte la primera ruta.
 *
 * ## Por qué `check-sso` y no `login-required`
 *
 * Con `login-required`, keycloak-js redirige al IdP **durante el bootstrap**:
 * si Keycloak está caído o tarda, el usuario ve una pantalla en blanco sin
 * ninguna explicación. Con `check-sso` la app arranca siempre; quien manda al
 * login es `authGuard`, que corre cuando ya hay una aplicación viva capaz de
 * enseñar un error. Además, `login-required` no deja sitio para las pantallas
 * de antes del tenant: el selector de negocio (`vendi-tenant`), la de «sin
 * acceso» (`vendi-admin`) y el arranque offline (`vendi-app`) necesitan una
 * aplicación viva aunque no haya sesión.
 *
 * El `catch` es deliberado: `init()` rechaza cuando el IdP no responde, y un
 * inicializador que rechaza aborta el bootstrap de Angular. La consecuencia
 * correcta de «no pude comprobar la sesión» es «arranca sin sesión», no
 * «pantalla en blanco».
 *
 * Vivía copiada en `nucleo/sesion.ts` de las tres apps; la deduplicación es
 * de la Etapa 1.3 (pista web). Depende solo de esta lib, así que aquí está.
 */
export function proveerSesion(config: ConfiguracionAuth): EnvironmentProviders {
  return provideAppInitializer(async () => {
    const auth = inject(AuthService);
    try {
      await auth.init({ ...config, onLoad: 'check-sso' });
    } catch (error) {
      console.error('No se pudo comprobar la sesión con Keycloak; se arranca sin sesión.', error);
    }
  });
}
