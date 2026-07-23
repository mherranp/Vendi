import { EnvironmentProviders, inject, provideAppInitializer } from '@angular/core';
import { AuthService, ConfiguracionAuth } from 'auth';

/**
 * Arranca la sesión de Keycloak antes de que se pinte la primera ruta.
 *
 * ## Por qué `check-sso` y no `login-required`
 *
 * Con `login-required`, keycloak-js redirige al IdP **durante el bootstrap**.
 * Si Keycloak está caído o tarda, el usuario ve una pantalla en blanco sin
 * ninguna explicación, exactamente el modo de fallo que la Etapa 2 ya cerró
 * para el catálogo de i18n. Con `check-sso` la app arranca siempre; quien manda
 * al login es `authGuard`, que corre cuando ya hay una aplicación viva capaz de
 * enseñar un error.
 *
 * Además, `login-required` haría imposible la pantalla "sin acceso": un usuario
 * autenticado sin `platform:admin` necesita que la app exista para poder
 * decirle por qué no puede entrar.
 *
 * El `catch` es deliberado: `init()` rechaza cuando el IdP no responde, y un
 * inicializador que rechaza aborta el bootstrap de Angular. La consecuencia
 * correcta de "no pude comprobar la sesión" es "arranca sin sesión", no
 * "pantalla en blanco".
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
