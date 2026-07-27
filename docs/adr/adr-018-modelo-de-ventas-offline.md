# ADR-018 — Modelo de ventas offline: venta append-only con ID de cliente y anulación como evento

**Fecha:** 2026-07-27 · **Estado:** Firmada
**Origen:** `docs/plan-maestro.md` §3 (Ventas/POS: cobro en <5s, ticket
compartible) y ADR-009 (el fiado es el modo normal de vender); plan de Fase 1,
Etapa 1.1-A. Complementa a ADR-017, que fija la capa de sincronización.

## Contexto

La venta es el caso extremo del offline: ocurre sin red, mueve dinero y stock
a la vez, puede ser fiada (ADR-009) y puede anularse. Si el modelo no es
idempotente, un reintento de la cola de sync duplica la venta y descuadra la
caja y el inventario — exactamente el daño que el POS promete eliminar del
cuaderno. Y si el número de venta lo asigna el servidor, el ticket que el
tendero ya compartió por WhatsApp deja de existir para el sistema.

## Decisión

**La venta es un hecho append-only creado en el dispositivo, con identidad y
número propios, que el servidor acepta tal cual y nunca edita.**

Tabla **`ventas`**: `id` UUIDv4 generado en el dispositivo (clave primaria);
`tenant_id`; `dispositivo_id` (ADR-017); `sesion_caja_id` (el modelo de
sesiones lo fija ADR-021); `consecutivo_local` entero por dispositivo — es el
número que ve el tendero y el que va en el ticket, con restricción única
`(tenant_id, dispositivo_id, consecutivo_local)`; `estado`
(`completada` | `anulada`); `medio_pago` (`efectivo` | `fiado` | otros medios
registrados como dato); `total_centavos` entero; `cliente_id` NULL salvo fiado;
`creada_en_cliente` (marca del reloj del dispositivo: dato del ticket, no
orden); `recibida_en` (marca del servidor: la única verdad temporal del
sistema); `secuencia_dispositivo`.

Tabla **`ventas_items`**: `tenant_id`, `venta_id`, `producto_id`, `cantidad`,
`precio_unitario_centavos`. El precio se congela en el ítem: el ticket no
cambia aunque el catálogo cambie después.

Las reglas:

- **Append-only.** Una venta sincronizada no se edita jamás. La única mutación
  permitida es `completada → anulada`: la anulación es una operación nueva que
  compensa el stock con el delta inverso y emite `venta.anulada`. Una venta aún
  no sincronizada puede anularse localmente, y **sube igualmente ya anulada**:
  la cola nunca se purga sin confirmación del servidor y la trazabilidad vale
  más que una fila de menos.
- **Stock por deltas, no por valores.** La venta no toca ningún campo `stock`
  del producto: al aplicarla, el servidor emite el movimiento de salida del
  modelo que fija ADR-020. La misma venta aplicada dos veces produce un solo
  movimiento, porque la fila ya existe (idempotencia por PK, ADR-017).
- **Turno offline.** La venta referencia la sesión de caja del negocio — una
  sesión abierta por tienda, como fija ADR-021 —; sin red, el dispositivo
  guarda la referencia local a la sesión que tiene abierta (o marca «sin
  sesión») y, al sincronizar, el servidor la resuelve a la sesión abierta del
  tenant; si no hay ninguna, abre una implícita (una sola: la protege el
  índice único parcial de ADR-021). El arqueo y sus diferencias son de
  ADR-021.
- **Fiado sin red.** Se permite fiar con el saldo local del cliente, que puede
  estar desactualizado. El servidor **no rechaza** la venta aunque supere el
  cupo — la mercancía ya salió de la tienda —; registra el exceso y lo muestra.
  La regla exacta de cupos es de ADR-022.
- **Dinero en enteros.** Totales y precios en centavos, nunca en flotante.
- **Multi-caja.** Dos cajeros del mismo negocio venden offline en paralelo sin
  compartir consecutivo, y ambos referencian la misma sesión de caja del
  negocio (ADR-021: una sesión abierta por tienda); el identificador público
  de una venta es `dispositivo + consecutivo`. El P&L y el forecast (ADR-006)
  suman por `recibida_en`, no por la marca del cliente.

## Alternativas descartadas

- **Autoincremental del servidor como número de venta.** O exige red en el
  momento del cobro — prohibido — o renumera al sincronizar, y entonces el
  ticket impreso o enviado por WhatsApp ya no coincide con el sistema.
- **Editar la venta (`UPDATE`) en lugar de anularla.** Rompe el append-only,
  que es lo que hace la caja auditable y la idempotencia del sync trivial.
- **Rechazar en el servidor el fiado que supera el cupo.** El rechazo crea una
  venta fantasma que solo existe en el dispositivo y que nadie sabe resolver en
  el mostrador. Se acepta y se señala.
- **`NUMERIC(12,2)` o flotante para el dinero.** El peso colombiano operativo
  no usa fracciones de centavo; el entero elimina la clase entera de errores de
  redondeo y comparación.

## Consecuencias

- `creada_en_cliente` puede mentir (reloj manipulado): se conserva para el
  ticket y la trazabilidad, pero orden, reportes y forecast usan
  `recibida_en`. Es la respuesta del modelo al escenario de QA «reloj
  adelantado/atrasado».
- El consecutivo no es único por negocio: dos cajas repiten números. Si la
  facturación DIAN (Fase 2) exige consecutivo fiscal único y central, será un
  ADR nuevo — no se paga hoy.
- La venta anulada sigue contando en el historial: los reportes que excluyen
  anuladas lo hacen por `estado`, nunca borrando.
## Tablas, eventos y candado

- **Tablas nuevas** (ambas con `tenant_id`, policy RLS e índice que empieza
  por `tenant_id`, vía `enable_rls(op, ...)`): `ventas`, `ventas_items`.
- **Eventos de outbox:** `venta.creada` y `venta.anulada`, con routing key
  `<tenant>.venta.<evento>` en el exchange único `events.tenant`; se emiten al
  aplicar el lote de sync, una sola vez por operación aceptada.
- **Candados:** (1) `test_sync_idempotente.py` — el mismo lote dos veces deja
  una venta, un movimiento de stock y un evento; (2) test de aislamiento
  cross-tenant por tabla nueva, con la plantilla
  `test_cross_tenant_isolation.py`, 0 SKIPPED; (3) test de anulación: anular no
  modifica ítems ni totales de la venta original y no borra el evento
  `venta.creada` ya publicado; (4) E2E Playwright del flujo de dinero: venta
  offline → sync → arqueo (gate de la Etapa 1.3).
