# ADR-023 — Permisos operativos por empleado: el catálogo que llena `_PERMISOS_CAJERO` y `_PERMISOS_ALMACENISTA`

**Fecha:** 2026-07-27 · **Estado:** Firmada (Fase 1, Etapa 1.1)
**Origen:** `docs/plan-maestro.md` §3 (Multi-empleado) y §7 (Fase 1).
Complementa ADR-015 (los roles de negocio son roles de realm) y cierra el
«vacío a propósito» declarado en
`backend/libs/vendi-core/src/vendi_core/auth/policies.py`.

## Contexto

Fase 0 dejó los tres roles de negocio sembrados en el realm, pero
`_PERMISOS_CAJERO` y `_PERMISOS_ALMACENISTA` están vacíos «a propósito»: sus
permisos son los del modelo de datos del MVP, que no existía. Con los ADRs de
dominio de Fase 1 (ventas ADR-018, catálogo e inventario ADR-019/ADR-020,
caja ADR-021, fiado ADR-022) el modelo ya existe y toca decidir tres cosas: qué permisos
concretos lleva cada rol, quién puede anular y cerrar (los gestos con dinero),
y cómo se verifica. El marco no cambia: permiso = `recurso:accion` como rol de
realm, autorización solo contra el JWT, Keycloak como fuente de verdad tras la
siembra (ADR-015, `policies.py`).

## Decisión

Catálogo nuevo de permisos de dominio, mínimo y cerrado (se amplía solo con
ADR nuevo):

```
venta:crear        venta:anular
caja:leer          caja:abrir        caja:cerrar      caja:movimiento
producto:leer      producto:editar
inventario:ajustar
compra:crear
cliente:gestionar  fiado:crear       fiado:abonar
reporte:leer
```

Reparto por rol (va a `PERMISOS_POR_ROL` como semilla; tras la siembra se
edita en Keycloak):

- **`dueno`** — todo lo anterior, más lo que ya tiene (`tenant:read`,
  `tenant:update`, `audit:read`). Sigue sin permisos de plataforma.
- **`cajero`** — `venta:crear`, `caja:leer`, `caja:abrir`, `caja:movimiento`,
  `producto:leer`, `cliente:gestionar`, `fiado:crear`, `fiado:abonar`. Lo que
  NO tiene es la decisión: **no anula ventas, no cierra la caja, no ajusta
  inventario, no ve reportes**. Anular y arquear son los dos gestos con los
  que se desfalca una tienda; quedan en manos del dueño en el MVP. El cajero
  abre su caja y vende; el dueño cuadra.
- **`almacenista`** — `producto:leer`, `producto:editar`,
  `inventario:ajustar`, `compra:crear`. No vende, no toca caja ni fiado: su
  trabajo es que el estante y el sistema digan lo mismo.

La verificación es la que ya existe y no gana excepciones:
`require_permission(...)` contra `realm_access.roles` del JWT, sin consulta a
base de datos en la ruta caliente. Los endpoints de dinero (`anular`,
`cerrar`, `ajustar`) lo declaran en el router; el 403 es la respuesta
correcta y esperada, no un error a ocultar. El límite de empleados por tier
(1/2/3 según ADR-010) se aplica en el endpoint de invitación —que cuenta
miembros de la Organization (ADR-014) contra la suscripción—, no en la
autorización: un token válido con su permiso siempre autoriza; lo que el tier
restringe es cuántas invitaciones se pueden emitir.

## Alternativas descartadas

- **Permisos por empleado editables (matriz configurable).** El tendero no
  quiere configurar una matriz: quiere decir «María es cajera». Tres roles
  fijos cubren el piloto; la matriz es la puerta de entrada al soporte
  eterno. Si el piloto pide granularidad, vendrá con su ADR.
- **Permisos en base de datos por tenant en vez de en el token.** Reintroduce
  la consulta por petición que ADR-015 eliminó, y una segunda fuente de
  verdad además de Keycloak. La autorización lee el token; punto.
- **Un rol `administrador` intermedio entre dueño y cajero.** Con máximo 3
  empleados (ADR-010) no hay organización que administrar: el administrador
  ES el dueño. Rol cuarto = concepto cuarto que explicar en cada venta.

## Consecuencias

- Comparten espacio de nombres con los roles de realm y se distinguen por
  forma (`recurso:accion`), como ya firmó ADR-015; estos nombres entran al
  `PERMISSION_CATALOG` y por tanto al candado que lo recorre.
- La siembra cambia: `roles_de_realm_del_grupo('cajero')` pasa a mapear 9
  roles de realm en vez de 1. Los realms ya aprovisionados (demo) se
  resiembran o se editan a mano en Keycloak; el código asume la semilla nueva.
- Un permiso que nadie tiene en el token del dueño es un bug de siembra, no
  de autorización: el check 23 de `verify-setup.sh` (el token del dueño trae
  `dueno`) se extiende para exigir también `venta:crear` y `caja:cerrar` en
  ese mismo token.
- La app oculta lo que el usuario no puede hacer leyendo los mismos claims
  del token (el backend sigue siendo el que manda; la UI solo ahorra el 403).

## Tablas, eventos y candado

- **Tablas nuevas:** ninguna. La membresía vive en la Organization de
  Keycloak (ADR-014) y los permisos en el JWT (ADR-015); añadir una tabla de
  asignación por tenant sería una segunda fuente de verdad de la pregunta que
  el token ya responde.
- **Eventos de outbox:** ninguno nuevo. La invitación de empleado queda en
  `audit_events` (módulo `audit` existente); no hay consumidor asíncrono que
  justifique evento.
- **Candado:** test de autorización por gesto con dinero —cajero que anula
  venta → 403, cajero que cierra caja → 403, almacenista que cobra fiado →
  403, y los mismos gestos con token de dueño → 200— al estilo de
  `test_un_rol_ausente_deniega_de_verdad` (distingue «deniega porque no lo
  tiene» de «deniega siempre») + test de que `PERMISOS_POR_ROL` solo contiene
  permisos declarados en `PERMISSION_CATALOG` + extensión del check 23 de
  `verify-setup.sh`.
