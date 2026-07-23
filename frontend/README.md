# Frontend de Vendi

Workspace de Angular 21 con cuatro aplicaciones y cinco librerías. Generado con
Angular CLI 21.2.17.

## Requisito previo: compilar las librerías

**`ng serve` y `ng build` pelados no funcionan en un árbol recién clonado.** Los
alias de `tsconfig.json` (`auth`, `data-access`, `domain`, `native`, `ui-kit`)
apuntan a `dist/`, no al código fuente: es la única forma de que las librerías se
compilen como paquetes independientes con ng-packagr sin violar `rootDir`. Si
`dist/` no existe, la resolución de módulos falla.

Antes de servir o compilar cualquier aplicación hay que ejecutar:

```bash
npm run build:libs
```

Los scripts `start:*`, `build:*`, `test` y `sync` de `package.json` ya lo
encadenan con hooks `pre*`, así que **usa siempre los scripts de npm, no `ng`
directamente**. Solo cuando trabajes sobre una librería y no sobre una app
necesitarás volver a lanzar `npm run build:libs` a mano para que las apps vean
el cambio.

## Aplicaciones

| App | Actor | Puerto de desarrollo | Script |
|---|---|---|---|
| `vendi-app` | Usuarios del tenant en la tienda (dueño, cajero, almacenista). Móvil Capacitor, POS offline-first | 4200 | `npm start` |
| `vendi-portal` | Público y prospectos: producto, planes, suscripción | 4201 | `npm run start:portal` |
| `vendi-tenant` | Dueño del negocio desde web: portal administrativo del tenant | 4202 | `npm run start:tenant` |
| `vendi-admin` | Nosotros: consola de plataforma para administrar tenants | 4203 | `npm run start:admin` |

Cada app tiene un puerto propio para que se puedan levantar varias en paralelo.

## Librerías

| Lib | Responsabilidad |
|---|---|
| `domain` | Lógica de negocio pura: modelos y reglas deterministas. Sin Angular, sin RxJS, sin red |
| `native` | Fachadas de las APIs de plataforma con fallback web. Único punto autorizado a importar `@capacitor/*` |
| `data-access` | Capa HTTP (`ApiService`, interceptores, cliente generado de la API) y persistencia local con Dexie |
| `auth` | Identidad OIDC contra Keycloak, sesión y entitlements de plan |
| `ui-kit` | Presentación: componentes, directivas, pipes y tokens de diseño |

### Fronteras de dependencia (ADR-011)

El grafo de dependencias permitido está codificado como reglas de ESLint, no
como convención escrita:

- `domain` no importa nada: ni framework, ni red, ni persistencia, ni UI.
- `native` no conoce dominio, UI, persistencia ni sesión.
- `data-access` no conoce UI ni sesión. Accede a plataforma vía `native`.
- `auth` **sí** puede importar `data-access` (necesita `/me/entitlements`); la
  dirección inversa está prohibida.
- `ui-kit` no hace HTTP ni toca Capacitor o Dexie.
- Las tres apps web (`vendi-portal`, `vendi-tenant`, `vendi-admin`) no pueden
  usar `@capacitor/*`, `dexie` ni `native`. Sí pueden usar `data-access`, que es
  la capa HTTP del monorepo. Solo `vendi-app` accede a plataforma nativa.

Cada frontera se declara una sola vez, en el `eslint.config.js` del proyecto,
mediante el helper `fronteraDeCapa()` de [`eslint.fronteras.js`](./eslint.fronteras.js).
El helper emite dos reglas a la vez: `no-restricted-imports` para el import
estático y `no-restricted-syntax` para el dinámico —`import()`,
`import('...').Tipo` y `require()`—, porque `no-restricted-imports` no inspecciona
`ImportExpression` y el lazy loading de Angular abriría un boquete en la frontera.

## Comandos

```bash
npm run build:libs        # compila las cinco librerías a dist/ (prerrequisito de todo lo demás)
npm start                 # sirve vendi-app en :4200
npm run start:portal      # sirve vendi-portal en :4201
npm run start:tenant      # sirve vendi-tenant en :4202
npm run start:admin       # sirve vendi-admin en :4203
npm run build             # compila vendi-app para producción
npm test -- --watch=false # ejecuta la suite de los nueve proyectos
npm run lint              # lint de los nueve proyectos, incluidas las fronteras ADR-011
```

### Móvil (Capacitor 8)

```bash
npm run sync              # compila vendi-app y sincroniza con android/ e ios/
npm run android           # compila, sincroniza y ejecuta en Android
npm run android:studio    # abre el proyecto en Android Studio
```

## Convenciones

- **Todo en español**: código comentado, documentación, mensajes de error y de
  lint, textos de interfaz.
- **Prefijo de selectores `vd`**: `vd-mi-componente` para elementos,
  `vdMiDirectiva` para atributos. Está impuesto por ESLint en todos los
  proyectos.
- **TypeScript estricto**: `strict`, `noImplicitOverride`,
  `noPropertyAccessFromIndexSignature`, `noImplicitReturns` y
  `noFallthroughCasesInSwitch` activos en todo el workspace.
