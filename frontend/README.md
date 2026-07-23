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

| App            | Actor                                                                                             | Puerto de desarrollo | Script                 |
| -------------- | ------------------------------------------------------------------------------------------------- | -------------------- | ---------------------- |
| `vendi-app`    | Usuarios del tenant en la tienda (dueño, cajero, almacenista). Móvil Capacitor, POS offline-first | 4200                 | `npm start`            |
| `vendi-portal` | Público y prospectos: producto, planes, suscripción                                               | 4201                 | `npm run start:portal` |
| `vendi-tenant` | Dueño del negocio desde web: portal administrativo del tenant                                     | 4202                 | `npm run start:tenant` |
| `vendi-admin`  | Nosotros: consola de plataforma para administrar tenants                                          | 4203                 | `npm run start:admin`  |

Cada app tiene un puerto propio para que se puedan levantar varias en paralelo.

## Librerías

| Lib           | Responsabilidad                                                                                       |
| ------------- | ----------------------------------------------------------------------------------------------------- |
| `domain`      | Lógica de negocio pura: modelos y reglas deterministas. Sin Angular, sin RxJS, sin red                |
| `native`      | Fachadas de las APIs de plataforma con fallback web. Único punto autorizado a importar `@capacitor/*` |
| `data-access` | Capa HTTP (`ApiService`, interceptores, cliente generado de la API) y persistencia local con Dexie    |
| `auth`        | Identidad OIDC contra Keycloak, sesión y entitlements de plan                                         |
| `ui-kit`      | Presentación: componentes, directivas, pipes y tokens de diseño                                       |

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
  la capa HTTP del monorepo.
- `vendi-app` es la única app que corre dentro del contenedor nativo y la única
  que puede importar `native`. Aun así **tampoco importa `@capacitor/*`**: la
  frontera está declarada en su `eslint.config.js`, igual que en las apps web.
  «`native` es el único punto autorizado a importar `@capacitor/*`» significa
  exactamente eso, sin excepciones para la app móvil; lo que la app consume es
  la fachada (`esPlataformaNativa()`, `nombreDePlataforma()`).

Cada frontera se declara una sola vez, en el `eslint.config.js` del proyecto,
mediante el helper `fronteraDeCapa()` de [`eslint.fronteras.js`](./eslint.fronteras.js).
El helper emite dos reglas a la vez a partir de un único grupo de patrones, para
tapar los tres agujeros conocidos de `no-restricted-imports`:

| Forma del import                                  | Quién la ve             |
| ------------------------------------------------- | ----------------------- |
| `import { X } from 'data-access'`                 | `no-restricted-imports` |
| `import('data-access')` (lazy loading de Angular) | `no-restricted-syntax`  |
| `import('data-access').Tipo` (posición de tipo)   | `no-restricted-syntax`  |
| `require('data-access')`                          | `no-restricted-syntax`  |
| `from '../../node_modules/@capacitor/core'`       | `no-restricted-syntax`  |

Las tres formas dinámicas se le escapan a `no-restricted-imports` porque la regla
no visita `ImportExpression`. La cuarta se le escapa cuando el patrón lleva barra
(`@capacitor/*`): sus patrones se resuelven con semántica `.gitignore` y quedan
anclados al principio del especificador, así que escribir la ruta relativa a mano
rodeaba la frontera. Ambas cosas están verificadas con sondas; si tocas el helper,
vuelve a probar **las cinco formas** antes de darlo por bueno.

## Configuración por entorno

Cada app tiene dos archivos en `src/environments/`:

| Archivo                      | Cuándo se usa                                   | Qué apunta      |
| ---------------------------- | ----------------------------------------------- | --------------- |
| `environment.ts`             | Configuración `production` (la **por defecto**) | `*.vendi.co`    |
| `environment.development.ts` | Configuración `development` (`npm run start:*`) | `*.vendi.local` |

El intercambio lo hace `fileReplacements` en la configuración `development` de
`angular.json`. La dirección importa: **el archivo de producción es el que se
compila salvo que se pida `development`**, así que un descuido nunca filtra una
URL de desarrollo al bundle de producción ni al AAB; a lo sumo hace que el
servidor de desarrollo apunte a producción, que es un fallo ruidoso e inmediato.

Identidad por app (realm `vendi-co` en las tres que la usan):

| App            | `clientId`    | Redirect URI de desarrollo | Notas                                                      |
| -------------- | ------------- | -------------------------- | ---------------------------------------------------------- |
| `vendi-app`    | `vendi-web`   | `http://localhost:4200/*`  | En Fase 0 aún no hace login (auth móvil = subproyecto 2)   |
| `vendi-tenant` | `vendi-web`   | `http://localhost:4202/*`  | Comparte cliente público PKCE con la app móvil             |
| `vendi-admin`  | `vendi-admin` | `http://localhost:4203/*`  | Cliente propio: no comparte redirect URIs con los negocios |
| `vendi-portal` | —             | —                          | Sitio público: sin Keycloak en Fase 0                      |

**En desarrollo las apps NO se sirven por Traefik**: se sirven con `ng serve`,
así que el redirect URI que el navegador presenta a Keycloak es
`http://localhost:420x/...`, no `https://app.vendi.local/...`. Esos tres
`localhost` están registrados en `infra/keycloak/realm-vendi-co.json` —
`vendi-web` lleva 4200 y 4202, `vendi-admin` lleva 4203— junto a los hosts de
producción `https://app.${VENDI_BASE_DOMAIN}/*` y
`https://admin.${VENDI_BASE_DOMAIN}/*`, que Keycloak sustituye al importar
(`KC_SPI_IMPORT_SINGLE_FILE_REPLACE_PLACEHOLDERS=true`).

Si cambias el puerto de una app en `angular.json`, **cambia también el redirect
URI del cliente en el realm**: si no, el login de la Etapa 4 muere con
`invalid_redirect_uri` y Keycloak solo lo dice en su log de eventos.

## i18n

`ngx-translate` está montado en las cuatro apps desde el primer día (spec §6.4).
El catálogo vive en `projects/<app>/public/i18n/es.json` y se sirve en
`/i18n/es.json`.

El idioma está **fijado a `es`**, no se negocia con el navegador: Fase 0 es solo
Colombia y no existe `en.json`. Un navegador en inglés no debe poder provocar un
404 del catálogo y una pantalla llena de claves crudas. Cuando llegue el segundo
país se añade el catálogo y se activa la detección.

Un `provideAppInitializer` espera a que el catálogo esté cargado antes de
arrancar la aplicación; sin eso el primer render pinta literalmente `app.titulo`.

**Regla de PR:** ninguna cadena visible se escribe a mano en un template, ni en
las apps ni —sobre todo— en las librerías. Todo texto de interfaz pasa por el
pipe `translate` y vive en un catálogo. Una librería que devuelva español
literal es intraducible desde fuera y bloquea la expansión regional.

## Cliente generado de la API

`scripts/codegen-api-client.sh` genera los tipos TypeScript de la API a partir
de su esquema OpenAPI, dentro de `data-access`
(`projects/libs/data-access/src/lib/api-client/`). Ni el esquema ni los tipos se
editan a mano; ver el
[README del directorio generado](./projects/libs/data-access/src/lib/api-client/README.md).

```bash
npm run codegen:api                                        # contra la API viva
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json npm run codegen:api   # congelado
CODEGEN_DRY_RUN=1 npm run codegen:api                      # solo imprime el plan
```

Si la API no responde, el script falla en rojo con el motivo: nunca reutiliza en
silencio el cliente anterior.

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
npm run format:check      # verifica el formato (prettier); `npm run format` lo corrige
npm run codegen:api       # regenera el cliente tipado de la API
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
