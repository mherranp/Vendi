import { EnvironmentProviders, inject, provideAppInitializer } from '@angular/core';
import { AuthService, ConfiguracionAuth } from 'auth';

/**
 * Arranca la sesión de Keycloak antes de que se pinte la primera ruta.
 *
 * El login del realm `vendi-co` es **passwordless por passkey**
 * (`browserFlow: browser-passwordless` en `infra/keycloak/realm-vendi-co.json`).
 * Eso es configuración del realm, no del cliente: aquí no hay nada que activar.
 * Lo único que esta app tiene que hacer bien es PKCE —lo pone `AuthService`—
 * y no meter el login en un WebView, cosa que en web no aplica y en móvil
 * resuelve la librería `native` (subproyecto 2).
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
 * Además, `login-required` no deja sitio para el selector de negocio: un dueño
 * con dos tiendas llega autenticado pero sin tenant activo, y necesita una
 * aplicación viva donde elegir.
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
