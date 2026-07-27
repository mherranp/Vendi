# ADR-025 — Notificaciones push: FCM como canal único de Fase 1

**Fecha:** 2026-07-27 · **Estado:** Firmada (Fase 1)
**Origen:** `docs/plan-maestro.md` §3 (recordatorios de fiado, briefing
matutino push) y §7 («push APNs» explícitamente en Fase 2). ADR-001 lo
presupone; ADR-009 promete los recordatorios.

## Contexto

El fiado (ADR-009) necesita recordatorios de vencimiento y el asistente IA
(ADR-026) necesita entregar el briefing matutino. El segmento es Android
dominante (plan maestro §1: «smartphone, Android dominante») y la app nativa
ya existe por Capacitor (ADR-001). El plan maestro deja «push APNs» para
Fase 2: en Fase 1 iOS entra solo por TestFlight, sin tienda pública.

## Decisión

**FCM es el único canal push de Fase 1.** El envío lo hace el `worker`
(ADR-016) con la credencial de servicio de Firebase (secreto sin default,
regla del repo); la recepción usa `@capacitor/push-notifications` detrás de la
librería `native` (ADR-011).

- **Un solo evento de entrada:** el módulo de notificaciones consume los
  eventos de dominio (`fiado.credito_vencido`, `inventario.alerta_stock`, los
  disparadores de IA) y encola en el outbox **`notificacion.enviar`** (tipo,
  destinatario, referencia al recurso). El módulo `push` del worker lo
  consume, resuelve los tokens del usuario y entrega por FCM. Los módulos de
  negocio no conocen FCM.
- **Tokens:** tabla `push_device_tokens` (`tenant_id` + RLS, usuario,
  plataforma, token, `actualizado_en`). Se registra al login y se borra al
  logout y cuando FCM responde `NotRegistered` — un token muerto que nadie
  purga es el origen del 90% de los «push no llegan».
- **Sin PII en el payload.** La notificación dice «Tienes 3 fiados por vencer
  esta semana», no «Pedro Gómez te debe $50.000»: la pantalla de bloqueo la
  ven otros. El detalle está dentro de la app, detrás del deep-link.
- **APNs queda para Fase 2**, como dice el plan maestro §7. En iOS Fase 1
  (TestFlight) no hay push: el briefing y los recordatorios aparecen como
  avisos in-app al abrir. El WhatsApp de ADR-009 sigue siendo deep-link
  manual del tendero hacia su cliente; no es envío automatizado.

## Alternativas descartadas

- **FCM + APNs desde ya.** Duplicar el pipeline de entrega, los certificados
  y las pruebas para una plataforma que en Fase 1 no tiene usuarios de pago:
  el plan maestro ya lo diferió y no hay presión nueva que lo revierta.
- **OneSignal u otro intermediario.** Otro proveedor con tokens y PII de por
  medio, otro secreto y otra factura, para entregar lo que FCM entrega gratis.
- **Notificaciones locales programadas en el dispositivo.** Funcionarían
  offline, pero el vencimiento de un fiado lo decide el servidor (el fiado se
  puede pagar desde otro dispositivo) y una alarma local no se entera: sería
  el recordatorio que suena por una deuda ya cobrada.

## Consecuencias

- `vendi-app` pide el permiso de notificaciones en el onboarding; la app
  funciona completa si se niega — el push es acelerador, no requisito.
- El briefing matutino (ADR-026) y las alertas de bajo stock (ADR-020) usan el
  mismo evento: no hay un segundo canal de notificación que mantener.
- **Deuda asumida:** usuarios iOS del piloto sin push. Se cierra con APNs en
  Fase 2; el evento `notificacion.enviar` ya está desacoplado del
  transporte, así que APNs entra como consumidor adicional, no como rediseño.

## Tablas, eventos y candado

- **Tablas nuevas:** `push_device_tokens` — con `tenant_id`, policy RLS e
  índice por `tenant_id` vía `enable_rls(op, 'push_device_tokens')`.
- **Eventos de outbox que emite:** ninguno propio; **consume**
  `notificacion.enviar`, que este ADR define y emite el módulo de
  notificaciones al traducir `fiado.credito_vencido` (ADR-022),
  `inventario.alerta_stock` (ADR-020) y los disparadores de IA (ADR-026).
- **Candado:** test de aislamiento cross-tenant de `push_device_tokens`
  (plantilla `backend/tests/integration/test_cross_tenant_isolation.py`); test
  del worker con FCM mockeado que prueba que `NotRegistered` borra el token;
  y test unitario del constructor del payload que falla si el cuerpo contiene
  nombre de cliente o monto (la regla «sin PII» hecha mecánica).
