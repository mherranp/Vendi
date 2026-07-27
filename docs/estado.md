# Estado de la fundación

Qué se entregó de verdad al cerrar la **Fase 0**, qué no, y qué queda vivo para
la Fase 1. Regla de este documento: **no promete nada que un comando no
demuestre.** Donde hay una afirmación, hay al lado el comando que la comprueba.

Fecha de corte: **2026-07-23** (cierre de la Etapa 5).

---

## Los cuatro criterios de cierre de Fase 0

| # | Criterio | Estado | Cómo se comprueba |
|---|---|---|---|
| 1 | `verify-setup.sh` en verde | **25/28 en verde, 1 omitido, 2 en rojo** | `bash scripts/verify-setup.sh` |
| 2 | Login con passkey | **Cumplido** | manual + `npm run verificar:passkey` (Playwright) |
| 3 | CRUD de negocio | **Cumplido** | `uv run pytest -q tests/api/test_tenants_crud.py` + spec de Playwright |
| 4 | El pipeline produce un AAB descargable | **Workflow escrito; sin ejecución registrada** | `.github/workflows/android.yml` |

### Criterio 1 — por qué 2 en rojo, y por qué no se tocan

Los dos fallos son **11b** y **11c**, y los dos dicen lo mismo:

```
[FALLO] api.vendi.co resuelve a 64.190.63.222, que NO es esta máquina
[FALLO] estos nombres salen a Internet en vez de a Traefik: accounts.vendi.co…
```

`vendi.co` es un dominio real registrado por un tercero, y el resolver
`/etc/resolver/vendi.co` **no existe en esta máquina** porque escribirlo exige
`sudo`. Los dos checks están detectando exactamente la condición peligrosa que
existen para detectar: **son el guarda funcionando, no un defecto**. Ponerlos en
verde relajándolos sería apagar la alarma en vez de apagar el fuego.

El criterio «todo en verde» (25 checks + los 2 del resolver) se alcanza en
cuanto el dueño de la máquina ejecute
`./scripts/setup-dnsmasq.sh` (procedimiento A de
[`docs/runbooks/dns-y-tls-local.md`](runbooks/dns-y-tls-local.md)). Todo lo demás
del stack ya se verifica por el dominio fijando la resolución en el cliente
(`curl --resolve`, `socket.getaddrinfo` parcheado en los tests), que no afloja
nada: hostname, SNI, cabecera `Host`, enrutado de Traefik y validación completa
del certificado siguen siendo los reales.

El check 17 se omite porque solo aplica con `APP_ENV=production`, y lo dice.

### Criterio 4 — lo que falta y por qué

**CERRADO el 2026-07-27** (nota añadida a posteriori; el texto original del
cierre de Fase 0 decía que el workflow estaba escrito pero jamás ejecutado por
no existir remoto). El remoto `origin` (github.com/mherranp/Vendi) se conectó y
la primera ejecución real exigió cuatro correcciones (`0f14efd`, `2b077ac`,
`466f377`, `3593cd1`), incluido un bug real de despliegue fresco: el compose no
pasaba `VENDI_PROVISIONING_CLIENT_SECRET` al contenedor de Keycloak y la
siembra recibía 401 en cualquier base vacía — en local no se notaba porque el
realm ya existía en el volumen. Evidencia: `gh run list` muestra `ci`, `e2e` y
`release-images` en verde en el SHA `3593cd1` (runs 30246206628, 30246206697,
30246206643), con `verify-setup.sh` 26 en verde / 2 omitidos / 0 fallos y 106
tests de integración passed, 0 skipped, dentro del propio CI.

---

## La suite de tests

```
cd backend && uv run pytest -q
418 passed
```

De ellos, **106 son `integration`**: hablan con el PostgreSQL, el RabbitMQ y el
Keycloak del compose, y con la API por su dominio. **No se omiten** si el
servicio falta: fallan con un mensaje que dice qué falta. Un test que desaparece
del recuento no prueba nada, y el job de CI convierte cualquier `SKIPPED` en
fallo.

Frontend: 250 specs (`npx ng test --watch=false`), más 2 specs E2E de
Playwright (`npm run e2e`: login con passkey y CRUD de negocio) contra el
stack por dominio.

---

## Medición final de la cosecha

El spec §5.2 estimaba **6.100 LOC** cosechadas de `base_saas` hacia la librería
transversal. Medición real de `backend/libs/vendi-core/src` (Python, sin
`__pycache__`, contando comentarios y docstrings — que aquí no son relleno: son
el registro de procedencia que el propio plan exige):

| Paquete | LOC | Categoría del spec | Desviación |
|---|---:|---|---|
| `auth` | 1.384 | con adaptación | `keycloak_admin.py` fue **reescritura dirigida**, no adaptación, como el spec ya anticipaba |
| `middleware` | 682 | sin cambios | — |
| `audit` | 588 | con adaptación | `tenant_slug` → `tenant_id UUID` |
| `db` | 483 | reescritura | `rls.py` es nuevo; `engine.py` y `session.py` reescritos |
| `retention` | 482 | con adaptación | ámbito por `tenant_id`; **ampliado** con SAVEPOINT por política |
| `jobs` | 426 | con adaptación | ídem |
| `messaging` | 393 | sin cambios | **desviación**: el dispatcher se endureció dos veces (D-05 y D-07) |
| `mail` | 390 | reducción a 200 | **desviación**: quedó en 390, no en 200 |
| `tenant` | 306 | reescritura | — |
| `storage` | 290 | con adaptación | bucket único por región con prefijo |
| `tracing` | 204 | sin cambios | — |
| resto (`config`, `files`, `events`, `errors`, `cache`, `logging`, `models`) | 506 | sin cambios | **desviación**: `audit`, `messaging` y `storage` no fueron «sin cambios» |
| **Total `vendi-core`** | **6.146** | estimado 6.100 | **+0,8 %** |

La estimación global acertó casi exactamente; lo que no acertó fue el **reparto**
por categorías. Tres paquetes que el spec daba por «sin cambios» (`audit`,
`messaging`, `storage`) sí requirieron adaptación, y `mail` no bajó a 200 LOC
porque el `SystemMailer` que sí se conserva arrastra más superficie de la
prevista.

Resto del repositorio, para contexto:

| Árbol | LOC |
|---|---:|
| `backend/services/api` (incluye migraciones y scripts) | 2.598 |
| `backend/services/worker` | 466 |
| `backend/tests` | 8.449 |
| `frontend/projects/libs` (TypeScript) | 6.024 |
| `frontend/projects/vendi-*` (TypeScript) | 3.538 |
| `infra/` + `scripts/` (compose, Traefik, bash, Python de operación) | 5.686 |

Que los tests (8.449) pesen más que la librería (6.146) es intencional: la
mayoría del valor de esta fundación está en los candados, no en el código que
vigilan.

Comandos que reproducen la tabla:

```bash
for d in backend/libs/vendi-core/src/vendi_core/*/; do
  printf '%s %s\n' "$(basename "$d")" \
    "$(find "$d" -name '*.py' -not -path '*__pycache__*' -exec cat {} + | wc -l)"
done | sort -k2 -nr
```

---

## Qué queda vivo para la Fase 1

Lo que está mal **a sabiendas**, con dueño y fecha, vive en
[`docs/deuda-tecnica.md`](deuda-tecnica.md). Resumen al cierre de Fase 0:

| # | Deuda | Vence |
|---|---|---|
| D-03 | El realm es semilla; la aplicación automática cubre solo el subconjunto seguro | Fase 1 |

Cerradas en la Etapa 5, con su evidencia en el registro de deuda: **D-01**
(ROPC), **D-04** (Keycloak sin `--optimized`), **D-06** (`alembic_version`
escribible), **D-07** (`exchange` del outbox), **D-08** (claim `groups` /
`has_role()` inerte). Cerrada en la Task 0.5.3 de Fase 1 (2026-07-27): **D-02**
— el aprovisionamiento se movió al servicio `provisioner`, la única unidad de
despliegue con `manage-realm` (ADR-027).

### Fuera del alcance de Fase 0, por diseño

Nada de esto es deuda: es alcance que el plan excluyó y que la Fase 1 recoge.

- **El dominio del MVP**: POS, inventario, compras, caja, fiado. No existe una
  sola tabla de negocio todavía — la única que hay (`files`) es de la librería.
- **Offline-first** (IndexedDB, cola de sincronización).
- **Autenticación móvil**: `vendi-app` compila y produce un AAB, y nada más.
- **Monetización**: portal de pago, webhooks, entitlements.
- **Módulos de backlog**: `api_keys`, `webhooks`, `feature_flags`,
  `notifications`, `account`, `tenant_settings`. El porqué de cada uno está en
  [ADR-016](adr/adr-016-backend-api-worker.md).
- **Terraform**: diferido a Fase 2 ([ADR-003](adr/adr-003-multi-region.md)). La
  reproducibilidad interina es el compose de producción versionado más
  `deploy.yml` y el runbook de la VM.
