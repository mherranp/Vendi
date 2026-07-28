# Estado de la fundación

Qué se entregó de verdad al cerrar la **Fase 0**, qué no, y qué queda vivo para
la Fase 1. Regla de este documento: **no promete nada que un comando no
demuestre.** Donde hay una afirmación, hay al lado el comando que la comprueba.

Fecha de corte: **2026-07-23** (cierre de la Etapa 5). Los cierres de Fase 1
se añaden como secciones propias, cada una con su fecha de corte.

---

## Los cuatro criterios de cierre de Fase 0

| # | Criterio | Estado | Cómo se comprueba |
|---|---|---|---|
| 1 | `verify-setup.sh` en verde | **25/28 en verde, 1 omitido, 2 en rojo** | `bash scripts/verify-setup.sh` |
| 2 | Login con passkey | **Cumplido** | manual + `npm run verificar:passkey` (Playwright) |
| 3 | CRUD de negocio | **Cumplido** | `uv run pytest -q tests/api/test_tenants_crud.py` + spec de Playwright |
| 4 | El pipeline produce un AAB descargable | **Workflow escrito; sin ejecución registrada** | `.github/workflows/android.yml` |

### Criterio 1 — por qué 2 en rojo, y por qué no se tocan

Los dos fallos son **11b** y **11c**, y los dos dicen lo mismo:

```
[FALLO] api.vendi.co resuelve a 64.190.63.222, que NO es esta máquina
[FALLO] estos nombres salen a Internet en vez de a Traefik: accounts.vendi.co…
```

`vendi.co` es un dominio real registrado por un tercero, y el resolver
`/etc/resolver/vendi.co` **no existe en esta máquina** porque escribirlo exige
`sudo`. Los dos checks están detectando exactamente la condición peligrosa que
existen para detectar: **son el guarda funcionando, no un defecto**. Ponerlos en
verde relajándolos sería apagar la alarma en vez de apagar el fuego.

El criterio «todo en verde» (25 checks + los 2 del resolver) se alcanza en
cuanto el dueño de la máquina ejecute
`./scripts/setup-dnsmasq.sh` (procedimiento A de
[`docs/runbooks/dns-y-tls-local.md`](runbooks/dns-y-tls-local.md)). Todo lo demás
del stack ya se verifica por el dominio fijando la resolución en el cliente
(`curl --resolve`, `socket.getaddrinfo` parcheado en los tests), que no afloja
nada: hostname, SNI, cabecera `Host`, enrutado de Traefik y validación completa
del certificado siguen siendo los reales.

El check 17 se omite porque solo aplica con `APP_ENV=production`, y lo dice.

### Criterio 4 — lo que falta y por qué

**CERRADO el 2026-07-27** (nota añadida a posteriori; el texto original del
cierre de Fase 0 decía que el workflow estaba escrito pero jamás ejecutado por
no existir remoto). El remoto `origin` (github.com/mherranp/Vendi) se conectó y
la primera ejecución real exigió cuatro correcciones (`0f14efd`, `2b077ac`,
`466f377`, `3593cd1`), incluido un bug real de despliegue fresco: el compose no
pasaba `VENDI_PROVISIONING_CLIENT_SECRET` al contenedor de Keycloak y la
siembra recibía 401 en cualquier base vacía — en local no se notaba porque el
realm ya existía en el volumen. Evidencia: `gh run list` muestra `ci`, `e2e` y
`release-images` en verde en el SHA `3593cd1` (runs 30246206628, 30246206697,
30246206643), con `verify-setup.sh` 26 en verde / 2 omitidos / 0 fallos y 106
tests de integración passed, 0 skipped, dentro del propio CI.

---

## Módulo catálogo (Fase 1, Etapa 1.2)

Fecha de corte: **2026-07-27**. Primer módulo de negocio del MVP, cerrado con
el gate de la Etapa 1.2 del plan maestro. Plan:
[`docs/superpowers/plans/2026-07-28-modulo-catalogo-plan.md`](superpowers/plans/2026-07-28-modulo-catalogo-plan.md)
(9 tareas TDD, commits `29cb6ac`…`fa5c3c1`, cada una con revisión
independiente registrada en `.superpowers/sdd/`).

Los comandos del gate que exigen el stack (migrar, tests de integración,
`verify-setup.sh`) se citan desde el CI, que los ejecuta contra PostgreSQL,
RabbitMQ y Keycloak reales en cada push: el run de corte es el `ci`
**30260179984** sobre el SHA `fa5c3c1`, con los 11 jobs en verde
(`gh run view 30260179984`). Un run verde es evidencia más fuerte que una
ejecución local del mismo día.

### Qué se entregó, y el comando que lo demuestra

**Tabla `productos` con RLS, índices y EAN único parcial (ADR-019).**
Migración `0004`, aplicada hasta head en el stack del CI:

```
$ bash scripts/migrate.sh          # run ci 30260179984, job «pytest -m integration»
INFO  [alembic.runtime.migration] Running upgrade 0003 -> 0004, Catálogo: tabla `productos` (ADR-019)…
[OK]    Migraciones aplicadas.
0004 (head)
```

**Aislamiento cross-tenant contra PostgreSQL real, 0 SKIPPED.** 6 tests
nuevos en `backend/tests/test_aislamiento_productos.py` (SELECT/UPDATE
acotados por la policy, INSERT con `tenant_id` ajeno bloqueado por `WITH
CHECK`, EAN repetido válido entre tenants y rechazado dentro del mismo, EAN
liberado en el borrado lógico). El job de CI convierte cualquier `SKIPPED` en
fallo, así que «passed» aquí significa que corrieron todos:

```
$ uv run pytest -q -m integration  # run ci 30260179984
139 passed, 353 deselected
```

Ahí dentro van también los candados transversales (`test_rls_coverage.py`,
`test_privilegios_de_vendi_app.py`), verdes sin edición: la tabla nueva hereda
los cuatro privilegios por defecto y quedó cubierta por el candado de RLS sin
tocar una línea de esos archivos.

**CRUD con permisos por rol (ADR-023) e idempotencia por UUID de cliente
(ADR-017).** Tres rutas en el contrato congelado:

```
$ python3 -c "import json; print('\n'.join(sorted(p for p in json.load(open('docs/api/openapi-fase0.json'))['paths'] if 'producto' in p)))"
/api/v1/productos
/api/v1/productos/por-codigo/{codigo}
/api/v1/productos/{producto_id}
```

15 tests de router (`backend/tests/api/test_catalogo_productos.py`) y 12 de
servicio (`backend/tests/test_catalogo_servicio.py`), todos integration y
verdes en el run de corte: creación idempotente con `id` de cliente, 409 al
reusar el id de un producto dado de baja, EAN duplicado 409 / entre tenants
201, cajero lee pero no edita (`permiso_ausente`), almacenista crea, edita y
también borra (el borrado lógico es una edición, ADR-023), producto de otro
negocio = 404, validación 422, límite de tier 403, negocio suspendido 403.

**Límite de productos por tier verificado en aplicación (ADR-010).**
`LIMITES_PRODUCTOS_POR_TIER = {gratis: 100, light: 500, pro: None}` contra las
filas VIVAS del tenant, con 403 `limite_de_productos_alcanzado`
(`test_el_limite_del_tier_se_verifica_contra_las_filas_vivas`,
`test_el_limite_del_tier_da_403`,
`test_el_limite_del_tier_light_se_detiene_en_500`). La fuente del tier hoy es fija (`pro` para
todos, decisión 2 del plan): registrada como deuda **D-09** en
[`docs/deuda-tecnica.md`](deuda-tecnica.md).

**Eventos de outbox según ADR-019** (`producto.creado/actualizado/eliminado`,
clave `<tenant_id>.producto.*`), emitidos en la misma transacción que la
escritura y comprobados leyendo `outbox_messages` con el rol de plataforma:

```
tests/test_catalogo_servicio.py::test_actualizar_emite_evento_con_los_cambios
tests/test_catalogo_servicio.py::test_actualizar_sin_cambios_no_emite_evento
tests/test_catalogo_servicio.py::test_eliminar_es_borrado_logico_libera_el_ean_y_emite_evento
```

**Permisos de catálogo en el token del dueño, contra el realm vivo** (check 23
de `verify-setup.sh`, ejecutado en el CI):

```
[OK]    aud=vendi-backend, rol de negocio y permisos de catálogo en el token del dueño
[OK]    27 en verde · 2 omitidos · 0 fallos (de 29)
```

**Suite completa verde, lint verde, contrato sin deriva.**

```
$ uv run pytest -q -m 'not integration'   # run ci 30260179984
353 passed, 139 deselected
$ uv run ruff check .                     # job «ruff + mypy» del CI; reproducido en local
All checks passed!
$ CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git status --short
(exit 0 y `git status` vacío: el cliente TS regenerado es idéntico al commiteado)
```

`contrato.ts` sigue compilando: el job `frontend / contratos`, los cuatro
`ng build` y `ng test` del mismo run, en verde. Los demás workflows sobre el
SHA de corte (`gh run list`): `e2e` 30260180052 y `release-images`
30260179985, todos success.

---

## Módulo ventas (Fase 1, Etapa 1.2)

Fecha de corte: **2026-07-27**. Segundo módulo de negocio del MVP —el
crítico: las ventas offline de ADR-018 sobre la capa de sincronización de
ADR-017—, cerrado con el gate de la Etapa 1.2 del plan maestro. Plan:
[`docs/superpowers/plans/2026-07-28-modulo-ventas-plan.md`](superpowers/plans/2026-07-28-modulo-ventas-plan.md)
(9 tareas TDD, commits `186b6ee`…`503499b`, cada una con revisión

> **Post-cierre (mismo día).** Tras el gate, la revisión de rama y el QA
> adversarial añadieron dos oleadas de correcciones ya en `main`: bloqueo
> `FOR UPDATE` del producto contra el lost update de `stock_actual`
> multi-caja (`49553da`), idempotencia del registro de dispositivos
> (`3b342fc`), D-18 (margen del watermark del delta) y los fixes de los 4
> bugs del QA (`fa290f5`: consolidación de movimientos por producto,
> cuantización de `cantidad` a 3 decimales, `tipo='anulacion'` con
> migración `0006`, 409 tipado en dispositivos). HEAD de código de cierre
> real: `fa290f5` — run ci 30288968606 en verde: **222 integration +
> 378 unitarios, 0 SKIPPED**.
independiente registrada en `.superpowers/sdd/`).

Los comandos del gate que exigen el stack (migrar, tests de integración,
`verify-setup.sh`) se citan desde el CI, que los ejecuta contra PostgreSQL,
RabbitMQ y Keycloak reales en cada push: el run de corte es el `ci`
**30283626280** sobre el SHA `503499b`, con los 11 jobs en verde
(`gh run view 30283626280`).

### Qué se entregó, y el comando que lo demuestra

**Cinco tablas nuevas con RLS, índices y grants (ADR-017/018/020/021).**
`dispositivos`, `caja_sesiones`, `ventas`, `ventas_items` y
`movimientos_inventario` en la migración `0005`, aplicada hasta head en el
stack del CI:

```
$ bash scripts/migrate.sh          # run ci 30283626280, job «pytest -m integration»
INFO  [alembic.runtime.migration] Running upgrade 0004 -> 0005, Ventas y sync offline: `dispositivos`, `caja_sesiones`, `ventas`, …
0005 (head)
[OK]    Migraciones aplicadas.
```

Las cinco heredan los cuatro privilegios por defecto de `vendi_app`
(decisión 11 del plan): el candado invertido
(`test_privilegios_de_vendi_app.py`) pasa sin edición, y el candado de
cobertura RLS (`test_rls_coverage.py`) cubre las cinco tablas — sus modelos
quedaron registrados en él en la tarea 2.

**Aislamiento cross-tenant contra PostgreSQL real, 0 SKIPPED.** 11 tests
nuevos en `backend/tests/test_aislamiento_ventas.py` (las cinco tablas:
SELECT/UPDATE acotados por la policy, INSERT con `tenant_id` ajeno bloqueado
por `WITH CHECK`). El job de CI convierte cualquier `SKIPPED` en fallo, así
que «passed» aquí significa que corrieron todos:

```
$ uv run pytest -q -m integration  # run ci 30283626280
200 passed, 376 deselected
```

**El candado del sync: el mismo lote dos veces deja UNA venta, UN movimiento
de stock y UN evento (ADR-017/018/020).**
`tests/test_sync_idempotente.py::test_el_mismo_lote_dos_veces_deja_una_venta_un_movimiento_y_un_evento`,
verde en el run de corte. Idempotencia por UUID de cliente (la PK de
`ventas`), segunda red por el índice único `(tenant_id, tipo, referencia_id,
producto_id)` de `movimientos_inventario` (decisión 2), una transacción por
lote con un SAVEPOINT por operación, y respuesta por operación
(`aceptada`/`duplicada`/`rechazada`): mismo `id` con payload divergente es
`rechazada` con motivo y `detalles`, no un no-op silencioso (decisión 4).

**Servicio y router del sync.** 23 tests de servicio
(`backend/tests/test_ventas_servicio.py`) y 14 de API
(`backend/tests/api/test_ventas_sync.py`), todos integration y verdes en el
run de corte: descuento de stock por deltas con la proyección `stock_actual`
actualizada en la misma transacción, sesión de caja resuelta en el servidor
(abierta del tenant o implícita; el índice único parcial de ADR-021 decide
la carrera de aperturas concurrentes), anulación como operación nueva no
destructiva que repone stock, venta que sube ya `anulada` sin movimientos ni
`venta:anular` (decisión 9), fiado con `cliente_id` obligatorio
(`fiado_requiere_cliente`), total verificado contra los ítems
(`total_incoherente`), tope de 200 operaciones por lote (decisión 7) y
carreras cerradas con `FOR UPDATE` al anular y choque idéntico de
`ventas_pkey` como `duplicada`.

**Tres rutas nuevas en el contrato congelado:**

```
$ python3 -c "import json; print('\n'.join(sorted(p for p in json.load(open('docs/api/openapi-fase0.json'))['paths'] if 'sync' in p or 'dispositivo' in p)))"
/api/v1/dispositivos
/api/v1/sync/delta
/api/v1/sync/lotes
```

`GET /sync/delta` drena el catálogo hacia los dispositivos: productos vivos
modificados desde el watermark, tumbas de los dados de baja, y `hasta` del
reloj del servidor como próximo `desde` (decisión 10).

**Permisos de ventas en el token del dueño, contra el realm vivo** (check 23
de `verify-setup.sh`, extendido por este módulo y ejecutado en el CI):

```
[OK]    aud=vendi-backend, rol de negocio y permisos de catálogo y ventas en el token del dueño
[OK]    27 en verde · 2 omitidos · 0 fallos (de 29)
```

El reparto firmado (ADR-023): el cajero crea pero NO anula. El chequeo de
`venta:anular` es POR OPERACIÓN dentro del lote (decisión 12): un lote de
solo anulaciones de un cajero devuelve todas sus operaciones `rechazada` con
`permiso_ausente` sin abortar el resto de su cola, y el guard de entrada
`exigir_venta_crear` da 403 al almacenista en `/api/v1/dispositivos`
(`test_registrar_dispositivo_exige_venta_crear`).

**Eventos de outbox según ADR-018** (`venta.creada`/`venta.anulada`, clave
`<tenant_id>.venta.*`), emitidos dentro de la misma transacción del lote, una
sola vez por operación aceptada — una `duplicada` o `rechazada` no emite:

```
tests/test_ventas_servicio.py::test_aplicar_una_venta_descuenta_stock_abre_sesion_implicita_y_emite_evento
tests/test_ventas_servicio.py::test_anular_repone_stock_emite_evento_y_no_toca_la_venta_original
```

**Suite completa verde, lint verde, contrato sin deriva.**

```
$ uv run pytest -q -m 'not integration'   # run ci 30283626280
376 passed, 200 deselected
$ uv run pytest -q -m integration         # run ci 30283626280
200 passed, 376 deselected
$ uv run ruff check .                     # job «ruff + mypy» del CI; reproducido en local
All checks passed!
$ CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git status --short
(exit 0 y `git status` vacío: el cliente TS regenerado es idéntico al commiteado)
```

`contrato.ts` sigue compilando: el job `frontend / contratos`, los cuatro
`ng build` y `ng test` del mismo run, en verde. Los demás workflows sobre el
SHA de corte (`gh run list`): `e2e` 30283626150, `release-images`
30283626103 y `deploy` 30284035180, todos success.

**Deuda registrada al cierre** (detalle, riesgo y candados en
[`docs/deuda-tecnica.md`](deuda-tecnica.md)): **D-10** (`ventas.cliente_id`
sin FK hasta el módulo 5), **D-11** (`caja_sesiones` sin endpoints propios
hasta el módulo 4), **D-12** (stock sin alertas de umbral hasta el módulo
3), **D-13** (carrera TOCTOU del cupo de tier del catálogo, detectada por el
QA adversarial), **D-14** (`datos` de la operación del sync opcional en el
contrato), **D-15** (`exigir_venta_anular` sin consumidor todavía), **D-16**
(el check 23 no tiene prueba negativa ejecutada) y **D-17** (`alembic check`
fuera del CI).

> *(Actualización al cierre del módulo inventario, 2026-07-27: **D-12** y
> **D-14** quedaron **cerradas** — el punto único de movimientos emite
> `inventario.alerta_stock` y `OperacionSync.datos` es requerido. Evidencia
> en la sección siguiente y en el registro de deuda.)*
>
> *(Actualización del pago de deuda de concurrencia, 2026-07-28: **D-13**
> quedó **cerrada** — `pg_advisory_xact_lock` por tenant serializa conteo e
> INSERT en `_exigir_cupo`; la carrera 101/100 que documentaba el QA
> adversarial ahora deja 100/100 con la segunda alta rechazada. Evidencia en
> el registro de deuda.)*

---

## Módulo inventario (Fase 1, Etapa 1.2)

Fecha de corte: **2026-07-27**. Tercer módulo de negocio del MVP —el
inventario de ADR-020 completo: compras, ajustes online y alertas de
umbral—, cerrado con el gate de la Etapa 1.2 del plan maestro. Plan:
[`docs/superpowers/plans/2026-07-28-modulo-inventario-plan.md`](superpowers/plans/2026-07-28-modulo-inventario-plan.md)
(11 tareas TDD, commits `9dfb26f`…`2d08df9`, cada una con revisión
independiente registrada en `.superpowers/sdd/`).

> **Post-cierre (mismo día).** Tras el gate, la revisión de rama y el QA
> adversarial añadieron correcciones ya en `main`: la fuga de `ultimo_costo`
> al cajero se cerró condicionándolo a `compra:crear` en productos **y** en
> el delta del sync (`5071c29`, `9dd0215`), el overflow del total de compra
> calculado en servidor pasó de 500 a 422 tipado (`5071c29`), y el QA añadió
> 20 tests adversariales (`c949048`: bordes de umbral, regresión del
> deadlock con orden inverso, atomicidad del 422, cross-tenant). Deuda
> registrada: D-19…D-25 con vencimiento antes del piloto. HEAD de código de
> cierre real: `8cb5125` — run ci 30310253728 en verde: **300 integration +
> 402 unitarios, 0 SKIPPED**.

Los comandos del gate que exigen el stack (migrar, tests de integración,
`verify-setup.sh`) se citan desde el CI, que los ejecuta contra PostgreSQL,
RabbitMQ y Keycloak reales en cada push: el run de corte es el `ci`
**30305515191** sobre el SHA `2d08df9`, con los 11 jobs en verde
(`gh run view 30305515191`).

### Qué se entregó, y el comando que lo demuestra

**Tres tablas nuevas con RLS, índices y grants (ADR-020/023).** `compras`,
`compra_items` y `ajustes_inventario` en la migración `0007`, aplicada hasta
head en el stack del CI. `movimientos_inventario` no se tocó: su CHECK ya
admite `compra`/`ajuste`/`merma` desde la 0005 (decisión 6 del plan):

```
$ bash scripts/migrate.sh          # run ci 30305515191, job «pytest -m integration»
INFO  [alembic.runtime.migration] Running upgrade 0006 -> 0007, Inventario y compras: `compras`, `compra_items` y `ajustes_inventario` (ADR-020/023).
0007 (head)
```

Las tres heredan los cuatro privilegios por defecto de `vendi_app`: el
candado invertido (`test_privilegios_de_vendi_app.py`) pasa sin edición, y
el de cobertura RLS (`test_rls_coverage.py`) cubre las tres tablas.

**Aislamiento cross-tenant contra PostgreSQL real, 0 SKIPPED.** 10 tests
nuevos en `backend/tests/test_aislamiento_inventario.py` (las tres tablas:
SELECT/UPDATE acotados por la policy, INSERT con `tenant_id` ajeno bloqueado
por `WITH CHECK`). El job de CI convierte cualquier `SKIPPED` en fallo, así
que «passed» aquí significa que corrieron todos:

```
$ uv run pytest -q -m integration  # run ci 30305515191
275 passed, 402 deselected
```

**El punto único de movimientos y las alertas de umbral (ADR-020; cierre de
D-12).** Todo cambio de stock —venta, anulación, compra, ajuste, merma— pasa
por `aplicar_movimiento`
(`backend/services/api/app/modules/inventario/stock.py`): inserta la fila
del libro, actualiza la proyección `stock_actual` y evalúa el cruce
comparando el nivel antes/después dentro del bloqueo `FOR UPDATE` (el nivel
se deriva de `stock_minimo`; no hay columna que mantener, decisión 2).
`inventario.alerta_stock` se emite SOLO cuando el nivel empeora: nunca por
movimiento, nunca al recuperarse, nunca dos veces por el mismo cruce. El
servicio de ventas delega en él (`VentasService._mover_stock` conserva su
firma). 14 tests en `backend/tests/test_inventario_alertas.py` (bordes
estrictos, cruce único, anti-spam de la cola de sync, recuperación y nuevo
cruce), más el test reforzado del stock negativo
(`test_ventas_servicio.py::test_el_stock_puede_quedar_negativo_y_la_venta_se_acepta`),
que ahora demuestra la alerta de `agotado`.

**Los candados firmados de ADR-020.** Alerta única por cruce
(`test_dos_ventas_seguidas_por_debajo_del_minimo_emiten_una_sola_alerta`,
`test_recuperarse_no_emite_y_volver_a_cruzar_si`,
`test_la_operacion_duplicada_no_reemite_la_alerta`) e invariante del libro
(`test_inventario_servicio.py::test_la_invariante_del_libro_tras_una_secuencia_mezclada`:
`stock_actual = SUM(movimientos)` tras una secuencia mezclada de venta,
compra, merma y ajuste), verdes en el run de corte.

**Compras con `ultimo_costo` y ajustes online idempotentes.** 16 tests de
servicio (`backend/tests/test_inventario_servicio.py`) y 12 de API
(`backend/tests/api/test_inventario_api.py`), todos integration: la compra
inserta movimientos tipo `compra`, actualiza `stock_actual` y `ultimo_costo`
y emite `compra.registrada` en una sola transacción, con el total calculado
por el servidor por línea en centavos enteros (decisión 7), los ítems
bloqueados en orden de `producto_id` (decisión 9, anti-deadlock:
`test_dos_compras_concurrentes_del_mismo_producto_dejan_el_stock_exacto`) e
idempotencia por el `id` del cliente. El ajuste es online-obligatorio
(ADR-020): calcula su delta contra el stock del servidor en el momento del
conteo, exige `motivo`, y su reintento con el mismo `id` es un no-op que
devuelve lo grabado — con payload divergente es 409 `ajuste_id_divergente`
(`test_el_mismo_id_de_ajuste_con_otro_payload_es_409`). NADA de esto entra
al lote del sync (decisión 3): son endpoints REST puros.

**Permisos y reparto (ADR-023).** `inventario:ajustar` y `compra:crear` en
el catálogo cerrado de 14: dueño todo, almacenista ambos, cajero NADA (403
`permiso_ausente` en compras y ajustes:
`test_el_cajero_no_compra_ni_ve_compras`,
`test_el_cajero_no_ajusta_ni_ve_ajustes`; el estado de stock lo lee
cualquier rol con `producto:leer`, decisión 10). El check 23 de
`verify-setup.sh`, extendido por este módulo, exige los seis permisos contra
el realm vivo en el CI:

```
[OK]    aud=vendi-backend, rol de negocio y permisos de catálogo, ventas e inventario en el token del dueño
[OK]    27 en verde · 2 omitidos · 0 fallos (de 29)
```

**Cuatro rutas nuevas (seis endpoints) en el contrato congelado, con
`datos` requerido (cierre de D-14):**

```
$ python3 -c "import json; d=json.load(open('docs/api/openapi-fase0.json'));"
  (rutas y métodos de inventario/compras, y 'datos' en el required de OperacionSync)
/api/v1/compras ['get', 'post']
/api/v1/compras/{compra_id} ['get']
/api/v1/inventario/ajustes ['get', 'post']
/api/v1/inventario/stock ['get']
datos requerido: True
```

**Eventos de outbox según ADR-020** (`compra.registrada`,
`inventario.alerta_stock` solo al cruzar hacia abajo, clave
`<tenant_id>.<evento>`), emitidos en la misma transacción que la escritura —
un rollback se lleva el movimiento Y la alerta (decisión 14):
`test_registrar_compra_mueve_stock_actualiza_ultimo_costo_y_emite_evento` y
los 14 de alertas.

**Suite completa verde, lint verde, contrato sin deriva.**

```
$ uv run pytest -q -m 'not integration'   # run ci 30305515191; reproducido en local
402 passed, 275 deselected
$ uv run pytest -q -m integration         # run ci 30305515191
275 passed, 402 deselected
$ uv run ruff check .                     # job «ruff + mypy» del CI; reproducido en local
All checks passed!
$ CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git status --short
(exit 0 y `git status` vacío: el cliente TS regenerado es idéntico al commiteado)
```

`contrato.ts` sigue compilando: el job `frontend / contratos`, los cuatro
`ng build` y `ng test` del mismo run, en verde. Los demás workflows sobre el
SHA de corte (`gh run list`): `e2e` 30305515198 y `android` 30305515782,
todos success.

**Deuda registrada al cierre** (detalle, riesgo y candados en
[`docs/deuda-tecnica.md`](deuda-tecnica.md)), detectada en las revisiones
del módulo: **D-19** (el reenvío de una compra con el mismo `id` y payload
distinto no detecta la divergencia: devuelve la existente en silencio),
**D-20** (el `FOR UPDATE` del producto es convención documentada, no
enforced), **D-21** (el sync de ventas bloquea los productos en el orden del
ticket: deadlock teórico multi-producto, heredado) y **D-22** (falta el test
literal `inventario.ajustar` → `tipo_desconocido`; lo cubre el genérico).
Cerradas en este módulo: **D-12** y **D-14**.

> *(Actualización del pago de deuda de concurrencia, 2026-07-28: **D-21**
> quedó **cerrada** — `_registrar_venta` toma los `FOR UPDATE` ordenados por
> `producto_id`, la misma receta de la compra (decisión 9); el deadlock de
> orden inverso, reproducido en test, ya no ocurre y los movimientos se
> insertan en el orden del ticket, como antes. Evidencia en el registro de
> deuda.)*

---

## Módulo caja y finanzas (Fase 1, Etapa 1.2)

Fecha de corte: **2026-07-28**. Cuarto módulo de negocio del MVP —la caja de
ADR-021 y las finanzas simples de ADR-006: sesiones, movimientos, arqueo que
suma desde el origen y se congela, P&L simple y forecast a 30 días—, cerrado
con el gate de la Etapa 1.2 del plan maestro. Plan:
[`docs/superpowers/plans/2026-07-28-modulo-caja-plan.md`](superpowers/plans/2026-07-28-modulo-caja-plan.md)
(11 tareas TDD, commits `d7e4eb7`…`9510891`, cada una con revisión
independiente registrada en `.superpowers/sdd/`).

> **Post-cierre (mismo día).** Tras el gate, la revisión de rama destapó el
> último camino del dinero sin sincronizar: la anulación del sync no
> resolvía sesión de caja, así que una devolución entre cierre y apertura
> desaparecía de todo arqueo — `_anular_venta` ahora resuelve la sesión con
> FOR UPDATE antes de estampar `anulada_en` (`9e2a017`, con 2 tests de
> carrera/hueco). El QA adversarial añadió 31 tests (`1d2de96`, 0 bugs
> contra lo firmado) y confirmó una fuga menor: los retiros del dueño eran
> visibles para el cajero — ahora solo los ve quien cierra caja (`c49c4c0`).
> Deuda registrada: D-26 (esperado negativo cierra sin error; decisión de
> producto antes del piloto). HEAD de código de cierre real: `c49c4c0` —
> run ci 30321339245 en verde: **385 integration + 412 unitarios,
> 0 SKIPPED**.

Los comandos del gate que exigen el stack (migrar, tests de integración,
`verify-setup.sh`) se citan desde el CI, que los ejecuta contra PostgreSQL,
RabbitMQ y Keycloak reales en cada push: el run de corte es el `ci`
**30318420990** sobre el SHA `9510891`, con los 11 jobs en verde
(`gh run view 30318420990`).

### Qué se entregó, y el comando que lo demuestra

**`caja_movimientos`, los CHECK del cierre completo y `ventas.anulada_en`
(migración `0008`, ADR-021).** `caja_sesiones` NO se recreó: existe completa
desde la `0005` con todas las columnas del arqueo (decisión 1 del plan); aquí
ganó dos CHECK —el cierre es completo o no es, y el conteo físico no es
negativo— y `ventas` ganó `anulada_en`, para que la devolución de una
anulación tardía caiga en la sesión abierta sin duplicar la venta como
movimiento (decisión 7). Aplicada hasta head en el stack del CI:

```
$ bash scripts/migrate.sh          # run ci 30318420990, job «pytest -m integration»
INFO  [alembic.runtime.migration] Running upgrade 0007 -> 0008, Caja: `caja_movimientos`, los CHECK del cierre completo y `ventas.anulada_en`
0008 (head)
[OK]    Migraciones aplicadas.
```

`caja_movimientos` hereda los cuatro privilegios por defecto de `vendi_app`:
el candado invertido (`test_privilegios_de_vendi_app.py`) pasa sin edición, y
el de cobertura RLS (`test_rls_coverage.py`) la cubre.

**Aislamiento cross-tenant contra PostgreSQL real, 0 SKIPPED.** 9 tests
nuevos en `backend/tests/test_aislamiento_caja.py` (SELECT acotado por la
policy, INSERT con `tenant_id` ajeno bloqueado por `WITH CHECK`, los CHECK de
tipo/categoría/monto y del cierre completo, la FK de sesión y la columna
`anulada_en`). El job de CI convierte cualquier `SKIPPED` en fallo, así que
«passed» aquí significa que corrieron todos:

```
$ uv run pytest -q -m integration  # run ci 30318420990
354 passed, 412 deselected
```

**Los candados firmados de ADR-021.** El arqueo suma desde las tablas de
origen y cuadra al peso
(`test_el_arqueo_suma_desde_las_tablas_de_origen_y_cuadra_al_peso`: ventas en
efectivo completadas de la sesión + ingresos − egresos − devoluciones
sembradas, exacto al centavo); la carrera de aperturas deja UNA sola sesión
(`test_dos_aperturas_concurrentes_dejan_una_sola_sesion`, decidida por el
índice único parcial); el arqueo se congela y nada lo reabre
(`test_el_arqueo_se_congela_y_nada_lo_reabre`); y dos cierres concurrentes se
serializan sobre la fila `FOR UPDATE` —uno cierra, el otro recibe 409
`caja_ya_cerrada`, un solo evento, un solo arqueo congelado—
(`test_dos_cierres_concurrentes_cierran_la_sesion_una_sola_vez`). Todos
verdes en el run de corte.

**El candado firmado de ADR-023: el cajero abre y mueve caja pero NO cierra
ni ve reportes.**
`tests/api/test_caja_api.py::test_el_cajero_abre_y_mueve_caja_pero_no_cierra`
(403 `permiso_ausente` al cerrar como cajero; el mismo gesto con el dueño,
200), y `PERMISOS_POR_ROL ⊆ PERMISSION_CATALOG` verde en
`test_auth_policies.py`. Los cinco permisos nuevos del catálogo cerrado, con
el reparto literal de ADR-023 (el dueño los cinco; el cajero `caja:leer`,
`caja:abrir`, `caja:movimiento` —no `caja:cerrar`, no `reporte:leer`; el
almacenista ninguno), exigidos contra el realm vivo por el check 23
extendido a los once permisos:

```
[OK]    aud=vendi-backend, rol de negocio y permisos de catálogo, ventas, inventario y caja en el token del dueño
[OK]    27 en verde · 2 omitidos · 0 fallos (de 29)
```

**El esperado vivo condicionado por permiso (lección de la fuga de
`ultimo_costo`).** `GET /caja/sesiones/actual` devuelve `efectivo_esperado`
en `null` sin `caja:cerrar` —el cajero ve la sesión y opera, pero no la cifra
con la que se cuadraría un faltante antes del arqueo— y el historial de
arqueos (`GET /caja/sesiones`) exige `caja:cerrar` directamente, porque
faltantes y sobrantes históricos son un reporte (decisión 4).

**El cambio quirúrgico en ventas.** `_resolver_sesion_caja` bloquea la sesión
abierta `FOR UPDATE`: cierre y sync se serializan sobre la fila, y una venta
que sincroniza tras el cierre cae en la sesión NUEVA, nunca en la cerrada —
el congelamiento es estructural, no un convenio (decisión 5). `_anular_venta`
estampa `anulada_en` (commit `e0c089d`).

**P&L simple y forecast 30d, con cada número declarando su fuente
(ADR-006).** El P&L por período (`dia`/`semana`/`mes` anclado a
`America/Bogota` con `zoneinfo`) suma las ventas completadas por
`recibida_en`, costea con el `ultimo_costo` ACTUAL declarado, suma ingresos y
resta egresos de caja, y trae las compras del período como línea informativa
de flujo que NO se resta del resultado (decisión 8). El forecast declara su
alcance honesto: saldo vivo de la sesión abierta + promedio de ventas en
efectivo de 30 días + cobros de fiado 0 (hasta el módulo 5, con su punto de
cambio único documentado) − promedio de egresos de 30 días, con
`dias_con_datos` en la respuesta (decisión 9). 7 tests en
`backend/tests/test_reportes_servicio.py`, verdes en el run de corte.

**Ocho endpoints (seis rutas) nuevos en el contrato congelado:**

```
$ python3 -c "import json; d=json.load(open('docs/api/openapi-fase0.json')); [print(p, sorted(m for m in d['paths'][p] if m in ('get','post'))) for p in sorted(d['paths']) if 'caja' in p or 'reporte' in p]"
/api/v1/caja/movimientos ['get', 'post']
/api/v1/caja/sesiones ['get', 'post']
/api/v1/caja/sesiones/actual ['get']
/api/v1/caja/sesiones/{sesion_id}/cerrar ['post']
/api/v1/reportes/forecast ['get']
/api/v1/reportes/pyl ['get']
```

13 tests de API en `backend/tests/api/test_caja_api.py` (apertura idempotente
y 409 `caja_ya_abierta` con la sesión vigente en `details`, movimiento con
`id` de cliente obligatorio y 409 `movimiento_id_divergente`, cierre
idempotente por reintento con el mismo conteo y 409 `caja_ya_cerrada` con
otro, sesión de otro negocio = 404), todos integration y verdes en el run de
corte.

**Eventos de outbox según ADR-021** (`caja.sesion_abierta`,
`caja.movimiento_registrado`, `caja.sesion_cerrada` con el resumen del
arqueo, clave `<tenant_id>.<evento>`), emitidos en la misma transacción que
la escritura:

```
tests/test_caja_servicio.py::test_abrir_caja_crea_la_sesion_y_emite_el_evento
tests/test_caja_servicio.py::test_registrar_movimiento_lo_ata_a_la_sesion_abierta_y_emite_evento
tests/test_caja_servicio.py::test_dos_cierres_concurrentes_cierran_la_sesion_una_sola_vez
```

**Suite completa verde, lint verde, contrato sin deriva.**

```
$ uv run pytest -q -m 'not integration'   # run ci 30318420990; reproducido en local
412 passed, 354 deselected
$ uv run pytest -q -m integration         # run ci 30318420990
354 passed, 412 deselected
$ uv run ruff check .                     # job «ruff + mypy» del CI; reproducido en local
All checks passed!
$ CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git status --short
(exit 0 y `git status` vacío: el cliente TS regenerado es idéntico al commiteado)
```

`contrato.ts` sigue compilando: el job `frontend / contratos`, los cuatro
`ng build` y `ng test` del mismo run, en verde. Los demás workflows sobre el
SHA de corte (`gh run list`): `e2e` 30318420932 y `android` 30318420936,
todos success.

**Deuda cerrada en este módulo** (detalle y evidencia en
[`docs/deuda-tecnica.md`](deuda-tecnica.md)): **D-11** (`caja_sesiones` sin
endpoints propios: este módulo los entregó) y **D-15**
(`exigir_venta_anular` sin consumidor: borrado en la Tarea 9, como mandaba su
propio vencimiento). **Sin deuda nueva registrada**: los hallazgos de las
revisiones del módulo no cumplen el criterio del registro (riesgo real y
vencimiento) — el tag OpenAPI `caja` de las rutas de reportes es cosmético;
`_sesion_abierta` con `scalar_one_or_none` solo daría 500 si el invariante de
una sesión abierta por tienda se rompiera, y lo impide estructuralmente el
índice único parcial; la aserción trivial «sin sesión abierta» del test del
forecast y la fase roja de la Tarea 8 no verificable como 404 son ruido
procesal sin riesgo en runtime.

---

## Módulo fiado y clientes (Fase 1, Etapa 1.2)

Fecha de corte: **2026-07-28**. Quinto módulo de negocio del MVP —el fiado
de ADR-009/ADR-022, «el cuaderno»: créditos con saldo vivo, abonos,
recordatorios de vencimiento y la base mínima de clientes—, cerrado con el
gate de la Etapa 1.2 del plan maestro. Plan:
[`docs/superpowers/plans/2026-07-28-modulo-fiado-plan.md`](superpowers/plans/2026-07-28-modulo-fiado-plan.md)
(12 tareas TDD, commits `a991a68`…`fd55d86`, cada una con revisión
independiente registrada en `.superpowers/sdd/`).

> **Post-cierre (mismo día).** La revisión de rama y el QA adversarial
> añadieron correcciones ya en `main`: el mensaje de cobro por WhatsApp
> mostraba el saldo en centavos como si fueran pesos (100× inflado, con el
> test codificando el error) — `f79097c`; una inversión de orden de bloqueo
> entre abono y anulación (deadlock reproducido por el QA con
> `deadlock detected` real) — el abono ahora bloquea la sesión antes que el
> crédito (`f79097c`); el upgrade del placeholder ya no pisa ediciones REST
> intermedias y la venta fiada a un cliente inexistente sale
> `cliente_no_encontrado` sin arrastrar el lote (`2006f59`). El QA añadió
> 23 tests adversariales (`a8681c3`). Deuda nueva: D-27/D-28. HEAD de
> código de cierre real: `2006f59` — run ci 30334755086 en verde:
> **455 integration + 430 unitarios, 0 SKIPPED**.

Los comandos del gate que exigen el stack (migrar, tests de integración,
`verify-setup.sh`) se citan desde el CI, que los ejecuta contra PostgreSQL,
RabbitMQ y Keycloak reales en cada push: el run de corte es el `ci`
**30331195290** sobre el SHA `fd55d86`, con los 11 jobs en verde
(`gh run view 30331195290`).

### Qué se entregó, y el comando que lo demuestra

**Tres tablas nuevas con RLS, índices, checks y grants (ADR-022/023).**
`clientes`, `fiado_creditos` (con `saldo_pendiente` materializado,
`CHECK (saldo_pendiente >= 0)` y `CHECK (saldo_pendiente <= monto_total)`) y
`fiado_abonos` (con la `sesion_caja_id` que cobró el efectivo) en la
migración `0009`, aplicada hasta head en el stack del CI:

```
$ bash scripts/migrate.sh          # run ci 30331195290, job «pytest -m integration»
INFO  [alembic.runtime.migration] Running upgrade 0008 -> 0009, Fiado y clientes: `clientes`, `fiado_creditos` y `fiado_abonos`
0009 (head)
```

Las tres heredan los cuatro privilegios por defecto de `vendi_app`: el
candado invertido (`test_privilegios_de_vendi_app.py`) pasa sin edición, y el
de cobertura RLS (`test_rls_coverage.py`) las cubre.

**Aislamiento cross-tenant contra PostgreSQL real, 0 SKIPPED.** 15 tests
nuevos en `backend/tests/test_aislamiento_fiado.py` (9 funciones parametrizadas:
SELECT de las tres tablas acotado por la policy, INSERT con `tenant_id` ajeno
bloqueado por `WITH CHECK`, los CHECK de saldo/estado/método, un crédito por
venta —`ux_fiado_creditos_venta`— y la FK del abono al crédito). El job de CI
convierte cualquier `SKIPPED` en fallo, así que «passed» aquí significa que
corrieron todos:

```
$ uv run pytest -q -m integration  # run ci 30331195290
449 passed, 430 deselected
```

**El crédito nace EN EL SYNC, en la misma transacción de la venta (decisión
1 del plan).** 15 tests en `backend/tests/test_fiado_sync.py`: la venta
fiada se convierte en crédito con `saldo_pendiente = total` en el SAVEPOINT
de la operación; `cliente.crear` entra al lote con el id del dispositivo
como PK (cierre de D-10 por adopción); la venta fiada sin cliente conocido
NO se rechaza — auto-alta placeholder `(sin nombre)`— y el `cliente.crear`
que llega tarde MEJORA el placeholder en vez de ser rechazado por
divergencia (fix `005c212`); el cupo se evalúa pero nunca rechaza y el
exceso viaja en `detalles.cupo_excedido` del resultado (ADR-018); la
anulación de la venta fiada anula el crédito (cuarto estado `anulado`,
`saldo_pendiente = 0`) sin tocar los abonos; la venta que sube ya anulada no
genera crédito; crear y anular la misma venta en el mismo lote funciona; y
el lote reenviado no duplica cliente, crédito ni eventos.

**Los candados firmados de ADR-022.** El saldo al peso
(`test_fiado_servicio.py::test_el_abono_descuenta_al_peso`: crédito de
100.000, abonos de 30.000 + 30.000 → saldo 40.000, historial intacto); el
abono que excede el saldo es un 422 tipado con el CHECK como red final
(`test_el_abono_mayor_que_el_saldo_es_422_tipado`); el trabajo diario
(`test_fiado_vencimientos.py::test_marca_vencido_y_encola_exactamente_un_evento`:
vencimiento de ayer → `vencido` + UN `fiado.credito_vencido`;
`test_recorrer_la_pasada_es_noop`: la transición de estado ES el
anti-duplicado; `test_no_toca_el_futuro_el_sin_fecha_el_saldado_ni_el_vecino`);
y el aislamiento por tabla de la sección anterior. Todos verdes en el run
de corte.

**El candado firmado de ADR-023: el almacenista no toca el fiado; el
cajero fía y cobra.**
`tests/api/test_fiado_api.py::test_el_almacenista_recibe_403_en_todo_el_cuaderno`
(403 en clientes, créditos, reprogramación y abonos) y
`test_el_abono_descuenta_y_el_cuaderno_lo_cuenta` (el mismo gesto con el
dueño y el cajero, 201, y el saldo se descuenta al peso); el cajero
gestiona clientes (`test_el_cajero_gestiona_clientes_y_el_almacenista_no`)
porque necesita saldo y cupo para fiar y cobrar (decisión 10). En el sync,
la venta fiada exige `fiado:crear` POR OPERACIÓN y `cliente.crear` exige
`cliente:gestionar` — la operación sin permiso es `rechazada`
`permiso_ausente`, no un 403 del lote
(`test_fiado_sync.py::test_la_venta_fiada_sin_permiso_es_rechazada_y_no_deja_credito`).
`PERMISOS_POR_ROL ⊆ PERMISSION_CATALOG` verde en `test_auth_policies.py`.
El catálogo queda COMPLETO: los 14 permisos de ADR-023, exigidos contra el
realm vivo por el check 23 extendido:

```
[OK]    aud=vendi-backend, rol de negocio y los 14 permisos de dominio en el token del dueño
[OK]    27 en verde · 2 omitidos · 0 fallos (de 29)
```

**El cuaderno: abonos al peso, historial, `wa.me` y reprogramación.** 17
tests de servicio (`backend/tests/test_fiado_servicio.py`) y 8 de API
(`backend/tests/api/test_fiado_api.py`), todos integration: el abono exige
el `id` del cliente (ancla de idempotencia ya puesta para el abono offline
de D-27), descuenta el saldo en la misma transacción con el crédito
bloqueado `FOR UPDATE`, y el que salda cierra el crédito y emite
`fiado.abono_registrado` Y `fiado.credito_saldado`
(`test_el_abono_que_salda_cierra_el_credito_y_emite_los_dos_eventos`); ni
un `saldado` ni un `anulado` admiten abonos (el historial no se reescribe);
el abono en efectivo exige sesión de caja abierta y guarda su
`sesion_caja_id` (`test_el_abono_en_efectivo_exige_caja_abierta`, 409
`caja_sin_sesion_abierta`); el detalle arma la `whatsapp_url` con el saldo
(`test_el_detalle_arma_el_wa_me_y_lo_omite_sin_telefono`); y reprogramar un
`vencido` a futuro lo devuelve a `vigente` — podrá volver a vencer con su
recordatorio (`test_reprogramar_un_vencido_a_futuro_lo_devuelve_a_vigente`).

**Los puntos de cambio del módulo 4, activados.** El arqueo suma los abonos
en efectivo de la sesión desde `fiado_abonos`
(`test_caja_servicio.py::test_el_arqueo_suma_los_abonos_en_efectivo_de_la_sesion`)
y el forecast proyecta cobros de fiado reales — `SUM(saldo_pendiente)` de
créditos `vigente`/`vencido` con `fecha_vencimiento <= hoy + 30 días`
(`test_reportes_servicio.py::test_el_forecast_proyecta_los_cobros_de_fiado`:
50.000 = 20.000 + 30.000; los sin fecha no entran y la respuesta lo dice en
`fuentes.cobros_fiado`).

**Ocho endpoints (cinco rutas) nuevos en el contrato congelado:**

```
$ python3 -c "import json; d=json.load(open('docs/api/openapi-fase0.json')); [print(p, sorted(m for m in d['paths'][p] if m in ('get','post','patch'))) for p in sorted(d['paths']) if 'fiado' in p or 'cliente' in p]"
/api/v1/clientes ['get', 'post']
/api/v1/clientes/{cliente_id} ['get', 'patch']
/api/v1/fiado/creditos ['get']
/api/v1/fiado/creditos/{credito_id} ['get', 'patch']
/api/v1/fiado/creditos/{credito_id}/abonos ['post']
```

**Eventos de outbox según ADR-022** (`fiado.credito_creado`,
`fiado.abono_registrado`, `fiado.credito_saldado`, `fiado.credito_vencido`,
más `fiado.credito_anulado` de la decisión 3, clave
`<tenant_id>.<evento>`), emitidos en la misma transacción que la escritura
— el del worker con el filtro `tenant_id` explícito de la sesión de
plataforma (scope `tenant`, el primer trabajo de ese tipo).

**Suite completa verde, lint verde, contrato sin deriva.**

```
$ uv run pytest -q -m 'not integration'   # run ci 30331195290; reproducido en local
430 passed, 449 deselected
$ uv run pytest -q -m integration         # run ci 30331195290
449 passed, 430 deselected
$ uv run ruff check .                     # job «ruff + mypy» del CI; reproducido en local
All checks passed!
$ CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git status --short
(exit 0 y `git status` vacío: el cliente TS regenerado es idéntico al commiteado)
```

`contrato.ts` sigue compilando: el job `frontend / contratos`, los cuatro
`ng build` y `ng test` del mismo run, en verde. Los demás workflows sobre el
SHA de corte (`gh run list`): `e2e` 30331195269 y `android` 30331195281,
todos success.

**Deuda cerrada en este módulo** (detalle y evidencia en
[`docs/deuda-tecnica.md`](deuda-tecnica.md)): **D-10** (`ventas.cliente_id`
sin FK: se cerró ADOPTANDO el `cliente_id` del dispositivo como PK de
`clientes`, como mandaba su vencimiento; la columna se queda sin FK a
propósito, decisión 4 del plan). **Deuda nueva registrada**: **D-27** (el
abono de fiado no viaja por el lote todavía — es REST online con la ancla
puesta; tensión declarada con ADR-022, decisión 6) y **D-28** (no hay delta
de clientes hacia dispositivos: un cliente creado en una caja llega a la
otra solo online, decisión 13). Ambas vencen antes del piloto. **Hallazgos
de las revisiones NO registrados** (no cumplen el criterio del registro:
riesgo real + vencimiento): `_CAMPOS_DEL_HECHO` sin `fecha_vencimiento` — el
reenvío que solo cambia la fecha sale `duplicada` conservando la primera,
pero la fecha es metadata del fiado corregible online por el endpoint de
reprogramación, no parte del hecho de la venta — y `fiado.credito_creado`
emitido antes que `venta.creada` en el outbox — el orden relativo de dos
eventos de la misma transacción no tiene consumidor todavía (el primero
será el módulo 7, que consume `fiado.credito_vencido`): si alguno de los
dos muerde de verdad, se registra con su vencimiento.

---

## La suite de tests

```
cd backend && uv run pytest -q
879 passed
```

De ellos, **449 son `integration`** (cifra de Fase 0: 106; el crecimiento viene de
los módulos catálogo, ventas, inventario, caja y fiado, ver sus secciones): hablan con el PostgreSQL, el
RabbitMQ y el Keycloak del compose, y con la API por su dominio. **No se omiten**
si el servicio falta: fallan con un mensaje que dice qué falta. Un test que
desaparece del recuento no prueba nada, y el job de CI convierte cualquier
`SKIPPED` en fallo. *(Actualizado al HEAD fd55d86, run ci 30331195290.)*

Frontend: 250 specs (`npx ng test --watch=false`), más 2 specs E2E de
Playwright (`npm run e2e`: login con passkey y CRUD de negocio) contra el
stack por dominio.

---

## Medición final de la cosecha

El spec §5.2 estimaba **6.100 LOC** cosechadas de `base_saas` hacia la librería
transversal. Medición real de `backend/libs/vendi-core/src` (Python, sin
`__pycache__`, contando comentarios y docstrings — que aquí no son relleno: son
el registro de procedencia que el propio plan exige):

| Paquete | LOC | Categoría del spec | Desviación |
|---|---:|---|---|
| `auth` | 1.384 | con adaptación | `keycloak_admin.py` fue **reescritura dirigida**, no adaptación, como el spec ya anticipaba |
| `middleware` | 682 | sin cambios | — |
| `audit` | 588 | con adaptación | `tenant_slug` → `tenant_id UUID` |
| `db` | 483 | reescritura | `rls.py` es nuevo; `engine.py` y `session.py` reescritos |
| `retention` | 482 | con adaptación | ámbito por `tenant_id`; **ampliado** con SAVEPOINT por política |
| `jobs` | 426 | con adaptación | ídem |
| `messaging` | 393 | sin cambios | **desviación**: el dispatcher se endureció dos veces (D-05 y D-07) |
| `mail` | 390 | reducción a 200 | **desviación**: quedó en 390, no en 200 |
| `tenant` | 306 | reescritura | — |
| `storage` | 290 | con adaptación | bucket único por región con prefijo |
| `tracing` | 204 | sin cambios | — |
| resto (`config`, `files`, `events`, `errors`, `cache`, `logging`, `models`) | 506 | sin cambios | **desviación**: `audit`, `messaging` y `storage` no fueron «sin cambios» |
| **Total `vendi-core`** | **6.146** | estimado 6.100 | **+0,8 %** |

La estimación global acertó casi exactamente; lo que no acertó fue el **reparto**
por categorías. Tres paquetes que el spec daba por «sin cambios» (`audit`,
`messaging`, `storage`) sí requirieron adaptación, y `mail` no bajó a 200 LOC
porque el `SystemMailer` que sí se conserva arrastra más superficie de la
prevista.

Resto del repositorio, para contexto:

| Árbol | LOC |
|---|---:|
| `backend/services/api` (incluye migraciones y scripts) | 2.598 |
| `backend/services/worker` | 466 |
| `backend/tests` | 8.449 |
| `frontend/projects/libs` (TypeScript) | 6.024 |
| `frontend/projects/vendi-*` (TypeScript) | 3.538 |
| `infra/` + `scripts/` (compose, Traefik, bash, Python de operación) | 5.686 |

Que los tests (8.449) pesen más que la librería (6.146) es intencional: la
mayoría del valor de esta fundación está en los candados, no en el código que
vigilan.

Comandos que reproducen la tabla:

```bash
for d in backend/libs/vendi-core/src/vendi_core/*/; do
  printf '%s %s\n' "$(basename "$d")" \
    "$(find "$d" -name '*.py' -not -path '*__pycache__*' -exec cat {} + | wc -l)"
done | sort -k2 -nr
```

---

## Qué queda vivo para la Fase 1

Lo que está mal **a sabiendas**, con dueño y fecha, vive en
[`docs/deuda-tecnica.md`](deuda-tecnica.md). Resumen al cierre de Fase 0:

| # | Deuda | Vence |
|---|---|---|
| D-03 | El realm es semilla; la aplicación automática cubre solo el subconjunto seguro | Fase 1 |

Cerradas en la Etapa 5, con su evidencia en el registro de deuda: **D-01**
(ROPC), **D-04** (Keycloak sin `--optimized`), **D-06** (`alembic_version`
escribible), **D-07** (`exchange` del outbox), **D-08** (claim `groups` /
`has_role()` inerte). Cerrada en la Task 0.5.3 de Fase 1 (2026-07-27): **D-02**
— el aprovisionamiento se movió al servicio `provisioner`, la única unidad de
despliegue con `manage-realm` (ADR-027).

### Fuera del alcance de Fase 0, por diseño

Nada de esto es deuda: es alcance que el plan excluyó y que la Fase 1 recoge.

- **El dominio del MVP**: POS, inventario, compras, caja, fiado. No existe una
  sola tabla de negocio todavía — la única que hay (`files`) es de la librería.
- **Offline-first** (IndexedDB, cola de sincronización).
- **Autenticación móvil**: `vendi-app` compila y produce un AAB, y nada más.
- **Monetización**: portal de pago, webhooks, entitlements.
- **Módulos de backlog**: `api_keys`, `webhooks`, `feature_flags`,
  `notifications`, `account`, `tenant_settings`. El porqué de cada uno está en
  [ADR-016](adr/adr-016-backend-api-worker.md).
- **Terraform**: diferido a Fase 2 ([ADR-003](adr/adr-003-multi-region.md)). La
  reproducibilidad interina es el compose de producción versionado más
  `deploy.yml` y el runbook de la VM.
