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
| D-16 | El check 23 de `verify-setup.sh` no tiene prueba negativa ejecutada (nadie lo ha visto fallar) | Fase 1 (Etapa 1.5) | backend |
| D-20 | El `FOR UPDATE` del producto que exige `aplicar_movimiento` es convención documentada, no enforced | Fase 1 (antes del piloto o al primer llamante nuevo) | backend |
| D-23 | El reintento de un ajuste cuyo producto fue dado de baja después devuelve 422 `producto_no_encontrado` en vez de la respuesta idempotente original | Fase 1 (antes del piloto) | backend |
| D-24 | Un ajuste con el `id` de otro tenant recibe 409 `ajuste_id_divergente` (efecto de la RLS que oculta la fila; criterio no firmado, espejo de `dispositivo_id_en_conflicto`) | Fase 1 (antes del piloto) | backend |
| D-25 | Una compra con `costo_unitario = 0` deja `ultimo_costo = 0` y el P&L mostrará margen del 100% hasta la próxima compra con costo real (decisión de producto pendiente) | Fase 1 (antes del piloto) | backend |
| D-26 | Una sesión puede cerrarse con `efectivo_esperado` NEGATIVO sin error (un egreso mayor que todo el efectivo de la sesión; decisión de producto pendiente: ¿advertencia al cerrar?) | Fase 1 (antes del piloto) | backend |
| D-28 | No hay delta de clientes hacia dispositivos: un cliente creado en una caja llega a la otra solo online (GET /clientes) | Fase 1 (antes del piloto) | backend |
| D-29 | La auth nativa de vendi-app (login por navegador del sistema: @capacitor/browser + esquema co.vendi.app:// + asset links para passkeys) no existe: la app autentica con el flujo WEB y el canal del piloto es la PWA instalada; el AAB nativo sigue siendo artefacto de CI | Fase 1 (antes del piloto nativo) | frontend |
| D-30 | Flake: la ordenación del outbox por `created_at` (= inicio de la transacción) puede invertir niveles de alerta entre eventos de la misma transacción; el test adversarial de inventario falla intermitente | Fase 1 (antes del piloto) | backend |

Cerradas en la Etapa 5, con su evidencia al final de este documento: **D-01**
(ROPC), **D-04** (Keycloak sin `--optimized`), **D-06** (`alembic_version`
escribible por el rol de la API), **D-07** (`exchange` del outbox sin defensa) y
**D-08** (el claim `groups` no se emite y `has_role()` era inerte).

Cerrada en la Task 0.5.3 de Fase 1: **D-02** (`manage-realm` en el proceso de la
API): el aprovisionamiento se movió al servicio `provisioner` (ADR-027).

Cerrada en la Tarea 8 del módulo inventario (Fase 1, Etapa 1.2): **D-14**
(`OperacionSync.datos` opcional en el contrato): el campo es requerido y la
operación sin `datos` es un 422 de pydantic, no una `rechazada` del lote.

Cerrada en la Tarea 11 del módulo inventario (Fase 1, Etapa 1.2): **D-12**
(el stock sin alertas de umbral): el punto único de aplicación de movimientos
emite `inventario.alerta_stock` al cruzar un nivel hacia abajo.

Cerrada en el QA adversarial del módulo inventario (Fase 1, Etapa 1.4): **D-22**
(el test literal `inventario.ajustar` → `tipo_desconocido` que la decisión 3
del plan daba por fijado y solo cubría el genérico).

Cerrada en la Tarea 9 del módulo caja y finanzas (Fase 1, Etapa 1.2): **D-15**
(`exigir_venta_anular` definido y exportado sin consumidor): el módulo 4 no le
dio uso y su propio vencimiento («si nada lo usa, se borra») mandaba retirarlo.

Cerrada en la Tarea 11 del módulo caja y finanzas (Fase 1, Etapa 1.2): **D-11**
(`caja_sesiones` existía y se poblaba sin endpoints propios): el módulo 4
entregó los endpoints de apertura, sesión actual, historial, cierre con arqueo
y movimientos (ADR-021).

Cerrada en la Tarea 12 del módulo fiado y clientes (Fase 1, Etapa 1.2): **D-10**
(`ventas.cliente_id` sin FK): se cerró adoptando el `cliente_id` del
dispositivo como PK de `clientes` (operación `cliente.crear` del lote), como
mandaba su vencimiento; la columna `ventas.cliente_id` se queda sin FK a
propósito.

Cerradas en el pago de deuda de concurrencia (Fase 1, antes del piloto — el
vencimiento de ambas): **D-13** (la carrera TOCTOU del cupo del catálogo:
`pg_advisory_xact_lock` por tenant serializa conteo e INSERT en
`_exigir_cupo`) y **D-21** (el sync de ventas bloquea los productos ordenados
por `producto_id`, la receta de la compra: el deadlock de orden inverso,
reproducido, ya no ocurre).

Cerradas en el pago de deuda del watermark y el candado de esquema (Fase 1 —
el vencimiento de ambas): **D-17** (`alembic check` corre en el job de
integración del CI contra la base migrada al head; la primera corrida ya
mordió: el `env.py` no importaba los modelos de negocio y el check proponía
borrar sus tablas) y **D-18** (el watermark del delta es
`now() - interval '5 seconds'`: la edición confirmada en la ventana se
re-entrega en el siguiente delta y el solape es inocuo porque el cliente
hace upsert por id).

Cerrada en el pago de deuda de la divergencia de compras (Fase 1 — su
vencimiento: antes del piloto): **D-19** (el reenvío de una compra con el
mismo `id` y payload distinto devolvía la existente en silencio): el
servicio compara el payload como `_reintento_de_ajuste` y el divergente es
409 `compra_id_divergente` con `details.campos`.

Cerrada en el pago de deuda del abono offline (Fase 1 — su vencimiento:
antes del piloto): **D-27** (el abono de fiado solo se registraba por REST
online): la operación `fiado.abonar` entra al lote del sync reutilizando
`FiadoService.registrar_abono` dentro del SAVEPOINT por operación — misma
ancla (el `id` de la operación), mismo FOR UPDATE, misma sesión de caja
resuelta en el servidor al aplicarse — y el cobro sin señal ya sube con la
cola del dispositivo.

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

## D-20 · El `FOR UPDATE` del producto es convención, no enforcement

**Qué es.** `aplicar_movimiento` (`inventario/stock.py`) asume que quien
llama cargó el producto con `with_for_update=True`: es un contrato escrito
en el docstring, y nada en el código lo exige. Un futuro llamante que cargue
el producto sin el bloqueo reabre el lost update de `stock_actual` (el que
el fix `49553da` cerró en ventas) y rompe la comparación antes/después de la
alerta.

**Por qué se aceptó.** Los cuatro llamantes actuales (venta, anulación,
compra, ajuste/merma) bloquean, y hay tests de carrera que lo demuestran
(`test_dos_compras_concurrentes_del_mismo_producto_dejan_el_stock_exacto`,
las carreras multi-caja de ventas). Forzarlo dentro de `aplicar_movimiento`
sería un SELECT extra por movimiento o una introspección frágil del estado
de la sesión.

**Riesgo si se olvida.** Un módulo futuro (importación masiva, traspasos)
que llame a `aplicar_movimiento` sin el bloqueo compila, pasa los tests de
unidad y corrompe el stock solo bajo concurrencia real.

**Vencimiento: Fase 1, antes del piloto o al primer llamante nuevo** (lo que
llegue antes): endurecer el punto único o revisar el llamante con este
mismo estándar.

**Candados mientras tanto:**

- El riesgo está concentrado: hay UN sitio donde vive el contrato (el
  docstring del punto único), no cinco copias.
- Los tests de carrera verdes en CI mueren si alguien quita el bloqueo de
  los caminos actuales.

---

## D-23 · El reintento de un ajuste sobre un producto dado de baja no es idempotente

**Qué es.** En `InventarioService.registrar_ajuste` el bloqueo/validación del
producto (`_producto_bloqueado`, que rechaza con 422 `producto_no_encontrado`
los productos dados de baja) corre ANTES del chequeo de la ancla de
idempotencia (`_reintento_de_ajuste`). Si el primer intento del ajuste se
confirmó y DESPUÉS el producto se dio de baja, el reintento byte-idéntico del
mismo ajuste no recupera la respuesta original: recibe un 422
`producto_no_encontrado`, como si el ajuste nunca hubiera existido.

**Por qué se aceptó.** El arreglo correcto (chequear la ancla antes de
validar el producto) exige reordenar el flujo para que el reintento no
necesite la fila del producto — hoy `_salida` calcula el nivel con el
`stock_minimo` del producto bloqueado — y eso mueve el orden de adquisición
del FOR UPDATE que la decisión 9 disciplina. La revisión final del módulo lo
dictaminó registrable, no bloqueante: el caso exige la secuencia ajuste →
baja → reintento, y el cliente que reintenta recibe un error tipado y
explicable, no un 500 ni un doble movimiento de stock.

**Riesgo si se olvida.** Un cliente offline-reactivo que reintenta un ajuste
tras la baja del producto interpreta el 422 como «el ajuste nunca entró» y
puede re-encolarlo o mostrar un falso pendiente; el ajuste SÍ está aplicado
en el libro. Nunca hay doble aplicación del delta: la fila del ajuste existe
y el delta ya se asentó en el primer intento.

**Vencimiento: Fase 1, antes del piloto.** Reordenar para que la ancla se
chequee antes de la validación del producto (persistiendo lo que `_salida`
necesita del producto en la fila del ajuste, o devolviendo el nivel sin él).

**Candados mientras tanto:**

- `backend/tests/test_inventario_servicio.py::test_el_reintento_del_ajuste_devuelve_lo_mismo_sin_mover_stock`
  (el reintento con el producto vivo sí es idempotente)

---

## D-24 · Un ajuste con el `id` de otro tenant recibe 409 `ajuste_id_divergente`

**Qué es.** En `InventarioService.registrar_ajuste`, un ajuste cuyo `id` ya
existe EN OTRO negocio no lo ve la RLS: el SELECT del reintento no encuentra
nada, el INSERT choca contra `ajustes_inventario_pkey` y
`_flush_traduciendo_integridad` lo traduce a 409 `ajuste_id_divergente` — el
mismo código que «mismo id con payload distinto en TU negocio», aunque aquí
no hay divergencia sino colisión con una fila invisible. Es el espejo de
`dispositivo_id_en_conflicto` (ventas): el criterio «la RLS decide qué
existe y el motivo no distingue ajeno de divergente» no está firmado para
los ajustes.

**Por qué se aceptó.** Detectado por el QA adversarial del módulo y
dictaminado aceptable: el 409 es tipado (nunca un 500), no fuga datos del
vecino (el detalle lleva los campos del PAYLOAD del llamante, no la fila
ajena), y fuera de un ataque la colisión de UUID entre tenants es
despreciable. Queda como decisión registrada pendiente de firma, no como
bug.

**Riesgo si se olvida.** Un cliente que reutiliza ids (migración desde otro
sistema, generador de UUID roto) recibe un mensaje («ya existe con datos
distintos») que describe un caso que no es el suyo, y si el criterio se
firma distinto en ventas, ajustes y dispositivos quedan desalineados sin
que nadie lo note.

**Vencimiento: Fase 1, antes del piloto.** Firmar el criterio: aceptar el
409 como decisión (espejo explícito de `dispositivo_id_en_conflicto`) o
distinguir los motivos, y alinear el mensaje con lo que el cliente puede
hacer al respecto.

**Candados mientras tanto:**

- `backend/tests/test_inventario_adversarial.py::test_el_ajuste_con_id_de_otro_tenant_es_409`
  (integration, corre en CI): el 409 es tipado, sin fila, sin movimiento y
  sin fuga del dato ajeno.
- `backend/tests/test_inventario_adversarial.py::test_el_ajuste_con_producto_de_otro_tenant_es_422_sin_fuga`:
  el mismo criterio RLS-decide para el producto del ajuste.
- `backend/tests/test_caja_adversarial.py::test_el_movimiento_con_id_de_otro_tenant_es_409_sin_tocar_la_fila_ajena`
  (integration, corre en CI): el C-4 del QA de caja es el MISMO fenómeno
  sobre `caja_movimientos` — el `id` del vecino choca contra
  `caja_movimientos_pkey` y sale 409 `movimiento_id_divergente` tipado, con
  la fila ajena intacta. La firma del criterio de D-24 cubre también este
  espejo; no se registra como deuda aparte.

---

## D-25 · Una compra con `costo_unitario = 0` deja `ultimo_costo = 0` y el P&L mostrará margen del 100%

**Qué es.** El schema de compras admite `costo_unitario_centavos = 0`
(`ge=0`: la bonificación del proveedor es un caso real) y
`registrar_compra` copia ese 0 a `productos.ultimo_costo` — el dato que el
P&L costea (ADR-006/020). Desde esa compra y hasta la próxima con costo
real, el P&L calculará margen del 100% sobre cada venta del producto.

**Por qué se aceptó.** Rechazar el 0 prohibiría las bonificaciones, y
«no tocar `ultimo_costo` cuando el costo es 0» dejaría costeado con un
precio que ya no es el de la última compra (la invariante firmada es que
`ultimo_costo` ES el costo de la última compra). Es una decisión de
producto pendiente: ¿permitir costo 0 tal cual, o exigir una confirmación
explícita (p. ej. `observaciones` obligatoria cuando el total es 0)?

**Riesgo si se olvida.** Un error de digitación (la factura decía 2000 y se
tecleó 0) infla silenciosamente el margen que el tendero ve en el P&L; el
dato se «cura» solo con la próxima compra, que puede no llegar nunca para
un producto de baja rotación.

**Vencimiento: Fase 1, antes del piloto.** Tomar la decisión de producto
(permitir, confirmar o requerir observaciones) y reflejarla en el schema o
en el servicio con su test.

**Candados mientras tanto:**

- `backend/tests/test_inventario_adversarial.py::test_la_compra_de_costo_cero_deja_ultimo_costo_en_cero`
  (integration, corre en CI): el comportamiento actual queda fijado —
  total 0, `ultimo_costo` 0, stock sumado — para que cualquier cambio sea
  una decisión explícita, no un efecto colateral.

---

## D-26 · Una sesión puede cerrarse con `efectivo_esperado` NEGATIVO sin error

**Qué es.** Un egreso manual mayor que todo el efectivo de la sesión (la
gaveta no da para el retiro, y el sistema no lo impide) deja
`efectivo_esperado < 0` y el cierre cuadra contra ese número: contado 0,
diferencia positiva. Ningún CHECK ni validación del cierre prohíbe el
esperado negativo.

**Por qué se aceptó.** El sobrante/faltante son DATOS del arqueo, no
errores: prohibir el cierre dejaría la caja abierta para siempre en un caso
que ya ocurrió físicamente. Pero un esperado negativo no describe una
realidad posible de la gaveta — indica algo roto upstream (un egreso mal
registrado, una venta en efectivo que no entró) — y hoy cierra en silencio.
Decisión de producto pendiente: ¿advertencia al cerrar (el arqueo lo
declara y exige confirmación) en vez del cierre mudo?

**Riesgo si se olvida.** El tendero cuadra contra un número imposible y el
arqueo «bien hecho» esconde el desfalco o el error de digitación que lo
produjo; la señal llega tarde o no llega.

**Vencimiento: Fase 1, antes del piloto.** Tomar la decisión de producto
(cierre mudo, advertencia con confirmación, o bloqueo) y reflejarla en
`cerrar_sesion` con su test.

**Candados mientras tanto:**

- `backend/tests/test_caja_adversarial.py::test_el_esperado_negativo_cierra_sin_error`
  (integration, corre en CI): el comportamiento actual queda fijado —
  esperado negativo, cierre sin error, diferencia contra el negativo —
  para que cualquier cambio sea una decisión explícita, no un efecto
  colateral.

---

## D-28 · No hay delta de clientes hacia dispositivos

**Qué es.** El delta del sync (`GET /api/v1/sync/delta`, ADR-017) drena el
catálogo — productos vivos modificados y tumbas — pero NO los clientes: un
cliente creado en una caja llega a la otra solo online, por
`GET /api/v1/clientes`. Offline, cada dispositivo ve los clientes que él
mismo creó.

**Por qué se aceptó.** Decisión 13 del plan del módulo fiado y clientes.
El caso real — dos cajas, una crea el cliente offline y la otra le fía sin
red antes de sincronizar — no es alcanzable sin que el segundo dispositivo
conozca el id del cliente, y ese id solo viaja hoy por la API online. La
red de seguridad del servidor (auto-alta placeholder `(sin nombre)` cuando
una venta fiada llega con un cliente desconocido, y el `cliente.crear`
tardío que mejora el placeholder) garantiza que el cuaderno nunca pierde
una deuda aunque el cliente llegue incompleto.

**Riesgo si se olvida.** En una tienda multi-caja con mala cobertura, la
caja 2 no puede fiarle a un cliente que la caja 1 acaba de crear: o espera
a la red, o el cliente se crea dos veces (uno por dispositivo) y el
cuaderno queda partido en dos fichas del mismo deudor, que alguien tiene
que unificar a mano.

**Vencimiento: Fase 1, antes del piloto.** Extender el delta con clientes
(mismo patrón watermark + upsert por id del catálogo) o firmar la decisión
contraria con su justificación si el piloto es monocaja.

**Candados mientras tanto:**

- `backend/tests/test_fiado_sync.py::test_la_venta_fiada_sin_cliente_conocido_no_se_rechaza`
  (integration, corre en CI): la venta fiada con cliente desconocido no se
  rechaza jamás — auto-alta placeholder editable después — así que la
  ausencia del delta no pierde fiados, solo comodidad.
- `backend/tests/test_fiado_sync.py::test_el_cliente_crear_tardio_mejora_el_placeholder`
  (integration, corre en CI): cuando el `cliente.crear` del dispositivo
  original llega, el placeholder se completa con el nombre real.
- `GET /api/v1/clientes` con búsqueda por nombre
  (`test_fiado_servicio.py::test_buscar_por_nombre`) es el camino online
  completo mientras tanto.

---

## D-29 · La auth nativa de `vendi-app` no existe: el canal del piloto es la PWA

**Qué es.** El plan maestro de la Etapa 1.3 pedía login por navegador del
sistema (`@capacitor/browser` + esquema `co.vendi.app://` + asset links para
passkeys). La pista móvil entregó el POS offline completo con el flujo **WEB**
(`AuthService`/`authGuard`/`tenantGuard` tal cual están, passkey en el
navegador) y dejó lo nativo para su propio subproyecto: la app del piloto es
la **PWA instalada** — que en Chrome Android tiene passkeys, service worker
de assets e IndexedDB, todo lo que el POS offline necesita. El AAB nativo
sigue siendo artefacto de CI (`android.yml` intacto) pero NO es el canal del
piloto.

**Por qué se aceptó.** Decisión 1 del plan de la pista móvil (tensión
declarada con el plan maestro, no escondida). El flujo nativo exige la
fachada en `native`, el manejo del deep-link de retorno (`appUrlOpen`), el
flujo OIDC manual fuera de keycloak-js (que navega con `window.location` y no
sirve para volver a la app), la asociación de asset links para passkeys y
—sobre todo— pruebas en dispositivo real que no son TDD-ables en CI. Es un
subproyecto propio, no una tarea más del cierre.

**Riesgo si se olvida.** El AAB instalado no puede iniciar sesión: el login
redirige dentro del WebView y el passkey falla. **Nadie debe repartir el AAB
del CI como «la app»**: el artefacto que se instala en el piloto es la PWA.

**Vencimiento: Fase 1, antes del piloto nativo / publicación** (depende de
B-3). Entregar la auth por navegador del sistema con sus pruebas en
dispositivo, o re-firmar la PWA como canal definitivo con su justificación.

**Candados mientras tanto:**

- El spec de `app.routes`
  (`frontend/projects/vendi-app/src/app/app.spec.ts`, el candado invertido de
  la decisión 10 del plan) fija que la ruta del POS lleva `authGuard` +
  `tenantGuard` y que `/elegir-negocio` no lleva `tenantGuard`: nadie
  improvisa un login dentro del WebView sin romper el test.
- La sección «POS offline-first en `vendi-app`» de
  [`docs/estado.md`](estado.md) declara la PWA como canal del piloto y el AAB
  como artefacto de CI, con el run `android` en verde como evidencia de que
  el workflow sigue produciéndolo sin cambios.

---

## D-30 · Flake: la ordenación del outbox por `created_at` puede invertir niveles de alerta

**Qué es.** `test_inventario_adversarial.py::test_dos_ventas_concurrentes_...`
falla de forma intermitente (reproducido ~5/10 en local, una vez en CI): el
`created_at` de `outbox_messages` es `now()` —inicio de la transacción— y la
ordenación por `(created_at, id)` puede invertir el orden real de los eventos
`bajo`/`agotado` cuando dos alertas confirman en la misma transacción o en
transacciones que comparten el mismo `now()`.

**Por qué queda abierta.** El flake está en la lectura del test (asume orden
cronológico estricto entre eventos) y, de fondo, en que el outbox no tiene
una secuencia monotónica propia. Arreglarlo de verdad es decidir si el
outbox gana una columna `secuencia` (migración + consumo) o si los tests de
alertas ordenan por `id`/no asumen orden. No es defecto del módulo de
inventario: la emisión exactamente-una-por-cruce está probada; es el orden
entre eventos lo que no está garantizado.

**Riesgo si se olvida.** Un CI rojo intermitente erosiona la señal del gate
(la regla del repo es que un rojo para la línea: con un flake conocido la
tentación es re-lanzar sin mirar, y entonces el rojo real pasa desapercibido).

**Vencimiento: antes del piloto.** Elegir e implementar una de las dos
correcciones (secuencia monotónica del outbox o tests que no asuman orden
estricto entre eventos de la misma transacción).

**Candados mientras tanto:** el test del cruce único
(`test_cruzar_hacia_abajo_emite_un_evento_por_cruce_y_no_por_movimiento`) y el
anti-spam (`test_dos_ventas_bajo_el_minimo_emiten_una_sola_alerta`) fijan la
emisión correcta sin depender del orden entre eventos.

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

### D-14 · `OperacionSync.datos` era opcional en el contrato

**Qué era.** En `OperacionSync` el campo `datos` tenía
`Field(default_factory=dict)`: una operación sin `datos` no era un 422 de
request; llegaba al servicio con `{}` y salía `rechazada` con motivo
`datos_invalidos`. El contrato OpenAPI tampoco marcaba `datos` como
requerido, así que un cliente que lo omitía no recibía la señal más temprana
posible.

**Cómo se cerró** (Tarea 8 del módulo inventario — el gatillo firmado de la
propia deuda: «Fase 1, módulo 3»). `datos` pasa a requerido en el schema
(`backend/services/api/app/modules/ventas/schemas.py`): la operación sin
`datos` es un 422 de pydantic en la frontera del lote, no una `rechazada`.
El comportamiento para `datos` presentes pero con contenido inválido NO
cambió: sigue siendo `rechazada` por operación (la unidad de fallo del lote
es la operación, decisión 6 del plan de ventas). El OpenAPI congelado
(`docs/api/openapi-fase0.json`) y el cliente TypeScript se actualizaron en
el mismo commit, así que el contrato publicado también marca `datos` como
requerido.

**Evidencia** (2026-07-28, rama `main`):

```
$ cd backend && uv run pytest tests/test_ventas_schemas.py -q -k sin_datos
1 passed, 14 deselected

$ python3 -c 'import json; d=json.load(open("docs/api/openapi-fase0.json"));
  print("datos" in d["components"]["schemas"]["OperacionSync"]["required"])'
True

$ CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh
→ el cliente TS queda con `datos:` requerido; una segunda corrida no cambia
  nada (sin deriva)
```

**Candados:**

- `backend/tests/test_ventas_schemas.py::test_una_operacion_sin_datos_es_422_de_schema`:
  pydantic corta la operación sin `datos` en la frontera.
- `backend/tests/api/test_ventas_sync.py::test_una_operacion_sin_datos_es_422_del_lote`
  (integration, corre en CI): el 422 es del request entero y nada se aplicó.
- `backend/tests/test_ventas_adversarial.py::test_una_operacion_sin_datos_ni_siquiera_entra_al_lote`:
  el ataque del QA adversarial que documentaba la deuda, reescrito — la
  operación sin `datos` ya no entra al servicio.
- `backend/tests/test_ventas_servicio.py::test_datos_mal_formados_rechazan_la_operacion_no_el_lote`
  (vigente): `datos` presentes pero inválidos siguen siendo `rechazada` con
  `datos_invalidos` sin arrastrar el lote.

---

### D-12 · El stock no tenía alertas de umbral

**Qué era.** El sync descontaba stock por deltas y actualizaba la proyección
`stock_actual`, pero nadie evaluaba `stock_minimo`: un producto podía quedar
en cero o en negativo (legítimo según ADR-020) sin que nadie se enterara.

**Cómo se cerró** (módulo inventario, Tareas 5 y 11 — su vencimiento
firmado). El nivel se deriva de `stock_minimo` (agotado `<= 0`, crítico
`< stock_minimo / 2`, bajo `< stock_minimo`, bordes estrictos) y se evalúa en
el punto ÚNICO por el que pasa todo movimiento
(`backend/services/api/app/modules/inventario/stock.py`,
`aplicar_movimiento`): con la fila del producto bloqueada `FOR UPDATE`, el
`stock_actual` antes del delta ES el estado post-commit del movimiento
anterior, así que la comparación es una función pura sin columna que
mantener. El evento `inventario.alerta_stock` (payload mínimo sin PII,
`resource_type="producto"`, clave `<tenant_id>.inventario.alerta_stock`) se
emite SOLO cuando el nivel empeora: nunca por movimiento, nunca al
recuperarse, nunca dos veces por el mismo cruce, y viaja en la misma
transacción que el movimiento. El servicio de ventas delega en el punto
único, así que una venta que cruza un umbral también alerta. Su consumidor
(el módulo de notificaciones, ADR-025) sigue sin existir: el evento queda
publicado en el outbox para cuando llegue.

**Evidencia** (run ci 30305515191 sobre `2d08df9`, 2026-07-27; los tests son
integration y corren contra el PostgreSQL real del CI):

```
$ uv run pytest tests/test_inventario_alertas.py -q
14 passed            # bordes estrictos; cruce único; anti-spam de la cola
                     # de sync; recuperación y nuevo cruce; la duplicada no re-emite
```

**Candados:**

- `backend/tests/test_inventario_alertas.py` (14 tests): un evento por cruce
  aunque haya N movimientos bajo el mismo umbral; recuperarse no emite y
  volver a cruzar sí; la operación `duplicada` del sync no re-emite.
- `backend/tests/test_ventas_servicio.py::test_el_stock_puede_quedar_negativo_y_la_venta_se_acepta`
  (reforzado en este módulo): el negativo sigue siendo legítimo y ahora
  demuestra la alerta de `agotado`.
- `backend/tests/test_inventario_servicio.py::test_comprar_no_emite_alerta_aunque_salga_del_rojo`:
  la compra que repone stock no alerta (re-arma el umbral).

---

### D-22 · Faltaba el test literal `inventario.ajustar` → `tipo_desconocido`

**Qué era.** La decisión 3 del plan del módulo firma que un lote con
`tipo: "inventario.ajustar"` sale `rechazada` con `tipo_desconocido` y dice
«hay test que lo fija», pero lo que existía era el genérico
(`test_un_tipo_desconocido_es_rechazada_no_422`, con un tipo inventado, y el
adversarial con inyección SQL): el comportamiento estaba cubierto, el
literal del plan no.

**Cómo se cerró** (QA adversarial del módulo, commit `c949048` — su
vencimiento firmado: «Fase 1, Etapa 1.4»). El test literal
`backend/tests/test_inventario_adversarial.py::test_el_lote_con_tipo_inventario_ajustar_es_tipo_desconocido_y_no_toca_nada`:
un lote con el tipo propio y un payload de ajuste perfectamente formado —no
una basura cualquiera— sale `rechazada` con `tipo_desconocido`, y ni fila
de ajuste, ni movimiento, ni stock tocado. Si alguien registra
`inventario.ajustar` como tipo del sync en el futuro, ESTE test se pone
rojo con nombre propio.

**Evidencia** (run ci 30309869727 sobre `f8fa154`, 2026-07-27; el test es
integration y corre contra el PostgreSQL real del CI):

```
$ gh run view 30309869727 --log   # job «backend / pytest -m integration (stack real)»
300 passed, 402 deselected        # incluye
                                  # test_el_lote_con_tipo_inventario_ajustar_es_tipo_desconocido_y_no_toca_nada
```

El run también cubrió los dos runs rojos anteriores: 30307855551 (sobre
`c949048`, donde nació el test) y 30308638352 (sobre `5071c29`) lo
ejecutaron y pasó, pero el job quedó rojo por el aritmético de umbrales de
`test_el_nivel_se_deriva_del_minimo_vigente...` (con mínimo 30 el stock 10
ya es crítico y nunca hay cruce bajo → crítico; corregido a mínimo 12 en
`9dd0215`) y por el flake de reloj de
`test_el_mismo_lote_dos_veces_deja_una_venta_un_movimiento_y_un_evento`
(el lote se construía por envío con `datetime.now()`; corregido en
`f8fa154` construyéndolo una sola vez).

**Candados:**

- El propio test literal, en CI sobre PostgreSQL real en cada push.
- `backend/tests/test_ventas_servicio.py::test_un_tipo_desconocido_es_rechazada_no_422`
  y `backend/tests/test_ventas_adversarial.py::test_un_tipo_con_inyeccion_sql_es_tipo_desconocido_y_no_pasa_nada`
  (los genéricos que ya cubrían el comportamiento, vigentes).

---

### D-15 · `exigir_venta_anular` estaba definido sin consumidor

**Qué era.** `backend/services/api/app/modules/ventas/dependencies.py`
definía y exportaba `exigir_venta_anular = exigir_permiso(PERM_VENTA_ANULAR)`
sin endpoint que lo usara: la anulación viaja como operación del lote del
sync y su chequeo es por operación dentro del servicio (decisión 12 del plan
de ventas). Código muerto exportado con nombre de permiso.

**Cómo se cerró** (Tarea 9 del módulo caja y finanzas — el vencimiento
firmado de la propia deuda: «Fase 1, módulo 4; si nada lo usa, se borra»,
decisión 11 del plan del módulo). El módulo 4 es caja y finanzas: ningún
endpoint nuevo le dio uso, así que se retiró la definición y su entrada en
`__all__`. El import de `PERM_VENTA_ANULAR` se conserva porque
`servicio_de_ventas` lo usa para derivar `puede_anular` (el chequeo por
operación no cambió). Si un futuro endpoint de anulación online lo necesita,
vuelve con una línea: `exigir_permiso(PERM_VENTA_ANULAR)`.

**Evidencia** (2026-07-28, rama `main`):

```
$ cd backend && grep -rn "exigir_venta_anular" . --include="*.py"
                                  → (sin resultados: ni definición, ni usos,
                                     ni imports en tests)

$ uv run pytest -q -m 'not integration'
412 passed, 354 deselected

$ uv run ruff check . && uv run ruff format --check .
All checks passed! · 218 files already formatted
```

**Candados:**

- El 403 por rol sigue probándose de verdad a nivel operación:
  `backend/tests/api/test_ventas_sync.py` (lote de anulaciones del cajero →
  todas `rechazada` con `permiso_ausente`) y
  `backend/tests/test_ventas_servicio.py` (mismo caso en el servicio) —
  los mismos candados que la deuda ya declaraba, ahora permanentes.

---

### D-11 · `caja_sesiones` existía y se poblaba sin endpoints propios

**Qué era.** La tabla `caja_sesiones` se creó completa en la migración `0005`
y el sync la poblaba (toda venta sincronizada pertenece a la sesión abierta
del tenant o a una implícita nueva con `base_inicial = 0`), pero no había
endpoints para abrir, cerrar ni arquear sesiones: eran del módulo 4.

**Cómo se cerró** (Tarea 11 del módulo caja y finanzas — su propio
vencimiento: «Fase 1, módulo 4 (caja y arqueo)»). El módulo entregó los
endpoints REST online firmados en ADR-021: apertura explícita idempotente
(`POST /api/v1/caja/sesiones`), sesión actual con el esperado vivo
condicionado por permiso (`GET /api/v1/caja/sesiones/actual`), historial de
arqueos (`GET /api/v1/caja/sesiones`, exige `caja:cerrar`), cierre con arqueo
que suma desde las tablas de origen y se congela
(`POST /api/v1/caja/sesiones/{sesion_id}/cerrar`) y movimientos manuales
(`GET`/`POST /api/v1/caja/movimientos`). Las sesiones implícitas ya vivas se
cierran y arquean por los mismos endpoints: ninguna queda abierta sin camino
de cierre.

**Evidencia** (2026-07-28, rama `main`, HEAD `9510891`):

```
$ cd backend && uv run pytest --collect-only -q tests/api/test_caja_api.py
13 tests collected

$ uv run pytest -q -m integration   # run ci 30318420990: los 13 pasan contra PostgreSQL real, 0 SKIPPED
354 passed, 412 deselected

$ python3 -c "import json; print('\n'.join(sorted(p for p in json.load(open('../docs/api/openapi-fase0.json'))['paths'] if 'caja' in p)))"
/api/v1/caja/movimientos
/api/v1/caja/sesiones
/api/v1/caja/sesiones/actual
/api/v1/caja/sesiones/{sesion_id}/cerrar
```

**Candados:**

- Los que la deuda ya declaraba, vigentes: el índice único parcial
  `(tenant_id) WHERE estado = 'abierta'` y los tests del sync que resuelve la
  sesión implícita.
- Los nuevos del módulo: `backend/tests/test_aislamiento_caja.py` (9 tests
  cross-tenant) y los candados del arqueo de ADR-021 (cuadre al peso,
  congelamiento, carrera de aperturas y de cierres), en CI en cada push.

---

### D-10 · `ventas.cliente_id` no tenía FK

**Qué era.** La venta fiada llevaba `cliente_id`, pero la columna no
referenciaba a ninguna tabla: `clientes` era del módulo 5 y no existía. El
vencimiento firmado mandaba: al crear `clientes`, adoptar el `cliente_id`
del dispositivo como PK (mismo patrón que `ventas` y `productos`) o migrar
las referencias.

**Cómo se cerró** (módulo fiado y clientes, Tareas 7 y 12 — su propio
vencimiento). Se adoptó la primera opción: la tabla `clientes` (migración
`0009`) usa como PK el UUID que genera el dispositivo, y el cliente sube
por el lote del sync con la operación nueva `cliente.crear` — el orden FIFO
de la cola del dispositivo garantiza que precede a la venta fiada que lo
referencia. La conversión venta → crédito existe y tiene tests: toda venta
`medio_pago='fiado'` aceptada crea su `fiado_creditos` en la misma
transacción (SAVEPOINT) de la operación, con `saldo_pendiente = total` y el
evento `fiado.credito_creado`. La columna `ventas.cliente_id` se queda SIN
FK a propósito (decisión 4 del plan): la venta no se rechaza jamás
(ADR-018) y Postgres no aplica RLS al verificar llaves foráneas, así que la
FK no añadiría aislamiento, solo fragilidad — un `cliente_id` de otro
tenant pasaría la FK sin ser visible. Lo que sí lleva FK RESTRICT es
`fiado_creditos.cliente_id`: el crédito lo crea el servidor, que garantiza
la fila del cliente antes (incluida la auto-alta placeholder `(sin nombre)`
cuando la venta fiada llega sin cliente conocido).

**Evidencia** (run ci 30331195290 sobre `fd55d86`, 2026-07-28; los tests
son integration y corren contra el PostgreSQL real del CI):

```
$ cd backend && uv run pytest --collect-only -q tests/test_fiado_sync.py
15 tests collected     # cliente.crear del lote con el id del dispositivo
                       # como PK; la venta fiada crea su crédito; la anulación
                       # anula el crédito; el reenvío no duplica

$ uv run pytest -q -m integration   # run ci 30331195290
449 passed, 430 deselected          # incluye los 15 de test_fiado_sync.py
                                    # y los 15 de test_aislamiento_fiado.py
```

**Candados:**

- `backend/tests/test_fiado_sync.py::test_cliente_crear_del_lote_crea_la_fila`
  y `::test_la_venta_fiada_se_convierte_en_credito_en_la_misma_transaccion`:
  la adopción del id del dispositivo y la conversión venta → crédito.
- `backend/tests/test_fiado_sync.py::test_la_venta_fiada_sin_cliente_conocido_no_se_rechaza`:
  la red de seguridad — el cuaderno nunca pierde una deuda.
- `backend/tests/test_ventas_servicio.py` (los candados que la deuda ya
  declaraba, vigentes): fiado sin cliente es `rechazada`
  `fiado_requiere_cliente`; cliente en venta no fiada,
  `cliente_solo_en_fiado`.

---

### D-13 · Carrera TOCTOU del cupo de tier del catálogo

**Qué era.** `_exigir_cupo` contaba las filas vivas y luego insertaba: con
99 productos y dos sesiones intercaladas (A hace flush sin commit, B cuenta
99 y pasa, ambas confirman) el negocio quedaba con **101 productos sobre un
límite de 100** — documentado con test por el QA adversarial del catálogo.

**Cómo se cerró** (pago de deuda de concurrencia, Fase 1 — su vencimiento:
antes del piloto). Con la receta que la propia entrada proponía:
`SELECT pg_advisory_xact_lock(hashtext(:tenant))` al entrar en
`_exigir_cupo` (`backend/services/api/app/modules/catalogo/service.py`),
antes del conteo. El bloqueo es de transacción: la segunda alta espera al
commit de la primera y su conteo ya ve la fila nueva — 100 >= 100 y sale el
403 tipado `limite_de_productos_alcanzado`. Se eligió el advisory lock sobre
un `FOR UPDATE` a una fila del negocio porque no hay fila local que bloquear
(el negocio vive en Keycloak, en Organizations) y no toca el esquema; una
colisión de `hashtext` entre tenants solo serializa de más, nunca de menos.
El costo —altas del MISMO negocio serializadas, y solo en tiers con límite—
es despreciable. El test que documentaba el 101/100 se invirtió (como la
entrada mandaba): ahora fija el rechazo de la segunda alta y el 100/100
final.

**Evidencia** (run ci 30339144864 sobre `61d67fc`, 2026-07-28; los tests son
integration y corren contra el PostgreSQL real del CI; la corrida local de
desarrollo usó un PostgreSQL 17 desechable con los init scripts del repo y
las migraciones al head):

```
$ cd backend && uv run pytest -q tests/test_catalogo_adversarial.py
9 passed        # incluye test_la_carrera_del_cupo_rechaza_la_segunda_alta:
                # el intercalado que antes dejaba 101/100 ahora rechaza la
                # segunda alta con limite_de_productos_alcanzado (100/100)

# ROJO previo (mismo test, código sin el arreglo): fallaba porque la
# segunda alta PASABA — el cupo seguía siendo poroso.

$ uv run pytest -q tests/test_catalogo_adversarial.py tests/test_catalogo_servicio.py \
    tests/test_ventas_adversarial.py tests/test_ventas_servicio.py tests/test_ventas_fixes_qa.py \
    tests/test_sync_idempotente.py tests/test_inventario_servicio.py tests/test_inventario_adversarial.py
108 passed      # PG desechable local; los tests del cupo (gratis 100, light
                # 500, filas vivas) siguen verdes con el bloqueo

$ uv run pytest -q -m 'not integration'
430 passed
$ uv run ruff check .
All checks passed!

$ uv run pytest -q -rs -m integration     # run ci 30339144864 sobre 61d67fc
475 passed, 430 deselected                # 0 SKIPPED (el grep del job lo exige)
```

**Candados:**

- `backend/tests/test_catalogo_adversarial.py::test_la_carrera_del_cupo_rechaza_la_segunda_alta`:
  la carrera intercalada exige el rechazo de la segunda alta y el 100/100;
  muere si alguien quita el advisory lock.
- Los tres tests del cupo que la entrada ya citaba, vigentes:
  `tests/api/test_catalogo_productos.py::test_el_limite_del_tier_da_403`,
  `test_catalogo_servicio.py::test_el_limite_del_tier_se_verifica_contra_las_filas_vivas`
  y `::test_el_limite_del_tier_light_se_detiene_en_500`.
- D-09 sigue viva y ahora importa más: cuando el tier deje de ser `pro` para
  todos, el cupo ya es exacto bajo concurrencia.

---

### D-21 · El sync de ventas bloqueaba los productos en el orden del ticket

**Qué era.** `_registrar_venta` tomaba el `FOR UPDATE` de cada producto en
el orden en que los ítems venían en el ticket del cliente: dos lotes
concurrentes con el mismo surtido en orden inverso adquirían los bloqueos en
orden opuesto y Postgres los interbloqueaba (`DeadlockDetected` → 500; la
idempotencia absorbía el reintento, pero era un error ruidoso esperando la
hora pico del piloto).

**Cómo se cerró** (pago de deuda de concurrencia, Fase 1 — su vencimiento:
antes del piloto). La receta firmada en la entrada, que es la de la compra
(decisión 9): la consolidación por producto (BUG-1 del QA) va primero y en
el orden del ticket, y los `FOR UPDATE` se toman después, ordenados por
`producto_id` (`backend/services/api/app/modules/ventas/service.py`). Lo
único que cambia es el orden de ADQUISICIÓN de los bloqueos: los movimientos
del libro se insertan en el orden del ticket, como antes — se verificó que
ningún índice ni la lógica imponen un orden (`ux_movimientos_origen` es
único por (tenant, tipo, referencia, producto), no por posición)— y se
conserva por no permutar lo que el cliente ve. El test nuevo corre los dos
lotes con el surtido invertido en `asyncio.gather`: antes del arreglo
reventaba con `DeadlockDetectedError` (reproducido en el ROJO del TDD);
ahora el perdedor espera el commit del ganador sobre la MISMA primera fila y
ambos lotes aplican una sola vez.

**Evidencia** (run ci 30339144864 sobre `61d67fc`, 2026-07-28; la corrida
local de desarrollo usó un PostgreSQL 17 desechable con los init scripts del
repo y las migraciones al head):

```
# ROJO previo (test nuevo, código sin el arreglo):
asyncpg.exceptions.DeadlockDetectedError: deadlock detected
DETAIL:  Process 173 waits for ShareLock on transaction 882; blocked by process 172.
         Process 172 waits for ShareLock on transaction 880; blocked by process 173.
[SQL: SELECT ... FROM productos WHERE productos.id = $1::UUID FOR UPDATE]

$ cd backend && uv run pytest -q tests/test_ventas_adversarial.py
16 passed       # incluye
                # test_lotes_con_el_mismo_surtido_en_orden_inverso_no_se_interbloquean:
                # dos cajas, [arroz, huevo] y [huevo, arroz] en gather, ambas
                # aceptada, stock exacto (10−2 y 3−2) y 4 movimientos

$ uv run pytest -q tests/test_caja_servicio.py tests/test_caja_adversarial.py \
    tests/test_caja_anulacion_sync.py tests/test_fiado_servicio.py \
    tests/test_fiado_adversarial.py tests/test_aislamiento_ventas.py \
    tests/test_aislamiento_inventario.py tests/test_outbox_transaccional.py
123 passed      # idempotencia, anulaciones y carreras de caja intactas:
                # solo cambió el orden de adquisición de los bloqueos

$ uv run pytest -q -rs -m integration     # run ci 30339144864 sobre 61d67fc
475 passed, 430 deselected                # 0 SKIPPED (el grep del job lo exige)
```

**Candados:**

- `backend/tests/test_ventas_adversarial.py::test_lotes_con_el_mismo_surtido_en_orden_inverso_no_se_interbloquean`:
  dos lotes con orden inverso en `gather`; muere (por deadlock o por stock
  erróneo) si alguien vuelve a bloquear en el orden del ticket.
- `backend/tests/test_inventario_adversarial.py` (la compra con 200
  productos ordenados) y `test_sync_idempotente.py`, vigentes: la receta de
  la compra y la idempotencia del sync no se tocaron.

---

### D-17 · `alembic check` no corría en CI

**Qué era.** Nada comparaba la metadata de los modelos SQLAlchemy con el DDL
que producen las migraciones: una columna añadida al modelo sin migración (o
al revés) solo se notaba cuando un test la tocaba, y una deriva que ningún
test tocara llegaba silenciosa a producción.

**Cómo se cerró** (pago de deuda, Fase 1 — su vencimiento). La investigación
previa respondió que `alembic check` (Alembic 1.18) sí funciona con el setup
del repo: el `env.py` ya lee `DATABASE_URL` del entorno y no pide más
variables. Y la primera corrida mordió de inmediato: el `env.py` solo
importaba `Tenant`, `AuditLog`, `File` y `OutboxMessage`, así que el check
proponía **borrar todas las tablas de negocio** (`productos`, `ventas`,
`caja_sesiones`, `dispositivos`, `compras`, `clientes`…) por no estar en el
metadata. Se corrigió el `env.py` importando los cinco módulos de modelos
que faltaban (la misma lista que registra `test_rls_coverage.py`) y con eso
el check sale limpio: no había deriva real, solo el punto ciego. El candado
quedó como paso «Candado metadata↔DDL (alembic check)» del job
`backend-integration` de `.github/workflows/ci.yml`, tras «Migrar y
sembrar»: reutiliza el stack ya levantado y migrado al head (coste de
segundos; en un job propio o con `services:` habría que reproducir el
initdb de roles, ver la nota 1 de la cabecera del workflow) y corre con el
mismo DSN de `vendi_platform` que `migrate.sh`.

**Evidencia** (run ci 30342293905 sobre `d919b1a`, 2026-07-28; la corrida
local usó un PostgreSQL 17 desechable con los init scripts del repo y las
migraciones al head):

```
$ cd backend/services/api && DATABASE_URL="postgresql+asyncpg://vendi_platform:***@127.0.0.1:55432/vendi" \
    uv run --project ../.. alembic check      # con el env.py ANTES del arreglo
INFO  [alembic.autogenerate.compare.tables] Detected removed table 'productos'
INFO  [alembic.autogenerate.compare.tables] Detected removed table 'ventas'
... (12 tablas de negocio: el env.py no importaba sus modelos)
FAILED: New upgrade operations detected: [('remove_index', ...), ('remove_table', Table('productos', ...

$ ... alembic check                           # con el env.py ya corregido
No new upgrade operations detected.           # exit=0: metadata y DDL al head coinciden

# En el CI, run 30342293905, job «backend / pytest -m integration (stack real)»,
# paso «Candado metadata↔DDL (alembic check)»: corre tras «Migrar y sembrar»
# contra la base del compose en el head y termina en verde en el mismo run
# que ejecuta la suite de integración (477 passed, 0 SKIPPED).
```

**Candados:**

- El propio paso del CI: una deriva metadata↔DDL pone rojo el job de
  integración en el siguiente push, con el diff del autogenerate en el log.
- `backend/tests/test_rls_coverage.py` sigue registrando todo modelo nuevo:
  un modelo que se añada allí pero no al `env.py` deja el check proponiendo
  borrar su tabla — el candado avisa en los dos sentidos.

---

### D-18 · El watermark del delta se fijaba con `now()` antes de leer

**Qué era.** `delta_productos` tomaba `hasta = now()` del servidor y DESPUÉS
leía los productos con `updated_at > desde`: una edición confirmada en la
ventana entre la captura y la lectura (su `updated_at` ya quedaba por debajo
del `hasta`) no llegaba en esa respuesta ni en ninguna posterior, y el
catálogo del dispositivo quedaba stale en silencio — el ticket salía con el
precio que el tendero ya había corregido.

**Cómo se cerró** (pago de deuda, Fase 1 — su vencimiento: antes del
piloto). Con la mitigación firmada en la propia entrada: el watermark de
salida es `now() - interval '5 seconds'`
(`backend/services/api/app/modules/ventas/service.py::delta_productos`). El
margen re-entrega en el siguiente delta lo confirmado dentro de la ventana,
y el solape es inocuo porque el cliente hace upsert por id — verificado
contra el contrato del endpoint: el docstring de `/sync/delta` manda guardar
el `hasta` tal cual como próximo `desde`, y el de `DeltaSalida` (OpenAPI
congelado) define los productos del delta como el estado a volcar en
IndexedDB, no como un diff estricto. El test que fijaba el contrato del
watermark se ajustó como la entrada ordenaba (el `hasta` con margen solo se
garantiza por encima de un `desde` anterior al margen, que es el caso real)
y dos tests nuevos fijan el margen: el watermark devuelto es `now() - 5s`
(el cliente lo guarda tal cual) y un producto editado «justo ahora» llega de
todos modos en el delta siguiente. El primer run del CI mordió además el
test de API del delta (`test_el_delta_baja_el_catalogo_y_las_tumbas`), que
daba por sentado «desde el watermark devuelto no hay nada nuevo»: con el
margen, lo confirmado dentro de los 5s se re-entrega, y ese test ahora fija
exactamente eso — la re-entrega del producto recién creado y nada más.

**Evidencia** (run ci 30342293905 sobre `d919b1a`, 2026-07-28; la corrida
local usó un PostgreSQL 17 desechable con los init scripts del repo y las
migraciones al head):

```
# ROJO previo (los dos tests nuevos, código sin el arreglo):
$ cd backend && uv run pytest tests/test_ventas_servicio.py -k 'watermark or margen'
FAILED tests/test_ventas_servicio.py::test_el_watermark_del_delta_lleva_el_margen_de_solape
FAILED tests/test_ventas_servicio.py::test_un_producto_editado_dentro_del_margen_llega_en_el_siguiente_delta
2 failed, 1 passed        # el producto editado en la ventana NO llegaba en
                          # el siguiente delta: el catálogo quedaba stale

$ uv run pytest -q tests/test_ventas_servicio.py
26 passed                 # con el margen: los dos tests nuevos y el contrato
                          # del watermark (ajustado como la entrada mandaba)

$ uv run pytest -q -m 'not integration'
430 passed
$ uv run ruff check .
All checks passed!

$ uv run pytest -q -rs -m integration     # run ci 30342293905 sobre d919b1a
477 passed, 430 deselected                # 0 SKIPPED (el grep del job lo exige)
```

**Candados:**

- `backend/tests/test_ventas_servicio.py::test_el_watermark_del_delta_lleva_el_margen_de_solape`:
  exige que el `hasta` quede ≥4s por debajo del `now()` del servidor; muere
  si alguien quita el margen.
- `backend/tests/test_ventas_servicio.py::test_un_producto_editado_dentro_del_margen_llega_en_el_siguiente_delta`:
  la edición dentro de la ventana llega en el delta siguiente; muere si el
  watermark vuelve a adelantarse a la lectura.
- `backend/tests/api/test_ventas_sync.py::test_el_delta_baja_el_catalogo_y_las_tumbas`
  fija el solape a nivel de endpoint: desde el `hasta` devuelto llega de
  nuevo lo confirmado dentro del margen, y nada más.

---

### D-19 · El reenvío de una compra con otro payload no detectaba la divergencia

**Qué era.** `InventarioService.registrar_compra`: si llegaba una compra con
un `id` ya registrado, devolvía la existente **sin comparar**
`proveedor_nombre`, `fecha` ni los ítems — un no-op silencioso ante la
divergencia, asimétrico con ajustes (409 `ajuste_id_divergente`) y ventas
(`rechazada` con motivo). El riesgo firmado: una app que reintenta con datos
corregidos recibía el 201 de la compra VIEJA y creía grabada la corrección.

**Cómo se cerró** (pago de deuda, Fase 1 — su vencimiento: antes del
piloto). Con la receta que la propia entrada proponía: `_reintento_de_compra`
(`backend/services/api/app/modules/inventario/service.py`), espejo de
`_reintento_de_ajuste`. Payload idéntico → se devuelve la existente (el
reintento legítimo, sin duplicar stock ni evento). Divergente → 409
`compra_id_divergente` con `details={"campos": [...]}`: `proveedor_nombre`,
`observaciones`, `items` (comparación normalizada como en ventas: la cantidad
guardada `10.000` de NUMERIC(14,3) iguala a la enviada `10` vía `Decimal`, en
conjunto sin orden — el schema prohíbe producto repetido) y `fecha` solo
cuando el cliente la envía (si vino en NULL la puso el servidor y el
reintento no puede reproducirla). La carrera de dos PRIMEROS envíos con el
mismo `id` sigue cayendo en `compras_pkey` y sale 409 tipado
(`compra_id_duplicado`), nunca 500 — fijado en test.

**Evidencia** (run ci 30344948097 sobre `91060d1`, que contiene el fix
`0a1354f`, 2026-07-28; la corrida local usó un PostgreSQL 17 desechable con
los init scripts del repo y las migraciones al head):

```
# ROJO previo (los dos tests de divergencia, código sin el arreglo):
$ cd backend && uv run pytest tests/test_inventario_servicio.py \
    -k 'otro_proveedor or otros_items'
FAILED tests/test_inventario_servicio.py::test_el_mismo_id_de_compra_con_otro_proveedor_es_409
FAILED tests/test_inventario_servicio.py::test_el_mismo_id_de_compra_con_otros_items_es_409
2 failed          # el reenvío divergente devolvía la existente EN SILENCIO

$ uv run pytest -q tests/test_inventario_servicio.py tests/test_inventario_adversarial.py
40 passed         # PG desechable local; incluye los dos de divergencia y
                  # test_dos_primeros_envios_concurrentes_de_la_misma_compra_dejan_una
                  # (la carrera cae en la pkey → 409 compra_id_duplicado:
                  # UNA fila, UN evento, el stock sumado UNA vez)

$ uv run pytest -q -m 'not integration'
430 passed
$ uv run ruff check . && uv run ruff format --check .
All checks passed! · 236 files already formatted

$ uv run pytest -q -m integration    # run ci 30344948097 sobre 91060d1 (contiene 0a1354f)
480 passed, 430 deselected           # 0 SKIPPED (el grep del job lo exige)
```

**Candados:**

- `backend/tests/test_inventario_servicio.py::test_el_mismo_id_de_compra_con_otro_proveedor_es_409`
  y `::test_el_mismo_id_de_compra_con_otros_items_es_409`: la divergencia es
  409 con los campos que difieren y la compra original queda intacta; mueren
  si el no-op silencioso vuelve.
- `backend/tests/test_inventario_servicio.py::test_registrar_compra_es_idempotente_por_el_id_del_cliente`:
  el reenvío idéntico sigue siendo un no-op (ni doble fila, stock ni evento).
- `backend/tests/test_inventario_adversarial.py::test_dos_primeros_envios_concurrentes_de_la_misma_compra_dejan_una`:
  la carrera de dos primeros envíos se resuelve por la pkey con 409 tipado.

---

### D-27 · El abono de fiado no viajaba por el lote del sync

**Qué era.** Los abonos del cuaderno se registraban SOLO por REST online
(`POST /api/v1/fiado/creditos/{credito_id}/abonos`). ADR-022 firma «un
abono registrado sin señal tiene que sincronizar sin duplicarse», pero la
operación `fiado.abonar` del lote quedó fuera del módulo 5 (decisión 6):
en una tienda, cobrar un fiado sin señal es tan normal como vender sin
señal — el POS encolaba la venta y el abono no podía encolarse, y el
cuaderno del dispositivo y el del servidor se desarmaban hasta que hubiera
red para cobrar por REST.

**Cómo se cerró** (pago de deuda, Fase 1 — su vencimiento: antes del
piloto). Con la receta de la propia entrada: UN camino nuevo del lote que
llama al MISMO servicio, sin tocar lo entregado.

- Schema `AbonoSync` (`fiado/schemas.py`): `cliente_id` REQUERIDO como
  ancla de coherencia (el dispositivo cobró contra el crédito que veía en
  el cuaderno de ESE cliente), `credito_id`, `monto` en centavos con la
  cota `le=TOPE_PRECIO` del abono online, `metodo_pago` de la lista
  firmada, `nota` con el validador `before` que no asume `str`.
  `sesion_caja_id` NO viaja (`extra="forbid"`): la sesión la resuelve el
  servidor.
- Dispatch `fiado.abonar` en `VentasService._aplicar_operacion`, dentro del
  SAVEPOINT por operación → `_registrar_abono`: el permiso `fiado:abonar`
  se exige POR OPERACIÓN (flag `puede_abonar`, fail-closed, patrón
  `puede_anular`); para `efectivo` se resuelve la sesión abierta ANTES del
  crédito (sesión → crédito, el orden que rompe el ciclo de espera con la
  anulación) abriendo la implícita si no hay ninguna (ADR-018: el cobro
  ocurrió físicamente, el lote no lo rechaza); y se delega en
  `registrar_abono_sync` (`fiado/sync.py`), que verifica el ancla
  cliente↔crédito (`rechazada abono_cliente_divergente`) y aplica con
  `FiadoService.registrar_abono` — el id del abono ES el id de la
  operación, la ancla de ADR-022 ya puesta en el POST online.
- Los errores de dominio del servicio (`abono_excede_saldo`,
  `credito_no_encontrado`, `credito_no_abonable`, `abono_id_divergente`)
  suben como excepción FUERA del savepoint y `_aplicar_operacion` los
  traduce a `rechazada` con el `code` como motivo: el 422/409/404 del
  online es por operación en el lote y no arrastra a las demás. El
  `campos_desconocidos` de `_validar_datos` se re-lanza intacto: sigue
  siendo el 422 del request entero, como antes.
- Idempotencia: la existencia previa de la PK distingue `duplicada` de
  `aceptada` (la fila es la prueba, ADR-017); el reenvío con otro monto es
  `rechazada abono_id_divergente`, nunca un no-op mudo. Cross-tenant: el
  crédito ajeno es invisible por RLS → `rechazada credito_no_encontrado`,
  el MISMO motivo que un inexistente — sin fuga.
- El contrato OpenAPI NO cambia (`fiado.abonar` viaja en
  `OperacionSync.datos`, como `cliente.crear`): el codegen contra el
  congelado no produce diff.

**Evidencia** (run ci 30348115730 sobre `0b613e8`, 2026-07-28; la corrida
local usó un PostgreSQL 17 desechable —contenedor `vendi-d27-pg`, puerto
127.0.0.1:55432, init scripts del repo y migraciones al head— sin tocar los
contenedores ajenos):

```
# ROJO previo (los 7 tests nuevos contra el backend SIN el cambio, vía
# `git stash` del código y pop inmediato):
$ cd backend && VENDI_TEST_PG_PORT=55432 uv run pytest tests/test_fiado_abono_sync.py -q
7 errors            # el fixture revienta: `VentasService` no conoce
                    # `puede_abonar` ni existe el dispatch `fiado.abonar`

$ VENDI_TEST_PG_PORT=55432 uv run pytest tests/test_fiado_abono_sync.py -q
7 passed            # feliz (saldo baja, sesión resuelta en el servidor,
                    # evento), sesión implícita si no hay abierta,
                    # reintento = duplicada sin doble descuento ni doble
                    # evento, exceso = rechazada abono_excede_saldo sin
                    # arrastrar el lote, almacenista = permiso_ausente,
                    # crédito ajeno = credito_no_encontrado sin fuga,
                    # ancla cliente↔crédito = abono_cliente_divergente

# Suites integration vecinas contra el PG desechable (regresión):
$ VENDI_TEST_PG_PORT=55432 uv run pytest -q tests/test_fiado_sync.py \
    tests/test_fiado_servicio.py tests/test_fiado_adversarial.py \
    tests/test_ventas_servicio.py tests/test_sync_idempotente.py \
    tests/test_caja_servicio.py tests/test_caja_anulacion_sync.py \
    tests/test_caja_adversarial.py tests/test_aislamiento_fiado.py \
    tests/test_ventas_adversarial.py tests/test_ventas_fixes_qa.py \
    tests/test_fiado_vencimientos.py
178 passed

$ uv run pytest -q -m 'not integration'
432 passed, 487 deselected
$ uv run ruff check . && uv run ruff format --check services/api/app tests
All checks passed! · 142 files already formatted

$ CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh
✨ openapi-typescript 7.13.0 → openapi.json e index.ts sin diff

$ uv run pytest -q -rs -m integration   # run ci 30348115730 sobre 0b613e8
487 passed, 432 deselected              # 0 SKIPPED (el grep del job lo exige);
                                        # los 11 jobs del run, success
```

**Candados:**

- `backend/tests/test_fiado_abono_sync.py` (7 tests, integration, corren en
  CI): el abono offline descuenta el saldo y cae en la sesión abierta al
  aplicarse; sin sesión abre la implícita; el reintento es `duplicada` sin
  doble descuento y la divergencia `abono_id_divergente`; el exceso es
  `rechazada abono_excede_saldo` y el abono bueno que viaja detrás se
  aplica; sin `fiado:abonar` es `permiso_ausente`; el crédito de otro
  tenant es `credito_no_encontrado` sin fuga; y el `cliente_id` que no es
  el del crédito es `abono_cliente_divergente`.
- `backend/tests/test_fiado_schemas.py::test_abono_sync_exige_cliente_credito_monto_y_metodo`
  y `::test_abono_sync_lleva_las_cotas_del_abono_online` (no integration):
  el ancla requerida, las cotas y el `sesion_caja_id` rechazado por
  `extra="forbid"` mueren si el contrato se afloja.

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
