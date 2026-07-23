# @vendi/domain

Lógica de negocio pura: modelos y motor de reglas deterministas. Sin Angular,
sin RxJS, sin red, sin persistencia y sin UI. La regla de oro: el código decide,
la IA narra.

Es la capa más interna del workspace: no importa ninguna otra librería de
`@vendi/*`. Todas las demás sí pueden importarla.

## Construir

```bash
npm run build:libs   # domain, native, ui-kit, data-access y auth, en orden
ng build domain      # solo esta librería
```

El resultado va a `dist/domain`. Es una librería interna del monorepo: se
consume por el mapeo de rutas de `tsconfig.json`, **no** se publica en npm.

## Tests unitarios

El runner es Vitest, a través del builder `@angular/build:unit-test`. En este
workspace no hay Karma: pasar `--browsers` aborta el comando sin ejecutar un
solo test.

```bash
ng test domain --watch=false   # solo esta librería
npm test                       # los 9 proyectos del workspace
```

## Tests de extremo a extremo

Los E2E son de Playwright y viven en `frontend/e2e`, no por librería:

```bash
npm run e2e
```
