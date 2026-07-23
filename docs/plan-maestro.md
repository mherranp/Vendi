# Vendi — Plan Maestro de Producto y Negocio (v1.0)

**Fecha:** 21 de julio de 2026 · **Estado:** Documento de consenso entre socios
**Fuentes fusionadas:** documentación Vendi (visión, plan técnico v2, monetización web-first, PDF inversores) + business plan del socio (`AI-Smart-Business-Manager-BP-VLM-Scanning.docx`)
**Regla de este documento:** en las diferencias de stack se mantiene la arquitectura Vendi (ADRs 001–004); del documento del socio se incorporan mercado, canal institucional, fiado, pipeline VLM, tiers de precio y modelo financiero (con supuestos etiquetados). Este documento es la fuente canónica; los demás quedan como anexos de detalle.

---

## 0. Registro de decisiones (ADR)

| ADR | Decisión | Estado |
|---|---|---|
| ADR-001 | Capacitor como empaquetado nativo desde el inicio (Angular 21 + PWA) | ✅ |
| ADR-002 | RabbitMQ como broker de tareas + Redis como cache | ✅ |
| ADR-003 | Arquitectura multi-región federada por país (MVP opera solo CO) | ✅ |
| ADR-004 | Cobro de suscripciones web-first (sin venta in-app; pasarela local) | ✅ |
| ADR-005 | Telemetría/analytics del POS | ⏳ Abierto |
| ADR-006 | **El MVP incluye P&L simple + forecast de flujo de caja a 30 días** (sin contabilidad formal ni tesorería) | ✅ Nuevo |
| ADR-007 | **Capa `AIProvider` con interfaz OpenAI-compatible**; Gemini 2.5 Flash primario, GPT-5 mini fallback, Qwen-VL opcional para recibos manuscritos | ✅ Nuevo |
| ADR-008 | **Módulo de marketing/publicidad (Meta Ads, CRM avanzado RFM) → Fase 3** | ✅ Nuevo |
| ADR-009 | **Fiado (crédito a clientes) + CRM mínimo de clientes entran al MVP** | ✅ Nuevo |
| ADR-010 | **Tiers: Gratis / Light (~$19.500 COP) / Pro (~$40.000–$60.000 COP) + add-on Facturación DIAN; trial de 1 mes del tier Pro sin tarjeta** | ✅ Nuevo |
| ADR-011 | Fronteras de importación del workspace Angular, validadas por `no-restricted-imports` | ✅ Fase 0 |
| ADR-012 | Cuatro aplicaciones Angular (`vendi-portal`, `vendi-tenant`, `vendi-admin`, `vendi-app`) y cinco librerías | ✅ Fase 0 |
| ADR-013 | Aislamiento multi-negocio con **RLS en schema único** y dos roles de base de datos | ✅ Fase 0 |
| ADR-014 | **Un realm por región** con una Organization de Keycloak por negocio (`alias = str(tenant_id)`) | ✅ Fase 0 |
| ADR-015 | Los roles de negocio son **roles de realm**; no se usa el claim `groups` | ✅ Fase 0 |
| ADR-016 | Backend como **monolito modular (`api`) + worker**, sobre la librería `vendi-core` cosechada de BaseSaaS | ✅ Fase 0 |

> Los ADR-001 … ADR-010 nacieron como filas de esta tabla. Desde la Etapa 5 de
> Fase 0 cada decisión tiene además su archivo en [`docs/adr/`](adr/) con
> contexto, alternativas descartadas y consecuencias; esta tabla queda como
> índice. Los ADR-011 … ADR-016 documentan las decisiones que tomó la fundación
> técnica y que antes solo vivían en el plan de implementación.

---

## 1. Visión y producto

**Vendi** es el ERP de bolsillo para los micro y pequeños negocios de Latinoamérica: ventas, inventario, compras, caja y fiado en el celular, con un asistente de IA que registra por voz y foto y convierte los datos del negocio en recomendaciones en lenguaje simple.

- **Segmento:** tiendas de barrio, ferreterías, minimercados, droguerías, cafeterías, boutiques — negocios sin computador, con smartphone (Android dominante), baja alfabetización digital.
- **Propuesta:** "El negocio entero en el celular" — registro en segundos (voz, foto, escáner), decisiones con datos, cero contabilidad formal.
- **Regla de oro de IA (consenso de ambos documentos):** las recomendaciones nacen de reglas deterministas sobre los datos; el LLM solo las narra. El código decide, la IA conversa.

## 2. Mercado (cifras del socio — ⚠️ pendientes de verificación con DANE/CCB antes de uso externo)

- ~1,93M PYMEs en Colombia; ~35% retail/wholesale (~675K negocios); micro-empresas (<10 empleados) >90% del tejido retail.
- Digitalización baja: ~28% usa facturación electrónica, <10% usa ERP; la mayoría lleva cuaderno o Excel.
- Infraestructura móvil madura: >75% smartphones, 4G >95%, Nequi+Daviplata >30M usuarios.
- **TAM** $135M/año (675K × $200 ARPU) · **SAM** $60M/año (250K negocios urbanos 2–20 empleados × $240) · **SOM** Y1 $480K → Y3 $3,6M.

**Dolores validados por ambos documentos:** inventario caótico (quiebres de stock = 8–15% de ventas perdidas/mes), compras dispersas en papel y WhatsApp, **fiado llevado de memoria o en cuaderno**, cero analítica, marketing limitado al boca a boca.

## 3. Alcance del MVP (Fase 1)

| Módulo | Incluye | Fuera de scope |
|---|---|---|
| **Ventas / POS** | Cobro en <5s, catálogo táctil, escáner de código, registro por voz, ticket compartible por WhatsApp e impresora Bluetooth | — |
| **Inventario** | Stock en vivo, alertas de bajo stock (3 niveles), carga por foto/código, clasificación ABC, conteo asistido (pipeline VLM §4.4) | Multi-bodega avanzado |
| **Compras** | Registro por foto de factura de proveedor (VLM), proveedores con historial de precios, sugerencias de reabastecimiento | — |
| **Caja + Finanzas simples (ADR-006)** | Apertura/cierre, ingresos/egresos, **P&L simple por período y categoría**, **forecast de flujo de caja a 30 días** | Contabilidad formal, tesorería, activos fijos, presupuestos |
| **Fiado + Clientes (ADR-009)** | Venta a crédito con saldo por cliente, recordatorios de vencimiento (WhatsApp/push), historial de pagos del cliente, base de clientes mínima | CRM avanzado / RFM (Fase 3, ADR-008) |
| **Asistente IA** | Consultas en lenguaje natural, recomendaciones diarias (reglas + narración LLM), registro por voz, briefing matutino push | — |
| **Multi-empleado** | Hasta 3 usuarios en Pro: roles dueño / cajero / almacenista con permisos diferenciados | — |
| **Facturación DIAN** | Fase 2 vía Factus (add-on) | No es MVP |

## 4. Arquitectura técnica (se mantiene la nuestra)

Stack confirmado: **FastAPI + Angular 21 (PWA + Material) + Capacitor + Keycloak 26 + PostgreSQL (RLS) + RabbitMQ + Redis**, multi-región federada por país (ADR-003, MVP solo región CO), offline-first con IndexedDB como fuente de verdad local, cobro web-first (ADR-004). Detalle completo en `docs/plan-tecnico.md`.

### 4.1 Capa `AIProvider` OpenAI-compatible (ADR-007)

Una sola interfaz (formato OpenAI: `/chat/completions`, function calling, multimodal) detrás de la cual se enchufa cualquier proveedor:

| Rol | Proveedor | Uso |
|---|---|---|
| **Primario** | Gemini 2.5 Flash (endpoint OpenAI-compatible) | Voz nativa, visión, asistente; ~$0.06/1M tokens entrada |
| **Fallback** | GPT-5 mini | Contingencia y segunda opinión (~$0.25/$2 por 1M) |
| **Especialista opcional** | Qwen-VL (DashScope, modo OpenAI-compatible) | Recibos manuscritos y layouts complejos — la contribución técnica más fuerte del documento del socio (Turbo $0.04/$0.08, VL-Plus $0.10/$0.30, VL-Max $1/$3 por 1M) |

Ventaja del formato OpenAI-compatible: cambiar de proveedor es cambiar `base_url` + API key, sin tocar código.

### 4.2 Pipeline de escaneo en 3 capas (adoptado del socio)

```
Capa 1 — On-device (<100ms): barcode/QR con ML Kit / AVFoundation (Capacitor). Sin red. Cubre recepción, consulta y POS.
Capa 2 — VLM estándar (4–6s): foto comprimida a 800px → Gemini Flash / Qwen-VL-Plus → extracción estructurada de recibos impresos y productos sin código.
Capa 3 — VLM avanzado (6–8s): recibos MANUSCRITOS (comunes con proveedores colombianos), imágenes borrosas, multipágina → Qwen-VL-Max. Se invoca solo si la capa 2 cae bajo umbral de confianza.
```

## 5. Monetización web-first (ADR-004 + ADR-010)

Cobro SOLO en portal web propio (cero comisión de tiendas; la app nunca vende ni enlaza al checkout). Detalle completo en `docs/monetizacion-web.md`. Tiers actualizados:

| Tier | Precio (hipótesis) | Límites |
|---|---|---|
| **Gratis** | $0 | 100 productos, 1 usuario, POS+inventario básico, IA 5 consultas/mes. **Trial: 1 mes de Pro completo al registrarse, sin tarjeta** |
| **Light** | ~$19.500 COP/mes (~$4,99) | 500 productos, transacciones ilimitadas, IA 30 consultas/día, 2 empleados. Escalón de conversión "precio de un café" |
| **Pro** | ~$40.000–$60.000 COP/mes | Ilimitado, IA completa (voz+foto), fiado, P&L y forecast, 3 empleados, reportes |
| **Add-on Facturación DIAN** | Paquete de documentos (costo Factus + margen) | Factura electrónica + POS electrónico (Fase 2) |

Pasarela local (Wompi / Mercado Pago / Bold — verificar tarifas): tarjeta y Nequi con recurrencia tokenizada; PSE y efectivo (Efecty/Baloto) como prepago 30 días. Ciclo de vida con 3 días de gracia, degradación a gratis sin pérdida de datos.

## 6. Go-to-market fusionado (dos motores)

**Motor 1 — Canal institucional (adoptado del socio):**
- Aliados objetivo: **CCB** (~450K empresas registradas), **CCM** (~200K), **FENALCO** (~65K afiliados). Red combinada >700K negocios.
- Mecánica: Vendi Gratis como "beneficio digital de membresía"; talleres co-brandeados de transformación digital (CCB hace 200+ eventos/año; costos compartidos ~30% nuestro); dashboard de datos agregados anonimizados para el gremio; **revenue share 5–8% del primer año de suscripción** por usuarios referidos.
- Valor: confianza institucional ("recomendado por la Cámara") + alcance masivo a bajo CAC.

**Motor 2 — Canal comunitario/digital (nuestro):**
- Contenido TikTok/WhatsApp/Facebook ("del cuaderno al celular"), agentes de barrio que instalan y enseñan, guion de venta por WhatsApp (`docs/monetizacion-web.md` §6), ASO en Play Store, referidos con incentivo.

**Embudo común:** gratis sin tarjeta → hábito diario (cierre de caja + briefing IA) → trial Pro 1 mes → conversión a Light/Pro → el dato histórico como switching cost.

## 7. Roadmap

- **Fase 0 (sem 1–4):** monorepo, CI/CD con binarios Capacitor, Keycloak realm CO + Organizations + passkeys, PG+RLS, RabbitMQ+Redis, **compose de producción versionado + workflow de despliegue** (IaC con Terraform **diferido a Fase 2**, ADR-003: con una sola región y un solo servidor, Terraform es coste sin beneficio y la reproducibilidad la da el compose versionado).
- **Fase 1 — MVP Colombia (sem 5–13):** POS offline-first, inventario, compras, caja + **P&L simple + forecast 30d**, **fiado + clientes**, asistente IA v1 + voz, escáner 3 capas, multi-empleado. Piloto 50–100 tiendas (semilla desde listas CCB). Play Store + PWA pública; TestFlight iOS.
- **Fase 2 — Monetización y formalización (mes 4–7):** portal de suscripción + pasarela, trial automático, Factus (clientes + autofacturación), foto de factura de compra, impresora Bluetooth, App Store pública, push APNs.
- **Fase 3 — Escala (mes 8+):** región MX (SAT), PE (SUNAT), pagos (links PSE/Nequi/Bre-B), **módulo de marketing: CRM avanzado RFM, campañas segmentadas, asistente de pauta Meta Ads (ADR-008)**, warehouse de analytics, API abierta.

## 8. Modelo financiero (estructura del socio, supuestos etiquetados — TODO validar en piloto)

**Escenario del socio (optimista):** conversión free→pago 20–23%, churn 5→3,5%/mes, ARPU $13→$17/mes; ingresos brutos Y1 $324K / Y2 $1,56M / Y3 $3,72M; utilidad neta Y1 +$67K, Y3 +$2,4M; break-even mes 6–7; CAC $45→$24; LTV/CAC 6x→11,3x.

**Ajustes que proponemos al adoptarlo:**
1. **Conversión base 8–12%** (el 20–23% es 4–10× el benchmark freemium 2–5%; el tier Light ayuda, pero no tanto) → el break-even se mueve al **mes 10–14**, aún saludable.
2. **Comisiones de tienda desaparecen** del modelo (ADR-004): el socio presupuestó $617K en comisiones a 3 años; con web-first ese rubro cae a ~3% de procesamiento local (**ahorro ~$550K a 3 años**) y se habilitan Nequi/PSE/Efecty.
3. **Ingresos por publicidad (18% del total del socio)** se mueven a Fase 3 (ADR-008) → ingresos Y1–Y2 provienen ~95% de suscripción + add-ons.
4. **Costo de R&D:** el socio asume fundador técnico sin costo; si el equipo contrata ingeniería, agregar esa línea (el PDF de inversores la estima en 50% de la ronda).
5. **IA a costo negligible:** ~$0,05–$0,20 USD por negocio activo/mes (Gemini Flash); el socio estimó $56K a 3 años con Qwen — mismo orden de magnitud, no mueve la aguja.

**Fundraising (base socio, ajustado):** semilla **$150K–$250K**; uso de fondos: 30% marketing+canales (incl. revenue share gremial), 10–15% infra+IA, 25% G&A/legal, 30–35% reserva. Pre-Series A opcional $300–500K (mes 12–15) si se superan las metas. Salidas potenciales: Mercado Libre, Rappi, Nubank, ERP global buscando entrada a PyME LATAM.

## 9. Personas y casos de uso (del socio — adoptados para material comercial)

- **Don Carlos, 55, tienda de barrio (Kennedy, Bogotá):** briefing matutino push, reabastecimiento con un tap, foto a recibos, "¿cuánto gané este mes?".
- **Laura, 32, boutique (El Poblado, Medellín):** análisis de temporada, clientes VIP, campaña de nuevas colecciones (Fase 3).
- **Roberto, 45, ferretería (Cali, 3.000 SKUs):** clasificación ABC, tendencias de precios del cemento, roles para 5 empleados.
- **Andrea, 38, minimercado ×3 (norte de Bogotá):** comparativo multi-tienda, compras consolidadas, forecast de caja para crédito bancario.

## 10. Riesgos consolidados

| Riesgo | Mitigación |
|---|---|
| Conversión free→pago menor a la proyectada | Escenario base 8–12%; tier Light; trial 1 mes; medición semanal en piloto |
| Dependencia del canal gremial | Tres instituciones en paralelo + motor comunitario propio; contratos con revenue share (no exclusividad) |
| Adopción tecnológica del segmento | Passkeys (sin contraseñas), voz/foto, agentes que instalan, onboarding por el asistente |
| Rechazo de tiendas (thin client / steering) | Plan gratis genuino, cero CTAs de compra in-app (ADR-004), Capacitor con features nativas |
| Sync offline / conflictos de stock | Deltas + auditoría; reconciliación al cierre; tests de caos |
| Pérdida de jobs fiscales/IA | RabbitMQ DLQ + backoff (ADR-002) |
| Alucinaciones del LLM | Reglas deterministas deciden; LLM narra; evals con casos del piloto |
| Dependencia de un proveedor de IA | `AIProvider` OpenAI-compatible (ADR-007): Gemini → GPT-5 mini → Qwen |
| Riesgo de persona única (fundador técnico) | Documentación como código desde el día 1; contratación de 1–2 ingenieros desde Y1/Y2 |
| Cifras de mercado sin verificar | Validación con DANE/CCB antes de material para inversores |

## 11. Métricas del piloto (Fase 1)

Retención semanal (>40% a semana 4), DAU/MAU, tiempo por venta registrada (<5s), % ventas por voz/escáner, conversión trial→pago (base 8–12%), mix de métodos de pago, churn mensual, NPS del segmento, costo IA por negocio (<$0,20 USD/mes).

---

### Anexos (documentos de detalle)

- `docs/plan-tecnico.md` — arquitectura completa, ADR-001..004, tiendas, IA.
- `docs/monetizacion-web.md` — portal de pago, webhooks→entitlements, ciclo de vida, guion WhatsApp.
- `docs/analisis-comparativo-socios.md` — análisis de diferencias y origen de cada fusión.
- `docs/adr/` — un archivo por decisión, ADR-001 … ADR-016. La tabla de §0 es
  el índice; el detalle (contexto, alternativas descartadas, consecuencias) vive
  ahí.
- `docs/Vendi_Inversores.pdf` — documento para inversores (a regenerar con este
  plan maestro).

> **Corrección de la Etapa 5 (2026-07-23).** Esta lista citaba dos anexos que no
> existen en el repositorio: `vision-producto/index.html` (la visión interactiva
> nunca se versionó; el contenido vivo es este mismo documento) y
> `investor_pdf/Vendi_Inversores.pdf` (el PDF está en `docs/`, no en una
> carpeta `investor_pdf/`). Se deja constancia en vez de borrar en silencio,
> porque las dos referencias se citan también desde
> `docs/analisis-comparativo-socios.md` y desde documentos que ya circularon.
