# Plan maestro de implementación — Fase 1 (MVP Colombia)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Llevar Vendi desde la fundación cerrada (Fase 0) hasta el MVP Colombia del plan maestro §7: catálogo + POS offline-first, inventario con alertas, compras, caja + P&L + forecast, fiado + clientes, IA v1, escáner y push FCM, con piloto de 50–100 tiendas.

**Architecture:** Se mantiene la arquitectura firmada de Fase 0 (ADR-001…016): monolito modular FastAPI + worker sobre `vendi-core`, RLS en schema único con dos roles, un realm Keycloak por región con Organizations, workspace Angular con 4 apps y fronteras mecánicas. Fase 1 añade el primer subárbol de dominio de negocio (`app/modules/` en la API, features en `vendi-app`/`vendi-tenant`) y la capa de sincronización offline que el POS exige.

**Tech Stack:** FastAPI 0.139 / SQLAlchemy 2.0 async / Alembic / PostgreSQL 17 RLS · Angular 21 (signals, Vitest) / Capacitor 8 / Dexie-IndexedDB (nuevo, requiere ADR) · Keycloak 26.6.4 · RabbitMQ outbox · Docker Compose + Traefik · GitHub Actions.

## Global Constraints

- Todo artefacto del repo en español riguroso (código, docstrings, commits, docs). Excepción heredada: módulos cosechados de BaseSaaS (deuda conocida, no ampliarla).
- Toda tabla nueva de dominio lleva `tenant_id` + policy RLS + índice por `tenant_id`, verificada por test de aislamiento cross-tenant contra PostgreSQL real (plantilla: `backend/tests/integration/test_cross_tenant_isolation.py`).
- Los tests de integración **fallan, no se omiten**, si falta el servicio (regla del `conftest.py`).
- Nada se declara hecho sin el comando que lo demuestra; cada cierre de etapa actualiza `docs/estado.md` y registra deuda nueva en `docs/deuda-tecnica.md` con vencimiento.
- Fronteras ADR-011 inviolables: `@capacitor/*` solo en `lib/native`; el cliente HTTP solo vía `data-access` generado por `scripts/codegen-api-client.sh`.
- Un ADR no se edita para cambiar de opinión; las decisiones nuevas son ADR nuevos (ADR-017+).
- Los secretos nunca tienen defaults; `.env` jamás se commitea.
- Git: commits por tarea, mensajes en español estilo oración (convención del repo). Nunca `git push` sin confirmación humana.

## Bloqueantes humanos (fuera del alcance de los agentes)

| # | Bloqueante | Responsable | Estado |
|---|---|---|---|
| B-1 | Crear/conectar remoto git y ejecutar los 5 workflows por primera vez | Humano (URL o `gh repo create`) | **Resuelto 2026-07-27**: remoto `origin` (github.com/mherranp/Vendi) conectado por el usuario; primera ejecución en curso (Task 0.5.2) |
| B-2 | Decidir dominio de producción (`vendi.co` es de un tercero) | Humano | Diferido por decisión del usuario (2026-07-27): no bloquea Fase 1 hasta el piloto |
| B-3 | Cuenta Google Play / FCM / Gemini API key para spikes | Humano | Pendiente — necesario en Etapa 1.4 |

---

## Fase 0.5 — Desbloqueo técnico (antes de cualquier módulo de negocio)

### Task 0.5.1: Conectar los candados huérfanos al CI

**Files:**
- Modify: `.github/workflows/ci.yml` (job `frontend-lint` o job nuevo `frontend-contratos`)
- Referencia: `scripts/codegen-api-client.sh`, `frontend/scripts/verificar-contraste.mjs`, `frontend/package.json`

**Interfaces:**
- Consume: el script de codegen ya existente y el verificador de contraste WCAG ya existente (diseñados en Etapa 5, nunca cableados).
- Produce: dos pasos bloqueantes en CI; la afirmación del header de `frontend/projects/libs/data-access/src/lib/api-client/index.ts` ("el CI la detecta con codegen + git diff --exit-code") pasa a ser verdadera.

- [x] **Step 1:** Añadir job/paso en `ci.yml` que regenere el cliente TS desde el OpenAPI congelado (`docs/api/openapi-fase0.json`) y falle si `git diff --exit-code` detecta deriva.
- [x] **Step 2:** Añadir paso que ejecute `verificar-contraste.mjs` (o su script npm equivalente) sobre el ui-kit.
- [x] **Step 3:** Verificación local: `CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git diff --exit-code` → salida 0; `npm run verificar:contraste` → salida 0 (12 pares ≥ 4.5:1). *(Nota de ejecución: el script no parsea flags; la interfaz real de modo congelado es la variable `CODEGEN_SCHEMA_FILE`, no `--frozen`.)*
- [x] **Step 4:** Commit: `ci: conectar candados de codegen y contraste WCAG diseñados en la Etapa 5`. — *Ejecutado como job nuevo `frontend-contratos` en `ci.yml`; incluye prueba negativa (path ficticio en el OpenAPI → `git diff` falla como debe).*

### Task 0.5.2: Remoto git + primera ejecución real del pipeline

**Bloqueado por B-1.** Cuando exista remoto:
- [x] `git remote add origin <url>` + push (con confirmación humana explícita). — *Remoto conectado por el usuario (github.com/mherranp/Vendi); push inicial del usuario 2026-07-27.*
- [x] Observar los 5 workflows; corregir lo que falle en runner limpio (cachés, tiempos de arranque del stack de 12 contenedores dentro de `timeout-minutes: 30`). — *4 fallos en cascada corregidos: `.env` invisible para compose (`0f14efd`), secreto de provisioning no pasado a Keycloak en base vacía (`2b077ac` — bug real de despliegue fresco), check 25 de verify-setup sin guarda para stack sin SPAs (`466f377`), base NSS ausente para mkcert/Chromium (`3593cd1`).*
- [x] Criterio de cierre verificable: badge verde de `ci.yml` y `e2e.yml` en el SHA de master, registrado en `docs/estado.md` (cierra el criterio 4 de Fase 0). — *ci, e2e y release-images en verde en SHA `3593cd1` (2026-07-27); `docs/estado.md` actualizado con los run IDs.*

### Task 0.5.3: Cerrar o acotar D-02 (credencial `manage-realm` en el proceso de la API)

- [x] Opción A (completa): mover el aprovisionamiento a una unidad de despliegue separada (servicio `provisioner` propio, fuera de la API). — *Cerrada 2026-07-27 con la opción A: servicio `backend/services/provisioner` (commits `6afb513` y `833f6d1`), decisión en ADR-027 y evidencia en `docs/deuda-tecnica.md` (D-02 cerrada).*
- [ ] Opción B (acotada, si A se difiere): rotación documentada + alcance mínimo + runbook; registrar en `deuda-tecnica.md` por qué se difiere. — *No aplicada: la opción A no encontró bloqueo estructural.*
- [x] Verificación: `verify-setup.sh` check 21 (roles mínimos de service accounts) en verde + test que prueba que la API arranca sin la credencial de provisioning cuando el módulo está deshabilitado. — *Check 21 y el nuevo check 26 (la API no tiene el secreto; el borde no alcanza el provisioner) en verde contra el stack real; `tests/api/test_api_sin_secreto_de_provisioning.py` prueba que la API se construye sin la credencial.*

---

## Etapa 1.1 — Arquitectura de dominio (ADRs ADR-017…ADR-026)

**Agentes:** 4 arquitectos en paralelo (scopes disjuntos, números de ADR pre-asignados para evitar colisiones; ninguno edita `docs/adr/README.md` — la tabla la integra el orquestador).

**Scopes:**
- **A — POS y sincronización offline** (ADR-017, ADR-018): IndexedDB/Dexie como fuente de verdad local, cola de sincronización, ids generados en cliente (UUID), resolución de conflictos, modelo de venta/turno offline. Es la decisión más arriesgada de Fase 1: condiciona backend, app móvil y tests.
- **B — Catálogo, inventario y compras** (ADR-019, ADR-020): modelo de productos/variantes, movimientos de stock, alertas, compras a proveedores.
- **C — Caja, fiado/clientes y multi-empleado** (ADR-021, ADR-022, ADR-023): sesiones de caja y arqueo (complementa ADR-006), diseño técnico del fiado (complementa ADR-009), permisos operativos por empleado sobre ADR-015.
- **D — Escáner, push y alcance técnico de IA v1** (ADR-024, ADR-025, ADR-026): escáner de 3 capas, FCM (ADR-001 lo presupone), qué es exactamente "consultas + recomendaciones por reglas narradas" sobre ADR-007.

**Criterio de cierre verificable:**
- [x] 10 archivos ADR numerados sin colisiones, formato exacto del directorio (contexto / decisión / alternativas descartadas / consecuencias), cada uno citando su presión de origen en `plan-maestro.md`.
- [x] Cada ADR de dominio declara: tablas nuevas (con `tenant_id`), eventos de outbox que emite, y el candado/test que lo hará verificable.
- [x] Tabla de `docs/adr/README.md` actualizada por el orquestador en un solo commit.
- [x] **Revisión de coherencia cruzada** (ejecutada 2026-07-27 por agente revisor independiente): corregidas 2 contradicciones de modelo (topología de `notificacion.enviar`; sesión de caja única por tienda vs. multi-caja offline — gana ADR-021, ADR-018 alineado), unificado el dinero a centavos enteros en ADR-019/021/022, y 3 desviaciones menores (miscita ADR-023, sección de cierre en ADR-017/018).

## Etapa 1.2 — Backend de dominio (por módulo, plan detallado propio)

**Regla:** ningún módulo entra a implementación sin (a) sus ADRs firmados, (b) un plan detallado propio en `docs/superpowers/plans/` escrito con la skill writing-plans (TDD, pasos de 2-5 min), (c) su migración Alembic revisada por el agente de seguridad.

**Orden (por dependencias):**
1. `modulo-catalogo` (base de todo: productos) — plan: `2026-07-28-modulo-catalogo-plan.md` — **CERRADO 2026-07-27** (gate verificado; evidencia comando+salida en `docs/estado.md`)
2. `modulo-ventas` + soporte de sincronización offline en la API (endpoints idempotentes de sync) — el módulo crítico — plan: `2026-07-28-modulo-ventas-plan.md` — **CERRADO 2026-07-27** (gate verificado; evidencia comando+salida en `docs/estado.md`)
3. `modulo-inventario` + alertas — plan: `2026-07-28-modulo-inventario-plan.md` — **CERRADO 2026-07-27** (gate verificado; evidencia comando+salida en `docs/estado.md`)
4. `modulo-caja` + P&L/forecast (ADR-006) — plan: `2026-07-28-modulo-caja-plan.md` — **CERRADO 2026-07-28** (gate verificado; evidencia comando+salida en `docs/estado.md`)
5. `modulo-clientes-fiado` (ADR-009)
6. `modulo-ia-v1` (ADR-007 + ADR-026)
7. `modulo-push` (FCM)

**Gate por módulo (idéntico para todos):**
- [x] Migración con RLS + índice + grants, revisada por security.
- [x] Tests de integración con aislamiento cross-tenant nuevo por tabla (0 SKIPPED).
- [x] OpenAPI congelado actualizado (`docs/api/`) + codegen + `contrato.ts` sigue compilando.
- [x] Eventos de outbox emitidos según su ADR; `pytest -m integration` verde; `ruff` verde.
- [x] Permisos del módulo (ADR-023) sembrados en el realm y exigidos por el check 23 de `verify-setup.sh`: cada módulo nuevo extiende ese check con los suyos, así la letra de ADR-023 se completa módulo a módulo.

*(Marcado por el módulo catálogo (2026-07-27 — run de CI 30260179984) y reverificado ítem a ítem por el módulo ventas (2026-07-27 — run de CI 30283626280), por el módulo inventario (2026-07-27 — run de CI 30305515191) y por el módulo caja (2026-07-28 — run de CI 30318420990); la lista se reusa y se vuelve a verificar por cada módulo siguiente.)*

## Etapa 1.3 — Frontend web y móvil (paralela a 1.2, medio paso detrás)

- [ ] **Web** (2 agentes): features en `vendi-tenant` (caja, inventario, fiado) sobre el cliente generado; `GET /tenants/mios` para reemplazar UUIDs por nombres en el selector (pendiente conocido de Fase 0); deduplicar `nucleo/sesion.ts` y `layout/avisos.component.ts` hacia libs; corregir `roleGuard` → ruta `/sin-permiso` (crearla o apuntar a `/sin-acceso`).
- [ ] **Móvil/offline** (1 agente dedicado, el de mayor riesgo): spike de Dexie + cola de sync PRIMERO (tradición `scripts/spikes/`), luego POS en `vendi-app`: auth por navegador del sistema (`@capacitor/browser`, esquema `co.vendi.app://`), catálogo local, venta offline, sincronización. Quitar el spec-candado de `app.spec.ts` solo cuando el login móvil exista.
- [ ] **Comercial**: `vendi-portal` con captación y precios (ADR-010).
- [ ] **Gate:** `ng test` verde en los 9 proyectos + nuevos specs por feature; E2E Playwright nuevo por flujo de dinero (venta, cobro de fiado, arqueo); budgets de bundle no relajados sin ADR.

## Etapa 1.4 — QA adversarial y seguridad (transversal, corre al cerrar cada módulo)

- [ ] **QA adversarial** (agente distinto del que escribió el código, incentivo a romper): fugas cross-tenant con datos semilla de dos tenants, doble submit en ventas y cobros, paginación rota, token expirado a media venta, sync offline con conflictos (mismo producto editado en dos dispositivos), reloj del cliente adelantado/atrasado.
- [ ] **Security**: checklist por módulo — ¿RLS? ¿índice tenant_id? ¿grants mínimos? ¿eventos sin PII de más? ¿endpoint con scope correcto? — y **extender `verify-setup.sh` con un check nuevo por cada riesgo encontrado** (el conocimiento se vuelve ejecutable y permanente).
- [ ] **Gate:** cada hallazgo termina en (a) fix + test de regresión, o (b) entrada numerada en `deuda-tecnica.md` con vencimiento. Ningún hallazgo queda en conversación.

## Etapa 1.5 — Cierre de Fase 1

- [ ] `docs/estado.md` reescrito con fecha de corte y evidencia comando+salida de cada criterio (piloto-ready: alta de tienda → vender offline → sincronizar → arquear caja → cobrar fiado).
- [ ] Deuda viva revisada: D-02/D-03 vencen aquí; nuevas entradas registradas.
- [ ] Runbooks nuevos en `docs/runbooks/` para: sync offline (qué hacer cuando un tenant tiene cola atascada), forecast, IA v1 (fallback sin Gemini).
- [ ] Commit de cierre de etapa estilo repo: `Etapa N cerrada: …`.

---

## Riesgos de orquestación y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Deriva de estilo/idioma entre agentes | Candado de cosecha + fronteras ESLint ya son mecánicos; revisión del orquestador entre tareas |
| Contexto insuficiente en subagentes | Todo prompt incluye: ADR aplicable, archivo plantilla a imitar, comando de verificación exacto |
| QA que se autocongratula | QA adversarial es agente distinto al implementador, KPI = hallazgos |
| Colisiones de archivos en paralelo | Scopes disjuntos; números de ADR pre-asignados; archivos compartidos (`adr/README.md`, `estado.md`) solo los toca el orquestador |
| El orquestador es cuello de botella | Cierres asíncronos por evidencia; al humano solo escalan B-1/B-2/B-3 y decisiones de producto |

## Self-Review

- **Cobertura del spec:** plan-maestro §7 Fase 1 (catálogo→Etapa 1.2 módulo 1; POS offline→1.1-A + 1.2 módulo 2 + 1.3 móvil; inventario→1.2 módulo 3; compras→ADR-020 + módulo 3; caja/P&L→ADR-021 + módulo 4; fiado→ADR-022 + módulo 5; IA v1→ADR-026 + módulo 6; escáner→ADR-024 + 1.3 móvil; push→ADR-025 + módulo 7; multi-empleado→ADR-023). Los entregables de publicación (Play Store, TestFlight) dependen de B-3 y se planifican al cerrar 1.3.
- **Placeholders:** las etapas 1.2+ remiten a planes detallados propios por diseño (scope check de writing-plans: un plan por subsistema); no se escriben hasta tener ADRs firmados para no congelar decisiones antes de tiempo.
- **Consistencia de tipos/contratos:** los contratos concretos (OpenAPI, eventos outbox, tablas) los fijan los ADRs de 1.1; este plan solo fija números de ADR, nombres de módulo y gates.
