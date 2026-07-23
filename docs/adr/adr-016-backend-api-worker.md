# ADR-016 — Backend: monolito modular (`api`) + `worker`, sobre `vendi-core`

**Fecha:** 2026-07-22 · **Estado:** Firmada (Fase 0)

## Contexto

Vendi arranca con un equipo pequeño y un producto cuyo dominio todavía no está
escrito (el POS es Fase 1). Existía además `BaseSaaS`, una plataforma propia con
años de trabajo en lo transversal: autenticación, auditoría, retención,
mensajería, almacenamiento, observabilidad.

## Decisión

Dos unidades de despliegue, una librería compartida:

- **`backend/libs/vendi-core`** — lo transversal, cosechado de `base_saas` con
  la tenancy reescrita. Es la librería, no un servicio.
- **`backend/services/api`** — monolito modular FastAPI. Los módulos de negocio
  (`tenants`, `auth`, `audit`, esqueleto de `platform`) son paquetes, no
  servicios.
- **`backend/services/worker`** — proceso aparte: drena el outbox hacia RabbitMQ
  y corre los trabajos programados (retención).

## Por qué el worker sí es un proceso aparte y los módulos no

La frontera de despliegue se pone donde hay una diferencia real de operación, no
donde hay una diferencia conceptual.

- El **worker** tiene ciclo de vida propio (bucle de sondeo, no petición), otro
  perfil de fallo (una tarea atascada no debe tumbar la API) y otra escala. Y
  sobre todo: usa la fábrica de sesión de **plataforma**, porque drena la cola de
  todos los negocios en una pasada. Meterlo dentro de la API pondría un
  `BYPASSRLS` vivo en el mismo proceso que atiende peticiones.
- Los **módulos de negocio** comparten transacción, sesión y despliegue. Partirlos
  en servicios hoy compraría latencia de red y consistencia eventual a cambio de
  una independencia que nadie necesita con un equipo de este tamaño.

## Alternativas descartadas

- **Microservicios desde el día 1.** Coste operativo sin ningún beneficio a esta
  escala, y con un dominio aún sin escribir es imposible poner las fronteras en
  el sitio correcto: se pondrían mal y costaría más deshacerlas.
- **Adoptar `base_saas` como dependencia.** Se descartó por la tenancy: BaseSaaS
  es schema-per-tenant y realm-per-tenant, justo las dos decisiones que Vendi
  invierte (ADR-013 y ADR-014). Sería una dependencia que hay que contradecir en
  cada archivo. La cosecha **quirúrgica** —copiar, adaptar, y dejar escrito de
  dónde vino cada cosa y qué cambió— resultó más barata y deja el resultado bajo
  control propio. El candado `test_candado_cosecha.py` verifica que no queda
  **código** del mundo anterior (los comentarios que citan el origen sí quedan,
  y son el activo).

## Almacenamiento: un bucket por región, con prefijo por negocio

**Un solo bucket por región**, con las claves prefijadas por `tenant_id`
(`<tenant_id>/...`). No un bucket por negocio.

Motivo: los proveedores de objetos tienen límites de cientos de buckets por
cuenta y el aprovisionamiento de bucket es lento y con cuota; con miles de
tiendas se choca contra el límite antes que contra ningún problema real. El
aislamiento lo da la ruta más la comprobación en la aplicación —la misma
comprobación que ya se hace para cualquier otro recurso—, y el día que haga
falta granularidad más fina, las políticas por prefijo de IAM existen.

Contrapartida honesta: el aislamiento del almacenamiento **no** lo garantiza el
motor, como sí lo hace RLS en la base. Es código, y el código se puede olvidar.
Por eso el acceso a archivos pasa por un único punto en `vendi_core.files`.

## Catálogo de módulos: qué se implementa en Fase 0 y qué queda en backlog

Fase 0 implementa **`tenants`, `auth`, `audit`** y el esqueleto de `platform`.

Quedan como backlog explícito, con su porqué: `api_keys` (no hay integradores
externos todavía), `webhooks` (ídem), `feature_flags` (con un solo despliegue no
hay nada que conmutar), `notifications` (llega con el fiado, ADR-009),
`account` y `tenant_settings` (necesitan el modelo de datos del MVP para saber
qué se configura).

La razón de listarlos en vez de implementarlos: cada uno de esos módulos, escrito
antes de tener un consumidor, se escribe contra un consumidor imaginado. Se
implementarán cuando exista quien los use, que es cuando se sabrá qué forma
tienen que tener.
