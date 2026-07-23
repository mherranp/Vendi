# @vendi/auth

Identidad (OIDC contra Keycloak), sesión, guards, interceptor de token y
entitlements de plan. El login abre el navegador del sistema vía la fachada de
`@vendi/native`, **nunca** dentro del WebView: los passkeys no funcionan ahí.

Puede importar `@vendi/domain`, `@vendi/native` y `@vendi/data-access`. Es la
librería más externa; ninguna otra la importa.

El doble de Keycloak para tests vive en el punto de entrada secundario
`@vendi/auth/testing`, no en el barril principal: exportarlo desde ahí creaba un
ciclo con la fábrica de `vi.mock('keycloak-js', …)`.

## Construir

```bash
npm run build:libs   # domain, native, ui-kit, data-access y auth, en orden
ng build auth        # solo esta librería
```

El resultado va a `dist/auth`. Es una librería interna del monorepo: se consume
por el mapeo de rutas de `tsconfig.json`, **no** se publica en npm.

## Tests unitarios

El runner es Vitest, a través del builder `@angular/build:unit-test`. En este
workspace no hay Karma: pasar `--browsers` aborta el comando sin ejecutar un
solo test.

```bash
ng test auth --watch=false   # solo esta librería
npm test                     # los 9 proyectos del workspace
```

## Tests de extremo a extremo

El login con passkey se verifica de extremo a extremo con Playwright, por el
dominio y a través de Traefik:

```bash
npm run verificar:passkey
```
