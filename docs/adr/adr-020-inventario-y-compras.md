# ADR-020 — Inventario por movimientos con idempotencia de sync, y compras simples

**Fecha:** 2026-07-27 · **Estado:** Firmada
**Origen:** `docs/plan-maestro.md` §3 (Inventario: stock en vivo, alertas de
bajo stock; Compras: registro y reabastecimiento) y §7 (Fase 1); P&L alimentado
por compras (ADR-006).

## Contexto

El POS es offline-first (ADR-017, en definición paralela): las ventas se
registran en el dispositivo con IDs generados en cliente y llegan al servidor
por una cola de sincronización, tarde, reordenadas y a veces repetidas. Aun así
el stock tiene que ser correcto — es la promesa «stock en vivo» del plan
maestro — y las alertas de bajo stock tienen que saltar una vez, no cada vez
que un reintento toca el mismo producto. Además, el tendero compra a
proveedores que no existen como entidad en ningún sistema: la factura es un
papel, a veces manuscrito.

## Decisión

**El inventario es un libro de movimientos más un contador mantenido, con
idempotencia por referencia de origen.**

- **`movimientos_inventario` es la verdad.** Cada cambio de stock es una fila:
  `tipo` (`venta`, `compra`, `ajuste`, `merma`), `cantidad NUMERIC` con signo
  (la venta descuenta, la compra suma), `referencia_id` (el UUID de la venta,
  la compra o el ajuste que lo causó) y `producto_id`. Nunca se edita ni se
  borra un movimiento: un error se corrige con otro movimiento.
- **`stock_actual` en `productos` es una proyección**, actualizada en la misma
  transacción que inserta el movimiento. El POS no puede pagar un `SUM()` sobre
  el libro en cada cobro (la promesa es cobrar en <5 s, plan maestro §3); la
  lectura es O(1) y el libro queda para auditoría y reconstrucción.
- **Idempotencia de sync con constraint, no con lógica.** Índice único
  `(tenant_id, tipo, referencia_id)`: la venta offline lleva el UUID que le dio
  el cliente (ADR-017), y el segundo intento de sincronizarla choca contra el
  índice y se reconoce como duplicada en vez de descontar dos veces. El
  servidor no confía en que el cliente no reintente; la base lo hace imposible.
- **Las ventas fuera de orden descuentan como deltas conmutativos.** Sumar y
  restar no depende del orden, así que una venta que llega tres días tarde se
  aplica igual. El `stock_actual` puede quedar **negativo** y se deja: la
  tienda ya vendió físicamente esa unidad, y bloquear la venta por falta de
  stock en el servidor rompería justo el escenario que el offline existe para
  salvar. El negativo se muestra como alerta de agotado.
- **Los ajustes son la excepción y por eso son online.** Un ajuste («conté 14,
  el sistema dice 16») se registra como delta calculado **contra el stock del
  servidor en el momento del conteo**. Un ajuste offline llegaría con un delta
  calculado contra un stock viejo y corrompería el contador de forma no
  conmutativa. El conteo físico requiere conexión; es la única operación de
  inventario que lo exige, y se declara así en la app.
- **Alertas de tres niveles por umbral, con evento solo al cruzar.**
  `stock_minimo NUMERIC` por producto. Los niveles son derivados, no
  configurables uno a uno: agotado (`<= 0`), crítico (`< stock_minimo / 2`),
  bajo (`< stock_minimo`). Al aplicar un movimiento se compara el nivel antes y
  después y se emite `inventario.alerta_stock` **solo cuando el nivel empeora**
  — si saltara por movimiento, una cola de sync de 40 ventas del mismo producto
  mandaría 40 notificaciones push (ADR-025) idénticas.
- **Compras: registro simple, proveedor como texto.** `compras` (fecha,
  `proveedor_nombre TEXT`, total, observaciones) + `compra_items` (producto,
  cantidad, `costo_unitario`). Al confirmarla, la misma transacción inserta los
  movimientos tipo `compra` y actualiza `ultimo_costo` en `productos`, que es
  lo que el P&L de ADR-006 costea. **No hay módulo de proveedores**: sin
  historial de precios consumido por nada en el MVP sería la entidad con
  consumidor imaginado que ADR-016 prohíbe escribir. La foto de factura con
  VLM es Fase 2 según el propio roadmap (§7).

Una sola bodega implícita: «multi-bodega avanzado» está fuera de scope en el
plan maestro §3.

## Alternativas descartadas

- **Solo la columna `stock_actual`, sin libro de movimientos.** No hay forma de
  auditar «¿por qué tengo menos arroz del que creía?» — la pregunta que el
  tendero le hace al sistema — ni de detectar la merma, ni de deduplicar la
  sync offline con una constraint.
- **Bloquear la venta cuando el stock del servidor llega a cero.** Con ventas
  offline llegando tarde, el stock del servidor es siempre una aproximación;
  rechazar ventas reales por un dato aproximado es peor que mostrar el
  negativo. La tienda de barrio no deja de vender porque el sistema diga.
- **Ajustes offline en la cola de sync.** No son conmutativos: dos dispositivos
  que ajustan el mismo producto producen resultados distintos según el orden de
  llegada, y no hay resolución correcta sin pedirle al usuario que decida.
  Mejor prohibido que mal resuelto.
- **Tabla `proveedores` con su CRUD e historial de precios.** El plan maestro §3
  lo menciona, pero para el piloto nadie lo consume (las sugerencias de
  reabastecimiento v1 se calculan de `compra_items`, que ya guarda el costo por
  compra). Se añadirá cuando exista el consumidor, como manda ADR-016.
- **Reordenar movimientos por la hora del cliente (`occurred_at`).** El reloj
  del dispositivo miente (la QA adversarial de la Etapa 1.4 lo prueba
  explícitamente), y para deltas conmutativos no aporta nada. El orden de
  aplicación es el de llegada; la hora del cliente se guarda como dato, no como
  criterio.

## Consecuencias

- El módulo de ventas (scope del arquitecto A/C) no descuenta stock por su
  cuenta: registra la venta y el inventario inserta el movimiento con
  `referencia_id = venta_id` en la misma transacción del endpoint de sync.
  Este ADR asume de ADR-017 la existencia de la cola con UUIDs de cliente y
  endpoints idempotentes; si ADR-017 decide otra clave de idempotencia, es el
  índice único `(tenant_id, tipo, referencia_id)` lo que hay que alinear.
- El `stock_actual` negativo es un estado legítimo y visible; la UI y las
  alertas tienen que tratarlo como información («vendiste de más según el
  sistema»), no como error.
- Reconstruir el stock desde el libro queda disponible como operación de
  soporte (runbook de sync, Etapa 1.5) para cuando un tenant reporte cifras
  imposibles.
- Los eventos de alerta llevan el mínimo payload (producto, nivel): nada de
  PII, como pide el checklist de seguridad de la Etapa 1.4.

## Tablas nuevas

- **`movimientos_inventario`** — `tenant_id` + RLS, índice por `tenant_id`,
  índice único `(tenant_id, tipo, referencia_id)`, índice
  `(tenant_id, producto_id)` para el libro por producto.
- **`compras`** — `tenant_id` + RLS, índice por `tenant_id`.
- **`compra_items`** — `tenant_id` + RLS, índice por `tenant_id`, FK a
  `compras` y a `productos`.

## Eventos de outbox que emite

- `compra.registrada` — alimenta P&L/forecast (ADR-006) y las futuras
  sugerencias de reabastecimiento.
- `inventario.alerta_stock` — solo al cruzar un umbral hacia abajo; su
  consumidor es el módulo de notificaciones (ADR-025), que lo traduce a
  `notificacion.enviar` para el envío FCM.
- Los movimientos de venta **no** emiten evento propio: el evento de negocio
  lo emite el módulo de ventas al registrarla, y duplicarlo inflaría el outbox
  sin información nueva.

## Candado verificable

- Test de integración de **doble sincronización**: aplicar dos veces el mismo
  lote offline (mismo `referencia_id`) deja el stock descontado una sola vez y
  la segunda aplicación se reporta como duplicada, no como error.
- Test de la **invariante del libro**: para un producto cualquiera,
  `stock_actual = SUM(cantidad de sus movimientos)` tras una secuencia mezclada
  de ventas, compras, mermas y un ajuste.
- Test de **alerta única**: N movimientos que cruzan el mismo umbral emiten
  exactamente un `inventario.alerta_stock` por cruce de nivel.
- Test de aislamiento cross-tenant por cada tabla nueva, con la plantilla
  `backend/tests/integration/test_cross_tenant_isolation.py`;
  `test_rls_coverage.py` delata cualquier tabla sin `enable_rls`.
