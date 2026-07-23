# ADR-014 — Un realm por región, una Organization de Keycloak por negocio

**Fecha:** 2026-07-22 · **Estado:** Firmada (Fase 0)
**Evidencia:** `docs/superpowers/specs/2026-07-22-verificacion-kc-organizations.md` (spike 1.1)

## Contexto

BaseSaaS, de donde se cosechó el código, usaba **un realm de Keycloak por
inquilino**. Con miles de tiendas eso son miles de realms: cada uno con sus
claves, sus flujos, su tema y su ciclo de importación. Cambiar la política de
passkeys pasa a ser un bucle sobre miles de realms que puede fallar a la mitad.

Keycloak 26 trae **Organizations** (GA), pensado exactamente para esto: varios
inquilinos dentro de un mismo realm.

## Decisión

**Un realm por región** (`vendi-co` para Colombia) y **una Organization por
negocio** dentro de él.

- `name` = `alias` = **`str(tenant_id)`** — el UUID con guiones.
- El nombre comercial del negocio va en `description`.
- El claim `organization` del token trae el alias, que **es** el `tenant_id`:
  el negocio se resuelve del token sin ninguna consulta a Keycloak ni a la base.

## Por qué el alias es un UUID y no el nombre del negocio

Medido: Keycloak exige `name` **único por realm** y devuelve
`409 A organization with the same name already exists`. Dos «Tienda Don Carlos»
en la misma región son dos negocios distintos y ambos tienen derecho a existir.
Si el nombre comercial fuera el `name` de la Organization, el alta de un negocio
fallaría por lo que otro eligió llamarse, y por los 409 se podrían **enumerar
los nombres de los demás negocios** de la región.

**Consecuencia que hay que aceptar con los ojos abiertos: la consola de Keycloak
muestra UUIDs.** Un operador que entre a `accounts.vendi.co` verá una lista de
identificadores y no de nombres de tienda. El nombre legible está ahí, en
`description`, pero no es lo que la consola pone primero. Se acepta porque la
alternativa —nombres legibles como identidad— es la que produce colisiones y
enumeración. Cuando duela de verdad, la salida es una vista propia en
`vendi-admin`, que ya lee la tabla `tenants`, no cambiar la identidad.

## Lo que el spike corrigió del diseño original

1. **El claim `organization` es polimórfico.** El mapper de fábrica emite una
   **lista de alias**; solo con `addOrganizationId=true` emite el mapa
   `alias → {"id": ...}`. El realm como código fija `addOrganizationId=true`,
   pero el parser de `vendi-core` acepta las dos formas: un realm importado a
   medias o un cliente creado a mano devolverían la lista, y un parser que
   asumiera el mapa reventaría con `AttributeError` sobre un `list` — un 500 en
   el camino de autenticación de toda la API.
2. **`scope=organization` a secas no basta.** Con un usuario que pertenece a más
   de una organización hay que pedir **`organization:*`**, o el claim llega
   vacío. Todos los clientes lo piden siempre.
3. **Suspender un negocio es cosa de la aplicación, no del IdP.** Deshabilitar
   la Organization en Keycloak **no impide el login**: solo saca la organización
   del claim, y no invalida los tokens ya emitidos. Por eso el estado
   (`activo` / `suspendido` / `eliminado`) vive en la tabla `tenants` y lo
   comprueba la API en cada petición, con un cache de 60 s que acota la latencia
   entre suspender y dejar de servir.

## Alternativas descartadas

- **Realm por inquilino** (lo heredado). Ver contexto.
- **Organization Groups** (novedad de 26.6). Permitiría modelar sucursales
  dentro de una Organization. **No se adopta**: en Fase 0 no hay modelo de
  sucursales, y adoptar una funcionalidad reciente del IdP para algo que
  todavía no se ha diseñado es comprar acoplamiento a cambio de nada.
- **Sucursales como entidad del IdP.** Se decide lo contrario: **las sucursales
  son datos** del negocio, no estructura de identidad. Una sucursal no tiene
  credenciales; tiene inventario y caja.

## Consecuencias

- Un solo realm que mantener por región: la política de passkeys, el tema y los
  flujos se cambian una vez.
- El realm es **semilla, no estado deseado continuo**: `--import-realm` no
  reimporta sobre un realm existente (medido: `Realm 'vendi-co' already exists.
  Import skipped`). La deriva la detecta `scripts/reconcile-keycloak.sh` y, en el
  subconjunto seguro, la aplica con `RECONCILE_APLICAR_CONFIG=1`.
- Toda la API de Organizations exige `manage-realm`, incluso para leer (medido).
  Por eso hay **dos** credenciales: `vendi-backend` (solo `manage-users`) para la
  API general y `vendi-provisioning` (`manage-realm` + `manage-users`) solo para
  el alta y baja de negocios. Ver D-02 en `docs/deuda-tecnica.md`.
- El dominio de la Organization es sintético (`<tenant_id>.tenants.vendi.co`) y
  verificado. No es obligatorio; se mantiene por unicidad y por dejar abierta la
  puerta a un identity-first por dominio de correo.
