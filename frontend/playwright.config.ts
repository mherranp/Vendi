import { defineConfig, devices } from '@playwright/test';

import { REGLAS_DE_RESOLUCION } from './e2e/helpers/stack';

/**
 * Configuración de las pruebas de extremo a extremo de Vendi.
 *
 * Harness cosechado de `/Users/maoherran/BaseSaaS/frontend/playwright.config.ts`
 * con TRES cambios que no son cosméticos y que conviene entender antes de
 * tocar nada aquí.
 *
 * ---------------------------------------------------------------------------
 * 1. NO se usa `ignoreHTTPSErrors`
 * ---------------------------------------------------------------------------
 * BaseSaaS lo activaba ("los certificados autofirmados están bien, probamos
 * comportamiento de UI, no la cadena TLS"). En Vendi es exactamente al revés:
 * `mkcert -install` dejó la CA local en el llavero del sistema precisamente
 * para que la validación funcione sola. Si un día fallara, sería una señal
 * REAL de que algo no está donde creemos —un certificado caducado, un router
 * sirviendo el certificado equivocado, un MITM—, y `ignoreHTTPSErrors` es la
 * bandera que taparía justo eso. Se queda apagada.
 *
 * ---------------------------------------------------------------------------
 * 2. La resolución de `*.vendi.co` se fija a 127.0.0.1 DENTRO del navegador
 * ---------------------------------------------------------------------------
 * El dominio `vendi.co` NO pertenece al dueño del producto: está registrado
 * por un tercero y resuelve públicamente a una IP ajena. Mientras no exista
 * `/etc/resolver/vendi.co` (lo instala el dueño, exige sudo), cualquier
 * petición a `*.vendi.co` que no fije la resolución SALE A INTERNET, al
 * servidor de ese tercero. Ya pasó una vez y un `client_secret` acabó fuera.
 *
 * `--host-resolver-rules` mapea todo el dominio al bucle local dentro de
 * Chromium, conservando el `Host` y el SNI reales —que es lo que hace que
 * Traefik enrute y que el certificado valide—. Es el equivalente de
 * `curl --resolve host:443:127.0.0.1`, y es INNEGOCIABLE: quitarlo no rompe
 * las pruebas de forma visible, las manda a un servidor que no es nuestro.
 *
 * Las llamadas HTTP que hacen los specs fuera del navegador (API de
 * administración de Keycloak) usan `pedir()` de `e2e/helpers/stack.ts`, que
 * aplica la misma protección por el lado de Node.
 *
 * ---------------------------------------------------------------------------
 * 3. Un solo trabajador y sin paralelismo
 * ---------------------------------------------------------------------------
 * Los dos specs mutan estado global del realm: `login-passkey` da de baja y
 * vuelve a registrar la credencial del dueño de demostración, y `tenants-crud`
 * crea y elimina negocios (que son Organizations de Keycloak). Con varios
 * trabajadores, `--repeat-each=5` —el ataque que pide la sección de QA de la
 * Etapa 5— se convertiría en cinco copias del mismo spec peleándose por el
 * mismo usuario. Serializar cuesta minutos y compra determinismo.
 *
 * Por la misma razón NO hay reintentos en local: un reintento que pasa a la
 * segunda es un flake escondido. En CI se permite uno solo para absorber la
 * lentitud de arranque del stack, nunca para tapar carreras.
 */
export default defineConfig({
  testDir: './e2e',
  // Ver nota 3: los specs comparten estado del realm.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Un login con passkey completo (dos ceremonias WebAuthn + dos redirecciones
  // al IdP) tarda del orden de 20 s en un stack frío.
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // Ver nota 1. NO añadir `ignoreHTTPSErrors`.
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          // Ver nota 2. Se mapean el dominio y todos sus subdominios. La regla
          // se deriva de BASE_DOMAIN para que renombrar la flota no deje las
          // pruebas apuntando al dominio antiguo.
          args: [`--host-resolver-rules=${REGLAS_DE_RESOLUCION}`],
        },
      },
    },
  ],
});
