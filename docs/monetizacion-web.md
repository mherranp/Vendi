# Vendi — Diseño de monetización web-first (implementación de ADR-004)

> Documento de detalle del Plan Maestro (`docs/plan-maestro.md` v1.0). Actualizado a ADR-010 (tiers Light/Pro + trial) el 21-jul-2026.

**Fecha:** 20 de julio de 2026 · **Estado:** Diseño para implementación (Fase 2 del roadmap)
**Principio rector (ADR-004):** la suscripción se vende SOLO en el portal web propio; la app nunca procesa pagos ni muestra CTAs de compra hacia afuera; el plan gratis es genuinamente útil.

***

## 1. Mapa del flujo end-to-end

```
 DESCUBRIMIENTO (orgánico)          VENTA (canales propios)           ACTIVACIÓN (automática)
 ─────────────────────────          ───────────────────────          ────────────────────────
 App gratis en Play Store/          ┌─ Agente de barrio (WhatsApp)   Pasarela confirma pago
 PWA/App Store → el tendero    ───► ├─ Campañas WhatsApp/TikTok  ──► (webhook firmado)
 usa ventas+inventario gratis       └─ Portal vendi.co/pro               │
 (y ve badges "Pro" sin CTA)              │                             ▼
                                     Pago: PSE / Nequi /          FastAPI /webhooks/payments
                                     tarjeta / efectivo (Efecty)   (idempotente, verifica firma)
                                                                            │
                                                                            ▼
                                                              Entitlements: tenant.plan=PRO,
                                                              valid_until=+30d
                                                                            │
                                              ┌─────────────────────────────┼─────────────────────┐
                                              ▼                             ▼                     ▼
                                     App sincroniza                  WhatsApp al cliente:   Autofactura vía
                                     entitlements                    "¡Ya eres Pro!"        Factus (IVA incl.)
                                     (login + cada sync)
```

**Regla anti-steering en la app (crítica para App Store/Play en Colombia):**

* ✅ Permitido: badges "Pro" en funciones bloqueadas, pantalla "Mi suscripción" para usuarios ya pagos, push notifications de estado de cuenta (no son steering), mensajería por WhatsApp/email fuera de la app.

* ❌ Prohibido: botones "Suscríbete en la web", precios junto a enlaces, degradar el plan gratis para empujar la venta, abrir el checkout en un WebView.

## 2. Planes y entitlements (ADR-010)

| | **Gratis** | **Light** (~$19.500 COP/mes) | **Pro** (~$40.000–$60.000 COP/mes) | **Add-on Facturación DIAN** |
|---|---|---|---|---|
| Ventas POS + inventario | ✅ 100 productos, 1 usuario | ✅ 500 productos, transacciones ilimitadas | ✅ ilimitado | ✅ |
| Compras, caja, P&L simple, forecast 30d | ✅ básico | ✅ | ✅ completo | ✅ |
| Fiado + clientes | — | ✅ | ✅ | ✅ |
| IA: asistente, voz, foto de factura | 5 consultas/mes | 30 consultas/día | ✅ completo ilimitado | ✅ |
| Multi-empleado (roles) | — | 2 usuarios | 3 usuarios (dueño/cajero/almacenista) | ✅ |
| Reportes y recomendaciones IA | — | briefing diario | ✅ completo | ✅ |
| Factura electrónica / POS electrónico | — | — | — | ✅ paquete de documentos (costo Factus + margen) |

**Trial (ADR-010):** todo registro nuevo recibe **1 mes de Pro completo, sin tarjeta**; al vencer degrada a Gratis (datos intactos). El trial es el principal motor de conversión y se mide semanalmente.

**Lógica del tier Light:** escalón de conversión "precio de un café" — reduce la barrera psicológica del primer pago; la migración natural Light→Pro ocurre cuando el negocio necesita IA ilimitada, fiado avanzado o el tercer empleado.

Los *entitlements* se evalúan en servidor (la API rechaza operaciones fuera de plan) y se cachean en cliente para gating de UI offline.

## 3. Portal web de pago (vendi.co/pro)

Mobile-first (el tendero paga desde el mismo celular), sin registro con contraseña: identificación por **celular + OTP de WhatsApp**. Pantallas:

1. **`/pro` — Landing de planes.** Tres tarjetas (Gratis actual / Light / Pro) con badge de "1 mes de Pro gratis al registrarte", precio anclado "menos de \$1.300 al día", métodos de pago visibles (logos PSE/Nequi/Efecty) — esto genera confianza en el segmento.
2. **`/checkout` — 3 pasos:** (a) celular + OTP → vincula al tenant existente; (b) datos de facturación (nombre/razón social, CC/NIT, municipio — prellenado si ya existe); (c) método de pago.
3. **Métodos y su lógica de recurrencia:**

   * **Tarjeta:** tokenizada en la pasarela → débito automático mensual. *Recurrencia real.*

   * **Nequi:** débito automático vía tokenización de Nequi (push de aprobación). *Recurrencia real.*

   * **PSE:** pago único → modelo **prepago de 30 días** con recordatorios (no hay débito automático confiable).

   * **Efectivo (Efecty/Baloto):** se genera referencia/pin → paga en corresponsal → webhook confirma (24–48 h). *Prepago.*
4. **`/confirmacion`:** estado del pago; si es efectivo/PSE pendiente, instrucciones grandes y claras con la referencia + botón "enviarme la referencia por WhatsApp".
5. **`/cuenta`:** gestión (cambiar método, descargar facturas, cancelar). Es la única pantalla enlazable desde la app ("Mi suscripción").

**Nota de cumplimiento:** PAN y datos sensibles los tokeniza la pasarela; Vendi nunca almacena tarjetas (reduce alcance PCI a SAQ-A).

## 4. Pasarela de pagos — comparativa (verificar tarifas vigentes antes de firmar)

| <br />                          | Wompi (Bancolombia) | Bold             | Mercado Pago                   |
| ------------------------------- | ------------------- | ---------------- | ------------------------------ |
| PSE / tarjetas                  | ✅                   | ✅                | ✅                              |
| Nequi (tokenización recurrente) | ✅                   | ✅                | ✅                              |
| Efectivo (Efecty/Baloto)        | ✅ (Efecty)          | ✅                | ✅ (amplia red)                 |
| Webhooks + API                  | ✅ buena DX          | ✅                | ✅ muy completa                 |
| Suscripciones nativas           | Parcial             | Parcial          | ✅ (pero modelar prepago igual) |
| Fit con el segmento             | Alto                | Alto (foco PyME) | Alto                           |

Costo estimado del rubro: \~2,5–3,5% + fijo por transacción (**verificar**). Recomendación: integrar detrás de una interfaz `PaymentProvider` (mismo patrón que `AIProvider`), empezar con **una** pasarela (sugerencia: Wompi o Mercado Pago por cobertura de efectivo) y dejar la segunda como contingencia.

## 5. Arquitectura de activación (webhooks → entitlements)

```
Pasarela ──webhook──► FastAPI POST /webhooks/payments/{provider}
                      1. Verificar firma del proveedor (rechazo 401 si falla)
                      2. Idempotencia: payment_id único (tabla payments, ON CONFLICT DO NOTHING)
                      3. Encolar en RabbitMQ (notify.jobs / billing.jobs) — nunca procesar pesado en el webhook
                           │
                           ▼
                      Worker: actualiza Entitlement {tenant_id, plan, valid_until, source_payment_id}
                           │
                           ├─► App: GET /me/entitlements en login y en cada sync (cache offline 24 h)
                           ├─► WhatsApp/push de confirmación (notify.jobs)
                           └─► Autofactura electrónica de la suscripción vía Factus (fiscal.jobs)
```

**Dónde vive el plan — decisión arquitectónica:** la fuente de verdad es la tabla `entitlements` en PostgreSQL (no Keycloak). Keycloak gestiona identidad y organizaciones; el plan es dato de negocio. La app y la API leen entitlements vía FastAPI. (Opcional: reflejar `plan` como atributo de la Organization en Keycloak solo para visibilidad administrativa.)

**Estados del ciclo de vida:**

```
GRATIS ──pago confirmado──► ACTIVO ──faltan 3 días──► POR_VENCER ──vence──► GRACIA (3 días) ──sin pago──► SUSPENDIDO (degrada a Gratis)
   ▲                                                                                                          │
   └──────────────────────────────────── reactivación inmediata al confirmar pago ◄───────────────────────────┘
```

* En GRACIA todo sigue funcionando (no castigar al tendero por un Efecty que tarda).

* SUSPENDIDO = vuelve al plan gratis; **sus datos nunca se pierden** (solo se limitan funciones Pro). Esto es clave para reactivación y para la promesa de marca.

**Dunning (canales propios, no in-app):** WhatsApp D-3 ("tu plan vence el viernes"), D-1 con link de renovación directa (link de pago de la pasarela con monto prellenado), D+1 y D+3 en gracia. Tono de ayuda, no de cobranza.

## 6. Guion de venta por WhatsApp (agentes de barrio)

**Primer contacto (tras demo o referido):**

> Hola {nombre}, soy {agente} del equipo de Vendi 👋 ¿Ya pudiste registrar tu primera venta en la app? Si quieres te muestro en 2 minutos cómo se hace, es facilito.

**Al detectar uso activo (3+ días con ventas):**

> {nombre}, vi que ya le estás sacando el jugo a Vendi 🙌 Con el plan Pro se te activa el asistente que te dice qué es lo que más vendes, te avisa cuando se te está acabando un producto y puedes registrar compras con solo tomarle foto a la factura del proveedor. Vale menos de \$1.300 al día. ¿Te paso el link para activarlo? Pagas con Nequi, PSE o en Efecty, como te quede fácil.

**Cierre con link de pago:**

> Listo, aquí tienes tu link personalizado: {link}. Le das clic, eliges cómo pagar y queda activo de una vez (si es Efecty, te llega una referencia y al pagar en el corresponsal se activa solo). Cualquier cosa me escribes 🤝

**Seguimiento (48 h sin pago):**

> {nombre}, ¿pudiste revisar el link? Si el pago se te complica, dime y te ayudo — también te puedo generar la referencia para pagar en efectivo en el Efecty más cercano.

**Reglas del agente:** nunca pedir datos de tarjeta por chat; solo links de pago oficiales del dominio; registrar cada gestión en el CRM simple (fase 3: leaderboard de agentes).

## 7. Cumplimiento y contabilidad propia

* **Autofacturación:** cada pago de suscripción genera factura electrónica al cliente vía Factus (dogfooding de nuestra propia integración), con IVA de servicios digitales en Colombia.

* **Habeas Data (Ley 1581):** autorización de tratamiento de datos en el checkout; datos de pago minimizados (tokenización en pasarela).

* **Conciliación:** reporte diario payments vs. entitlements (job en RabbitMQ) para detectar pagos sin activar y activaciones sin pago.

## 8. Métricas del motor de monetización

Conversión trial→pago (escenario base 8–12%), conversión Gratis→Light→Pro, mix de métodos de pago (esperado: Nequi y efectivo dominan), churn mensual, reactivaciones tras gracia, tiempo promedio orden-efectivo→confirmación, costo de procesamiento como % del MRR (meta: <4%).

## 9. Tareas de implementación (Fase 2)

1. Interfaz `PaymentProvider` + integración pasarela #1 (checkout, webhooks, links de pago).
2. Tablas `payments` + `entitlements` + máquina de estados del ciclo de vida.
3. Portal web `/pro`, `/checkout` (OTP por WhatsApp), `/cuenta`.
4. Worker de activación + dunning por WhatsApp (notify.jobs en RabbitMQ).
5. Autofacturación vía Factus (depende de la integración DIAN).
6. Endpoint `/me/entitlements` + gating en API y cliente (cache offline).
7. Dashboard interno de métricas §8.

