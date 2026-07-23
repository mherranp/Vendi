# Vendi — Plan técnico de construcción (v2)

> ⚠️ **Este documento quedó consolidado en `docs/plan-maestro.md` (v1.0, 21-jul-2026), que es la fuente canónica.** Aquí permanece el detalle técnico de ADR-001..004.

**Fecha:** 20 de julio de 2026 · **Estado:** v2 — incorpora ADR-001, ADR-002, ADR-003 (firmados por el equipo)
**Stack:** Python + FastAPI · Angular 21 (PWA + Material) · Keycloak 26 · Capacitor · PostgreSQL · RabbitMQ + Redis

---

## 0. Registro de decisiones (ADR)

| ADR | Decisión | Fecha | Estado |
|---|---|---|---|
| ADR-001 | **Capacitor como empaquetado nativo desde el inicio** (no TWA→Capacitor) | 2026-07-20 | ✅ Firmado |
| ADR-002 | **RabbitMQ como broker de tareas + Redis como cache** (evaluados RabbitMQ vs Redis-as-queue) | 2026-07-20 | ✅ Firmado |
| ADR-003 | **Arquitectura multi-región desde el diseño** (federada por país) | 2026-07-20 | ✅ Firmado |
| ADR-004 | **Cobro de suscripciones web-first** (sin venta dentro de la app; pasarela propia) | 2026-07-20 | ✅ Firmado |
| ADR-005 | Telemetría/analytics del POS (PostHog self-hosted vs gestionado) | — | ⏳ Abierto |

---

## 1. Veredicto del stack

| Componente | Elección | Veredicto | Notas |
|---|---|---|---|
| Backend | **Python + FastAPI** | ✅ Aprobado | Ecosistema IA nativo (LLMs, Whisper, visión), OpenAPI automático, async para I/O intensivo |
| Frontend | **Angular 21 PWA + Material** | ✅ Aprobado | Zoneless, signals estables, standalone por defecto, `@angular/service-worker`, Material 3 |
| Empaquetado móvil | **Capacitor (ADR-001)** | ✅ Firmado | Un solo path de binarios para Play Store y App Store; acceso nativo a impresora Bluetooth, escáner, push y biometría desde el MVP |
| IdP | **Keycloak 26** | ✅ Aprobado | 26.6.4 actual; Organizations (multi-tenancy GA) + passkeys soportados. Un despliegue por región (ADR-003) |
| Base de datos | **PostgreSQL 16/17** | ✅ Aprobado | Row-Level Security para aislamiento multi-tenant; una primaria por región |
| Broker de tareas | **RabbitMQ (ADR-002)** | ✅ Firmado | Celery con broker RabbitMQ; DLQ para reintentos fiscales (Factus/DIAN) |
| Cache | **Redis** | ✅ Aprobado | Cache, rate limiting, sesiones de sync; NO como cola principal (ver ADR-002) |

**Conclusión general:** stack viable y coherente. Las tres ADRs quedan incorporadas abajo con sus consecuencias completas.

---

## 2. Arquitectura general (multi-región federada — ADR-003)

Modelo: **una región autónoma por país**, con el tenant "anclado" a su región de origen. No hay replicación cruzada de datos operativos en v1 — un tendero colombiano nunca necesita datos de México. Esto simplifica enormemente la consistencia y cumple residencia de datos por diseño (Ley 1581 Colombia, LFPDPPP México, Ley 29733 Perú).

```
                    ┌────────────────────────────┐
                    │  Capa global (compartida)  │
                    │  · DNS geolocalizado       │
                    │    co.app.vendi / mx. / pe.│
                    │  · CI/CD + IaC (Terraform) │
                    │  · Registry de contenedores│
                    │  · Observabilidad central  │
                    │  · Analytics (fase 3,      │
                    │    datos anonimizados)     │
                    └─────────────┬──────────────┘
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
│  REGIÓN CO (v1)   │  │  REGIÓN MX (f3)   │  │  REGIÓN PE (f3)   │
│ Stack completo:   │  │  Misma plantilla  │  │  Misma plantilla  │
│ · FastAPI         │  │  IaC, mismo       │  │  · SAT vía        │
│ · PostgreSQL+RLS  │  │  código, config   │  │    proveedor local│
│ · RabbitMQ+Redis  │  │  por región       │  │                 │
│ · Keycloak 26     │  │  · SAT (CFDI)     │  │                 │
│   (realm CO)      │  │                 │  │                 │
│ · Factus (DIAN)   │  │                 │  │                 │
└────────▲──────────┘  └───────────────────┘  └───────────────────┘
         │ HTTPS/JSON · JWT (OIDC)
┌────────┴──────────────────────────────────────────────────────┐
│  App — Angular 21 (PWA + Material 3) + Capacitor (ADR-001)    │
│  ├─ IndexedDB (Dexie) → POS offline-first                     │
│  ├─ Service Worker → cache + cola de sincronización           │
│  └─ Plugins nativos: impresora BT, escáner, push, biometría   │
└───────────────────────────────────────────────────────────────┘
```

**Consecuencias de multi-región desde el inicio (ADR-003):**
- **Config por región, código único:** la app resuelve su región por subdominio (`co.`, `mx.`, `pe.`) y el onboarding asigna el tenant a la región del país declarado. Variables de entorno/IaC parametrizan endpoints de facturación fiscal por país (Factus en CO, proveedor SAT en MX).
- **Keycloak: un despliegue independiente por región** (no clustering cross-región — es la parte más frágil de Keycloak y no aporta aquí; el usuario no viaja entre países). Realm exportado como código garantiza configuración idéntica.
- **Sin active-active:** cada región opera y escala sola. El failover entre regiones NO es objetivo en v1 (RPO/RTO se cubren con backups regionales cifrados).
- **Capa global delgada:** CI/CD, IaC, observabilidad central y (fase 3) exportación de eventos anonimizados a un warehouse para analytics regional y dataset CPG.
- **Costo:** la plantilla de región nueva se levanta con IaC en días, no meses — pero el MVP solo opera la región CO.

**Multi-tenancy:** cada negocio = una *Organization* de Keycloak 26 + `tenant_id` en todas las tablas. Aislamiento en dos capas: scoping en la API y Row-Level Security en PostgreSQL.

**Offline-first (crítico):** la venta NUNCA depende del internet. Catálogo, stock y caja viven en IndexedDB (Dexie.js); cada venta se guarda local primero y entra a cola de sincronización (Background Sync + reintento). Conflictos: *last-writer-wins* por documento con auditoría; el stock se reconcilia por deltas, no valores absolutos.

---

## 3. ADR-001 — Empaquetado móvil: Capacitor desde el inicio

**Contexto:** se evaluó TWA (Trusted Web Activity, vía Bubblewrap) como camino inicial a Play Store con migración posterior a Capacitor.

**Decisión:** **Capacitor como empaquetado único desde el MVP**, para Play Store y App Store.

**Justificación:**
- **Periféricos de POS desde el día uno:** impresora térmica Bluetooth (ticket físico), escáner de código de barras por cámara, lector NFC futuro. La web sola no resuelve bien estos casos; Capacitor sí (plugins nativos).
- **App Store viable:** Apple rechaza PWAs puras (Guideline 4.2, vigente en 2026), pero un binario Capacitor con funcionalidad nativa real (escáner, biometría, push, impresión) cumple el estándar de "más que un sitio reempaquetado".
- **Un solo path de release:** evita la migración TWA→Capacitor a mitad de camino (cambio de binario, keystore y listing).
- **La PWA sigue existiendo:** la misma build Angular se sirve como PWA instalable desde el navegador — canal de adquisición sin fricción de tienda ni review.

**Consecuencias:**
- CI/CD debe construir binarios Android (AAB) e iOS (IPA): runners con Android SDK y macOS/Xcode (p.ej. GitHub Actions `macos-latest`, o EAS/Bitrise/Appflow).
- Costos de tiendas desde el inicio: Google Play **$25 únicos** + Apple Developer **$99/año**.
- Ciclos de review de tienda en cada release nativa — mitigado porque la lógica vive en la web layer y las actualizaciones de contenido no requieren resubir binario (solo cambios de plugins/config nativa).
- El service worker de la PWA y el WebView de Capacitor deben coordinar estrategia de cache para no duplicar lógica offline: la fuente de verdad offline es IndexedDB, no el cache del SW.
- Push: FCM (Android) + APNs (iOS) vía plugin de Capacitor, unificado detrás del servicio de notificaciones del backend.

---

## 4. ADR-002 — Cola de tareas: RabbitMQ + Redis

**Contexto:** se pidió evaluar RabbitMQ vs Redis como infraestructura de colas.

**Decisión:** **RabbitMQ como broker de tareas (con Celery); Redis queda para cache, rate limiting y estado efímero.**

**Comparativa:**

| Criterio | RabbitMQ | Redis (como cola) |
|---|---|---|
| Durabilidad de mensajes | Persistencia + confirmaciones (publisher confirms) | Débil sin AOF estricto; pérdida posible ante reinicio |
| Routing | Exchanges topic/direct: por tipo de tarea, por región, por tenant | Listas/streams simples, sin routing rico |
| Reintentos y DLQ | Dead-letter exchanges nativos — crítico para webhooks fiscales (Factus/DIAN) | Manual |
| Mensajes diferidos | Delayed message plugin (reintentos con backoff) | Manual |
| Carga operativa | Un servicio más | Reutiliza Redis existente |
| Fit con Celery | Broker natural y mejor soportado | Soportado pero con caveats de garantías |

**Por qué importa aquí:** las operaciones fiscales (envío de factura a Factus, recepción de validación DIAN, reintentos ante caída del proveedor) y los trabajos de IA (foto de factura, recomendaciones batch nocturnas, push) no pueden perderse silenciosamente. RabbitMQ con DLQ y backoff diferido es la respuesta correcta para ese perfil de riesgo.

**Consecuencias:**
- Topología inicial de exchanges: `ai.jobs` (voz/visión/asistente), `fiscal.jobs` (Factus/DIAN), `notify.jobs` (push/email), `sync.jobs` (sincronización offline), cada uno con su DLQ.
- Redis NO se elimina: cache de catálogo, rate limiting por tenant, locks de sincronización.
- En cada región, un clúster RabbitMQ propio (ADR-003): los jobs fiscales nunca cruzan fronteras.

---

## 5. Modelos de IA por caso de uso

Principios: (a) **las recomendaciones de negocio nacen de reglas deterministas sobre datos propios** y el LLM solo las narra en lenguaje simple — nunca al revés (costo, latencia, alucinaciones); (b) **capa de abstracción multi-proveedor** (`AIProvider` en FastAPI) desde el día uno.

| Caso de uso | Modelo recomendado | Alternativa | Costo aprox. (investigado jul 2026) |
|---|---|---|---|
| Registro por voz ("vendí dos arroces") → venta estructurada | **Gemini 2.5 Flash** (audio nativo: transcribe + estructura en una llamada, buen español) | faster-whisper (self-hosted) + LLM pequeño | Desde ~$0.06/1M tokens entrada; multimodal (texto, imagen, audio, video) |
| Foto de factura de proveedor → compras + stock | **Gemini 2.5 Flash** (visión, mismo proveedor) | GPT-5 mini (visión) | Ver arriba |
| Asistente conversacional | **Gemini 2.5 Flash** con function calling contra la API propia | Claude Haiku 4.5 ($1/$5 por 1M) o GPT-5 mini (~$0.25/$2 por 1M) | — |
| Recomendaciones diarias proactivas | **Motor de reglas** (rotación, stock bajo, horas pico, fugas de caja) + LLM solo para redactar | — | Marginal |
| Matching de productos (catálogo, dedupe) | **Embeddings** (Gemini/OpenAI) + pgvector | — | Muy bajo |
| Fallback configurado | **GPT-5 mini** | Claude Haiku 4.5 | $0.25/$2 por 1M tokens |

**Por qué Gemini 2.5 Flash primario:** un solo proveedor cubre voz + visión + texto, contexto de 1M tokens, ~70% más barato que Claude Haiku 4.5 en entrada, y evita un pipeline STT separado en el MVP.

**Estimación de costo IA por negocio activo/mes (hipótesis a validar en piloto):** ~60 registros de voz + ~4 fotos + ~30 consultas ≈ **USD $0.05–0.20 por negocio/mes**. Contra un plan de $20.000–$40.000 COP, negligible (<2% del ARPU).

**Privacidad:** los datos de venta no se envían crudos al LLM; el asistente consulta agregados vía function calling. Los jobs de IA corren en la región del tenant (ADR-003) y los payloads a proveedores externos se minimizan y anonimizan. Cumplimiento Ley 1581 (Habeas Data) documentado desde el diseño.

---

## 6. Keycloak 26 — decisión y trade-offs

**A favor:** Organizations (multi-tenancy nativo: cada negocio = organización, invitación de usuarios, dominios de email), passkeys soportados en 26.x (login con huella/Face ID — enorme para usuarios no técnicos), OIDC/OAuth2 + SAML, sin costo por usuario (Apache 2.0), Quarkus = arranque en segundos.

**Con ADR-003 (multi-región):** un despliegue de Keycloak **independiente por región**, cada uno con su PostgreSQL. No se intenta clustering cross-región (la parte más frágil de Keycloak y sin beneficio aquí). El realm se exporta como código (keycloak-config-cli / Terraform provider) para garantizar configuración idéntica entre regiones y recuperación ante desastre.

**Trade-offs aceptados:** ~2–4 GB RAM por instancia regional, un servicio JVM más que monitorear y parchear; fijar tag exacto en producción (`26.6.4`), nunca `latest`.

**Integración:** app Angular con Authorization Code + PKCE (`angular-oauth2-oidc` o plugin Capacitor para redirect nativo); FastAPI valida JWT vía JWKS del realm regional.

**Alternativas descartadas:** Auth0/Clerk/Firebase Auth (costo por MAU — incompatible con freemium masivo), Supabase Auth (sin Organizations ni passkeys maduros).

---

## 7. Publicación en tiendas (actualizado por ADR-001)

### Google Play (Android)
Binario **Capacitor AAB** (Android Studio / Gradle en CI). Cuenta $25 únicos + verificación de identidad. Ficha: nombre ≤30 caracteres, descripción ≤80, 2–8 screenshots, icono 512×512, feature graphic 1024×500, política de privacidad sin login, clasificación de contenido y formulario de seguridad de datos. Revisión 24–72 h. Al ser app nativa (no TWA), no aplica el requisito de Digital Asset Links ni las reglas de calidad TWA; sí aplican las políticas estándar de funcionalidad mínima — cubiertas por el POS real offline.

### Apple App Store (iOS)
Binario **Capacitor IPA** (Xcode en CI macOS). Apple Developer **$99/año**. Para cumplir Guideline 4.2, la app incluye funcionalidad nativa genuina desde el MVP: escáner de códigos con cámara, biometría (Face ID/huella vía passkey + plugin local), impresión Bluetooth y push APNs. TestFlight para el piloto iOS.

### PWA (canal propio)
La misma build se publica como PWA instalable (manifest + service worker) — canal de adquisición directo sin fricción de tienda, especialmente útil para el piloto y para usuarios que llegan por WhatsApp/TikTok.

### Cobro de suscripciones: modelo web-first (ADR-004)

**Problema:** vender la suscripción dentro de la app obliga a usar el billing de la tienda y a pagar comisión (Google Play: 15% estándar para desarrolladores pequeños en "resto del mundo" — Colombia mantiene el esquema legacy hasta sept-2027; desde jun-2026 en EE.UU./Reino Unido/EEE hay tarifa de servicio 10% en suscripciones + 5% de billing si se usa Play Billing. Apple: 30%, o 15% con Small Business Program).

**Decisión:** **la suscripción NO se vende dentro de la app; se vende en un portal web propio.** La app es gratuita con funcionalidad real (plan gratis) y actúa como compañera de una herramienta web paga.

**Base legal/políticas (verificada jul 2026):**
- **Apple — Guideline 3.1.3(f):** las apps gratuitas que son "companion de una herramienta web paga" (VOIP, cloud storage, email, web hosting) NO requieren IAP, siempre que no haya compra dentro de la app NI llamados a la acción hacia la compra externa. Es el modelo de Slack, Notion y Figma.
- **Google Play:** Play Billing solo es obligatorio cuando se venden bienes digitales *dentro* de la app; si no se vende nada in-app, no aplica.
- **Anti-steering:** en storefronts fuera de EE.UU./UE (Colombia incluida) la app NO puede enlazar ni anunciar el checkout web. La comunicación de venta se hace por canales propios fuera de la app (WhatsApp, email, agentes de barrio) — expresamente permitido por Apple.

**Condiciones para que el modelo pase revisión:**
1. El plan gratis debe ser genuinamente útil (ventas + inventario básico) — una app que es solo un login-wall se rechaza como "thin client" (Guideline 4.2). Nuestro freemium lo cubre por diseño.
2. Cero enlaces/CTAs de compra dentro de la app en storefronts no elegibles. En la app solo: "Gestionar mi suscripción" (permitido) sin publicidad de precios.
3. No degradar artificialmente el plan gratis para empujar a la web.

**Ventaja adicional decisiva para el segmento:** el billing de las tiendas no soporta cómo paga un tendero colombiano. El portal web con pasarela local (**Wompi, Bold o Mercado Pago**) habilita PSE, Nequi, Daviplata, tarjetas y **efectivo (Efecty/Baloto)** — imprescindible para este mercado — con costo de procesamiento ~3% en vez de 15–30%.

**Lo que asumimos a cambio:** facturación propia de la suscripción (irónicamente, vía Factus), IVA de servicios digitales en Colombia, reembolsos, dunning/reintentos de cobro y portal de gestión de cuenta. Beneficios colaterales: identidad de suscriptor unificada entre plataformas, control total de ofertas y cancelaciones, y cero dependencia de los cambios de política de las tiendas.

→ **Diseño detallado de implementación:** ver `docs/monetizacion-web.md` (flujo end-to-end, planes, portal de pago, webhooks→entitlements, ciclo de vida, guion de venta por WhatsApp).

---

## 8. Roadmap técnico por fases (actualizado)

**Fase 0 — Fundaciones (sem 1–4):** monorepo (FastAPI + Angular + Capacitor), CI/CD con build de binarios (Android primero), Keycloak 26 región CO (realm como código + Organizations + passkeys), PG + RLS, RabbitMQ + Redis, **compose de producción versionado + `deploy.yml` + runbook de la VM**, despliegue staging. *Entregable:* login con passkey, CRUD de tenant, pipeline que produce AAB de prueba.

> **Corrección de la Etapa 5 (2026-07-23).** Esta línea decía «IaC parametrizado
> por región (ADR-003)» como entregable de Fase 0, y el plan maestro §7 lo
> repetía. **Terraform se difiere a Fase 2** (ver `docs/adr/adr-003-multi-region.md`):
> con una sola región y un solo servidor, un módulo de Terraform es coste de
> mantenimiento sin ningún despliegue que lo ejercite, y el primer uso real
> —levantar la región MX— cae en Fase 3. La reproducibilidad interina de Fase 0
> la dan `infra/docker-compose.override.prod.yml` versionado,
> `.github/workflows/deploy.yml` y el runbook de despliegue en la VM. La
> parametrización POR REGIÓN del diseño (§3) no cambia: sigue siendo la
> arquitectura; lo que se difiere es escribirla en Terraform.

**Fase 1 — MVP Colombia (sem 5–13):** catálogo + POS offline-first, inventario con alertas, compras, caja, asistente IA v1 (consultas + recomendaciones por reglas narradas), registro por voz (Gemini), escáner de códigos, push FCM. *Entregable:* piloto 50–100 tiendas; app en Play Store (track cerrado → producción); PWA pública; TestFlight iOS interno.

**Fase 2 — Formalización (mes 4–7):** portal web de suscripción con pasarela local (PSE/Nequi/efectivo — ADR-004), Factus sandbox → producción (facturación DIAN de clientes + autofacturación de la suscripción), foto de factura de compra, impresora Bluetooth de tickets, App Store pública, push APNs, reportes IA avanzados.

**Fase 3 — Escala LATAM (mes 8+):** segunda región (México, SAT vía proveedor local — la plantilla IaC de ADR-003 se estrena aquí), Perú (SUNAT), pagos (links PSE/Nequi/Bre-B), embeddings de catálogo, warehouse global de analytics anonimizados.

## 9. Riesgos técnicos y mitigación (actualizado)

| Riesgo | Mitigación |
|---|---|
| Sync offline con conflictos de stock | Deltas + auditoría; reconciliación al cierre de caja; tests de caos de conectividad |
| Rechazo de Apple (Guideline 4.2) | Capacitor con features nativas reales desde MVP (ADR-001); PWA como canal alterno |
| Costo operativo de Keycloak ×N regiones | Una instancia por región, realm como código, runbook; no clustering cross-región |
| Complejidad operativa multi-región temprana | MVP opera SOLO región CO; la multi-región es diseño + IaC, no despliegue prematuro |
| Pérdida de jobs fiscales/IA | RabbitMQ con DLQ + backoff (ADR-002); alertas sobre DLQ no vacía |
| Alucinaciones del LLM en recomendaciones | Reglas deterministas como fuente de verdad; LLM solo narra; evals con casos del piloto |
| Duplicación de lógica offline SW vs Capacitor | Fuente de verdad única: IndexedDB; SW solo cachea assets de la app |
| Dependencia de un proveedor de IA | Interfaz `AIProvider` + fallback (Gemini → GPT-5 mini) |
| Rechazo de tienda por "thin client" o steering | Plan gratis genuinamente útil; cero CTAs de compra in-app (ADR-004); venta por canales propios |
| Menor conversión de checkout web vs IAP nativo | Venta asistida por WhatsApp/agentes; pago en efectivo (Efecty) y Nequi, métodos que el billing de tienda no soporta |

---

### Fuentes consultadas (julio 2026)

- Angular 21 en producción (zoneless, signals, standalone, PWA, Material 3) — federicocalo.dev "Modern Angular" (feb–mar 2026).
- Publicación en Google Play (TWA/Bubblewrap, política 4.3) y App Store (Guideline 4.2, Capacitor) — saastostore.com (ene 2026), mobiloud.com (may 2026), freeCodeCamp (ago 2025), zenn.dev State of PWA 2026.
- Keycloak 26.6.4 (Quarkus, Java 21, Organizations, passkeys) — tech-insider.org (jun 2026), CNCF blog, skycloak.io.
- Precios de modelos IA — apis.you (2026): Gemini 2.5 Flash desde $0.06/1M entrada, Claude Haiku 4.5 $1/$5, GPT-5 mini ~$0.25/$2 (benchlm.ai, jun 2026).
- Políticas de cobro en tiendas — Apple App Review Guideline 3.1.3(f) (companion apps de herramientas web pagas); forasoft.com "How to Legally Avoid the 30% Apple App Store Commission in 2026" (ene 2026); ecorpit.com "Google Play fee split 2026" (jul 2026); funnelfox.com (abr 2026).
