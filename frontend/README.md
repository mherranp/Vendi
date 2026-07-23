# Frontend de Vendi

Workspace de Angular 21 con cuatro aplicaciones y cinco librerías. Generado con
Angular CLI 21.2.17.

## Requisito previo: compilar las librerías

**`ng serve`, `ng build` y `ng test` pelados no funcionan en un árbol recién
clonado.** Los
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

Esto **también aplica a los tests de las librerías**: `npx ng test auth` o
`npx ng test ui-kit` fallan en un árbol limpio, porque sus specs resuelven
`data-access` y `domain` por los mismos alias hacia `dist/`. Si quieres lanzar
un proyecto suelto, compila primero:

```bash
npm run build:libs && npx ng test ui-kit --watch=false
```

`npm test` lo hace por ti (`pretest → build:libs`) y corre los nueve proyectos.

## Aplicaciones

| App            | Actor                                                                                             | Puerto de desarrollo | Script                 |
| -------------- | ------------------------------------------------------------------------------------------------- | -------------------- | ---------------------- |
| `vendi-app`    | Usuarios del tenant en la tienda (dueño, cajero, almacenista). Móvil Capacitor, POS offline-first | 4200                 | `npm start`            |
| `vendi-portal` | Público y prospectos: producto, planes, suscripción                                               | 4201                 | `npm run start:portal` |
| `vendi-tenant` | Dueño del negocio desde web: portal administrativo del tenant                                     | 4202                 | `npm run start:tenant` |
| `vendi-admin`  | Nosotros: consola de plataforma para administrar tenants                                          | 4203                 | `npm run start:admin`  |

Cada app tiene un puerto propio para que se puedan levantar varias en paralelo.

### Qué contiene cada app en Fase 0

- **`vendi-admin`** — login PKCE contra el cliente `vendi-admin` del realm
  `vendi-co`, shell con `FullLayoutComponent` y el CRUD de negocios
  (`/negocios`). El permiso de entrada es `platform:admin`; quien entra
  autenticado y sin él aterriza en `/sin-acceso`, **no** en una consola vacía
  (una tabla sin filas afirmaría que la plataforma no tiene negocios).
- **`vendi-tenant`** — login PKCE contra el cliente `vendi-web`. El realm está
  configurado como passwordless por passkey (`browserFlow:
browser-passwordless`), así que el flujo de passkey es del IdP y aquí no hay
  nada que activar. Página "Mi negocio" (`GET /tenants/me`) y selector para el
  dueño con más de un negocio (`/elegir-negocio`, al que redirige `tenantGuard`).
- **`vendi-app`** — pantalla única "próximamente" y **sin login**. No es una
  tarea pendiente: la auth móvil es el subproyecto 2, porque el login tiene que
  salir al navegador del sistema (los passkeys no funcionan dentro del WebView
  de Capacitor) y eso depende de la fachada de `native`. Lo que sí demuestra en
  Fase 0 es el criterio 4: `ng build vendi-app && npx cap sync android &&
./gradlew bundleDebug` produce un `.aab`. Un spec vigila que no se cuele un
  guard de sesión antes de traer el flujo correcto.
- **`vendi-portal`** — página pública única con el enlace a la consola del
  negocio. Sin captación ni precios: la monetización es el subproyecto 4.

Ojo: en Fase 0 las apps **no** se sirven por Traefik. Los routers de
`infra/traefik/templates/dynamic.yml.tpl` están comentados a la espera de que
exista `frontend/Dockerfile` (Etapa 5), así que en desarrollo se sirven con
`ng serve` en los puertos de arriba, que son los `redirect_uri` registrados en
el realm.

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

| Archivo                      | Cuándo se usa                                   | Qué apunta   |
| ---------------------------- | ----------------------------------------------- | ------------ |
| `environment.ts`             | Configuración `production` (la **por defecto**) | `*.vendi.co` |
| `environment.development.ts` | Configuración `development` (`npm run start:*`) | `*.vendi.co` |

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
`http://localhost:420x/...`, no `https://app.vendi.co/...`. Esos tres
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

Las cuatro apps lo arrancan con **un solo proveedor**, `proveerI18nVendi()` de
`data-access`, en lugar del bloque de ~20 líneas que la Etapa 2 duplicó en cada
`app.config.ts`. Ese bloque era **fail-hard** y ese es el defecto que cierra la
Etapa 3:

- El `provideAppInitializer` esperaba a `use('es')`. Si `/i18n/es.json` no se
  podía descargar —sin red, PWA instalada, 404 tras un despliegue a medias— la
  promesa **rechazaba**, Angular abortaba el bootstrap y el usuario veía una
  **pantalla en blanco**. Para un POS que promete funcionar sin conexión eso no
  es aceptable.
- Ahora el cargador (`CargadorDeTraduccionesResiliente`) no puede fallar: ante
  error o timeout de 5 s devuelve `CATALOGO_MINIMO_ES`, un catálogo empotrado en
  el bundle. El peor caso pasa de "pantalla en blanco" a "arranca en español".
- `CATALOGO_MINIMO_ES` es **completo, no mínimo**, y esto es una invariante que
  se rompió una vez: mientras solo traía `app`/`comun`/`layout`/`errores`, la
  app degradada arrancaba pintando `ui.404.titulo` y un `ui.validacion.requerido`
  debajo de cada campo obligatorio, porque los componentes de `ui-kit` usan el
  pipe `| translate` directo (que devuelve la clave) y no `traducir()`.
  **Toda clave que pueda pintar un componente tiene que estar en el catálogo
  empotrado.** Lo vigilan dos tests: `i18n.provider.spec.ts` (`instant()` tras un
  arranque degradado no devuelve ninguna clave cruda) y
  `ui-kit/src/lib/testing/respaldo-i18n.spec.ts`, que monta los componentes con
  ese mismo catálogo y barre el DOM. Además, `CATALOGO_DE_PRUEBA` de
  `ui-kit/testing` **es** `CATALOGO_MINIMO_ES` —no una copia—, así que toda la
  suite de `ui-kit` se ejecuta contra la ruta degradada de producción y la
  deriva entre los dos catálogos no puede volver a ocurrir. Es el único motivo
  por el que `eslint.config.js` de `ui-kit` abre `data-access` en
  `src/lib/testing/` (directorio que `tsconfig.lib.json` excluye del paquete).
- Y para que ni siquiera se degrade, `ngsw-config.json` de `vendi-app` precarga
  `/i18n/*.json` en un `assetGroup` propio con `installMode: prefetch`. Los dos
  mecanismos son complementarios: el service worker evita el degradado, el
  catálogo empotrado evita la pantalla en blanco cuando no hay service worker
  (primera visita, WebView de Capacitor, navegador que lo bloquea).
- `traducir()` cierra el último hueco: `TranslateService.instant()` devuelve la
  **clave** cuando no la encuentra, y un tendero no debe leer `errores.servidor`.
  El helper cae al catálogo mínimo antes de rendirse.
- **El catálogo remoto se FUSIONA sobre el empotrado, no lo sustituye** (Etapa
  4). Antes se devolvía el `es.json` de la app tal cual, así que bastaba con que
  a un `es.json` le faltara una clave del catálogo empotrado —el caso real de
  `comun.reintentar` en las cuatro apps— para que el pipe `| translate` pintara
  la clave cruda con el catálogo cargado correctamente: la red de seguridad solo
  actuaba cuando el HTTP fallaba, que es justo cuando menos falta hacía. Con la
  fusión, el `es.json` de cada app solo tiene que declarar **lo suyo** y lo que
  quiera sobrescribir; el resto lo cubre `CATALOGO_MINIMO_ES` por debajo.

**Regla de PR:** ninguna cadena visible se escribe a mano en un template, ni en
las apps ni —sobre todo— en las librerías. Todo texto de interfaz pasa por el
pipe `translate` y vive en un catálogo. Una librería que devuelva español
literal es intraducible desde fuera y bloquea la expansión regional.

### Contraste: los tokens de color están bajo candado

Las insignias de estado (`vd-status-badge`) se pintaban con el mismo tono como
texto y como fondo (`color-mix(--vd-acento-X 15%, transparent)`), lo que daba
**2.2:1** en claro: menos de la mitad del 4.5:1 que exige WCAG 2.1 AA, y sobre
un texto de 12 px en mayúsculas. `--vd-texto-terciario` daba 3.97:1 por el mismo
motivo. Ahora cada variante es un **par** fondo/texto que conmuta entero con el
esquema de color, y el texto terciario se compone al 80 % en vez del 70 %.

Que no vuelva a ocurrir lo vigila `scripts/verificar-contraste.mjs`, que parsea
`_tokens.scss` —el archivo real, no una copia— y calcula la razón de contraste
de cada par en claro y en oscuro:

```bash
npm run verificar:contraste
```

No es un spec de vitest porque el runner (esbuild) no tiene cargador para
`.scss`: un test solo podría llevar una copia de los valores, que es exactamente
la segunda fuente de verdad que hace inútil al candado.

## Tema y tokens de diseño

El tema vive en `projects/libs/ui-kit/src/lib/theme/` (`tema.scss` →
`_tokens.scss` + `_utilidades.scss`) y se consume desde el `styles.scss` de cada
app **después** de `mat.theme()`:

```scss
@use '@angular/material' as mat;
html {
  @include mat.theme((...));
}
@use 'tema' as *;
```

`tema` se resuelve por `stylePreprocessorOptions.includePaths` contra
`dist/ui-kit/src/lib/theme`, así que —igual que los alias de TypeScript— hay que
haber ejecutado `npm run build:libs` antes.

Los tokens de superficie y texto **no declaran colores propios**: se derivan de
las variables de sistema de Material 3 (`--mat-sys-*`). Mantener dos paletas
paralelas es exactamente lo que hace que un componente de Material y uno propio
se vean distintos en modo oscuro. El tema de Vendi solo aporta lo suyo: la rampa
de marca, los acentos semánticos, la escala tipográfica, el espaciado y el
objetivo táctil de 48 px (Vendi se usa con el dedo, de pie, detrás de un
mostrador).

### Modo oscuro: `color-scheme` se declara en un solo sitio

`mat.theme()` emite sus variables como `light-dark(claro, oscuro)`, que se
resuelve con el `color-scheme` calculado del elemento. Por eso **`color-scheme`
se declara únicamente en `:root`, dentro de `ui-kit/theme/_tokens.scss`**, junto
a los overrides `--vd-*` del modo oscuro:

| Situación          | Selector                                                              | `color-scheme`   |
| ------------------ | --------------------------------------------------------------------- | ---------------- |
| Por defecto        | `:root`                                                               | `light dark`     |
| Sistema en oscuro  | `@media (prefers-color-scheme: dark) :root:not([data-theme='light'])` | `dark`           |
| Forzado por la app | `:root[data-theme='dark'] / [data-theme='light']`                     | `dark` / `light` |

Los `styles.scss` de las apps **no** deben declarar `color-scheme` (lo que
genera `ng new` es `body { color-scheme: light }`, y hay que borrarlo). Cuando
estuvo declarado en los dos sitios, Material quedaba clavado en claro mientras
los tokens `--vd-*` sí conmutaban con la preferencia del sistema: en cualquier
dispositivo en modo oscuro salían superficies blancas con el texto de marca en
`--vd-marca-300`, ~1.5:1 de contraste, muy por debajo del 4.5:1 de WCAG AA.
Verificado sobre el CSS compilado: en modo oscuro `--vd-superficie-1` resuelve a
`#121316` y `--vd-texto-marca` a `#6ee7b7` (12.1:1); en claro, `#faf9fd` y
`#047857` (5.2:1).

La rampa de marca es **provisional** hasta que exista manual de identidad;
cambiarla es tocar un solo bloque de `_tokens.scss`.

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
npm run verificar:contraste  # candado WCAG AA sobre los tokens de color de ui-kit
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
