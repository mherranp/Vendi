# ADR-021 — Sesiones de caja con arqueo: una caja por tienda, base del P&L y el forecast

**Fecha:** 2026-07-27 · **Estado:** Firmada (Fase 1, Etapa 1.1)
**Origen:** `docs/plan-maestro.md` §3 (Caja + Finanzas simples) y §7 (Fase 1).
Complementa ADR-006, que firmó el QUÉ (P&L simple + forecast 30d) sin fijar el
modelo operativo de caja del que ambos se calculan.

## Contexto

El tendero abre el día con una base, mete y saca plata, y cierra contando el
efectivo. Ese conteo —el arqueo— es el hábito diario que el embudo del plan
maestro (§6) usa como gancho de retención, y es además la única fuente de
gastos menores que no pasan por ventas ni compras. Sin un modelo de caja, el
P&L de ADR-006 no tiene de dónde leer los egresos y el forecast no tiene
punto de partida (el saldo actual). Con multi-empleado (ADR-023) además hay
que decidir de quién es la caja cuando dos personas atienden.

## Decisión

**Una sesión de caja abierta por tienda a la vez**, con apertura, movimientos
y cierre con arqueo, en dos tablas:

- **`caja_sesiones`** — una fila por turno de caja: `abierta_por`,
  `abierta_en`, `base_inicial`, `cerrada_por`, `cerrada_en`,
  `efectivo_esperado`, `efectivo_contado`, `diferencia`, `estado`
  (`abierta`/`cerrada`). La unicidad de la sesión abierta se garantiza con un
  **índice único parcial** `(tenant_id) WHERE estado = 'abierta'`: la regla
  «una caja por tienda» la hace cumplir la base, no el código.
- **`caja_movimientos`** — ingresos y egresos manuales con `tipo`
  (`ingreso`/`egreso`), `categoria` (lista cerrada corta: arriendo, servicios,
  retiro del dueño, otro…), `monto`, `nota` y la sesión a la que pertenecen.
  Las ventas en efectivo y los abonos de fiado (ADR-022) **no se duplican**
  como movimientos: el arqueo los suma desde su tabla de origen. Duplicarlos
  sería dos fuentes de verdad para el mismo peso.

El arqueo es una cuenta, no una pantalla mágica:

```
efectivo_esperado = base_inicial
                  + ventas en efectivo de la sesión
                  + abonos de fiado en efectivo de la sesión
                  + ingresos manuales − egresos manuales
diferencia        = efectivo_contado − efectivo_esperado   (faltante/sobrante)
```

Relación con ADR-006: el **P&L** lee ventas, compras y `caja_movimientos` por
período y categoría —no pide nada nuevo al usuario, que era la condición
firmada—. El **forecast a 30 días** parte del saldo de caja actual y proyecta
ventas por promedio histórico más cobros de fiado con vencimiento en la
ventana (ADR-022), menos egresos recurrentes; la pantalla declara de qué
datos sale, como manda ADR-006.

Dos reglas de representación: los montos son enteros en centavos (criterio
unificado de Fase 1, ADR-018; la moneda única del MVP es el peso colombiano y
multi-moneda no existe en el roadmap) y las fechas se guardan en UTC pero el
«día» del P&L y del cierre se calcula en `America/Bogota`.

## Alternativas descartadas

- **Una sesión por empleado (cajas paralelas).** Es el modelo de los POS de
  retail grande. En la tienda de barrio hay UNA gaveta: dos sesiones abiertas
  sobre el mismo efectivo harían imposible el arqueo, que es justo la
  funcionalidad que retiene al usuario. Quién registró cada venta ya queda en
  la venta misma; la caja es del negocio.
- **Duplicar ventas y abonos como filas de `caja_movimientos`.** Simplifica la
  consulta del arqueo a costa de que cualquier anulación o abono posterior
  tenga que sincronizar dos tablas. El desfase entre ambas sería un faltante
  fantasma en cada cierre.
- **Saldo de caja materializado y actualizado por triggers.** Estado derivado
  guardado es estado que se desincroniza; el saldo se calcula con un `SUM`
  sobre datos que ya están, y a la escala de una tienda sobra.

## Consecuencias

- El cierre exige sesión abierta: vender sin caja abierta es posible (el POS
  offline no puede depender de ella), pero entonces esa venta no entra al
  arqueo de ninguna sesión. La app avisa, no bloquea.
- `efectivo_esperado` y `diferencia` se congelan al cerrar: aunque luego se
  anule una venta de esa sesión, el arqueo firmado no cambia (la anulación
  cae en la sesión abierta en ese momento). Es la única forma de que el
  cierre de ayer siga cuadrando mañana.
- Caja básica es de todos los tiers —es el hábito diario del embudo—; P&L y
  forecast son Pro/Light según ADR-010. El tier se aplica en la capa de
  producto, no en este modelo de datos.
- Las ventas y abonos que se suman al arqueo llegan por sincronización
  offline con id generado en el cliente (ADR-017): el endpoint de cierre debe
  aceptar que lleguen ventas de la sesión DESPUÉS de cerrada (dispositivo que
  sincroniza tarde). Esas ventas reabren la cuenta solo en reportes, nunca en
  la fila ya cerrada.

## Tablas, eventos y candado

- **Tablas nuevas:** `caja_sesiones` y `caja_movimientos`, ambas con
  `tenant_id` + policy RLS (idioma de ADR-013) + índice que empieza por
  `tenant_id`, más el índice único parcial de sesión abierta.
- **Eventos de outbox:** `caja.sesion_abierta`, `caja.sesion_cerrada` (con el
  resumen del arqueo: insumo del briefing matutino de IA y de la telemetría),
  `caja.movimiento_registrado`.
- **Candado:** test de integración de aislamiento cross-tenant por tabla
  (plantilla `test_cross_tenant_isolation.py`) + test del arqueo (sesión con
  ventas, abonos e ingresos/egresos sembrados: `efectivo_esperado` cuadra al
  peso y `diferencia = contado − esperado`) + test que un segundo `INSERT` de
  sesión abierta para el mismo tenant revienta contra el índice único.
