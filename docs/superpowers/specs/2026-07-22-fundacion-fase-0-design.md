# Vendi — Fundación de Fase 0 (diseño)

**Fecha:** 22 de julio de 2026 · **Estado:** Diseño aprobado, pendiente de plan de implementación
**Decide:** cómo se construye la fundación técnica de Vendi a partir de BaseSaaS
**Fuente canónica de producto y negocio:** `docs/plan-maestro.md` — este documento no la contradice, la implementa

---

## 1. Contexto

El repositorio está en Fase 0 apenas iniciada: `backend/`, `infra/` y `scripts/` están
vacíos; el frontend tiene cuatro aplicaciones Angular 21 y cinco librerías, todas en
andamiaje. No hay código de dominio.

Existe un activo relevante fuera del repositorio: **BaseSaaS**, un esqueleto SaaS
multi-tenant maduro (44.500 líneas de Python, 99 archivos de test, 11 specs E2E, 33
runbooks, stack docker-compose completo), escrito íntegramente por el mismo autor. Su
stack coincide casi exactamente con el de Vendi: FastAPI, Angular 21, Keycloak 26,
PostgreSQL 17, RabbitMQ 4, Redis 7, Material 3.

La pregunta que este documento responde: **qué se toma de BaseSaaS, qué se reescribe y
qué se descarta.**

## 2. Alcance

Este spec cubre **solo la fundación de Fase 0**. El resto del trabajo se descompone en
specs propios porque cada uno tiene densidad suficiente para merecerlo:

| Sub-proyecto | Contenido | Cuándo |
|---|---|---|
| **1. Fundación Fase 0** ← este spec | Tenancy, layout del repo, cosecha de BaseSaaS, infraestructura, CI, documentación de desarrollador | Ahora |
| 2. Autenticación multi-superficie | OIDC nativo en Capacitor, login offline, cambio rápido de usuario, passkeys, almacenamiento seguro de tokens | Inmediatamente después — bloquea el POS |
| 3. Modelo de datos y API del MVP | ERD de los siete módulos, contrato OpenAPI, sincronización por deltas | Tras 1 |
| 4. Motor offline-first | IndexedDB/Dexie como fuente de verdad, cola de sincronización, reconciliación de stock | Tras 3 |
| 5. Monetización | `PaymentProvider`, entitlements, webhooks de pasarela | Fase 2 (ya especificado en `docs/monetizacion-web.md`) |

## 3. Decisión de fundación: cosecha quirúrgica

**Vendi forkea sin relación con BaseSaaS.** No hay upstream, no hay cherry-pick, no hay
coordinación. Vendi se lleva lo que sirve y diverge.

Se descartaron dos alternativas:

- **Fork completo y refactorizar in-place.** Levanta el stack el mismo día, pero arrastra
  ~40 % de código que Vendi nunca usará y obliga a operar el cambio de tenancy a corazón
  abierto sobre 36 archivos en funcionamiento.
- **Fork sin tocar tenancy, migrar tras el piloto.** Con 50–100 tiendas funcionaría. Se
  descarta porque migrar realms de Keycloak invalida las passkeys ya enroladas y obliga a
  re-enrolar a cada usuario — inaceptable en un segmento de baja alfabetización digital.

El activo real de BaseSaaS no es `platform-service`, que es donde Vendi más diverge, sino
la librería transversal, la infraestructura y los runbooks. Ahí el acoplamiento al modelo
de tenancy está confinado a seis archivos.

## 4. Modelo de tenancy

### 4.1 Base de datos: RLS en un schema único por región (ADR-013)

BaseSaaS usa **schema por tenant**. Para Vendi es el modelo equivocado: schema-per-tenant
obliga a correr Alembic una vez por tienda, y el objetivo de Vendi son decenas de miles de
negocios freemium, no las decenas o cientos de tenants B2B para los que BaseSaaS fue
diseñado.

Un schema por región. Toda tabla de negocio lleva `tenant_id UUID NOT NULL`, columna que se
añade a `TenantModel` — el mixin que hoy solo aporta clave primaria y timestamps.

```sql
ALTER TABLE ventas ENABLE ROW LEVEL SECURITY;
ALTER TABLE ventas FORCE ROW LEVEL SECURITY;   -- el owner de la tabla tampoco escapa
CREATE POLICY tenant_isolation ON ventas
  USING (tenant_id = current_setting('vendi.tenant_id')::uuid);
```

**Dos roles de conexión.** `vendi_app` sin `BYPASSRLS` es el que usa la API; `vendi_platform`
con `BYPASSRLS` queda reservado para `vendi-admin` y los jobs de plataforma. Separar los
roles evita el patrón habitual de "la policy me estorba, conecto como superusuario".

**Propagación del tenant.** El middleware ejecuta `SET LOCAL vendi.tenant_id = '<uuid>'`
dentro de la transacción del request. `SET LOCAL` y no `SET`: el valor muere con la
transacción y no se filtra entre requests que comparten conexión del pool.

**Red de seguridad.** Se replica el patrón que BaseSaaS ya aplica a `search_path`: un
listener en el checkout del pool resetea `vendi.tenant_id`, de modo que un handler que
olvide el `SET LOCAL` no herede el tenant del request anterior. Con la variable ausente la
policy no hace match y la consulta devuelve cero filas: **falla cerrado**, que es la
dirección correcta del error.

Consecuencias operativas:

- Alembic corre **una vez por región**, no una vez por tienda.
- Provisionar un tenant es un `INSERT`, no DDL — milisegundos en vez de segundos.
- Desaparece el problema `create_all()` vs. Alembic que BaseSaaS documenta en
  `orm-alembic-sync.md`; ese runbook no se porta.

### 4.2 Identidad: un realm por región, cada negocio una Organization (ADR-014)

Realm `vendi-co`. Cada negocio es una Organization de Keycloak 26; el `tenant_id` se resuelve
del claim de organización del token.

BaseSaaS usa **realm por tenant**, que para Vendi falla por dos motivos independientes:

1. **Escala.** Keycloak degrada mucho antes de los 10.000 realms.
2. **La app móvil.** Con realm-per-tenant, `vendi-app` tiene un problema de huevo y gallina:
   para autenticar necesita saber a qué realm ir, y para saber el realm necesita saber quién
   es el usuario. Se resolvería con una pantalla previa de "¿cuál es tu negocio?", fricción
   inaceptable para un cajero de tienda de barrio. Con un realm por región hay un solo
   endpoint de login y la organización se resuelve del token.

**Sucursales dentro del tenant.** Los roles (`dueño`, `cajero`, `almacenista`) son roles de
realm, no por organización. Esto obliga a una decisión de modelado que se toma
explícitamente: **un negocio con varias tiendas es un tenant con varias sucursales, no varios
tenants.** Es lo que pide la persona "Andrea, minimercado ×3" del plan maestro —comparativo
multi-tienda y compras consolidadas— y evita el caso de un usuario con roles distintos en
organizaciones distintas, que Keycloak no modela bien.

**A verificar antes de implementar:** el nombre exacto del claim de organización y el scope
requerido en Keycloak 26.6.4.

## 5. Backend

### 5.1 Layout (ADR-016)

```
backend/
  libs/vendi-core/        ← librería transversal cosechada de base_saas
  services/api/           ← monolito modular FastAPI, todos los módulos de negocio
  services/worker/        ← OutboxDispatcher + JobScheduler + consumidores IA/fiscal
```

Sin `realtime-service` ni `storage-service` como servicios en el MVP: el push va por FCM y no
por WebSocket, y el almacenamiento de fotos entra como módulo dentro de `api` usando
`vendi_core.storage`. Se sigue el árbol de decisión del propio BaseSaaS: un módulo es lo más
barato hasta que el contexto acotado duela lo suficiente para extraerlo.

### 5.2 Cosecha de `base_saas` (6.100 LOC)

| Categoría | LOC aprox. | Contenido |
|---|---|---|
| **Sin cambios** | 2.400 | `middleware` (correlation-id, error handler, security headers, secret redactor, api-version, client-ip), `audit`, `storage`, `messaging` (outbox transaccional), `tracing`, `config/secrets`, `files`, `events`, `errors`, `cache`, `logging`, `models` |
| **Con adaptación** | 2.200 | `auth` — `jwt.py`, `dependencies.py` y `policies.py` casi intactos; `keycloak_admin.py` pasa de `create_realm()` a `create_organization()`. `jobs` y `retention` — el scope `tenant` itera `tenant_id` en vez de schemas |
| **Reescritura** | 450 | `tenant/` (el middleware resuelve organización y emite el `SET LOCAL`), `db/session.py`, `db/engine.py` |
| **Reducción** | 704 → 200 | De `mail/` solo sobrevive `SystemMailer`, para facturas y dunning del portal. SMTP por tenant, plantillas en base de datos, pixel de tracking y unsubscribe no aplican: una tienda de barrio no envía correo transaccional |

### 5.3 Módulos de negocio

De `platform-service` (11.200 LOC) **no se porta código, se porta el catálogo de módulos.**
Se reimplementan en `api` los que aplican:

`tenants`, `auth`, `audit`, `api_keys`, `webhooks`, `feature_flags`, `notifications`,
`account`, `tenant_settings`, `platform`, `impersonation`.

Dos observaciones sobre esa lista: el firmado HMAC de `webhooks` (formato compatible con
Stripe, con reintentos vía DLX) es exactamente lo que necesitará `/webhooks/payments` en Fase
2; e `impersonation` vale mucho en este segmento, porque el soporte va a necesitar entrar a
la cuenta del tendero para ayudarlo.

Se descartan ~3.400 LOC que no encajan: `mail` completo, `signup` (el de Vendi es celular +
OTP de WhatsApp, no email), `service_accounts`, `invitations`, `tenant_idp` y
`tenant_security` (TOTP; Vendi va por passkeys).

### 5.4 Lo que Vendi construye desde cero

BaseSaaS no tiene equivalente para: `AIProvider` (ADR-007), `PaymentProvider` + entitlements
(ADR-004/010), canal WhatsApp dentro del outbox, motor de reglas deterministas, y la API de
sincronización por deltas del POS offline.

## 6. Frontend

### 6.1 Topología de aplicaciones (ADR-012)

| App | Actor | Equivalente en BaseSaaS |
|---|---|---|
| `vendi-portal` | Público y prospectos: producto, planes, suscripción (`/pro`, `/checkout`, `/cuenta`) | `www` |
| `vendi-tenant` | Dueño del negocio, desde web: portal administrativo del tenant | `app` |
| `vendi-admin` | Nosotros: consola de plataforma para administrar tenants | `admin` |
| `vendi-app` | Usuarios del tenant en la tienda (dueño, cajero, almacenista): móvil Capacitor | — |

`vendi-app` no tiene equivalente y es donde se concentra el riesgo técnico del frontend:
POS offline-first, periféricos nativos y autenticación sin red. Su diseño de autenticación
es el sub-proyecto 2.

### 6.2 Mapeo de librerías

El corte por capas de Vendi (ADR-011) es más fino que el de BaseSaaS, donde `ui-core` mezcla
autenticación, HTTP, layout y realtime. El mapeo no es 1:1:

| Lib Vendi | Recibe |
|---|---|
| `domain` | `models/` adaptados. Nada más — es TypeScript puro, sin Angular ni RxJS |
| `data-access` | `api.service.ts`, interceptores `correlation-id` y `error`, `feature-flags.service`, el script `codegen-api-client.sh` |
| `auth` | `auth/` completo: `AuthService` con signals + Keycloak PKCE, `auth.guard`, `auth.interceptor`, `has-permission.directive`, `keycloak.fake` para tests |
| `ui-kit` | `ui-theme` (tokens light/dark), los ocho componentes de `ui-components`, `FormRenderer` de `ui-dataforms`, `FullLayoutComponent`, banner de impersonación, badge de notificaciones |
| `native` | Nada — es todo nuevo (Capacitor) |

Se descartan `websocket.service` (sin realtime en el MVP) y `freeze.service` con su banner
(Vendi degrada a plan gratis, no congela el workspace).

### 6.3 Fronteras de dependencia (ADR-011)

Las reglas ya existen como `no-restricted-imports` en el `eslint.config.js` de cada librería,
pero no están documentadas en ninguna parte. El grafo es:

- `domain` — TypeScript puro. No importa Angular, RxJS, Capacitor ni nada.
- `native` — solo envuelve APIs de plataforma. No conoce dominio, UI, persistencia ni sesión.
- `data-access` — HTTP y persistencia. No conoce UI. Accede a plataforma vía `native`.
- `auth` — identidad y entitlements. No conoce UI. Abre el navegador del sistema vía `native`.
- `ui-kit` — presentación. No hace HTTP, no toca Capacitor ni Dexie.

**Contradicción a resolver.** `auth/eslint.config.js` prohíbe importar `data-access`, pero el
mensaje de `data-access/eslint.config.js` afirma que "la dependencia va auth → data-access, no
al revés". Las dos reglas se contradicen y hay que quedarse con una.

**Se resuelve a favor de `auth → data-access`**, es decir, se quita `data-access` de la lista
de prohibidos de `auth`. El motivo: `auth` necesita leer `/me/entitlements` y cachearlo para el
gating offline (`docs/monetizacion-web.md` §2). Si no puede usar `data-access`, tiene que
montar su propio HTTP y duplicar los interceptores de correlación y de errores. La dirección
inversa sigue prohibida: `data-access` nunca importa `auth`, y el token llega por un
interceptor que registra la aplicación. Queda como cláusula de ADR-011 y se refleja en ambos
archivos.

### 6.4 i18n

Se monta `ngx-translate` desde el inicio aunque el MVP sea solo Colombia. La terminología
cambia entre países —*tienda*, *abarrotes*, *bodega*— y retrofitear catálogos sobre cuatro
aplicaciones es mucho más caro que arrancar con ellos.

## 7. Infraestructura y CI

Se porta completa y casi sin tocar, porque no tiene acoplamiento al modelo de tenancy:
`docker-compose` con Traefik y TLS, Postgres, Redis, RabbitMQ, MinIO, Keycloak, Prometheus y
Grafana; los scripts `dev.sh`, `migrate.sh`, `seed.sh`, `verify-setup.sh`, `setup-certs.sh`,
`setup-dnsmasq.sh` y `codegen-api-client.sh`; el tema white-label de Keycloak; y los cuatro
workflows de CI. `reconcile-keycloak.sh` se adapta de realms a Organizations.

**Terraform se difiere a Fase 2.** ADR-003 exige IaC parametrizado por región, y BaseSaaS solo
llega a docker-compose. El MVP se despliega con compose sobre una sola VM en la región CO; la
plantilla Terraform se escribe cuando exista una segunda región que la justifique. Levantar
IaC multi-región para una sola región es precisamente la sobre-ingeniería que
`docs/analisis-comparativo-socios.md` critica del documento del socio.

## 8. Documentación

### 8.1 Correcciones

| Archivo | Corrección |
|---|---|
| `plan-maestro.md:158-159` | Anexos rotos: `vision-producto/index.html` no existe y el PDF de inversores está en `docs/`, no en `investor_pdf/` |
| `plan-maestro.md:11-23` | La tabla de ADRs termina en 010 y no refleja ninguna decisión de construcción |
| `analisis-comparativo-socios.md:5` | Las mismas dos referencias rotas |
| `plan-tecnico.md §2, §6` | Dice "PostgreSQL (RLS)" y "Organizations" en genérico; ahora hay un diseño concreto al que apuntar |

### 8.2 Registro de decisiones

Los diez ADRs existentes migran del plan maestro a `docs/adr/` como archivos individuales —
una decisión por archivo, con contexto y consecuencias. Se añaden los que salen de este spec:

| ADR | Decisión |
|---|---|
| ADR-011 | Fronteras de dependencia del workspace Angular (ya en el código, sin documentar) |
| ADR-012 | Topología de cuatro aplicaciones frontend y qué actor usa cada una |
| ADR-013 | Aislamiento multi-tenant por RLS en schema único; descarta schema-per-tenant |
| ADR-014 | Un realm por región + Organizations; sucursales dentro del tenant |
| ADR-015 | Fundación por cosecha quirúrgica de BaseSaaS, sin relación upstream |
| ADR-016 | Backend como `api` + `worker`; sin realtime ni storage como servicios en el MVP |

ADR-003 gana una consecuencia nueva: Terraform diferido a Fase 2. ADR-005 (telemetría del POS)
sigue abierto y queda fuera del alcance de este spec.

### 8.3 Documentación de desarrollador

Hoy no existe: el repositorio no tiene ni README. Se crea siguiendo el modelo de BaseSaaS, que
ya probó funcionar:

- `README.md` y `CLAUDE.md` en la raíz
- `docs/ARCHITECTURE.md` — decisiones de fundación y puntos de extensión
- `docs/getting-started.md` — de clone a primer endpoint
- `docs/env-reference.md`
- `docs/runbooks/` — se adaptan los que apliquen de los 33 de BaseSaaS; `orm-alembic-sync.md`
  no se porta, porque RLS elimina el problema que documenta
- `docs/estado.md` — progreso real contra el roadmap, que hoy no existe en ninguna parte

## 9. Verificación

Se porta el andamiaje de pruebas de BaseSaaS: 99 archivos de test backend, 11 specs Playwright
y los cuatro workflows de CI. Dos tests cambian de naturaleza al cambiar el modelo de tenancy:

- `test_cross_tenant_isolation.py` se refuerza. Con RLS el aislamiento lo garantiza el motor,
  así que el test puede intentar la fuga directamente en SQL y esperar cero filas, en vez de
  confiar en la disciplina del código de aplicación.
- `test_search_path_reset_hook.py` se convierte en su equivalente para `vendi.tenant_id`:
  verificar que una conexión devuelta al pool no arrastra el tenant del request anterior.

**Criterio de Fase 0 terminada** — el mismo que usa BaseSaaS, más el entregable que pide
`plan-tecnico.md §8`:

1. `verify-setup.sh` pasa todos sus checks de humo en verde.
2. Login con passkey funcionando.
3. CRUD de tenant funcionando.
4. Pipeline de CI que produce un AAB de prueba.

## 10. Riesgos de esta fundación

| Riesgo | Mitigación |
|---|---|
| El claim de organización de Keycloak 26 no se comporta como se asume | Verificar contra 26.6.4 antes de escribir el middleware de tenant; es la primera tarea del plan |
| Un handler olvida el `SET LOCAL` y consulta sin tenant | Reset en checkout del pool + policy que falla cerrado + test dedicado |
| Código cosechado arrastra supuestos de schema-per-tenant no detectados | La cosecha se hace archivo por archivo, no por copia masiva; los 36 archivos acoplados están identificados |
| La reescritura de `keycloak_admin.py` resulta mayor de lo estimado | Es la pieza con más incertidumbre; se aborda temprano y se mide antes de comprometer el resto del cronograma |
| Diferir Terraform deja la región CO sin reproducibilidad | El compose de producción queda versionado y `verify-setup.sh` valida el despliegue; la deuda se paga en Fase 2 con una segunda región que la justifica |

---

### Referencias

- `docs/plan-maestro.md` — fuente canónica de producto y negocio
- `docs/plan-tecnico.md` — detalle de ADR-001..004
- `docs/monetizacion-web.md` — diseño de monetización (sub-proyecto 5)
- `docs/analisis-comparativo-socios.md` — origen de las decisiones fusionadas con el socio
- BaseSaaS `docs/ARCHITECTURE.md` — las decisiones de fundación que aquí se adoptan o descartan
