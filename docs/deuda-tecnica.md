# Deuda técnica del proyecto

Registro de las decisiones que se toman **a sabiendas de que están mal**, con
quién las tomó, por qué, y **cuándo dejan de ser aceptables**. Una deuda sin
fecha de vencimiento no es deuda: es una decisión permanente que nadie firmó.

Cada entrada se cierra borrándola de aquí y dejando la evidencia de que el
arreglo funciona (comando + salida), no marcándola como "hecha".

| # | Deuda | Vence | Dueño |
|---|---|---|---|
| D-03 | El realm es semilla, no estado deseado continuo (mitigado en la Etapa 5: se aplica el subconjunto seguro) | Fase 1 | backend |
| D-09 | El tier del negocio se resuelve como `pro` para todos (módulo catálogo, decisión 2 del plan) | Fase 1 (módulo de suscripciones) | backend |
| D-10 | `ventas.cliente_id` no tiene FK: la tabla `clientes` es del módulo 5 | Fase 1 (módulo 5, clientes-fiado) | backend |
| D-11 | `caja_sesiones` existe y se puebla (apertura implícita del sync) sin endpoints propios | Fase 1 (módulo 4, caja) | backend |
| D-12 | El stock no tiene alertas de umbral: el negativo es visible en `stock_actual` pero nadie notifica | Fase 1 (módulo 3, inventario) | backend |
| D-13 | Carrera TOCTOU del cupo de tier del catálogo: dos altas concurrentes dejan 101/100 (QA adversarial) | Fase 1 (antes del piloto) | backend |
| D-14 | `OperacionSync.datos` es opcional en el contrato: una operación sin `datos` es `rechazada`, no 422 | Fase 1 (módulo 3) | backend |
| D-15 | `exigir_venta_anular` está definido y exportado sin endpoint que lo use | Fase 1 (módulo 4; si nada lo usa, se borra) | backend |
| D-16 | El check 23 de `verify-setup.sh` no tiene prueba negativa ejecutada (nadie lo ha visto fallar) | Fase 1 (Etapa 1.5) | backend |
| D-17 | `alembic check` (deriva metadata↔DDL) no corre en CI | Fase 1 | backend |

Cerradas en la Etapa 5, con su evidencia al final de este documento: **D-01**
(ROPC), **D-04** (Keycloak sin `--optimized`), **D-06** (`alembic_version`
escribible por el rol de la API), **D-07** (`exchange` del outbox sin defensa) y
**D-08** (el claim `groups` no se emite y `has_role()` era inerte).

Cerrada en la Task 0.5.3 de Fase 1: **D-02** (`manage-realm` en el proceso de la
API): el aprovisionamiento se movió al servicio `provisioner` (ADR-027).

> Runbooks operativos relacionados: el procedimiento completo de respaldo y
> restauración (qué se vuelca, qué NO, y cómo se promueve una copia a base
> viva) está en [`docs/respaldo-y-restauracion.md`](respaldo-y-restauracion.md).

---

## D-03 · El realm de Keycloak es semilla, no estado deseado continuo

**Qué es.** `--import-realm` importa `realm-vendi-co.json` **solo si el realm no
existe**. Un cambio en el JSON no se aplica reiniciando.

**Qué se hizo.** `scripts/reconcile-keycloak.sh` **detecta** la deriva de
clientes, flujos, ajustes del realm y roles de la cuenta de servicio
(`scripts/lib/kc_deriva_config.py`), y la de organizaciones contra la tabla
`tenants`.

**Mitigación aplicada en la Etapa 5.** Con `RECONCILE_APLICAR_CONFIG=1` el
script **aplica** la deriva de configuración en el subconjunto donde corregir no
puede tirar sesiones ni rotar credenciales: interruptores de cliente
(`publicClient`, `standardFlowEnabled`, `directAccessGrantsEnabled`,
`serviceAccountsEnabled`, `implicitFlowEnabled`, `enabled`), `redirectUris`,
`webOrigins`, client scopes declarados con sus protocol mappers y las listas de
scopes por defecto y opcionales de cada cliente
(`scripts/lib/kc_aplicar_config.py`). Tras aplicar, vuelve a comparar e imprime
el resultado, así que la corrección se demuestra en la misma ejecución.

El `PUT` se hace sobre una copia del objeto **vivo** con solo los campos
declarados encima. Es deliberado: así conserva el `secret` del cliente, sus
mappers dedicados y todo lo que el JSON no declara.

Es lo que cerró D-01 en el realm existente. Ejecución real:

```
[APLICADO] client scope 'vendi-audiencia' creado
[APLICADO] cliente 'admin-cli': directAccessGrantsEnabled
[APLICADO] cliente 'vendi-web': directAccessGrantsEnabled
[APLICADO] cliente 'vendi-web': scope 'vendi-audiencia' añadido a defaultClientScopes
[OK]       sin deriva de configuración: clientes, flujos, roles de servicio y ajustes cuadran
```

**Qué falta, y por qué la deuda NO se cierra.** Quedan fuera, a propósito:

- **Los flujos de autenticación y sus enlaces.** Reenlazar `browserFlow` con
  sesiones abiertas es la forma más rápida de dejar a todo el mundo fuera, y un
  flujo importado a medias deja el realm sin login.
- **Los ajustes del realm, los roles y los usuarios.** Un script capaz de
  *añadir* roles a una cuenta de servicio es un camino de escalada de
  privilegios con forma de herramienta de mantenimiento.
- **Crear clientes que falten.** Se informa, no se crea.

Para esos tres, el script sigue informando y decidiendo el operador.

**Vencimiento: Fase 1**, cuando haya más de un entorno desplegado y la deriva
deje de ser hipotética.

**Ocurrencia real (2026-07-23).** El renombrado de `vendi.local` a `vendi.co`
lo demostró en vivo: cambiar `BASE_DOMAIN` y reiniciar el stack actualizó el
JSON, Traefik y las apps, pero el realm existente se quedó con
`https://app.vendi.local/*` y `https://admin.vendi.local/*` en los
`redirectUris` de `vendi-web` y `vendi-admin`. `reconcile-keycloak.sh` lo
detectó con exactitud (`faltan [...] · sobran [...]`) y la corrección hubo que
aplicarla a mano contra la Admin API, cliente por cliente, preservando el resto
del objeto para no pisar secretos. Es justo el trabajo manual que la parte
pendiente de esta deuda debe automatizar. Los `webOrigins` no hicieron falta:
valen `"+"`, que deriva de los `redirectUris` y por tanto es independiente del
dominio.

---

## D-09 · El tier del negocio se resuelve como `pro` para todos

**Qué es.** El límite de productos por tier (ADR-010) se verifica de verdad en
la aplicación —`LIMITES_PRODUCTOS_POR_TIER = {"gratis": 100, "light": 500,
"pro": None}` contra las filas vivas del tenant, con 403
`limite_de_productos_alcanzado`— pero la **fuente** del dato es fija: la
dependencia `tier_del_negocio`
(`backend/services/api/app/modules/catalogo/dependencies.py`) devuelve `"pro"`
para todo negocio. En Fase 1 no existe módulo de suscripciones ni columna de
tier en `tenants`.

**Por qué se aceptó.** Decisión 2 del plan del módulo catálogo: el plan maestro
§5 registra a todo negocio nuevo en el trial de Pro (1 mes, sin tarjeta), así
que el valor fijo coincide con la realidad del piloto. Lo diferido es solo la
fuente del dato, no la verificación: los tests la ejercitan de verdad. En la
API con `dependency_overrides` para `gratis` (alta 101 → 403), y en el
servicio para `gratis` (alta 101) y `light` (la alta 501 lanza
`limite_de_productos_alcanzado` con `details` `{"tier": "light", "limite": 500}`).

**Riesgo si se olvida.** El día que se dé de alta un negocio por debajo de Pro
sin haber cerrado esta deuda, su límite real (100 o 500) no se le aplicará:
heredará el de Pro (ilimitado).

**Vencimiento: Fase 1**, al existir el módulo de suscripciones (o cualquier
fuente real del tier). El único punto de cambio es la dependencia
`tier_del_negocio`.

**Candados mientras tanto** (los dos primeros, verdes en el run de CI
30258309167, 2026-07-27; el tercero se añadió en el fix post-review):

- `backend/tests/api/test_catalogo_productos.py::test_el_limite_del_tier_da_403`
- `backend/tests/test_catalogo_servicio.py::test_el_limite_del_tier_se_verifica_contra_las_filas_vivas`
- `backend/tests/test_catalogo_servicio.py::test_el_limite_del_tier_light_se_detiene_en_500`

---

## D-10 · `ventas.cliente_id` no tiene FK

**Qué es.** La venta fiada lleva `cliente_id`, pero la columna no referencia
a ninguna tabla: `clientes` es del módulo 5 y todavía no existe.

**Por qué se aceptó.** Decisión 8 del plan del módulo ventas: el fiado sin
red está permitido por ADR-018, así que el sync no puede rechazar una venta
real porque su referencia aún no exista en el servidor. El crédito lo crea el
módulo 5, que tiene todo lo que necesita en la venta y en el evento
`venta.creada` (lleva `medio_pago`, `cliente_id` y total). Como los módulos
se entregan en orden antes del piloto, ninguna venta real queda huérfana de
crédito.

**Riesgo si se olvida.** Si el módulo 5 crea `clientes` con su propia
convención de ids sin mirar las ventas ya sincronizadas, los fiados vendidos
antes de su llegada apuntarían a clientes que no existen y no generarían
crédito.

**Vencimiento: Fase 1, módulo 5 (clientes-fiado).** Al crear `clientes`, el
módulo 5 adopta el `cliente_id` del dispositivo como PK (mismo patrón de id
de cliente que `ventas` y `productos`) o migra las referencias.

**Candados mientras tanto:**

- `backend/tests/test_ventas_servicio.py`: fiado sin cliente es `rechazada`
  con `fiado_requiere_cliente`, y cliente en venta no fiada con
  `cliente_solo_en_fiado` — la columna solo se puebla en ventas fiadas.
- El evento `venta.creada` conserva `cliente_id`, `medio_pago` y total para
  que el módulo 5 cree el crédito sin releer la venta.

---

## D-11 · `caja_sesiones` existe y se puebla sin endpoints propios

**Qué es.** La tabla `caja_sesiones` se creó completa en la migración `0005`
y el sync la puebla: toda venta sincronizada pertenece a la sesión abierta
del tenant o a una implícita nueva (`base_inicial = 0`, `abierta_por` el
usuario que sincroniza). Pero no hay endpoints para abrir, cerrar ni arquear
sesiones: son del módulo 4.

**Por qué se aceptó.** Decisión 3 del plan: ADR-018 firma que la venta
referencia sesión de caja resuelta en servidor, y grabar las ventas del
piloto con `sesion_caja_id` NULL obligaría a re-procesarlas cuando llegue la
caja (el arqueo suma por sesión). La tensión declarada con ADR-021 («vender
sin caja abierta es posible… pero esa venta no entra al arqueo») se resolvió
a favor de ADR-018: una venta con sesión siempre puede excluirse de un
arqueo; una sin sesión nunca puede incluirse.

**Riesgo si se olvida.** Las sesiones implícitas quedan abiertas
indefinidamente (nadie puede cerrarlas hasta el módulo 4). Es visible y sin
pérdida de datos, pero si el módulo 4 no llegara, la operación no tendría
cierre de caja que cuadrar.

**Vencimiento: Fase 1, módulo 4 (caja y arqueo).** El módulo 4 encontrará la
tabla y sus filas ya vivas: añade los endpoints, `caja_movimientos` y los
eventos de caja.

**Candados mientras tanto:**

- El índice único parcial `(tenant_id) WHERE estado = 'abierta'` (ADR-021)
  garantiza UNA sesión abierta por tienda y decide la carrera de aperturas
  implícitas concurrentes (quien pierde re-lee la ganadora).
- `backend/tests/test_ventas_servicio.py::test_aplicar_una_venta_descuenta_stock_abre_sesion_implicita_y_emite_evento`
  y `::test_la_segunda_venta_reusa_la_sesion_implicita`.

---

## D-12 · El stock no tiene alertas de umbral

**Qué es.** El sync descuenta stock por deltas en `movimientos_inventario` y
actualiza la proyección `stock_actual`, pero no evalúa `stock_minimo`: un
producto puede quedar en cero o en negativo (legítimo según ADR-020) sin que
nadie se entere.

**Por qué se aceptó.** Decisión 1 del plan: las alertas de tres niveles con
`inventario.alerta_stock` se difirieron al módulo 3 porque su consumidor es
el módulo de notificaciones (ADR-025), que aún no existe — emitir un evento
que nadie consume no avisa a nadie.

**Riesgo si se olvida.** El tendero se entera del quiebre de stock cuando el
cliente lo pide, no antes. El dato no se pierde: `stock_actual` viaja en cada
producto del `GET /sync/delta`, así que el dispositivo ya puede mostrarlo.

**Vencimiento: Fase 1, módulo 3 (inventario y alertas).**

**Candados mientras tanto:**

- `stock_actual` actualizado en la misma transacción del lote (probado en
  `test_aplicar_una_venta_descuenta_stock_abre_sesion_implicita_y_emite_evento`)
  y servido por el delta del sync.
- El `tipo` de `movimientos_inventario` ya admite `venta`, `compra`,
  `ajuste` y `merma`: el módulo 3 no migra nada.

---

## D-13 · Carrera TOCTOU del cupo de tier del catálogo

**Qué es.** `_exigir_cupo` cuenta las filas vivas y luego inserta: con 99
productos y dos sesiones intercaladas (A hace flush sin commit, B cuenta 99
y pasa, ambas confirman) quedan **101 productos con límite 100**. Lo
documentó el QA adversarial del catálogo con test commiteado
(`.superpowers/sdd/qa-adversarial-report.md`).

**Por qué se aceptó.** El límite por tier vive en aplicación por diseño
firmado (ADR-019); sin `SERIALIZABLE` ni bloqueo, toda verificación
cuenta-luego-inserta tiene esta ventana. Impacto real bajo: la ingesta del
catálogo es síncrona y por un solo negocio a la vez; superar el cupo por uno
no rompe nada más que la letra del límite.

**Riesgo si se olvida.** Con ingesta masiva concurrente (importaciones del
módulo 3, o varios dispositivos sincronizando altas) el sobre-paso deja de
ser anecdótico y el límite del tier —que es un límite comercial, ADR-010— se
vuelve poroso.

**Vencimiento: Fase 1, antes del piloto.** Arreglo propuesto por el propio
QA: `SELECT pg_advisory_xact_lock(hashtext(tenant_id::text))` al entrar en
`_exigir_cupo` — serializa las altas del negocio sin tocar el esquema.

**Candados mientras tanto:**

- `backend/tests/test_catalogo_adversarial.py::test_la_carrera_del_cupo_supera_el_limite_aunque_el_check_pase`
  (documenta el 101/100; si alguien cierra la ventana, este test es el que
  hay que invertir).
- D-09 sigue viva: hoy el tier es `pro` (ilimitado) para todos, así que la
  carrera no tiene efecto observable hasta que exista una fuente real del
  tier.

---

## D-14 · `OperacionSync.datos` es opcional en el contrato

**Qué es.** En `OperacionSync` el campo `datos` tiene
`Field(default_factory=dict)`: una operación sin `datos` no es un 422 de
request; llega al servicio con `{}` y sale `rechazada` con motivo
`datos_invalidos`.

**Por qué se aceptó.** Decisión 6 del plan: el contenido de `datos` se
valida por operación dentro del procesamiento del lote (la unidad de fallo
es la operación, no el request). Pero la opcionalidad del CAMPO es un paso
más allá: el contrato OpenAPI no marca `datos` como requerido, así que un
cliente que lo omite no recibe la señal más temprana posible.

**Riesgo si se olvida.** Bajo: el comportamiento es correcto (la operación
se rechaza con motivo y no aplica nada), solo es menos explícito de lo que
el contrato podría ser. Con más tipos de operación (módulo 3 en adelante)
conviene hacerlo requerido para que el 422 lo dé pydantic.

**Vencimiento: Fase 1, módulo 3** (cuando el sync gane tipos de operación
nuevos y el contrato se revise).

**Candado mientras tanto:**

- `backend/tests/test_ventas_servicio.py`: operación con datos inválidos es
  `rechazada` con `datos_invalidos` y no arrastra al resto del lote.

---

## D-15 · `exigir_venta_anular` está definido sin consumidor

**Qué es.** `backend/services/api/app/modules/ventas/dependencies.py`
define y exporta `exigir_venta_anular = exigir_permiso(PERM_VENTA_ANULAR)`,
pero ningún endpoint lo usa: la anulación viaja como operación del lote y su
chequeo es por operación dentro del servicio (decisión 12), y los guards de
entrada del router son `exigir_venta_crear` (dispositivos y lotes) y
`exigir_producto_leer` (delta).

**Por qué se aceptó.** El plan (tarea 6) lo dejó preparado para un endpoint
de anulación directa que finalmente no se construyó: la anulación del piloto
sube por el sync. Es código muerto exportado, y el código muerto con nombre
de permiso invita a usarlo mal o a creer que hay una ruta que no existe.

**Riesgo si se olvida.** Cosmético hoy; confuso mañana. Si el módulo 4 (o un
endpoint de anulación online) lo usa, la deuda se cierra sola; si no, hay
que borrarlo.

**Vencimiento: Fase 1, módulo 4.** O lo estrena un endpoint, o se retira.

**Candado mientras tanto:**

- El 403 por rol se prueba de verdad a nivel operación:
  `backend/tests/api/test_ventas_sync.py` (lote de anulaciones del cajero →
  todas `rechazada` con `permiso_ausente`) y
  `backend/tests/test_ventas_servicio.py` (mismo caso en el servicio).

---

## D-16 · El check 23 no tiene prueba negativa ejecutada

**Qué es.** El check 23 de `verify-setup.sh` (aud, rol y permisos de
catálogo y ventas en el token del dueño) pasa en verde en el CI, pero nadie
ha ejecutado la mutación: quitar un permiso del realm y ver el check fallar.
Sin esa prueba, el candado podría estar aprobando siempre por la razón
equivocada (la cultura del repo lo exige: «distinguir deniega porque no lo
tiene de deniega siempre»).

**Por qué se aceptó.** La prueba negativa exige mutar el realm del stack
local (quitar `venta:crear` del grupo `dueno`, correr el check, restaurar),
y el cierre del módulo se hizo sin tocar contenedores locales, con la
evidencia citada del CI.

**Riesgo si se olvida.** Que el check 23 sea un placebo y nadie lo sepa
hasta que un permiso falte de verdad en un despliegue.

**Vencimiento: Fase 1, Etapa 1.5.** Ejecutar la mutación contra el stack
local y pegar la salida del fallo en este registro al cerrarla.

**Candado mientras tanto:**

- El check corre en cada `verify-setup.sh` del CI (job «pytest -m
  integration»): `[OK] aud=vendi-backend, rol de negocio y permisos de
  catálogo y ventas en el token del dueño` — si la siembra deja de incluir
  un permiso, el CI se pone rojo en el siguiente push.

---

## D-17 · `alembic check` no corre en CI

**Qué es.** Nada compara la metadata de los modelos SQLAlchemy con el DDL
que producen las migraciones (`alembic check`): una columna añadida al
modelo sin migración (o al revés) solo se nota cuando un test la toca.

**Por qué se aceptó.** En el módulo ventas los modelos se escribieron contra
la migración (tarea 2, «alineados con la migración 0005») y los tests de
integración contra PostgreSQL real ejercitan el DDL completo, así que la
deriva habría reventado la suite. El candado automático es defensa en
profundidad, no la primera línea.

**Riesgo si se olvida.** Una deriva metadata↔DDL que ningún test toque
(columna sin uso todavía, índice olvidado) llegaría silenciosa a producción.

**Vencimiento: Fase 1.** Añadir `alembic check` al job `ruff + mypy` del CI
(o uno propio) con el stack levantado.

**Candado mientras tanto:**

- `backend/tests/test_rls_coverage.py` registra todo modelo nuevo y exige su
  tabla con policy RLS — una tabla sin migrar lo pone rojo.
- Los tests de integración corren contra la base migrada hasta head en cada
  push (job «pytest -m integration», 0 SKIPPED permitidos).

---

## Deuda menor que entra viva a Fase 1

Anotada al cierre de Fase 0 por el arquitecto. Ninguna bloquea el cierre; toda
tiene que resolverse o re-firmarse en Fase 1:

- **Invalidación de i18n sin sello de versión.** Los catálogos `/i18n/*.json`
  dependen del `max-age=300` de nginx (≤5 min de desfase tras desplegar). El
  mecanismo `?v=<version>` que BaseSaaS insinuaba nunca existió en el código y
  se retiró de la documentación en la Etapa 5. Si 5 minutos dejan de ser
  aceptables: `appVersion` en los environments + query en el cargador.
- **`BASE_DOMAIN` horneado en las imágenes de las SPAs.** `release-images.yml`
  compila con `secrets.DEPLOY_DOMAIN`: las imágenes publicadas sirven para UN
  dominio. No escala a la topología de realm por región (ADR-014): en Fase 1,
  o imágenes por región, o configuración en tiempo de arranque.
- **La etiqueta de imagen se recalcula en vez de propagarse.** `deploy.yml`
  reconstruye `sha-<7>` a partir del SHA del `workflow_run`; lo robusto es que
  `release-images.yml` la exponga como output.
- **Las SPAs se sirven sin CSP ni HSTS.** El middleware `secure-headers` de
  Traefik pone frameDeny/nosniff/referrer-policy, pero las únicas páginas que
  ejecutan JavaScript no llevan Content-Security-Policy; la API (JSON) sí.
- **`default-roles-vendi-co` duplicado.** El realm tiene además
  `default-roles-vendi-co-1` (artefacto del import) y es el `-1` el que se
  asigna: inofensivo, pero ensucia `realm_access.roles` de todos los tokens.
- **Login: la contraseña es la opción por defecto** y el passkey queda tras
  «Pruebe de otra manera». Es configuración del flujo del realm.
- **Frontend:** 39 claves i18n sin respaldo empotrado; `vendi-portal` con URL
  fija; sobre de error dual (`{detail}` frente a `{success,...}`); 401 a media
  sesión sin re-login; códigos de error de `vendi-core` en inglés (contra la
  restricción global de español).
- **Los E2E de CRUD acumulan filas `Tienda e2e-*` en estado `eliminado`** en la
  base de dev (baja lógica, por diseño; Keycloak sí queda limpio). Falta un
  camino de purga fuera de la UI o un truncado periódico en dev/CI.
- **Los 5 workflows de CI nunca se han ejecutado en GitHub Actions**: el
  repositorio no tiene remoto. Validados estáticamente y cada comando
  reproducido en local; el primer push real es la prueba pendiente.

---

## Cerradas en Fase 1

### D-02 · `manage-realm` en la cuenta de servicio de Keycloak

**Qué era.** En Keycloak 26.6.4 toda la API de Organizations exige
`manage-realm` —medido: ningún subconjunto de roles de `realm-management`
alcanza Organizations, ni para leer— y `manage-realm` es reescribir el realm:
crear flujos de autenticación, reenlazar `browserFlow` (sacando el login con
passkey), apagar la protección de fuerza bruta y abrir el auto-registro. La
mitigación de la Etapa 3 partió el privilegio en dos clientes (`vendi-backend`
con solo `manage-users`; `vendi-provisioning` con `manage-realm`), pero **las
dos credenciales vivían en el proceso de la API**: un RCE se llevaba las dos.
Las matrices completas de medición (spikes C1–C4, riesgo residual medido sobre
el realm vivo) quedan en la historia de git de este archivo.

**Cómo se cerró** (Task 0.5.3, opción A completa; decisión y riesgo residual
en [ADR-027](adr/adr-027-provisioner-separado.md)). El aprovisionamiento se
movió a una unidad de despliegue propia, `backend/services/provisioner`: es el
único proceso con `VENDI_PROVISIONING_CLIENT_SECRET` y expone por la red
interna (`vendi-net`, sin puertos publicados, sin router en Traefik) las
operaciones acotadas —crear/borrar/consultar Organizations y la siembra del
realm—, no la Admin API de Keycloak. La API dejó de recibir el secreto: el
campo desapareció de sus `Settings` (ningún despliegue puede entregárselo) y
`TenantService`, la siembra y el reconciliador hablan con el provisioner por
HTTP interno (`vendi_core.provisioning.cliente`, con timeout, reintentos
acotados y correlation-id). El alta de negocio sigue siendo síncrona y
compensada; cambió el transporte, no el contrato. De paso,
`keycloak_backend_client_secret` perdió el defecto `""`: la API ya no arranca
sin credencial para fallar tarde.

**Riesgo residual, sin adornos.** Quien comprometa la API todavía puede pedir
al provisioner sus operaciones acotadas (crear/borrar organizaciones,
sembrar). Es un daño real pero acotado: ya no puede reescribir los flujos de
autenticación, apagar la protección de fuerza bruta ni abrir el auto-registro,
porque el provisioner no expone eso y la credencial que lo permite no está en
el proceso comprometido.

**Evidencia** (stack real del compose, 2026-07-27):

```
$ docker compose exec api printenv KEYCLOAK_PROVISIONING_CLIENT_SECRET
                                → (vacío: la API no la tiene)
$ docker compose exec provisioner printenv KEYCLOAK_PROVISIONING_CLIENT_SECRET
                                → (presente: el provisioner sí)

$ bash scripts/seed.sh          # orquesta por HTTP; el secreto no pasa por la API
[OK]    Siembra completa.

# Alta y baja reales ejecutadas DENTRO del proceso de la API (TenantService →
# provisioner → Keycloak), con limpieza al final:
tenant_creado        kc_org_id=15360eb2-ebac-4925-aceb-3a0faf0d8f08 tenant_id=f590499d-601b-464c-a940-13b915b1c709
org en keycloak via provisioner: True
tenant_eliminado     tenant_id=f590499d-601b-464c-a940-13b915b1c709
org tras la baja: None

$ bash scripts/verify-setup.sh
[OK]    21. vendi-backend=manage-users · vendi-provisioning=manage-realm,manage-users
[OK]    26. la API no tiene el secreto, el provisioner sí y responde, el borde da 404
            y no hay puertos expuestos

$ cd backend && uv run pytest -q -m 'not integration'
335 passed
$ uv run pytest -q -rs -m integration
106 passed           # incluye test_el_alta_completa_a_traves_del_provisioner,
                     # alta y baja reales por HTTP sin secreto en el anfitrión
```

**Candados:**

- `verify-setup.sh` check 26: falla si el secreto aparece en el entorno de la
  API, si el provisioner deja de responder, si el borde enruta
  `provisioner.<dominio>` (debe ser 404) o si publica un puerto fuera de
  loopback.
- `verify-setup.sh` check 21 (ya existía): los roles mínimos de las dos
  cuentas de servicio.
- `tests/api/test_api_sin_secreto_de_provisioning.py`: la API se construye sin
  la credencial y `Settings` no tiene campo que la acepte aunque esté en el
  entorno.
- `tests/api/test_tenants_provisioning.py::test_el_alta_completa_a_traves_del_provisioner`
  (integration): el camino entero por HTTP, sin `VENDI_PROVISIONING_CLIENT_SECRET`
  fuera del contenedor del provisioner.
- `tests/test_keycloak_admin_orgs.py::test_el_cliente_de_la_api_no_alcanza_organizations`
  (ya existía): `vendi-backend` sigue sin alcanzar Organizations.

---

## Cerradas en la Etapa 5 (cierre de Fase 0)

Cada una se cierra con la evidencia de que el arreglo funciona —comando y salida
real—, no con una marca de «hecho».

### D-01 · ROPC (`directAccessGrantsEnabled`) en el realm de negocio

**Qué era.** El cliente público `vendi-web` aceptaba el grant de contraseña: con
`client_id`, usuario y contraseña se obtenía un token completo sin pasar por el
navegador, anulando la política de passkey del realm.

**Hallazgo que amplió el alcance.** No era solo `vendi-web`. **`admin-cli`, que
Keycloak crea de fábrica en TODOS los realms, también tenía ROPC encendido en
`vendi-co`** — cliente público, grant de contraseña, mismo agujero con otro
nombre. Cerrar solo `vendi-web` habría dejado la puerta abierta al lado y con la
sensación de haberla cerrado.

**Cómo se cerró.** `directAccessGrantsEnabled: false` en `vendi-web` y en
`admin-cli`, en `infra/keycloak/realm-vendi-co.json` **y aplicado al realm vivo**
con `RECONCILE_APLICAR_CONFIG=1 bash scripts/reconcile-keycloak.sh`. La siembra
ya no lo necesitaba: `scripts/seed.sh` llama a `TenantService` en proceso, no por
HTTP. Los E2E y los scripts de verificación usan `admin-cli` del realm **master**,
que es la credencial de administración del propio Keycloak y no la de la
aplicación.

**Evidencia** (medido antes y después, por el dominio):

```
# antes
POST https://accounts.vendi.co/realms/vendi-co/protocol/openid-connect/token
  grant_type=password client_id=vendi-web username=dueno@demo.vendi.co
→ HTTP 200, access_token completo

# después (vendi-web, admin-cli y vendi-admin)
→ HTTP 400 {"error":"unauthorized_client",
            "error_description":"Client not allowed for direct access grants"}
```

**Candado.** Check 22 de `verify-setup.sh`: lista los clientes del **realm vivo**
—no del JSON, que es la semilla y no decide— y falla si alguno tiene
`directAccessGrantsEnabled`.

---

### D-04 · Keycloak arrancaba sin `--optimized` en producción

**Qué era.** `docker-compose.override.prod.yml` usaba `start --import-realm` sin
`--optimized`: cada arranque hacía un build implícito de decenas de segundos,
alargando la indisponibilidad de cada despliegue y de cada reinicio.

**Cómo se cerró.** `infra/keycloak/Dockerfile` construye la imagen de Vendi con
`kc.sh build` ya ejecutado; el override de producción pasa a
`image: ${VENDI_IMAGE_REGISTRY:?…}/vendi-keycloak:${VENDI_IMAGE_TAG:?…}` y
`command: start --optimized --import-realm`. `release-images.yml` la publica
junto a `vendi-api`, `vendi-worker` y las tres SPAs.

**Trampa medida al escribirlo**, anotada para que nadie la repita:
`--features=organizations` **aborta el build** con
`'organizations' is an unrecognized feature`. En 26.6.4 Organizations no es una
funcionalidad opcional —está activa de fábrica— y el nombre de la lista es
`organization`, en singular. No hay que declararla.

**Evidencia:**

```
$ docker build -t vendi-keycloak:prueba infra/keycloak
… naming to docker.io/library/vendi-keycloak:prueba done

$ docker run --rm vendi-keycloak:prueba start --optimized …
ISPN000974: Virtual threads support: enabled
…                        # arranca y va directo a la base; ningún
                         # «you must first run kc.sh build»
```

**Sin verificar:** el arranque completo en la topología de producción (con base
real y ACME). Lo comprobado es que la imagen construye y que `--optimized` deja
de rechazarse.

---

### D-06 · `alembic_version` era escribible por `vendi_app`

**Qué era.** El rol de la API conservaba SELECT/INSERT/UPDATE/DELETE sobre
`alembic_version`, y ninguno de los dos candados de la Etapa 3 lo veía: uno
enumeraba nombres concretos, el otro solo mira tablas con columna `tenant_id`.
Con UPDATE sobre esa tabla, cualquier handler puede hacer que la siguiente
migración crea que el esquema está en otro punto del que está.

**Cómo se cerró.** Migración `0003`
(`REVOKE ALL ON alembic_version FROM vendi_app`) más el candado **invertido**
que pedía la deuda: `backend/tests/test_privilegios_de_vendi_app.py` recorre
**todas** las tablas del esquema `public` y exige que los privilegios de
`vendi_app` coincidan con `PRIVILEGIOS_DE_VENDI_APP`. Una tabla nueva sin
clasificar lo pone rojo aunque nadie se acuerde de actualizarlo.

**Evidencia:**

```
# antes de la migración
alembic_version | DELETE,INSERT,SELECT,UPDATE
$ uv run pytest -q tests/test_privilegios_de_vendi_app.py
2 failed

# después
$ bash scripts/migrate.sh        # → 0003 (head)
$ uv run pytest -q tests/test_privilegios_de_vendi_app.py
3 passed
```

---

### D-07 · La columna `exchange` del outbox no tenía defensa

**Qué era.** Resto de D-05. La policy de INSERT acota `tenant_id` y nada más, así
que `vendi_app` podía encolar una fila con el `exchange` que quisiera; el
dispatcher lo usaba literalmente en `declare_exchange`, de modo que un nombre
nuevo **lo creaba** —escritura en la topología del broker desde el rol de la
API— y uno reservado reventaba la publicación.

**Cómo se cerró.** Misma receta que D-05: no confiar en el texto. `OutboxDispatcher`
recibe su `exchange` y publica **siempre** ahí; cuando la fila dice otra cosa se
registra `outbox_exchange_ignorado` con los dos valores. La columna se conserva
porque es el registro de lo que el llamante pidió.

**Candado y su comprobación de mutación:**
`test_un_exchange_ajeno_no_se_declara_ni_desvia_el_mensaje` afirma las dos
mitades —el mensaje sale por el exchange bueno **y** el ajeno no existe después
(`declare_exchange(..., passive=True)` → `ChannelNotFoundEntity`)—. Se comprobó
que el test detecta la regresión revirtiendo el dispatcher a `msg.exchange`:

```
$ uv run pytest -q tests/worker/test_outbox_dispatch.py -k exchange_ajeno
FAILED … AssertionError: el mensaje no llegó al exchange configurado
$ # restaurado
10 passed
```

---

### D-08 · El claim `groups` no se emite; `has_role()` era inerte

**Qué era.** Token real de `dueno@demo.vendi.co`: `groups: None`. Ningún mapper
de grupo está en los default client scopes, así que `has_role()` y
`require_role()` devolvían `False` para todo el mundo —el dueño incluido— y
cualquier comprobación de rol denegaba **por la razón equivocada**.

**Cómo se cerró — y por qué NO se añadió el mapper.** Los roles de negocio de
Vendi son **roles de realm** por restricción del plan, y los roles de realm ya
viajan en `realm_access.roles` con un scope que el realm trae de fábrica. Añadir
un mapper de grupos habría exigido gestionar client scopes (403 para
`vendi-provisioning`, medido) para acabar emitiendo por un segundo canal lo que
ya viaja por el primero — dos fuentes de verdad para la misma pregunta. Decisión
completa en [ADR-015](adr/adr-015-roles-de-negocio-como-roles-de-realm.md).

Lo implementado: la siembra crea `dueno`, `cajero` y `almacenista` como roles de
realm y hace que el grupo homónimo mapee `{su rol} ∪ {sus permisos}`;
`has_role()` lee `roles`; el campo `UserContext.groups` **se retira** (un campo
siempre vacío es una trampa esperando al siguiente que escriba `require_role`).

**Evidencia** (token de ejemplo generado por Keycloak para `vendi-web` y el
usuario demo, antes y después):

```
antes:   realm_access = ['audit:read', 'default-roles-…', 'tenant:read', 'tenant:update']
         groups       = None
después: realm_access = ['audit:read', 'default-roles-…', 'dueno', 'tenant:read', 'tenant:update']
```

**Candados.** Check 23 de `verify-setup.sh` (falla si el token del dueño deja de
traer `dueno`), `test_un_rol_ausente_deniega_de_verdad` y
`test_require_role_corta_a_quien_solo_trae_permisos`, que distinguen «deniega
porque no lo tiene» de «deniega siempre».

---

### Extra de la Etapa 5 · Cierres que no tenían número de deuda

**Audiencia del token sin validar.** `KEYCLOAK_AUDIENCE` estaba vacío, es decir,
la API **no comprobaba `aud`**: cualquier token firmado por el realm servía,
aunque se hubiera emitido para otro público. Medido sobre un token real de
`vendi-web`: `aud = None` — el claim ni siquiera existía.

Se añadió el client scope `vendi-audiencia` (mapper `oidc-audience-mapper` →
`aud: vendi-backend`) a `vendi-web` y `vendi-admin`, y `KEYCLOAK_AUDIENCE` pasa a
tener **defecto no vacío**: un despliegue que olvide la variable falla cerrado.

```
$ TOK=$(… client_credentials de vendi-backend …)   # aud = realm-management
$ curl --resolve api.vendi.co:443:127.0.0.1 -H "Authorization: Bearer $TOK"        https://api.vendi.co/api/v1/tenants/me
{"success":false,"message":"Token inválido o expirado","code":"token_invalido"}   HTTP 401
```

**`/docs` y `/openapi.json` abiertos en el borde.** Decisión: **se cierran salvo
que se pidan**. `DOCS_PUBLICOS` es `false` por defecto y entonces FastAPI **no
registra las rutas** —el 404 es real, no un middleware que las tapa—. El compose
de desarrollo las enciende. Lo que publican no es documentación de marketing: es
el mapa completo de rutas, esquemas y códigos de error, incluidas las de
plataforma, y en Fase 0 no hay ni un consumidor externo que lo necesite (el
cliente TypeScript se genera contra `docs/api/openapi-fase0.json`).

```
$ DOCS_PUBLICOS=false docker compose … up -d api
/docs           404
/redoc          404
/openapi.json   404
/health         200
```

**CORS: `Access-Control-Allow-Headers: *` junto a `Allow-Credentials: true`.**
Combinación inválida: la especificación de Fetch obliga a comparar el `*`
**literalmente** en peticiones con credenciales, así que el preflight de
cualquier petición con `Authorization` se habría rechazado en el navegador —sin
un solo log en el backend— en cuanto alguien usara `withCredentials`. Se
sustituye por la lista explícita, en el middleware `cors-api` de Traefik y en la
constante `CABECERAS_CORS` de la aplicación, con un test que compara los dos
archivos para que no puedan separarse.

```
$ curl -i -X OPTIONS --resolve api.vendi.co:443:127.0.0.1 \
       https://api.vendi.co/api/v1/tenants/me \
       -H 'Origin: https://app.vendi.co' -H 'Access-Control-Request-Method: GET' \
       -H 'Access-Control-Request-Headers: authorization,x-tenant-id'
access-control-allow-headers: Accept,Accept-Language,Authorization,Content-Type,X-Correlation-Id,X-Requested-With,X-Tenant-Id
access-control-allow-credentials: true
```

---

## Cerradas en la Etapa 4

### D-05 · La policy de INSERT del outbox no restringía `routing_key` ni `payload`

**Qué era.** Medido por el QA de la Etapa 3 con sonda real: la policy
`outbox_encolado_del_tenant` solo acota la **columna** `tenant_id`. Una sesión
de `vendi_app` con el GUC del negocio A podía encolar legalmente una fila con
`tenant_id = A` y `routing_key = '<B>.venta.creada'`, y `payload` diciendo ser
de B. `OutboxDispatcher` publicaba `msg.routing_key` y `msg.payload`
literalmente, así que un consumidor ligado a `<B>.#` recibía un evento originado
en A.

**Cómo se cerró.** La primera de las dos mitigaciones propuestas, que es la que
cierra también el payload: el dispatcher **deriva** la clave de enrutado de
`msg.tenant_id` —la columna, que sí está defendida por la policy— en vez de
confiar en el texto almacenado, y reescribe el campo `tenant_id` del payload con
el mismo valor. Lo que aporta el llamante es solo el sufijo (el nombre del
evento), que no decide destinatario.

El primer segmento se descarta **solo si tiene forma de prefijo** (un UUID o el
literal `plataforma`, las dos únicas cosas que `DomainEventService.emit` puede
haber puesto ahí). Descartarlo a ciegas convertiría `venta.creada` en
`<tenant>.creada` y rompería el enrutado de los consumidores honestos mientras
intenta protegerlos.

Para el código correcto la derivación es un no-op; para el equivocado es un
candado. Implementación: `vendi_core.messaging.outbox.derivar_clave_de_enrutado`
y `_payload_saneado`. Cuando la clave almacenada y la derivada difieren, se
registra `outbox_clave_de_enrutado_corregida` con las dos, de modo que un
handler mal escrito se ve en el log en vez de fallar en silencio.

**Candados.** `backend/tests/worker/test_outbox_dispatch.py`:

- `test_la_clave_se_deriva_de_la_columna_tenant_id` — la tabla de casos.
- `test_una_clave_de_enrutado_ajena_no_llega_al_otro_negocio` — encola con el
  rol `vendi_app` y el GUC de A pero con la clave y el payload de B, contra el
  PostgreSQL y el RabbitMQ del compose, con **dos colas reales**, y afirma que
  el mensaje sale por `A.#` y nunca por `B.#`.

**Resto abierto.** La columna `exchange` quedó fuera de esta mitigación:
ver **D-07**.


---

## Cerradas en la Etapa 3 (ronda de corrección de QA)

Se dejan anotadas aquí, y no borradas, porque las dos eran decisiones de diseño
que llegaron a estar escritas en `docs/ARCHITECTURE.md` como si fueran
correctas. El registro de que se corrigieron —y de por qué la primera versión
parecía razonable— vale más que el hueco.

### `vendi_app` sin ningún privilegio sobre `outbox_messages`

**Qué era.** La migración `0001` hacía `REVOKE ALL` sobre las dos tablas de
plataforma, con el argumento de que «una tabla sin RLS a la que llega el rol de
la API es exactamente el agujero que este diseño existe para cerrar». El
argumento es bueno; la conclusión, no. `OutboxService.enqueue(session, ...)`
escribe en la sesión del llamante, que en un handler es la de tenant, así que el
patrón entero era inutilizable desde la API:

```
permission denied for table outbox_messages
```

**Por qué no se detectó.** Ningún test cubría el encolado, y el contrato del
módulo («la escritura de negocio y el encolado ocurren en la MISMA
transacción») era una afirmación sobre privilegios de Postgres que ningún test
de unidad con una sesión falsa podía comprobar.

**Cómo se cerró.** `GRANT INSERT` —y solo `INSERT`— más una policy de INSERT que
ata el `tenant_id` al GUC, más `eager_defaults=False` en el modelo para que el
`INSERT` no lleve `RETURNING`. La matriz completa está en
`docs/ARCHITECTURE.md`, sección «Tablas de plataforma». El candado es
`backend/tests/test_outbox_transaccional.py`.

`audit_events` **sigue completamente revocada** para `vendi_app`, y eso no es
una asimetría por olvido: la auditoría se escribe fuera de la transacción del
llamante a propósito, con la fábrica de sesión de plataforma.

### El runner de retención cerraba en éxito una pasada que no había borrado nada

**Qué era.** Todas las políticas del mismo ámbito comparten una transacción, y
en PostgreSQL un error la deja **abortada**: cualquier sentencia posterior falla
con `current transaction is aborted`. Como el runner traga los errores y
devuelve 0, una sola tabla mal escrita —o todavía sin migrar— hacía que todas
las políticas siguientes devolvieran 0 en silencio y que el ciclo se registrase
como `retention_run_finished` con una fila de auditoría `status='success'`. La
retención entera se convertía en un no-op que parecía funcionar.

Agravante: el estado se calculaba con `"success" if total >= 0 else "failure"`,
y una suma de conteos nunca es negativa. La fila decía «éxito» por construcción.

**Cómo se cerró.** Cada política corre dentro de un `SAVEPOINT`
(`session.begin_nested()`), así que un fallo revierte solo esa política y la
transacción sigue utilizable; los fallos se acumulan en `_failed_this_run` y
acaban en la fila de auditoría como `status='failure'` y
`changes.politicas_fallidas`. Candados:
`test_retention_runner.py::test_una_politica_rota_no_anula_las_siguientes` y
`::test_una_pasada_con_una_politica_rota_se_audita_como_fallida`.
