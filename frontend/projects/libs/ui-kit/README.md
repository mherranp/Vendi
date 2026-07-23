# @vendi/ui-kit

Presentación pura: componentes, directivas, pipes y tokens de diseño. Sin HTTP,
sin persistencia y sin plataforma nativa. Recibe datos por inputs y emite
eventos por outputs.

Puede importar `@vendi/domain`. No importa `@vendi/data-access`,
`@vendi/auth`, `@vendi/native`, `@angular/common/http`, `@capacitor/*` ni
`dexie` (la lista completa la hace cumplir
`projects/libs/ui-kit/eslint.config.js`). El prefijo de selectores es `vd`.

## Construir

```bash
npm run build:libs   # domain, native, ui-kit, data-access y auth, en orden
ng build ui-kit      # solo esta librería
```

El resultado va a `dist/ui-kit`. Es una librería interna del monorepo: se
consume por el mapeo de rutas de `tsconfig.json`, **no** se publica en npm.

## Tests unitarios

El runner es Vitest, a través del builder `@angular/build:unit-test`. En este
workspace no hay Karma: pasar `--browsers` aborta el comando sin ejecutar un
solo test.

```bash
ng test ui-kit --watch=false   # solo esta librería
npm test                       # los 9 proyectos del workspace
```

## Contraste de color

Los tokens de diseño tienen su propio candado de accesibilidad:

```bash
npm run verificar:contraste
```

## Tests de extremo a extremo

Los E2E son de Playwright y viven en `frontend/e2e`, no por librería:

```bash
npm run e2e
```
