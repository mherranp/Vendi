# ADR-027 — El aprovisionamiento de negocios vive en un servicio `provisioner` separado

**Fecha:** 2026-07-27 · **Estado:** Firmada (Fase 1, Task 0.5.3) · Cierra la deuda D-02

## Contexto

En Keycloak 26.6.4 **toda** la API de Organizations exige `manage-realm`
(medido en la matriz de D-02, `docs/deuda-tecnica.md`): no hay subconjunto de
roles de `realm-management` que dé alta y baja de negocios sin él. Y
`manage-realm` no es «administrar organizaciones»: es reescribir el realm —
crear flujos de autenticación, reenlazar `browserFlow` (sacando el login con
passkey), apagar la protección de fuerza bruta y abrir el auto-registro
público. Combinado con `manage-users`, es un camino completo a cuenta de
administrador de cualquier tenant.

La mitigación de Fase 0 partió el privilegio en dos clientes (`vendi-backend`
con solo `manage-users`, `vendi-provisioning` con `manage-realm`), pero **los
dos secretos vivían en el proceso de la API**. La propia entrada de la deuda
lo decía sin adornos: quien comprometa la API con ejecución de código se lleva
las dos credenciales. El cierre exigía mover el aprovisionamiento a otra
unidad de despliegue.

## Decisión

Nueva unidad de despliegue, `backend/services/provisioner`, que es **el único
proceso con `VENDI_PROVISIONING_CLIENT_SECRET`**. Expone por la red interna
del compose (`vendi-net`, sin puertos publicados, sin router en Traefik) una
superficie **acotada y semántica**: crear y borrar la Organization de un
negocio, consultarla por alias, listarla, gestionar su membresía y las
operaciones de siembra del realm. La API deja de recibir el secreto —el campo
desaparece de sus `Settings`, no solo el valor— y pide esas operaciones por
HTTP interno (`vendi_core.provisioning.cliente`) con timeout, reintentos
acotados y propagación del correlation-id. La siembra (`scripts/seed.sh`) y el
reconciliador siguen ejecutándose desde el contenedor de la API, pero
orquestan llamadas al provisioner.

La transacción del alta de negocio no cambia: sigue siendo síncrona y
compensada (rollback si la organización no se crea). Lo que cambia es el
transporte de una llamada, no el contrato.

## Alternativas descartadas

- **Opción B del plan (rotación documentada + alcance mínimo + runbook).** No
  cierra el riesgo, lo calendariza: la credencial con `manage-realm` seguiría
  en el proceso que atiende peticiones de todos los tenants. Era la salida
  prevista solo si la opción completa encontraba un bloqueo estructural, y no
  lo encontró.
- **Un proxy genérico de la Admin API de Keycloak.** Convertiría al
  provisioner en `manage-realm` accesible por HTTP: la misma credencial que se
  sacó de la API, servida a cualquier proceso de la red interna. Cada ruta del
  provisioner es una operación de negocio concreta; añadir una exige responder
  «¿qué operación del producto la necesita?».
- **Un token compartido API→provisioner.** Sería una segunda credencial
  custodiada por la API para proteger la primera: el mismo problema con otro
  nombre. La autenticación es la red: sin puertos publicados y sin router en el
  borde, alcanzar el provisioner exige estar ya dentro de `vendi-net`. El
  check 26 de `scripts/verify-setup.sh` vigila las dos cosas.
- **Mover la siembra y el reconciliador al contenedor del provisioner.**
  Arrastraría la tabla `tenants` y el DSN de plataforma a ese servicio,
  agrandando su superficie para ahorrar un salto HTTP que ya está hecho.

## Consecuencias

- Quien comprometa la API —por fuga de configuración o por ejecución de
  código— obtiene `manage-users`, no reescritura del realm. Para alcanzar
  `manage-realm` tiene que saltar a otro contenedor.
- **Riesgo residual, dicho en voz alta:** la API comprometida todavía puede
  pedir al provisioner sus operaciones acotadas (crear y borrar organizaciones
  de tenants, sembrar el realm). Es un daño real pero órdenes de magnitud
  menor que reescribir los flujos de autenticación o apagar la protección de
  fuerza bruta, y es el mismo daño que ya puede hacer con `manage-users`
  sobre usuarios.
- El alta de negocio gana una dependencia de disponibilidad: si el provisioner
  cae, el alta falla con 502 tipado y compensación, y el resto de la API sigue
  sirviendo. Es el patrón correcto (falla cerrado, no a medias), pero es una
  pieza más que vigilar.
- El `Settings` de la API no tiene campo para el secreto: ningún despliegue
  puede entregárselo por accidente, y hay un test que lo prueba
  (`tests/api/test_api_sin_secreto_de_provisioning.py`). De paso se cerró la
  deuda menor asociada: `keycloak_backend_client_secret` ya no tiene defecto
  `""`, así que la API no arranca sin credencial para fallar tarde.
- Los tests de integración hablan con el provisioner por `127.0.0.1:8010`,
  que solo publica el override de desarrollo — mismo criterio que los puertos
  de postgres, redis y keycloak.
