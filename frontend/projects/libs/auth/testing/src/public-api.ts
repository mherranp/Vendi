/*
 * Public API Surface of auth/testing
 *
 * Punto de entrada **secundario**: el doble de `keycloak-js` y las ayudas para
 * arrancar un `AuthService` real contra él.
 *
 * Está separado del punto de entrada principal por una razón concreta, no por
 * estética. Los specs sustituyen `keycloak-js` con
 *
 *     vi.mock('keycloak-js', async () => ({
 *       default: (await import('auth/testing')).KeycloakFake,
 *     }));
 *
 * Si el doble se exportara desde `auth` a secas, esa fábrica importaría el
 * barril `auth` → que importa `AuthService` → que importa `keycloak-js` → que
 * es justo el módulo que la fábrica está resolviendo: un ciclo que cuelga al
 * ejecutor de pruebas en lugar de fallar. Este punto de entrada no depende de
 * `AuthService`, así que no hay ciclo posible.
 *
 * Además queda fuera del bundle de producción de las apps: nadie puede
 * importar el doble por accidente desde código que se despliega.
 */

export {
  CONFIG_AUTH_DE_PRUEBA,
  KeycloakFake,
  ORG_POR_DEFECTO,
  arrancarSesionFalsa,
} from './lib/keycloak.fake';
export type {
  OpcionesDeSesionFalsa,
  PerfilFalso,
  ServicioAuthArrancable,
} from './lib/keycloak.fake';
