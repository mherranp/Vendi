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

---

## La suite de tests

```
cd backend && uv run pytest -q
576 passed
```

De ellos, **200 son `integration`** (cifra de Fase 0: 106; el crecimiento viene de
los módulos catálogo y ventas, ver sus secciones): hablan con el PostgreSQL, el
RabbitMQ y el Keycloak del compose, y con la API por su dominio. **No se omiten**
si el servicio falta: fallan con un mensaje que dice qué falta. Un test que
desaparece del recuento no prueba nada, y el job de CI convierte cualquier
`SKIPPED` en fallo. *(Actualizado al HEAD 0e02c29, run ci 30283626280.)*

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
