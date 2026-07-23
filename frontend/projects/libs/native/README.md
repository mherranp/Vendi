# @vendi/native

Fachadas de las APIs de plataforma con fallback web. Es el **único** punto del
workspace autorizado a importar `@capacitor/*`: así la misma base de código
corre como PWA y como app nativa sin que el resto se entere de en cuál está.

No importa **ninguna** otra librería `@vendi/*` (ni `@vendi/domain`, ni
`@vendi/ui-kit`, ni `@vendi/data-access`, ni `@vendi/auth`) ni `dexie`:
`native` solo envuelve APIs de plataforma y no conoce dominio, UI,
persistencia ni sesión. El ESLint del workspace
(`projects/libs/native/eslint.config.js`) hace cumplir esta frontera.

## Construir

```bash
npm run build:libs   # domain, native, ui-kit, data-access y auth, en orden
ng build native      # solo esta librería
```

El resultado va a `dist/native`. Es una librería interna del monorepo: se
consume por el mapeo de rutas de `tsconfig.json`, **no** se publica en npm.

## Tests unitarios

El runner es Vitest, a través del builder `@angular/build:unit-test`. En este
workspace no hay Karma: pasar `--browsers` aborta el comando sin ejecutar un
solo test.

```bash
ng test native --watch=false   # solo esta librería
npm test                       # los 9 proyectos del workspace
```

## Tests de extremo a extremo

Los E2E son de Playwright y viven en `frontend/e2e`, no por librería:

```bash
npm run e2e
```
