# @vendi/data-access

Persistencia local (IndexedDB como fuente de verdad offline), cola de
sincronización, cliente de la API, interceptores, avisos al usuario e i18n. El
acceso a plataforma va siempre por `@vendi/native`.

Puede importar `@vendi/domain` y `@vendi/native`. No importa `@vendi/ui-kit` ni
`@vendi/auth`.

## Construir

```bash
npm run build:libs     # domain, native, ui-kit, data-access y auth, en orden
ng build data-access   # solo esta librería
```

El resultado va a `dist/data-access`. Es una librería interna del monorepo: se
consume por el mapeo de rutas de `tsconfig.json`, **no** se publica en npm.

## Tests unitarios

El runner es Vitest, a través del builder `@angular/build:unit-test`. En este
workspace no hay Karma: pasar `--browsers` aborta el comando sin ejecutar un
solo test.

```bash
ng test data-access --watch=false   # solo esta librería
npm test                            # los 9 proyectos del workspace
```

## Cliente de la API

Los tipos del cliente se generan desde el `openapi.json` del backend; no se
editan a mano:

```bash
npm run codegen:api
```

## Tests de extremo a extremo

Los E2E son de Playwright y viven en `frontend/e2e`, no por librería:

```bash
npm run e2e
```
