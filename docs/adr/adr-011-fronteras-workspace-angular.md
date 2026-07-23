# ADR-011 — Fronteras de importación del workspace Angular

**Fecha:** 2026-07-22 · **Estado:** Firmada (Fase 0)

## Contexto

El workspace Angular tiene cinco librerías (`domain`, `data-access`, `ui-kit`,
`auth`, `native`) y cuatro aplicaciones. Sin una regla mecánica, en seis meses
`ui-kit` importa `HttpClient` «solo para este componente», `domain` importa
`@capacitor/core` «solo para detectar la plataforma», y el grafo de dependencias
se convierte en una bola: ya no se puede construir la web sin arrastrar
Capacitor, ni probar el dominio sin levantar HTTP.

Una convención escrita en un documento no es una frontera. Una regla de ESLint
que rompe la compilación sí.

## Decisión

Cada librería y cada aplicación declara su frontera con `no-restricted-imports`
(helper `fronteraDeCapa` en `frontend/eslint.fronteras.js`), y el mensaje de
error **explica el porqué**, no solo prohíbe:

| Capa | No puede importar | Razón |
|---|---|---|
| `domain` | todo: `@angular/*`, `rxjs`, `@capacitor/*`, `dexie` y cualquier lib `@vendi/*` | TypeScript puro, sin framework: modelos y reglas de negocio sin HTTP, sin UI, sin plataforma. La reactividad vive en `data-access` y en las apps |
| `data-access` | `ui-kit`, `auth`, `@capacitor/*` | la dependencia va `auth → data-access`, no al revés |
| `ui-kit` | `@angular/common/http`, `@capacitor/*`, `dexie`, `data-access`, `auth`, `native` | presentación pura: entra por inputs, sale por outputs |
| `auth` | `ui-kit`, `dexie`, `@capacitor/*` | identidad y entitlements; para abrir el navegador usa `native` |
| `native` | `domain`, `ui-kit`, `data-access`, `auth`, `dexie` | solo envuelve APIs de plataforma |
| `vendi-portal`, `vendi-tenant`, `vendi-admin` | `@capacitor/*`, `dexie`, `native` | son web pura |
| `vendi-app` | `@capacitor/*` (directo) | tiene que pasar por la fachada de `native` |

## La regla que sostiene todo lo demás

**`native` es el único punto del workspace autorizado a importar
`@capacitor/*`.** De ahí sale todo: las tres apps web se construyen sin arrastrar
nada nativo, y el día que se cambie de plugin —o de Capacitor— hay exactamente
un archivo que tocar.

## Alternativas descartadas

- **Convención documentada sin herramienta.** Se incumple el primer martes que
  alguien tiene prisa, y nadie lo ve en la revisión porque un import más en un
  archivo largo no llama la atención.
- **Nx con `enforce-module-boundaries`.** Da lo mismo a cambio de adoptar Nx
  entero en un workspace que hoy no lo necesita.

## Consecuencias

- Una violación rompe `npm run lint`, y el job `frontend-lint` de CI es
  bloqueante.
- El mensaje de error es parte de la regla: quien lo lea tiene que entender por
  qué la frontera existe, o la sorteará con un `eslint-disable`.
