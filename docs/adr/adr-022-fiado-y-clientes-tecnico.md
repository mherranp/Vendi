# ADR-022 — Diseño técnico del fiado: créditos con saldo vivo, abonos y recordatorios por push

**Fecha:** 2026-07-27 · **Estado:** Firmada (Fase 1, Etapa 1.1)
**Origen:** `docs/plan-maestro.md` §3 (Fiado + Clientes) y §7 (Fase 1).
Complementa ADR-009, que firmó que el fiado entra al MVP; este ADR fija el
cómo. Estrecha el «WhatsApp/push» de ADR-009 a push en el MVP (ver Decisión).

## Contexto

El fiado es el cuaderno: «Don Carlos me debe 43.000 del martes». La tentación
es modelarlo como saldo acumulado por cliente, pero el cuaderno real no es un
saldo: es una lista de fiados, cada uno con su fecha y sus pagos. De esa
diferencia dependen dos funcionalidades firmadas: el historial de pagos del
cliente (ADR-009) y los recordatorios por vencimiento, que exigen saber QUÉ
fiado vence, no solo cuánto debe alguien. ADR-016 dejó el módulo
`notifications` en backlog explícito «llega con el fiado»: este es el
consumidor que lo activa.

## Decisión

Tres tablas y un saldo calculado por crédito:

- **`clientes`** — la entidad mínima de ADR-009: `nombre`, `telefono`
  (formato WhatsApp colombiano, sin validación internacional en MVP), `nota`,
  `limite_credito` opcional. Sin más: el CRM avanzado es Fase 3 (ADR-008).
- **`fiado_creditos`** — una fila por venta fiada: `cliente_id`, `venta_id`
  (la venta existe con `metodo_pago = 'fiado'`; el crédito no duplica las
  líneas), `monto_total`, `saldo_pendiente` (ambos enteros en centavos,
  criterio unificado ADR-018), `fecha_vencimiento`, `estado`
  (`vigente`/`vencido`/`saldado`). `saldo_pendiente` SÍ se materializa y se
  descuenta en la misma transacción de cada abono, con un `CHECK
  (saldo_pendiente >= 0)`: es el dato que se consulta en cada pantalla de
  cliente y en el forecast (ADR-021), y el CHECK convierte el desfase en
  error en vez de en dato malo.
- **`fiado_abonos`** — cada pago parcial o total: `credito_id`, `monto`
  (entero en centavos), `metodo_pago`, `registrado_por`, `nota`. Los abonos
  en efectivo los suma el
  arqueo de la sesión de caja abierta (ADR-021); no se duplican como
  movimiento de caja.

El **saldo por cliente** no se guarda: es `SUM(saldo_pendiente)` de sus
créditos no saldados. El límite de crédito se evalúa contra esa suma al crear
el crédito; se puede superar con confirmación del dueño (el cuaderno nunca
le dijo que no a nadie; el POS tampoco, pero que lo diga en voz alta).

**Recordatorios: push al tendero, no WhatsApp al cliente.** Un trabajo diario
del worker marca `vencido` los créditos cuya fecha pasó y encola
`fiado.credito_vencido`; el módulo de notificaciones lo traduce a
`notificacion.enviar`, el evento único que el módulo de push convierte en FCM
al dueño (ADR-025). WhatsApp queda como **compartir manual**: la pantalla del
crédito ofrece un enlace `wa.me` con el mensaje prearmado («Hola Carlos, te
recuerdo el fiado de $43.000…»). Motivo medido: la API de WhatsApp Business
cobra por conversación, exige plantillas aprobadas y una cuenta que no existe
(los bloqueantes B-3 ya acumulan FCM y Gemini); el enlace `wa.me` cuesta
cero, funciona hoy y es exactamente cómo el tendero ya cobra. ADR-009 decía
«WhatsApp/push»: este ADR elige push automático + WhatsApp manual para el
MVP; el WhatsApp automático, si vuelve, vuelve con su ADR.

Los ids de créditos y abonos se generan en el cliente (ADR-017): un abono
registrado sin señal tiene que sincronizar sin duplicarse, y la idempotencia
la da el id, no la reintentada.

## Alternativas descartadas

- **Saldo único por cliente (sin créditos individuales).** Es más simple y no
  sirve: sin fiados individuales no hay fecha de vencimiento, luego no hay
  recordatorios, y no hay «debe 43.000 DEL MARTES», que es cómo el tendero
  piensa. Mataría las dos funcionalidades que justifican el módulo.
- **Aplicar abonos al crédito más antiguo automáticamente (sin elegir).** El
  tendero cobra fiados concretos («pásame lo del martes»); la asignación
  automática decide por él y luego la pantalla no coincide con su memoria. El
  abono se registra contra el crédito que el usuario toca.
- **WhatsApp automático vía API desde el MVP.** Coste por mensaje, plantillas
  por aprobar y una dependencia más antes del piloto, para un flujo que el
  `wa.me` manual cubre gratis. Se reevalúa cuando el piloto diga cuántos
  recordatorios se envían de verdad.

## Consecuencias

- Fiado es funcionalidad Pro (ADR-010): la restricción vive en la capa de
  producto; este modelo no lleva lógica de tier.
- Un crédito `saldado` nunca vuelve a `vigente`: si el cliente paga de más o
  se anula un abono, se registra el movimiento inverso, no se reabre. El
  historial de pagos de ADR-009 es la verdad y no se reescribe.
- `fecha_vencimiento` la pone el tendero por fiado (con default configurable,
  p. ej. 15 días): sin fecha no hay recordatorio, y forzarla es forzar un
  dato que el cuaderno no siempre tiene. Crédito sin vencimiento = sin
  recordatorio, declarado en pantalla.
- El trabajo diario de vencimiento corre en el worker con sesión de
  plataforma (BYPASSRLS, ADR-013/016): es cross-tenant por construcción,
  igual que el dispatcher del outbox.

## Tablas, eventos y candado

- **Tablas nuevas:** `clientes`, `fiado_creditos`, `fiado_abonos`, todas con
  `tenant_id` + policy RLS (idioma de ADR-013) + índice que empieza por
  `tenant_id`, más el `CHECK (saldo_pendiente >= 0)` en `fiado_creditos`.
- **Eventos de outbox:** `fiado.credito_creado`, `fiado.abono_registrado`,
  `fiado.credito_saldado`, `fiado.credito_vencido` (lo emite el trabajo
  diario; dispara el push).
- **Candado:** test de integración de aislamiento cross-tenant por tabla +
  test de saldo (crédito de 100, abonos de 30 + 30: saldo 40; abono de 41
  revienta contra el CHECK) + test del trabajo diario (crédito con
  vencimiento de ayer pasa a `vencido` y encola exactamente un
  `fiado.credito_vencido`, idempotente al re-correr).
