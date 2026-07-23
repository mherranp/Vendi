# Análisis comparativo — Documento del socio vs. documentación Vendi

**Fecha:** 21 de julio de 2026
**Documento analizado:** `AI-Smart-Business-Manager-BP-VLM-Scanning.docx` (business plan del socio, en inglés)
**Comparado contra:** `vision-producto/index.html`, `investor_pdf/Vendi_Inversores.pdf`, `docs/plan-tecnico.md` (v2, ADR-001..004), `docs/monetizacion-web.md`

---

## 1. Qué valor SUMA el documento del socio (adoptar)

| # | Aporte | Detalle | Acción sugerida |
|---|---|---|---|
| 1 | **TAM/SAM/SOM cuantificado** | TAM $135M/año (675K negocios retail × $200), SAM $60M (250K negocios urbanos), SOM Y1 $480K → Y3 $3.6M | Llena el hueco explícito de nuestro PDF de inversores. **Verificar cifras DANE antes de usar** |
| 2 | **Modelo financiero a 3 años** | Ingresos por línea, costos por categoría, break-even mes 6–7, margen bruto 85–87%, CAC $45→$24, LTV/CAC 6x→11.3x, payback 3 meses | Es nuestro mayor gap. Adoptar la estructura; revisar supuestos (ver §4) |
| 3 | **Canal GTM institucional** | CCB (450K empresas), CCM (200K), FENALCO (65K) con mecánica concreta: beneficio de membresía, talleres co-brandeados, revenue share 5–8%, dashboard de datos para el gremio | Fusionar con nuestro GTM de agentes/WhatsApp — son canales complementarios (institucional arriba, comunitario abajo) |
| 4 | **Fiado (crédito a clientes)** | Ventas a crédito con recordatorios de vencimiento | **Falta crítica en nuestro MVP** — el fiado es el corazón de la tienda de barrio. Entra como módulo core (y exige un CRM mínimo de clientes) |
| 5 | **Pipeline de escaneo en 3 capas** | Barcode on-device <100ms → OCR local <500ms → VLM cloud 4–8s solo para recibos complejos/manuscritos; "device-first, cloud-fallback" | Adoptar tal cual en nuestra capa IA (mejora costo, latencia y offline) |
| 6 | **Tier Light de ultra-bajo costo** | $4.99/mes (~$19.500 COP) como puente free→pago + trial de 1 mes del tier Pro sin tarjeta | Incorporar a `monetizacion-web.md`: Light como escalón de conversión |
| 7 | **Casos de uso con personas** | Don Carlos (tienda), Laura (boutique), Roberto (ferretería), Andrea (minimercado ×3) | Excelente material narrativo para el PDF de inversores y la página de visión |
| 8 | **Nuevas líneas de ingreso** | Add-on packs (chats IA extra, empleados, tiendas), comisión de publicidad Meta Ads 8–12%, servicios de valor agregado | Evaluar para fase 3; el módulo de marketing/CRM (RFM) queda como candidato de roadmap |
| 9 | **Fundraising concreto** | $150K semilla con uso de fondos (30% marketing, 10% infra+IA, 25% G&A, 35% reserva), pre-Series A opcional, exit (Mercado Libre, Rappi, Nubank) | Alimenta la sección 9 de nuestro PDF que hoy tiene placeholders |

## 2. En qué DIFIERE (conflictos a decidir como socios)

| Tema | Documento del socio | Nuestra documentación (ADRs firmados) | Comentario |
|---|---|---|---|
| **Stack móvil** | Nativo puro: Swift/SwiftUI + Kotlin/Compose + KMP (60–70% reutilización) | Angular 21 + Capacitor (ADR-001) | Conflicto directo. Su argumento (retención nativa, capacidades del sistema) aplica igual a Capacitor, que ES app nativa con shell WebView + plugins. Nuestro stack da 1 codebase vs 2 + KMP |
| **Backend** | Microservicios en Alibaba Cloud (ACK) | FastAPI monolito modular + RabbitMQ (ADR-002) | Para un MVP, microservicios en K8s es sobre-ingeniería; FastAPI modular migra a servicios cuando duela |
| **Proveedor IA** | Dify + Qwen (Alibaba Cloud, US West) | Capa `AIProvider` multi-proveedor, Gemini 2.5 Flash primario | Qwen-VL es buena opción de costo para recibos; nuestra abstracción permite usarlo como proveedor adicional sin casarnos. Dify añade una capa de orquestación que FastAPI + function calling cubre con menos piezas |
| **Identidad** | Auth en API Gateway de Alibaba | Keycloak 26 (Organizations + passkeys) | Sin Keycloak pierden passkeys (login por huella — clave para el segmento) y multi-tenancy resuelto |
| **Cobro de suscripción** | **Por App Store/Google Play (90%→60% de ingresos)** — proyecta **$617K USD en comisiones a 3 años** ($404K solo en Y3) | **Web-first, ADR-004 firmado** (~3% pasarela local: PSE, Nequi, Efecty) | **La diferencia más costosa del documento.** Su propio modelo muestra el problema: la comisión de tienda es su 3er mayor costo a 3 años. Además el billing de tienda no soporta cómo paga el tendero (Efecty, Nequi, PSE) |
| **Residencia de datos** | Alibaba US West (única región) | Multi-región federada por país (ADR-003) | Su opción es más simple de operar al inicio; la nuestra cumple residencia por diseño y escala a MX/PE |
| **Facturación DIAN** | Solo en tier Premium, mencionada sin proveedor | Factus API como fase 2 para todos los pagos | Nuestro enfoque la convierte en palanca de monetización, no en feature de lujo |
| **Alcance MVP** | Incluye finanzas (P&L, cash flow), CRM y marketing desde Y1 | Sin contabilidad/tesorería; Caja simple | Matiz: su "Financial Management" es P&L + flujo de caja simple, NO contabilidad formal — compatible con nuestra decisión si se acota. CRM mínimo se vuelve necesario de todos modos por el fiado |
| **Equipo** | Fundador técnico hace todo gratis (costo R&D = $0) | Equipo con 50% de fondos a ingeniería | Modelos de costo no comparables directamente; el suyo concentra riesgo de persona única (él mismo lo reconoce) |

## 3. Qué le FALTA a lo nuestro respecto al documento del socio (gaps a cerrar)

1. **Modelo financiero a 3 años con unit economics** — el mayor gap; nuestro PDF tiene placeholders en la sección de inversión.
2. **Módulo de fiado/cartera de clientes** con recordatorios — ausente del MVP y es funcionalidad core de barrio (arrastra consigo un CRM mínimo de clientes).
3. **Canal GTM institucional** (cámaras de comercio y FENALCO) con mecánica de revenue share — nuestro GTM era solo comunitario/digital.
4. **Trial de 1 mes del plan Pro** y **tier Light ~$5** como escalón de conversión free→pago.
5. **Pipeline de escaneo device-first en 3 capas** (nuestro diseño mandaba todo a la nube).
6. **Multi-empleado con roles y permisos** (cajero vs almacenista vs dueño) — nosotros solo decíamos "hasta 3 usuarios".
7. **Forecast de flujo de caja a 30 días** — extensión natural de Caja + reglas IA.
8. **Personas y casos de uso narrativos** para material comercial e inversores.
9. **Estrategia de fundraising detallada** (montos, uso de fondos, rondas, exit).

## 4. Alertas sobre las cifras del socio (verificar antes de adoptar)

- **Conversión free→pago del 20–23%** es 4–10× el benchmark típico de freemium SaaS (2–5%); con tier Light de $5 quizá llegue a 8–12%, pero 20% es muy optimista — el break-even mes 6–7 depende de este número.
- **Cifras de mercado sin fuente verificable**: "1.93M PYMEs", "28% facturación electrónica (DANE 2024)", "<10% ERP", "75% smartphones" — plausibles pero hay que confirmarlas con DANE/CCB antes de ponerlas ante inversores.
- **Churn 5%/mes con LTV de 18 meses** es coherente aritméticamente, pero 5%/mes en micro-negocios (alta mortalidad empresarial) puede ser optimista.
- **Comisión blended 15%→23%** de tiendas: correcta en dirección, y precisamente por eso ADR-004 (web-first) le ahorraría a su modelo ~$550K en 3 años (comisión tienda vs ~3% pasarela).
- **El documento está en inglés** — para inversores LATAM conviene versión en español.

## 5. Recomendación de fusión

**Adoptar del socio:** TAM/SAM/SOM (verificado), estructura financiera 3 años, canal institucional CCB/CCM/FENALCO, fiado+CRM mínimo en el MVP, pipeline VLM de 3 capas, tier Light + trial 1 mes, personas/casos de uso, plan de fundraising.

**Mantener de lo nuestro (justificado):** Angular 21 + Capacitor (ADR-001 — una codebase, mismas capacidades nativas), FastAPI + RabbitMQ (ADR-002), Keycloak 26 (passkeys para usuarios no técnicos), **web-first billing (ADR-004 — le ahorra ~$550K a su propio modelo financiero y habilita Nequi/Efecty)**, Factus para DIAN, multi-región federada (ADR-003), y la regla de oro compartida: IA narra, el código determinista decide (ambos documentos coinciden aquí).

**A negociar entre socios:** Qwen/Dify como proveedor adicional dentro de `AIProvider` (especialmente Qwen-VL para recibos manuscritos — su punto más fuerte), y si el alcance Y1 incluye el módulo de marketing Meta Ads o queda para fase 3.
