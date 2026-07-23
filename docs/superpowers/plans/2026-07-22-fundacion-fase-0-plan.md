# Fundación Fase 0 de Vendi — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** construir la fundación técnica de Vendi cosechando BaseSaaS, con tenancy por RLS en schema único y un realm regional con Keycloak Organizations, hasta cumplir los cuatro criterios de cierre de Fase 0 del spec.

**Arquitectura:** monolito modular FastAPI (`services/api`) + worker (`services/worker`) sobre la librería transversal `vendi-core` cosechada de `base_saas`; frontend Angular 21 con cuatro apps y cinco libs ya andamiadas; infraestructura docker-compose cosechada de BaseSaaS. El aislamiento multi-tenant lo garantiza PostgreSQL RLS (fail-closed) y la identidad un realm `vendi-co` con una Organization por negocio.

**Stack:** Python 3.12 + FastAPI + SQLAlchemy 2 async + asyncpg + Alembic · Angular 21.2 + Capacitor 8 + keycloak-js 26.x · Keycloak 26.6.4 · PostgreSQL 17 · RabbitMQ 4 · Redis 7 · MinIO · Traefik · uv.

**Spec fuente:** `docs/superpowers/specs/2026-07-22-fundacion-fase-0-design.md`
**Repos:** Vendi = `/Users/maoherran/Work/Products/Vendi/software` · BaseSaaS = `/Users/maoherran/BaseSaaS` (solo lectura: se cosecha, nunca se modifica).

## Restricciones globales

- Todo en español: código comentado, commits, docs, mensajes de error de cara al usuario.
- Rol de conexión de la API: `vendi_app` (**sin** `BYPASSRLS`). Rol de plataforma/migraciones: `vendi_platform` (**con** `BYPASSRLS`, owner de las tablas).
- GUC de tenant: `vendi.tenant_id`. Siempre `SET LOCAL`, nunca `SET`, en código de request.
- Realm Keycloak: `vendi-co`, imagen fijada `quay.io/keycloak/keycloak:26.6.4`, nunca `latest`.
- Roles de negocio (roles de realm): `dueno`, `cajero`, `almacenista` (sin tildes ni eñes en identificadores técnicos).
- Prefijo de selectores Angular: `vd`. Las fronteras de imports de ADR-011 se validan por `no-restricted-imports` en cada lib.
- python-keycloak ≥ 7.1 (trae la API de Organizations; verificado en el venv de BaseSaaS: 7.1.1).
- Alcance: SOLO Fase 0. Sin modelo de datos del MVP, sin offline-first, sin monetización, sin auth móvil (subproyectos 2–5). `vendi-app` en Fase 0 solo compila y produce AAB; no tiene login.
- Los módulos de negocio de §5.3 del spec que no se necesitan para los criterios de Fase 0 (`api_keys`, `webhooks`, `feature_flags`, `notifications`, `account`, `tenant_settings`) **no se implementan aquí**; quedan como backlog documentado en `docs/ARCHITECTURE.md`. Fase 0 implementa: `tenants`, `auth`, `audit` y el esqueleto de `platform`.

## Modelo de ejecución

El plan se ejecuta por **etapas secuenciales**. Dentro de cada etapa hay una **pista backend** y una **pista frontend** que avanzan en paralelo sin bloquearse (cuando una etapa es asimétrica, se dice explícitamente). Cada pista tiene un QA adversarial cuyo trabajo es demostrar que las tareas NO están terminadas usando la sección "Superficie de ataque para QA". El arquitecto solo declara la etapa cerrada cuando se cumple el "Criterio de integración".

```
Etapa 1 (spikes de riesgo: KC Organizations + RLS)      ← lo más incierto primero
   └─► Etapa 2 (infraestructura + esqueleto de repos)
          └─► Etapa 3 (vendi-core con tenancy RLS ∥ libs frontend)
                 └─► Etapa 4 (API mínima + tenants ∥ apps conectadas)
                        └─► Etapa 5 (CI + AAB + E2E + documentación)
```

---

# Etapa 1 — Spikes de riesgo: Keycloak Organizations y RLS

**Composición:** pista backend con las dos tareas de riesgo; pista frontend con una tarea corta (resolver la contradicción de ESLint y fijar dependencias). La etapa es deliberadamente backend-pesada: nada de lo que sigue puede diseñarse en firme sin las respuestas de estas dos tareas.

**Por qué primero:** el spec asume comportamientos concretos de Keycloak 26 Organizations (claim, scope, roles) y de RLS (fail-closed con cero filas) que hay que demostrar con evidencia antes de escribir `vendi-core`. El propio spec lo marca como primera tarea.

**Hechos ya verificados en la revisión del spec** (el spike los confirma contra 26.6.4, no los descubre):

- El scope `organization` es un client scope **opcional** built-in del realm; define el mapper "Organization Membership".
- El claim `organization` es un **mapa por alias**: `{"organization": {"<alias>": {"id": "...", "groups": [...]}}}`. El **id de la organización NO se incluye por defecto** — hay que activar "Add organization id" en el mapper.
- `scope=organization:*` incluye todas las organizaciones del usuario; `scope=organization:<alias>` una concreta.
- Keycloak 26.6.0 añadió **Organization Groups** (jerarquías de grupos por organización, visibles en el claim). Contexto para ADR-014: existe un mecanismo nativo si algún día se necesita diferenciación por organización; la decisión "sucursales = datos del tenant, roles = realm" se mantiene por simplicidad.
- python-keycloak 7.1.1 expone `create_organization`, `organization_user_add/remove`, `get_user_organizations`, `get_organization_members` (verificado en el código instalado).

### Tarea 1.1 (backend): spike ejecutable de Keycloak 26.6.4 Organizations

**Files:**
- Create: `scripts/spikes/kc-orgs-spike.sh`
- Create: `docs/superpowers/specs/2026-07-22-verificacion-kc-organizations.md` (informe con evidencia)

**Interfaces:**
- Produces: el informe fija para la Etapa 3 → nombre exacto del claim, shape, configuración del scope (¿default u opcional?), formato de alias admitido, y la decisión **alias = `str(tenant_id)`** (o su alternativa con lookup).

- [ ] **Paso 1: escribir el script del spike.** Levanta KC 26.6.4 efímero, crea realm + organization + usuario vía kcadm/REST, obtiene un token y lo decodifica. Contenido:

```bash
#!/usr/bin/env bash
# Spike: verificar Keycloak 26.6.4 Organizations contra los supuestos de ADR-014.
set -euo pipefail

KC_IMG="quay.io/keycloak/keycloak:26.6.4"
docker rm -f kc-spike 2>/dev/null || true
docker run -d --name kc-spike -p 8089:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  "$KC_IMG" start-dev
echo "Esperando a Keycloak..."
until curl -sf http://localhost:8089/realms/master >/dev/null; do sleep 2; done

KCADM="docker exec kc-spike /opt/keycloak/bin/kcadm.sh"
$KCADM config credentials --server http://localhost:8089 --realm master --user admin --password admin

# 1. Realm regional con organizations habilitadas
$KCADM create realms -s realm=vendi-co -s enabled=true -s organizationsEnabled=true

# 2. Cliente público PKCE (como vendi-app/vendi-tenant)
$KCADM create clients -r vendi-co -s clientId=vendi-web -s publicClient=true \
  -s standardFlowEnabled=true -s directAccessGrantsEnabled=true \
  -s 'redirectUris=["*"]' -s 'attributes={"pkce.code.challenge.method":"S256"}'

# 3. Organization con alias en formato UUID (la hipótesis de diseño: alias = tenant_id)
TENANT_ID="1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e"
$KCADM create organizations -r vendi-co \
  -s name="Tienda Don Carlos" -s alias="$TENANT_ID" \
  -s 'domains=[{"name":"'$TENANT_ID'.tenants.vendi.local","verified":true}]'
ORG_ID=$($KCADM get organizations -r vendi-co --fields id,alias | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["id"])')

# 4. Usuario miembro
$KCADM create users -r vendi-co -s username=cajera1 -s enabled=true \
  -s 'credentials=[{"type":"password","value":"spike","temporary":false}]'
UID_=$($KCADM get users -r vendi-co -q username=cajera1 --fields id | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["id"])')
$KCADM create "organizations/$ORG_ID/members" -r vendi-co -b "\"$UID_\""

# 5. Tokens: sin scope, con scope=organization, con scope="organization:*"
for SCOPE in "openid" "openid organization" "openid organization:*"; do
  echo "=== scope: $SCOPE ==="
  curl -s http://localhost:8089/realms/vendi-co/protocol/openid-connect/token \
    -d grant_type=password -d client_id=vendi-web -d username=cajera1 -d password=spike \
    -d "scope=$SCOPE" \
   | python3 -c 'import sys,json,base64
t=json.load(sys.stdin)
if "access_token" not in t: print("ERROR:", t); raise SystemExit
p=t["access_token"].split(".")[1]; p+="="*(-len(p)%4)
c=json.loads(base64.urlsafe_b64decode(p))
print(json.dumps({k:c.get(k) for k in ("organization","scope","iss","realm_access")}, indent=2, ensure_ascii=False))'
done
echo "Spike listo. Deja el contenedor vivo para pruebas manuales; bórralo con: docker rm -f kc-spike"
```

- [ ] **Paso 2: ejecutar y responder el checklist.** Cada punto se responde en el informe con el output pegado (tokens decodificados, respuestas de la Admin API):

  1. ¿El claim se llama `organization` y su shape es un mapa por alias? ¿Qué contiene el valor por alias por defecto?
  2. ¿Aparece el claim SIN pedir el scope? Si no: asignar `organization` como **default client scope** del cliente (`$KCADM update clients/<id>/default-client-scopes/...`) y repetir — decidir si va como default (recomendado: default, para que el middleware nunca dependa de que el frontend pida el scope).
  3. Con el usuario en **dos** organizaciones: ¿qué trae `scope=organization` a secas? ¿Y `organization:*`? ¿Hay prompt de selección o error? (crear una segunda org y repetir el paso 5 del script).
  4. ¿Acepta el alias un string con formato UUID (guiones incluidos)? — el paso 3 del script lo prueba. Si lo rechaza: decisión alternativa = alias libre + columna `kc_org_alias` en la tabla `tenants` + cache de resolución (documentar cuál quedó).
  5. ¿Es **obligatorio** el dominio al crear la organización? ¿Acepta el dominio sintético `<tenant_id>.tenants.vendi.local`? ¿Falla la creación de una segunda org con dominio distinto pero mismo patrón?
  6. ¿Se puede **deshabilitar** una organización, y eso bloquea el login de sus miembros? (Hipótesis de la revisión: NO lo bloquea, porque los usuarios son del realm → la suspensión de tenant se hará a nivel de aplicación. Confirmar y anotarlo como consecuencia en ADR-014.)
  7. Activar "Add organization id" en el mapper del scope y verificar que el `id` de la org aparece en el claim.
  8. ¿`organizationsEnabled=true` en el realm basta, o hay feature flag de arranque? (en 26.x Organizations es supported por defecto; confirmar con la imagen exacta).
  9. Login identity-first: con organizations habilitadas, ¿cambia la pantalla de login del realm para flujos de navegador? ¿Afecta al flujo PKCE estándar de un usuario que NO llega por dominio de email?
  10. WebAuthn passwordless (passkeys): crear la policy en el realm (`WebAuthn Passwordless Policy`), registrar una passkey con un usuario en Chrome (authenticator virtual en `chrome://webauthn-internals` o dispositivo real) y hacer login sin contraseña. ¿Convive con organizations sin fricción?

- [ ] **Paso 3: escribir el informe** `docs/superpowers/specs/2026-07-22-verificacion-kc-organizations.md` con: cada pregunta, su evidencia, y el bloque final "Decisiones que fija este spike" (claim, scope default, alias=tenant_id o alternativa, dominio sintético, suspensión app-level, config de passkeys). Este informe es entrada obligatoria de las tareas 3.4, 3.5 y de ADR-014.

- [ ] **Paso 4: commit**

```bash
git add scripts/spikes/kc-orgs-spike.sh docs/superpowers/specs/2026-07-22-verificacion-kc-organizations.md
git commit -m "Spike de Keycloak 26.6.4 Organizations: claim, scope, alias UUID, dominios y passkeys"
```

**Criterios de aceptación (verificables):**
- `bash scripts/spikes/kc-orgs-spike.sh` corre de cero a tokens decodificados sin intervención manual.
- El informe responde las 10 preguntas con output pegado, no con prosa.
- El bloque "Decisiones que fija este spike" no contiene ningún "pendiente".

### Tarea 1.2 (backend): spike de RLS en PostgreSQL 17

**Files:**
- Create: `scripts/spikes/rls-spike.sql`
- Create: `scripts/spikes/rls-spike.sh` (levanta `postgres:17` efímero y ejecuta el .sql con psql, mostrando resultados)
- Create: `docs/superpowers/specs/2026-07-22-verificacion-rls.md`

**Interfaces:**
- Produces: el idiom exacto de policy y de reset que usarán las tareas 3.3 y 3.8.

- [ ] **Paso 1: escribir el SQL del spike.** Debe demostrar, en este orden:

```sql
-- rls-spike.sql — ejecutar con psql -v ON_ERROR_STOP=0 para ver los errores esperados
-- Roles
CREATE ROLE vendi_platform LOGIN PASSWORD 'spike' BYPASSRLS;
CREATE ROLE vendi_app LOGIN PASSWORD 'spike';

-- Tabla de prueba (owner: vendi_platform, como en producción)
SET ROLE vendi_platform;
CREATE TABLE ventas (id serial PRIMARY KEY, tenant_id uuid NOT NULL, total numeric);
GRANT SELECT, INSERT, UPDATE, DELETE ON ventas TO vendi_app;
GRANT USAGE, SELECT ON SEQUENCE ventas_id_seq TO vendi_app;
ALTER TABLE ventas ENABLE ROW LEVEL SECURITY;
ALTER TABLE ventas FORCE ROW LEVEL SECURITY;

-- A. El idiom INGENUO del spec: falla con ERROR, no con cero filas
CREATE POLICY p_naive ON ventas
  USING (tenant_id = current_setting('vendi.tenant_id')::uuid);
INSERT INTO ventas (tenant_id, total) VALUES ('11111111-1111-1111-1111-111111111111', 100);
RESET ROLE; SET ROLE vendi_app;
SELECT * FROM ventas;      -- ESPERADO: ERROR unrecognized configuration parameter
RESET ROLE; SET ROLE vendi_platform;
DROP POLICY p_naive ON ventas;

-- B. El idiom ROBUSTO: NULLIF + missing_ok → cero filas sin error
CREATE POLICY tenant_isolation ON ventas
  USING (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid);
RESET ROLE; SET ROLE vendi_app;
SELECT count(*) AS sin_guc_debe_ser_0 FROM ventas;               -- 0 filas, sin error
BEGIN;
SET LOCAL vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
SELECT count(*) AS con_guc_debe_ser_1 FROM ventas;               -- 1
COMMIT;
SELECT count(*) AS tras_commit_debe_ser_0 FROM ventas;           -- 0: SET LOCAL murió con la tx

-- C. WITH CHECK cierra el INSERT cruzado
BEGIN;
SET LOCAL vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
INSERT INTO ventas (tenant_id, total)
  VALUES ('22222222-2222-2222-2222-222222222222', 50);           -- ESPERADO: ERROR RLS violation
ROLLBACK;

-- D. FORCE aplica al owner sin BYPASSRLS... y BYPASSRLS lo salta
RESET ROLE; SET ROLE vendi_platform;
SELECT count(*) AS platform_lo_ve_todo FROM ventas;              -- 1 (BYPASSRLS)

-- E. El "reset" de un GUC custom: SET a cadena vacía es el único fiable
RESET ROLE; SET ROLE vendi_app;
SET vendi.tenant_id = '11111111-1111-1111-1111-111111111111';    -- fuga simulada a nivel sesión
SET vendi.tenant_id = '';                                        -- lo que hará el hook de checkout
SELECT count(*) AS tras_reset_debe_ser_0 FROM ventas;            -- 0 (NULLIF neutraliza '')

-- F. Plan de consulta: el predicado RLS usa el índice
RESET ROLE; SET ROLE vendi_platform;
CREATE INDEX ix_ventas_tenant ON ventas (tenant_id);
RESET ROLE; SET ROLE vendi_app;
BEGIN; SET LOCAL vendi.tenant_id = '11111111-1111-1111-1111-111111111111';
EXPLAIN SELECT * FROM ventas WHERE total > 10;                   -- debe mencionar ix_ventas_tenant o Seq con filtro tenant
COMMIT;
```

- [ ] **Paso 2: escribir `rls-spike.sh`** (docker run `postgres:17-alpine` efímero, `psql -v ON_ERROR_STOP=0 -f rls-spike.sql`, output completo a pantalla) y ejecutarlo.

- [ ] **Paso 3: escribir el informe** `docs/superpowers/specs/2026-07-22-verificacion-rls.md`. Debe dejar explícito el hallazgo A: **el idiom del spec (§4.1) tal como está escrito falla con ERROR 500, no con cero filas**; el idiom que se adopta es el de B (con la corrección correspondiente a ADR-013). Documentar también E (el hook de checkout ejecuta `SET vendi.tenant_id = ''`, no `RESET`).

- [ ] **Paso 4: commit**

```bash
git add scripts/spikes/rls-spike.sql scripts/spikes/rls-spike.sh docs/superpowers/specs/2026-07-22-verificacion-rls.md
git commit -m "Spike de RLS en PG17: idiom NULLIF fail-closed, FORCE+BYPASSRLS, reset de GUC en checkout"
```

**Criterios de aceptación:**
- `bash scripts/spikes/rls-spike.sh` reproduce los 6 escenarios (A–F) con los resultados esperados anotados en el propio output.
- El informe fija el texto SQL exacto de la policy que usará `vendi-core`.

### Tarea 1.3 (frontend): resolver la contradicción ESLint y fijar dependencias del workspace

**Files:**
- Modify: `frontend/projects/libs/auth/eslint.config.js` (quitar `data-access` del grupo prohibido; actualizar mensaje)
- Modify: `frontend/projects/libs/data-access/eslint.config.js` (mensaje: confirmar dirección `auth → data-access`)
- Modify: `frontend/package.json` (añadir `keycloak-js@26.x`, `@ngx-translate/core@^17`, `@ngx-translate/http-loader@^17`)

- [ ] **Paso 1:** en `auth/eslint.config.js`, cambiar el grupo a `['ui-kit', 'dexie', '@capacitor/*']` y el mensaje a: `'auth maneja identidad y entitlements. Puede usar data-access (la dependencia va auth → data-access). Para abrir el navegador del sistema usa la fachada de native, no @capacitor/browser directo.'`
- [ ] **Paso 2:** verificar que `data-access/eslint.config.js` mantiene `auth` prohibido (ya lo hace — no tocar el grupo, solo revisar el mensaje).
- [ ] **Paso 3:** `cd frontend && npm install keycloak-js@26 @ngx-translate/core@17 @ngx-translate/http-loader@17`
- [ ] **Paso 4:** `npx ng lint` — debe pasar en las 5 libs y 4 apps.
- [ ] **Paso 5: commit**

```bash
git add frontend/projects/libs/auth/eslint.config.js frontend/projects/libs/data-access/eslint.config.js frontend/package.json frontend/package-lock.json
git commit -m "ADR-011: la dependencia auth → data-access queda permitida; deps keycloak-js y ngx-translate"
```

**Criterios de aceptación:** `npx ng lint` verde; `grep -n "data-access" frontend/projects/libs/auth/eslint.config.js` no aparece en ningún grupo prohibido; ambos mensajes cuentan la misma historia.

### Superficie de ataque para QA — Etapa 1

- **KC spike:** repetir el spike con el usuario en **cero** organizaciones y en **dos**; el informe debe cubrir ambos o está incompleto. Pedir el token con `scope=organization:<alias-inexistente>` y ver qué pasa. Crear una organización con alias duplicado y con dominio duplicado. Verificar que el claim sobrevive al **refresh token** (no solo al access token inicial). Intentar crear la org SIN dominio: si falla y el informe no lo documenta, la tarea no está terminada.
- **RLS spike:** ejecutar el script **dos veces seguidas** (¿es re-ejecutable o revienta por objetos existentes?). Conectar como `vendi_app` y probar `SET ROLE vendi_platform` (debe fallar: `vendi_app` no debe ser miembro). Probar `ALTER TABLE ventas DISABLE ROW LEVEL SECURITY` como `vendi_app` (debe fallar: no es owner). Probar un `UPDATE ventas SET tenant_id = '2222...'` con GUC del tenant 1 (WITH CHECK debe bloquearlo). Verificar el caso `current_setting('vendi.tenant_id', true)` cuando la variable NUNCA se definió en la sesión vs. cuando se definió y se puso a `''` — ambos deben dar cero filas.
- **ESLint:** escribir un import `data-access` → `auth` temporal y confirmar que lint lo rechaza; escribir `auth` → `data-access` y confirmar que pasa. Borrar los archivos de prueba.

### Criterio de integración — Etapa 1

El arquitecto cierra la etapa cuando: (1) ambos informes existen con evidencia ejecutable y sin "pendientes"; (2) las decisiones fijadas (idiom de policy, alias de organización, scope default, suspensión app-level, config passkey) están escritas y son consistentes entre los dos informes; (3) si el spike de KC **refutó** algún supuesto del spec (p. ej. alias UUID no admitido, dominio obligatorio problemático), existe la corrección correspondiente redactada para ADR-014 antes de que la Etapa 3 empiece; (4) lint del frontend verde.

---

# Etapa 2 — Infraestructura cosechada y esqueleto de los repos

**Composición:** dos pistas reales. Backend: layout de `backend/` + cosecha de `infrastructure/` y `scripts/`. Frontend: entornos, i18n y codegen. La pista frontend no depende de ninguna tarea backend de esta etapa (usa el stack cuando esté, pero sus entregables compilan sin él).

### Tarea 2.1 (backend): layout del backend con uv

**Files:**
- Create: `backend/pyproject.toml` (workspace uv), `backend/libs/vendi-core/pyproject.toml`, `backend/libs/vendi-core/src/vendi_core/__init__.py`
- Create: `backend/services/api/pyproject.toml`, `backend/services/api/app/main.py` (FastAPI con `/health` que devuelve `{"status":"ok"}`)
- Create: `backend/services/worker/pyproject.toml`, `backend/services/worker/worker/__main__.py` (loop asyncio que loguea un latido y sale limpio con SIGTERM)

- [ ] **Paso 1:** replicar la estructura de dependencias de `/Users/maoherran/BaseSaaS/backend/base_saas/pyproject.toml` en `vendi-core` (mismos extras: `auth`, `cache`, `messaging`, `storage`, `tracing`, `all`, `dev`; **sin** extra `mail` completo — solo `aiosmtplib`, `jinja2` para `SystemMailer`). Fijar `python-keycloak>=7.1.0`.
- [ ] **Paso 2:** `cd backend && uv sync` — resuelve sin errores.
- [ ] **Paso 3:** test de humo `backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient
from app.main import app

def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok"}
```

`uv run pytest tests/test_health.py -v` → PASS.
- [ ] **Paso 4: commit** — `git commit -m "Layout del backend: workspace uv con vendi-core, services/api y services/worker"`

### Tarea 2.2 (backend): cosecha de `infrastructure/` → `infra/`

**Files:**
- Create: `infra/docker-compose.yml`, `infra/docker-compose.override.dev.yml`, `infra/docker-compose.override.prod.yml` (cosechados de `/Users/maoherran/BaseSaaS/infrastructure/`)
- Create: `infra/postgres/init/01-roles.sh`
- Create: `infra/keycloak/realm-vendi-co.json` (realm como código) y `infra/keycloak/vendi-theme/` (adaptado del tema `basesaas-theme`)
- Create: `infra/traefik/`, `infra/prometheus/`, `infra/grafana/` (cosecha con renombres `basesaas`→`vendi`)

- [ ] **Paso 1: copiar y renombrar.** `cp -R /Users/maoherran/BaseSaaS/infrastructure/ infra/` y aplicar los renombres: servicios/redes/volúmenes `basesaas*`→`vendi*`, dominios `*.basesaas.dev`→`*.vendi.local`, imagen de Keycloak `26.1`→`26.6.4`, Postgres a `postgres:17`. Quitar del compose los servicios `storage-service` y `realtime-service` si existen como servicios propios (ADR-016). MinIO, Redis, RabbitMQ, Prometheus, Grafana y Traefik se quedan.
- [ ] **Paso 2: roles de Postgres.** `infra/postgres/init/01-roles.sh` (el entrypoint oficial ejecuta `.sh` con env):

```bash
#!/usr/bin/env bash
set -euo pipefail
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<-SQL
  CREATE ROLE vendi_platform LOGIN PASSWORD '${VENDI_PLATFORM_DB_PASSWORD}' BYPASSRLS;
  CREATE ROLE vendi_app LOGIN PASSWORD '${VENDI_APP_DB_PASSWORD}';
  CREATE DATABASE vendi OWNER vendi_platform;
SQL
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d vendi <<-SQL
  ALTER SCHEMA public OWNER TO vendi_platform;
  GRANT USAGE ON SCHEMA public TO vendi_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE vendi_platform IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vendi_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE vendi_platform IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO vendi_app;
SQL
```

- [ ] **Paso 3: realm como código.** Construir `infra/keycloak/realm-vendi-co.json` a partir de las decisiones del spike 1.1: `organizationsEnabled: true`, clientes `vendi-web` (público PKCE, para tenant/app), `vendi-admin` (público PKCE, para la consola), `vendi-backend` (confidencial, service account con permisos de admin de organizations), scope `organization` como **default** en `vendi-web` con "Add organization id" activado, WebAuthn Passwordless Policy configurada, `bruteForceProtected: true`, `loginTheme: vendi`, locales `["es"]` con `defaultLocale: es`. Montarlo con `--import-realm` en el compose.
- [ ] **Paso 4:** `docker compose -f infra/docker-compose.yml -f infra/docker-compose.override.dev.yml config` valida; `docker compose up -d` levanta todo; `docker compose ps` muestra todos los servicios `healthy`.
- [ ] **Paso 5:** verificación de roles: `psql postgresql://vendi_app:...@localhost/vendi -c "SELECT rolbypassrls FROM pg_roles WHERE rolname='vendi_app'"` → `f`; ídem `vendi_platform` → `t`.
- [ ] **Paso 6: commit** — `git commit -m "Infraestructura cosechada de BaseSaaS: compose con KC 26.6.4, realm vendi-co como código y roles RLS de Postgres"`

### Tarea 2.3 (backend): cosecha de `scripts/`

**Files:**
- Create: `scripts/dev.sh`, `scripts/migrate.sh`, `scripts/seed.sh`, `scripts/verify-setup.sh`, `scripts/setup-certs.sh`, `scripts/setup-dnsmasq.sh`, `scripts/reconcile-keycloak.sh` (cosecha de `/Users/maoherran/BaseSaaS/scripts/`)

- [ ] **Paso 1:** copiar los siete scripts y adaptar: dominios `vendi.local`, rutas `infra/`, DSN con `vendi_platform` en `migrate.sh` (obligatorio: Alembic corre con BYPASSRLS; ver hallazgo del spike 1.2) y `vendi_app` como DSN de la API en `dev.sh`. **No** portar: `alembic-stamp-consolidated.sh`, `new-product.sh`, `scaffold.sh`, `gdpr-tenant-dump.sh` (asumen schema-per-tenant o son del meta-producto BaseSaaS).
- [ ] **Paso 2:** `reconcile-keycloak.sh`: cambiar el recorrido de realms por el recorrido de organizations del realm `vendi-co` (`GET /admin/realms/vendi-co/organizations` paginado) comparando contra la tabla `tenants` vía la API. Dejar el esqueleto funcional aunque la tabla `tenants` llegue en la Etapa 4 (el script falla limpio con "API sin módulo tenants aún" hasta entonces).
- [ ] **Paso 3:** `verify-setup.sh`: adaptar los checks al stack de Vendi (Traefik, PG con ambos roles, Redis, RabbitMQ, MinIO, KC con realm `vendi-co` respondiendo `.well-known/openid-configuration`, Prometheus, Grafana). Añadir un check nuevo: `SELECT rolbypassrls FROM pg_roles WHERE rolname='vendi_app'` debe ser `f`.
- [ ] **Paso 4:** `bash scripts/verify-setup.sh` → todos los checks disponibles en verde (los que dependen de la API pueden reportar `SKIP` explícito hasta la Etapa 4, nunca falso verde).
- [ ] **Paso 5: commit** — `git commit -m "Scripts de desarrollo cosechados: dev, migrate (rol platform), verify-setup y reconcile de organizations"`

### Tarea 2.4 (frontend): entornos, i18n y codegen

**Files:**
- Create: `frontend/projects/*/src/environments/environment.ts` y `environment.development.ts` en las 4 apps (apiUrl, keycloakUrl, realm `vendi-co`, clientId por app)
- Create: `scripts/codegen-api-client.sh` (cosecha de BaseSaaS; genera el cliente TS desde `/openapi.json` de la API hacia `frontend/projects/libs/data-access/src/lib/api-client/`)
- Create: bootstrap ngx-translate en las 4 apps + `frontend/projects/*/public/i18n/es.json` inicial

- [ ] **Paso 1:** entornos por app: `vendi-tenant` y `vendi-app` usan clientId `vendi-web`; `vendi-admin` usa `vendi-admin`; `vendi-portal` no usa Keycloak.
- [ ] **Paso 2:** cosechar `codegen-api-client.sh` adaptando la ruta de salida a `data-access`. El script debe fallar con mensaje claro si la API no está arriba.
- [ ] **Paso 3:** ngx-translate en `app.config.ts` de las 4 apps con `TranslateHttpLoader` sobre `/i18n/`, `defaultLanguage: 'es'`. Un `es.json` mínimo por app (título de la app y un par de claves del layout). Regla de PR documentada en el README del frontend: ninguna cadena visible hardcodeada en templates de las libs.
- [ ] **Paso 4:** `npx ng build vendi-portal && npx ng build vendi-tenant && npx ng build vendi-admin && npx ng build vendi-app` — verdes. `npx ng test --watch=false` (los specs de andamiaje) — verde.
- [ ] **Paso 5: commit** — `git commit -m "Entornos por app, ngx-translate con catálogo es y codegen del cliente API"`

### Superficie de ataque para QA — Etapa 2

- **Persistencia real:** `docker compose down && docker compose up -d` — ¿sobrevive el realm importado y los roles de PG? (`--import-realm` solo importa si el realm no existe: verificar el comportamiento en re-arranque y documentarlo en el compose). `docker compose down -v && up -d` — ¿el stack se reconstruye de cero sin pasos manuales?
- **Roles PG:** conectarse como `vendi_app` e intentar `CREATE TABLE` en `public` (debe fallar: no tiene CREATE). Intentar `SET ROLE vendi_platform` desde `vendi_app` (debe fallar). Revisar que `01-roles.sh` no queda con contraseñas hardcodeadas — deben venir de `.env` y `verify-setup.sh` debe chequear que no son las de ejemplo en modo prod.
- **Realm como código:** borrar a mano un cliente en la consola de KC y re-arrancar: ¿el drift se detecta o se corrige? Si la respuesta es "no hasta reconcile", debe estar documentado en el propio JSON o en el runbook, no ser una sorpresa.
- **verify-setup.sh:** apagar un servicio (`docker compose stop redis`) y correrlo: debe fallar en rojo, no colgarse ni dar verde. Medir que termina en <60s con todo caído (timeouts de curl).
- **Frontend:** `rm -rf node_modules && npm ci && ng build` en limpio. Cambiar el idioma del navegador y verificar que no hay claves crudas (`app.title`) pintadas en pantalla.

### Criterio de integración — Etapa 2

(1) `bash scripts/dev.sh` levanta el stack completo desde un clon limpio (tras `setup-certs`/`dnsmasq` documentados); (2) `verify-setup.sh` verde (con SKIP explícitos solo en checks de API); (3) el realm `vendi-co` responde su `.well-known` y la consola de KC muestra Organizations habilitadas y la policy de passkeys; (4) las cuatro apps compilan y las libs pasan lint; (5) ningún secreto de ejemplo en archivos commiteados (revisión del arquitecto sobre `git diff`).

---

# Etapa 3 — `vendi-core` con tenancy RLS ∥ cosecha de libs frontend

**Composición:** dos pistas plenamente paralelas. La pista backend construye `vendi-core` (cosecha + reescritura de tenancy). La pista frontend cosecha `ui-*` de BaseSaaS hacia las cinco libs de Vendi. El único punto de contacto es el contrato del token (claim `organization`), ya fijado por el informe del spike 1.1.

## Pista backend

### Tarea 3.1 (backend): cosecha "sin cambios" de `base_saas` → `vendi_core`

**Files:**
- Create: `backend/libs/vendi-core/src/vendi_core/{middleware,tracing,config,errors,events,cache,logging,models,files,storage}/` — copiados de `/Users/maoherran/BaseSaaS/backend/base_saas/src/base_saas/`
- Create: los tests correspondientes desde `/Users/maoherran/BaseSaaS/backend/tests/` (los que cubren estos paquetes)

- [ ] **Paso 1:** copiar paquete a paquete (no `cp -R` masivo del árbol entero — la regla del spec: archivo por archivo). Renombrar imports `base_saas`→`vendi_core` (`grep -rl 'base_saas' | xargs sed -i '' 's/base_saas/vendi_core/g'` y revisar el diff).
- [ ] **Paso 2: excepciones dentro de la cosecha "sin cambios"** (hallazgos de la revisión del spec; son adaptaciones menores pero reales):
  - `storage/policy.py` NO se porta (política de bucket-por-tenant). Decisión Fase 0: **un solo bucket por región** (`vendi-co-media`) con prefijo `{tenant_id}/` — decenas de miles de buckets freemium no escalan en S3. Documentar en ADR-016.
  - `files/models.py`: hereda `TenantModel`, que en la tarea 3.3 gana `tenant_id` — verificar que la tabla resultante lo incluye.
- [ ] **Paso 3:** copiar y adaptar los tests de estos paquetes; `uv run pytest tests/ -v` → verdes.
- [ ] **Paso 4: commit** — `git commit -m "Cosecha de vendi-core: middleware, tracing, config, errors, events, cache, logging, models, files y storage (bucket único por región)"`

### Tarea 3.2 (backend): cosecha con adaptación de `audit` y `messaging`

**Files:**
- Create: `vendi_core/audit/` — de `base_saas/audit/`, con `tenant_slug: str` → `tenant_id: uuid.UUID | None` en `events.py`, `models.py` (columna e índice `ix_audit_events_tenant_timestamp`), `decorator.py` (lee `request.state.tenant.tenant_id`) y `service.py`
- Create: `vendi_core/messaging/` — de `base_saas/messaging/`, quitando `{"schema": "public"}` de `outbox.py` (schema único regional) y añadiendo `tenant_id` nullable a `outbox_messages` (los eventos de plataforma no tienen tenant)

**Interfaces:**
- Produces: `AuditEvent(tenant_id: UUID | None, ...)`, `OutboxService.enqueue(session, exchange, routing_key, payload, tenant_id=None)`.

- [ ] **Paso 1:** copiar + aplicar las adaptaciones. Decisión explícita (documentar en el módulo): `audit_events` y `outbox_messages` son **tablas de plataforma**: no llevan policy RLS; solo `vendi_platform` (worker, admin) las lee cross-tenant, y la API escribe en ellas vía los servicios, nunca las expone directo. Justificación: el dispatcher del outbox y las consultas de auditoría de la consola son inherentemente cross-tenant.
- [ ] **Paso 2:** cosechar sus tests, adaptarlos, `pytest` verde.
- [ ] **Paso 3: commit** — `git commit -m "Cosecha adaptada de audit y messaging: tenant_id UUID y tablas de plataforma sin RLS"`

### Tarea 3.3 (backend): reescritura de `db/` — TenantModel, engine y session con RLS

**Files:**
- Create: `vendi_core/db/base.py` (cosechado + `tenant_id` en `TenantModel`)
- Create: `vendi_core/db/engine.py`, `vendi_core/db/session.py` (reescritos)
- Create: `vendi_core/tenant/context.py` (ContextVar)
- Test: `backend/tests/test_rls_session.py`

**Interfaces:**
- Produces: `current_tenant_id: ContextVar[uuid.UUID | None]` · `create_engine(url, role=...)` con hook de checkout · `create_session_factory(engine)` que emite `SET LOCAL` en cada `after_begin` leyendo el ContextVar.

- [ ] **Paso 1: test primero** (falla porque nada existe):

```python
# backend/tests/test_rls_session.py — requiere el PG del compose (marker: integration)
import uuid, pytest
from sqlalchemy import text
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

T1, T2 = uuid.uuid4(), uuid.uuid4()

@pytest.mark.integration
async def test_set_local_se_emite_en_cada_transaccion(pg_app_url, ventas_de_prueba):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    token = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            n1 = (await s.execute(text("SELECT count(*) FROM ventas"))).scalar()
            assert n1 == 1                      # solo las filas de T1
            await s.commit()                    # muere la tx y el SET LOCAL
            n2 = (await s.execute(text("SELECT count(*) FROM ventas"))).scalar()
            assert n2 == 1                      # after_begin re-emitió el SET LOCAL
    finally:
        current_tenant_id.reset(token)

@pytest.mark.integration
async def test_sin_tenant_cero_filas_sin_error(pg_app_url, ventas_de_prueba):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    async with factory() as s:
        assert (await s.execute(text("SELECT count(*) FROM ventas"))).scalar() == 0
```

(El fixture `ventas_de_prueba` crea la tabla con la policy del spike 1.2 usando el DSN de `vendi_platform` e inserta una fila por tenant.)

- [ ] **Paso 2: implementación.**

```python
# vendi_core/tenant/context.py
from contextvars import ContextVar
import uuid

current_tenant_id: ContextVar[uuid.UUID | None] = ContextVar("current_tenant_id", default=None)
```

```python
# vendi_core/db/engine.py — igual al de BaseSaaS pero el hook resetea el GUC de tenant
def _install_tenant_guc_reset(engine: AsyncEngine) -> None:
    if not engine.url.drivername.startswith("postgresql"):
        return

    @event.listens_for(engine.sync_engine, "checkout")
    def _reset(dbapi_conn, conn_record, conn_proxy):
        cursor = dbapi_conn.cursor()
        try:
            # SET a '' y no RESET: un GUC custom nunca definido en la sesión
            # hace que RESET no tenga efecto definible; '' + NULLIF en la
            # policy es el par fail-closed verificado en el spike de RLS.
            cursor.execute("SET vendi.tenant_id = ''")
        finally:
            cursor.close()
```

```python
# vendi_core/db/session.py
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from vendi_core.tenant.context import current_tenant_id

def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @event.listens_for(factory.class_.sync_session_class, "after_begin")
    def _set_tenant(session, transaction, connection):
        if transaction.nested:
            return  # SAVEPOINT hereda el GUC de la transacción externa
        tenant_id = current_tenant_id.get()
        if tenant_id is not None:
            # tenant_id es uuid.UUID: la interpolación es segura por tipo.
            connection.exec_driver_sql(f"SET LOCAL vendi.tenant_id = '{tenant_id}'")

    return factory
```

Nota de implementación: si el listener sobre `factory.class_.sync_session_class` registra a nivel de clase global (afectaría a la factory de plataforma), registrar en su lugar con una subclase de `Session` por factory — el test `test_platform_session_no_emite_set_local` (paso 3) decide.
- [ ] **Paso 3:** añadir `create_platform_session_factory(engine)` **sin** el listener (para el worker y los endpoints de plataforma) y su test: una sesión de plataforma con `current_tenant_id` seteado ve TODAS las filas (BYPASSRLS y sin SET LOCAL).
- [ ] **Paso 4:** `uv run pytest tests/test_rls_session.py -m integration -v` → PASS.
- [ ] **Paso 5: commit** — `git commit -m "db reescrito para RLS: TenantModel con tenant_id, SET LOCAL por transacción vía ContextVar y reset de GUC en checkout"`

### Tarea 3.4 (backend): reescritura de `tenant/middleware.py` para Organizations

**Files:**
- Create: `vendi_core/tenant/middleware.py`, `vendi_core/tenant/context.py` (ampliar con `TenantContext`)
- Test: `backend/tests/test_tenant_middleware.py`

**Interfaces:**
- Consumes: `UserContext` de 3.5 con campo `organizations: dict[str, str]` (alias → org_id).
- Produces: `request.state.tenant: TenantContext(tenant_id: UUID)` y el ContextVar seteado/reseteado por request.

- [ ] **Paso 1: tests primero** (con tokens fake): (a) token con una organización → `tenant_id` resuelto del alias, ContextVar seteado durante el request y **reseteado al salir** (incluso si el handler lanza); (b) token sin organizaciones → 403 en rutas de tenant, pasa en rutas públicas (`/health`, `/docs`, `/openapi.json`) y de plataforma (`/api/v1/platform/*`); (c) token con dos organizaciones → exige header `X-Tenant-Id` cuyo valor esté entre los alias del claim, si no 400; (d) alias que no es UUID → 401 con log, nunca 500.
- [ ] **Paso 2: implementación.** Esqueleto:

```python
class TenantMiddleware(BaseHTTPMiddleware):
    """Resuelve el tenant desde el claim `organization` del token (alias = tenant_id,
    decisión del spike KC-orgs) y lo publica en request.state.tenant y en el
    ContextVar que la sesión de BD usa para el SET LOCAL."""

    async def dispatch(self, request, call_next):
        # ... rutas públicas y de plataforma pasan sin tenant ...
        user = getattr(request.state, "user", None)  # lo puso la validación JWT
        aliases = list(user.organizations) if user else []
        if len(aliases) == 1:
            tenant_id = uuid.UUID(aliases[0])
        elif len(aliases) > 1:
            elegido = request.headers.get("X-Tenant-Id", "")
            if elegido not in aliases:
                return JSONResponse({"detail": "X-Tenant-Id requerido"}, status_code=400)
            tenant_id = uuid.UUID(elegido)
        else:
            ...  # 403 en rutas de tenant
        token = current_tenant_id.set(tenant_id)
        try:
            request.state.tenant = TenantContext(tenant_id=tenant_id)
            return await call_next(request)
        finally:
            current_tenant_id.reset(token)
```

Portar de BaseSaaS lo que aplica del middleware original (orden de resolución, manejo de errores con log en vez de 500); **no** portar: resolución por subdominio (Vendi no usa subdominio por tenant), `X-Organization` por slug, prefijos `sk_live_` (API keys quedan fuera de Fase 0), freeze middleware.
- [ ] **Paso 3:** `pytest tests/test_tenant_middleware.py -v` → PASS.
- [ ] **Paso 4: commit** — `git commit -m "TenantMiddleware para Organizations: alias→tenant_id, multi-org con X-Tenant-Id y reset garantizado del ContextVar"`

### Tarea 3.5 (backend): `auth/` — jwt con issuer fijado, contexto, policies y `keycloak_admin` para Organizations

**Files:**
- Create: `vendi_core/auth/jwt.py` (cosechado + issuer/realm permitido), `vendi_core/auth/context.py` (`UserContext.organizations: dict[str,str]`), `vendi_core/auth/dependencies.py`, `vendi_core/auth/policies.py` (permisos de Vendi), `vendi_core/auth/ssl.py` (sin cambios)
- Create: `vendi_core/auth/keycloak_admin.py` (reescrito)
- Test: `backend/tests/test_jwt_validator.py`, `backend/tests/test_keycloak_admin_orgs.py` (integración contra el KC del compose)

**Interfaces:**
- Produces: `JWTValidator(keycloak_url, allowed_realms=["vendi-co"], audience=...)` · `UserContext(user_id, username, roles, organizations: dict[str,str], acr, actor, token_exp)` · `VendiKeycloakAdmin` con: `create_organization(tenant_id: UUID, name: str) -> str` (alias=`str(tenant_id)`, dominio `f"{tenant_id}.tenants.vendi.local"`), `delete_organization(org_id)`, `add_member(org_id, user_id)`, `remove_member(org_id, user_id)`, `create_user(username, email, password?, roles: list[str]) -> str`, `ensure_realm_role(name)`, `set_user_groups(...)` y `exchange_token_for_user(...)` (impersonación, cosechado con realm fijo).

- [ ] **Paso 1: jwt.py.** Cosechar y adaptar: (a) **nuevo parámetro `allowed_realms`** — el validador de BaseSaaS acepta tokens de CUALQUIER realm del KC (correcto en realm-per-tenant, agujero en realm regional: un token del realm `master` validaría). Si `realm not in allowed_realms` → `ValueError`. (b) `_build_user_context` lee `organization` (mapa alias→`{"id": ...}`) en vez de `tenant_slug`; sin fallback al realm. Test: token firmado del realm `master` (o issuer arbitrario) → rechazado; claim `organization` ausente → `organizations == {}` (no excepción).
- [ ] **Paso 2: policies.py.** Reescribir el catálogo: permisos de Fase 0 (`tenant:read/create/update/delete`, `platform:admin`, `impersonate:user`) y los grupos semilla `dueno`, `cajero`, `almacenista` con sus permisos (dueno: todo lo de su tenant; cajero/almacenista: se dejan declarados vacíos hasta el spec del MVP — comentario explícito). Mantener el patrón BaseSaaS: permiso = realm role, rol de negocio = group.
- [ ] **Paso 3: keycloak_admin.py.** Reescritura dirigida por lo medido en la revisión: de los 797 LOC originales sobreviven con `realm` fijado los helpers de roles/grupos/usuarios/required actions y `exchange_token_for_user`; **mueren** `create_realm`, `delete_realm`, `set_realm_enabled`, `ensure_identity_provider`/IdP, service accounts (fuera de Fase 0); **nacen** los métodos de organizations sobre python-keycloak 7.x (`a_create_organization`, `a_organization_user_add`, ...). Consecuencia documentada en el módulo y en ADR-014: **no existe "deshabilitar el realm" por tenant — la suspensión de un tenant es un estado en la tabla `tenants` que la API consulta**, no un switch en el IdP.
- [ ] **Paso 4: test de integración** `test_keycloak_admin_orgs.py` (marker integration, contra el KC del compose): crea organización con alias UUID, añade miembro, lista miembros, borra; verifica idempotencia de `ensure_realm_role`.
- [ ] **Paso 5:** `pytest tests/test_jwt_validator.py tests/test_keycloak_admin_orgs.py -v` → PASS.
- [ ] **Paso 6: commit** — `git commit -m "auth para realm regional: issuer fijado, UserContext con organizations y KeycloakAdmin reescrito a Organizations"`

### Tarea 3.6 (backend): `jobs/` y `retention/` — scope tenant itera `tenant_id`

**Files:**
- Create: `vendi_core/jobs/` y `vendi_core/retention/` cosechados; en `jobs/types.py` el contexto pasa de `tenant_slug/tenant_schema` a `tenant_id: uuid.UUID | None`; en `jobs/scheduler.py` el scope `tenant` itera los `tenant_id` activos (callable inyectado `list_active_tenant_ids`) y setea `current_tenant_id` por iteración; `retention/runner.py` pierde los `SET search_path` y usa sesión de plataforma + filtro/SET LOCAL por tenant.
- Test: cosechar los tests de jobs/retention y adaptarlos.

- [ ] **Paso 1:** cosechar + adaptar según lo anterior. El runner de retención usa la **sesión de plataforma** y setea el ContextVar por tenant en cada pasada (así ejerce el mismo camino RLS que la API cuando purga tablas de tenant).
- [ ] **Paso 2:** `pytest` de los tests adaptados → PASS.
- [ ] **Paso 3: commit** — `git commit -m "jobs y retention adaptados: el scope tenant itera tenant_id sobre RLS en vez de schemas"`

### Tarea 3.7 (backend): reducción de `mail/` a `SystemMailer`

**Files:**
- Create: `vendi_core/mail/system_mailer.py`, `vendi_core/mail/mime.py` + el provider SMTP mínimo, cosechados. NO portar: `mailer.py` (por-tenant), `renderer.py` con plantillas en BD, `tracking.py`, `secrets.py` de SMTP por tenant.

- [ ] **Paso 1:** cosechar los 3 archivos, quitar toda referencia a `tenant_schema`, catálogo de plantillas = Jinja en el paquete (facturas/dunning llegan en Fase 2). Test de humo con SMTP fake cosechado si existe.
- [ ] **Paso 2: commit** — `git commit -m "mail reducido a SystemMailer: sin SMTP por tenant, sin plantillas en BD, sin tracking"`

### Tarea 3.8 (backend): Alembic + helper RLS + tests de aislamiento

**Files:**
- Create: `backend/services/api/alembic/` (env.py de una sola pasada — sin bucle por schemas), `backend/services/api/alembic/versions/0001_fundacion.py`
- Create: `vendi_core/db/rls.py` (helper DDL)
- Test: `backend/tests/test_rls_coverage.py`, `backend/tests/test_cross_tenant_isolation.py`, `backend/tests/test_tenant_guc_reset_hook.py`

**Interfaces:**
- Produces: `vendi_core.db.rls.enable_rls(op, table_name: str)` para toda migración futura.

- [ ] **Paso 1: helper.**

```python
# vendi_core/db/rls.py
POLICY_SQL = """
CREATE POLICY tenant_isolation ON {table}
  USING (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
"""

def enable_rls(op, table: str) -> None:
    """Toda tabla de negocio (TenantModel) DEBE pasar por aquí en su migración."""
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(POLICY_SQL.format(table=f'"{table}"'))
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
```

- [ ] **Paso 2: test-lint de cobertura RLS** — el candado que impide olvidar la policy en tablas futuras:

```python
# backend/tests/test_rls_coverage.py (integration; corre tras migrate)
async def test_toda_tabla_tenant_tiene_rls_forzado_y_policy(pg_platform_session):
    filas = (await pg_platform_session.execute(text("""
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
               (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS n_policies
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND EXISTS (SELECT 1 FROM information_schema.columns col
                      WHERE col.table_name = c.relname AND col.column_name = 'tenant_id'
                        AND col.table_name NOT IN ('audit_events', 'outbox_messages'))
    """))).all()
    sin_rls = [f for f in filas if not (f.relrowsecurity and f.relforcerowsecurity and f.n_policies >= 1)]
    assert not sin_rls, f"Tablas con tenant_id sin RLS forzado + policy: {sin_rls}"
```

- [ ] **Paso 3:** `test_cross_tenant_isolation.py` (la versión reforzada que pide el spec §9): con el DSN de `vendi_app`, sembrar filas de dos tenants (vía sesión de plataforma), y en SQL directo: SELECT/UPDATE/DELETE con el GUC del tenant 1 no toca jamás filas del tenant 2; INSERT con `tenant_id` ajeno → error de RLS; sin GUC → cero filas y cero error.
- [ ] **Paso 4:** `test_tenant_guc_reset_hook.py` (equivalente del `test_search_path_reset_hook.py` de BaseSaaS): fija `SET vendi.tenant_id` a nivel de **sesión** en una conexión, la devuelve al pool, saca una conexión y verifica `current_setting('vendi.tenant_id', true) IN ('', NULL)`.
- [ ] **Paso 5:** migración `0001_fundacion.py`: tablas de plataforma `audit_events`, `outbox_messages` (sin RLS, comentario del porqué) — las tablas de negocio llegan con el módulo tenants (4.2) y el MVP. `bash scripts/migrate.sh` verde; los tres tests verdes.
- [ ] **Paso 6: commit** — `git commit -m "Alembic de pasada única, helper enable_rls y los tres tests candado del aislamiento"`

## Pista frontend

### Tarea 3.9 (frontend): lib `domain`

**Files:**
- Create: `frontend/projects/libs/domain/src/lib/models/` — cosechar `ui-core/src/lib/models/{api-response,user}.model.ts` de BaseSaaS, adaptados: `UserProfile.tenantSlug: string` → `tenantId: string`; añadir `Tenant` (id, nombre, estado, plan) alineado con la API de 4.2.

- [ ] **Paso 1:** cosechar + adaptar + exportar en `public-api.ts`. Sin imports de Angular/RxJS (el lint de la lib lo vigila).
- [ ] **Paso 2:** `npx ng lint domain && npx ng test domain --watch=false` → verde.
- [ ] **Paso 3: commit** — `git commit -m "domain: modelos cosechados con tenantId y modelo Tenant"`

### Tarea 3.10 (frontend): lib `data-access`

**Files:**
- Create: `data-access/src/lib/api.service.ts`, `interceptors/correlation-id.interceptor.ts`, `interceptors/error.interceptor.ts`, `services/feature-flags.service.ts` — cosechados de `ui-core`.

- [ ] **Paso 1:** cosechar los 4 archivos + sus specs (`.spec.ts`) de BaseSaaS; adaptar imports a los paths de Vendi (`domain`). El interceptor de error usa mensajes en español vía ngx-translate.
- [ ] **Paso 2:** `npx ng test data-access --watch=false` → specs cosechados verdes.
- [ ] **Paso 3: commit** — `git commit -m "data-access: api.service, interceptores de correlación y error, feature flags"`

### Tarea 3.11 (frontend): lib `auth`

**Files:**
- Create: `auth/src/lib/auth.service.ts`, `auth.guard.ts`, `auth.interceptor.ts`, `has-permission.directive.ts`, `keycloak.fake.ts` — cosechados de `ui-core/src/lib/auth/` + specs.

**Interfaces:**
- Produces: `AuthService.tenantId: Signal<string | null>` (del claim `organization`), `AuthService.roles: Signal<string[]>`, `hasPermission(p: string): boolean`.

- [ ] **Paso 1:** cosechar y adaptar `auth.service.ts`: el tipo del token pasa de `tenant_slug` a:

```ts
export type VendiTokenParsed = KeycloakTokenParsed & {
  organization?: Record<string, { id?: string }>;
};
// tenantId = único alias del mapa; si hay varios, el seleccionado se fija con
// selectTenant(alias) y se envía como X-Tenant-Id en auth.interceptor.
```

Configuración: realm `vendi-co` + clientId por app desde `environment` (no derivado del tenant). Mantener intactos: guard de refresh re-entrante, guard de logout doble, `keycloak.fake.ts` para tests (adaptar el fake al nuevo claim).
- [ ] **Paso 2:** `auth.interceptor.ts`: Bearer + `X-Tenant-Id` cuando hay selección. `has-permission.directive.ts` sin cambios de fondo.
- [ ] **Paso 3:** cosechar `auth.service.spec.ts` (142 LOC) y adaptarlo al claim; añadir spec nuevo: token con dos organizaciones → `tenantId` es null hasta `selectTenant()`.
- [ ] **Paso 4:** `npx ng test auth --watch=false && npx ng lint auth` → verde (lint confirma que auth puede importar data-access tras 1.3).
- [ ] **Paso 5: commit** — `git commit -m "auth: AuthService con signals sobre el claim organization, guard, interceptor con X-Tenant-Id y fake de Keycloak"`

### Tarea 3.12 (frontend): lib `ui-kit`

**Files:**
- Create: `ui-kit/src/lib/theme/` (cosecha de `ui-theme`: tokens M3 light/dark re-tematizados a Vendi), `ui-kit/src/lib/components/` (los 8 de `ui-components`: confirm-dialog, data-table, empty-state, file-upload, loading-spinner, not-found, page-header, status-badge), `ui-kit/src/lib/forms/` (`FormRenderer` + validators de `ui-dataforms`), `ui-kit/src/lib/layout/full-layout/`, `ui-kit/src/lib/impersonation/impersonation-banner.component.ts`, `ui-kit/src/lib/notifications/notifications-badge.component.ts`

- [ ] **Paso 1:** cosechar por componente con sus specs; prefijo de selector `bs-`→`vd-`; textos a claves ngx-translate en `es.json` de la lib consumidora. NO portar: `websocket.service`, `freeze.service`, `frozen-banner`, `when-not-frozen.directive`, `idp-logo` (sin IdPs externos), `branding/*` (Vendi no es white-label).
- [ ] **Paso 2:** el banner de impersonación queda presentacional puro (recibe `@Input() actor`), la lógica de sesión vive en `auth` — respeta la frontera "ui-kit no hace HTTP".
- [ ] **Paso 3:** `npx ng test ui-kit --watch=false && npx ng lint ui-kit` → verde. `npx ng build ui-kit` → verde.
- [ ] **Paso 4: commit** — `git commit -m "ui-kit: tema M3 de Vendi, ocho componentes, FormRenderer, FullLayout y banners"`

### Superficie de ataque para QA — Etapa 3

- **Backend / RLS (lo más importante del plan):**
  - En `test_cross_tenant_isolation`: probar también `SELECT ... FOR UPDATE`, `DELETE ... RETURNING` y un `UPDATE ventas SET tenant_id = :otro` (reasignación de tenant: WITH CHECK debe bloquearla). Probar una query con JOIN entre dos tablas de tenant.
  - Sesión que hace `commit()` a mitad de request y sigue consultando: sin el `after_begin`, devuelve cero filas EN SILENCIO. Escribir el exploit primero y verificar que el listener lo neutraliza. Ídem con `rollback()`.
  - Ejecutar dos requests concurrentes con tenants distintos sobre un pool de tamaño 1 (fuerza reutilización de conexión) y verificar no-contaminación.
  - Usar la factory de **plataforma** desde un handler de tenant a propósito: ¿algo lo impide o al menos lo hace ruidoso? Proponer el candado si no existe (p. ej. dependencia FastAPI separada y grep de CI).
  - `keycloak_admin`: crear dos organizaciones con el mismo alias (debe fallar limpio); borrar una org que no existe (¿idempotente o 500?); KC caído → ¿error tipado o traceback crudo?
  - JWT: token expirado, token sin `kid`, token del realm `master`, token con `aud` ausente, claim `organization` con alias no-UUID. Todos deben terminar en 401 tipado, jamás 500.
  - Correr `pytest` completo DOS veces seguidas contra el mismo compose: la suite debe ser re-entrante (limpieza de datos).
- **Frontend:**
  - `keycloak.fake`: simular expiración de token durante navegación y verificar que el refresh re-entrante no dispara dos updates.
  - Forzar respuesta 500 y 0 (network error) en `api.service` y verificar que `error.interceptor` produce mensaje traducido, no `[object Object]`.
  - `has-permission.directive` con permiso inexistente → no pinta y no explota.
  - Buscar imports prohibidos con el lint pero también con `grep -rn "from 'auth'" projects/libs/data-access` (el lint solo ve patrones que conoce).
  - `ng build` de las 4 apps con las libs nuevas: presupuestos de bundle no reventados.

### Criterio de integración — Etapa 3

(1) `uv run pytest` completo verde incluidos los markers `integration` contra el compose; (2) los tres tests candado (aislamiento SQL directo, reset del GUC, cobertura RLS) pasan y el arquitecto revisó personalmente sus asserts (son la garantía central del producto); (3) `ng test` y `ng lint` verdes en las 5 libs; (4) ningún archivo cosechado conserva `base_saas`, `basesaas`, `tenant_slug` ni `search_path` (grep de cierre: `grep -rn 'base_saas\|search_path\|tenant_slug' backend/libs frontend/projects/libs` → vacío); (5) el mapa de cosecha real (qué archivo vino de dónde y con qué cambio) quedó anotado en `docs/ARCHITECTURE.md` §cosecha, porque los LOC del spec eran estimación y el arquitecto debe registrar la medición final.

---

# Etapa 4 — API mínima con módulo tenants ∥ apps conectadas

**Composición:** dos pistas paralelas. Backend entrega la API que cumple los criterios 2–3 de Fase 0; frontend conecta `vendi-admin` y `vendi-tenant` contra ella. La pista frontend puede empezar contra el OpenAPI congelado del paso 4.1/4.2 (contrato primero) sin esperar la implementación.

### Tarea 4.1 (backend): app factory de `services/api`

**Files:**
- Create: `backend/services/api/app/main.py` (reescrito sobre el esqueleto de 2.1), `app/lifespan.py`, `app/settings.py`
- Test: `backend/tests/api/test_app_smoke.py`

- [ ] **Paso 1:** cablear en orden los middlewares cosechados (correlation-id → security headers → client-ip → api-version → error handler → JWT/tenant) siguiendo el `app/` de referencia de BaseSaaS (240 LOC que el spec no listó en la cosecha; aquí es donde se adaptan). Lifespan: engines (uno `vendi_app`, uno `vendi_platform`), factories de sesión (tenant y plataforma), `JWTValidator(allowed_realms=["vendi-co"])`, `VendiKeycloakAdmin`, Redis.
- [ ] **Paso 2:** `/health` (liveness, sin dependencias) y `/health/ready` (PG, Redis, KC `.well-known`). Prometheus `/metrics`.
- [ ] **Paso 3:** test de humo: la app arranca con settings de test, `/health` 200, un request sin token a una ruta protegida → 401 con envelope de error estándar (`ErrorResponse`).
- [ ] **Paso 4: commit** — `git commit -m "services/api: app factory con la cadena de middlewares cosechada y health/ready/metrics"`

### Tarea 4.2 (backend): módulo `tenants` + `auth` + `audit` cableado

**Files:**
- Create: `backend/services/api/app/modules/tenants/{models,schemas,service,router}.py`
- Create: `backend/services/api/app/modules/platform/router.py` (listado cross-tenant para la consola, con sesión de plataforma y permiso `platform:admin`)
- Create: migración `0002_tenants.py`
- Test: `backend/tests/api/test_tenants_crud.py`, `backend/tests/api/test_tenants_provisioning.py`

**Interfaces:**
- Produces (contrato para el frontend): `POST /api/v1/platform/tenants {nombre} → 201 {id, nombre, estado}` · `GET /api/v1/platform/tenants?skip&limit → PagedList<Tenant>` · `PATCH /api/v1/platform/tenants/{id} {nombre?, estado?}` · `DELETE /api/v1/platform/tenants/{id}` (soft delete + org deshabilitada) · `GET /api/v1/tenants/me → {id, nombre, estado}` (el tenant del token).

- [ ] **Paso 1: modelo.** `Tenant` NO hereda `TenantModel` (es tabla de plataforma): `id UUID pk`, `nombre`, `estado` enum (`activo|suspendido|eliminado`), `kc_org_id`, timestamps. Sin RLS (está en la lista de excepciones del test de cobertura → actualizar el test 3.8 añadiendo `tenants` a las tablas de plataforma).
- [ ] **Paso 2: provisioning.** `TenantService.create`: (a) INSERT del tenant (transacción, sesión de plataforma); (b) `create_organization(tenant_id, nombre)`; (c) si KC falla → rollback y error tipado (compensación: no queda tenant sin org). El camino inverso (org creada, INSERT falla) se cubre con `reconcile-keycloak.sh` — documentado en el runbook de la Etapa 5. **La suspensión es app-level** (hallazgo del spike 1.1): `TenantMiddleware`/dependencia consulta `estado` con cache Redis TTL 60s y responde 403 `tenant_suspendido` — cablearlo y testearlo.
- [ ] **Paso 3: TDD del CRUD** con el patrón de tests de API de BaseSaaS (client de test + token fake): crear/listar/renombrar/suspender/borrar; usuario sin `platform:admin` → 403; `GET /tenants/me` con token de organización → el propio; con token de otra org → el suyo y solo el suyo.
- [ ] **Paso 4:** `audit` cableado: cada operación del CRUD emite evento con `tenant_id`, actor y correlation id; test lo verifica leyendo `audit_events` con sesión de plataforma.
- [ ] **Paso 5:** `bash scripts/migrate.sh && uv run pytest tests/api -v` → verde. Congelar `openapi.json` (`curl api/openapi.json > docs/api/openapi-fase0.json`) para el codegen del frontend.
- [ ] **Paso 6: commit** — `git commit -m "Módulo tenants: provisioning INSERT+Organization con compensación, suspensión app-level y auditoría"`

### Tarea 4.3 (backend): worker con OutboxDispatcher + JobScheduler

**Files:**
- Modify: `backend/services/worker/worker/__main__.py` — arranca `OutboxDispatcher` (drena `outbox_messages` → RabbitMQ) y `JobScheduler` (cron con el scope tenant de 3.6) sobre la sesión de plataforma.
- Test: `backend/tests/worker/test_outbox_dispatch.py` (integración: encolar un evento vía `OutboxService` y verlo llegar a una cola de RabbitMQ del compose)

- [ ] **Paso 1:** cablear siguiendo `mail_worker/__main__.py` de BaseSaaS (sin el `MailSendConsumer` — no hay mail transaccional de tenant en Vendi).
- [ ] **Paso 2:** test de integración del ciclo completo outbox→exchange. SIGTERM → apagado limpio (test con timeout).
- [ ] **Paso 3: commit** — `git commit -m "worker: OutboxDispatcher y JobScheduler sobre sesión de plataforma"`

### Tarea 4.4 (backend): `seed.sh` de desarrollo

**Files:**
- Modify: `scripts/seed.sh` — crea (idempotente): roles/grupos de realm (`dueno`, `cajero`, `almacenista`, permisos de policies.py), usuario `admin@vendi.local` con `platform:admin`, un tenant demo "Tienda Don Carlos" vía API con su organización, y un usuario `dueno@demo.vendi.local` miembro de la organización con grupo `dueno`.

- [ ] **Paso 1:** implementar contra la API + kcadm. Correrlo dos veces: la segunda es no-op limpia.
- [ ] **Paso 2:** `verify-setup.sh`: quitar los SKIP de API — ahora chequea `/health/ready` y que el tenant demo existe.
- [ ] **Paso 3: commit** — `git commit -m "seed idempotente: roles de realm, admin de plataforma y tenant demo con su organización"`

### Tarea 4.5 (frontend): `vendi-admin` — login + CRUD de tenants

**Files:**
- Create: `frontend/projects/vendi-admin/src/app/features/tenants/` (listado con `data-table`, formulario alta/edición con `FormRenderer`, acciones suspender/eliminar con `confirm-dialog`)
- Create: shell con `FullLayoutComponent`, guard de `auth`, cliente generado por `codegen-api-client.sh` desde `docs/api/openapi-fase0.json`

- [ ] **Paso 1:** generar el cliente API (`bash scripts/codegen-api-client.sh`) y construir la feature sobre él + `PagedList`.
- [ ] **Paso 2:** login PKCE contra `vendi-co` con clientId `vendi-admin`; usuario sin `platform:admin` ve pantalla de "sin acceso", no una consola vacía.
- [ ] **Paso 3:** specs de componente con `keycloak.fake` + `HttpTestingController`: listar, crear, suspender (con confirmación), error de API → mensaje traducido.
- [ ] **Paso 4:** `ng test vendi-admin --watch=false && ng build vendi-admin` verdes; prueba manual contra el stack: crear tenant desde la UI y verlo en la BD y en KC (organización creada).
- [ ] **Paso 5: commit** — `git commit -m "vendi-admin: login de plataforma y CRUD de tenants contra la API"`

### Tarea 4.6 (frontend): `vendi-tenant` — login con passkey y shell

**Files:**
- Create: `frontend/projects/vendi-tenant/src/app/` shell: `FullLayoutComponent`, guard, página "Mi negocio" que muestra `GET /tenants/me` (nombre, estado, y el `tenantId` resuelto del claim)

- [ ] **Paso 1:** login PKCE con clientId `vendi-web`. El flujo de passkey es del realm (configurado en 2.2): registrar passkey desde el account console o al primer login (required action), login posterior sin contraseña.
- [ ] **Paso 2:** "Mi negocio" consume el cliente generado; con dos organizaciones muestra selector (usa `AuthService.selectTenant`).
- [ ] **Paso 3:** specs con `keycloak.fake`; build verde; prueba manual: login con passkey en Chrome (authenticator virtual o huella real) → ver "Tienda Don Carlos".
- [ ] **Paso 4: commit** — `git commit -m "vendi-tenant: login con passkey del realm y página Mi negocio sobre el claim organization"`

### Tarea 4.7 (frontend): `vendi-app` y `vendi-portal` en estado Fase 0

**Files:**
- Modify: `frontend/projects/vendi-app/` — pantalla única "Vendi — próximamente" SIN login (la auth móvil es el subproyecto 2; dejar comentario-ancla al spec futuro). Verificar `npx cap sync android` y build local del AAB.
- Modify: `frontend/projects/vendi-portal/` — página pública mínima ya limpiada; solo asegurar i18n y build.

- [ ] **Paso 1:** `ng build vendi-app && npx cap sync android && (cd android && ./gradlew bundleDebug)` → produce `.aab` local.
- [ ] **Paso 2: commit** — `git commit -m "vendi-app compila a AAB local sin login; portal mínimo verificado"`

### Superficie de ataque para QA — Etapa 4

- **Provisioning:** matar Keycloak (`docker compose stop keycloak`) y crear un tenant → la API debe devolver error tipado y NO dejar fila huérfana (verificar en BD). Crear dos tenants con el mismo nombre (¿permitido? decidir y testear). Crear tenant, borrar, recrear con el mismo nombre → la organización anterior no colisiona (alias distinto porque tenant_id es nuevo — verificarlo de verdad).
- **Suspensión app-level:** suspender el tenant demo y, con un token EMITIDO ANTES de la suspensión (aún válido), llamar `GET /tenants/me` → 403 en ≤60s (TTL del cache). Reactivar → vuelve el acceso sin re-login.
- **Aislamiento end-to-end:** con dos tenants sembrados, tomar el token del dueño del tenant A y pedir recursos del B por todos los caminos: ids en URL, header `X-Tenant-Id` con alias del B (no siendo miembro) → 400/403, jamás datos. Este es EL test de la etapa.
- **Worker:** encolar 100 eventos y matar el worker a mitad → al reiniciar no hay pérdida ni duplicado no-idempotente visible en la cola. RabbitMQ caído al arrancar el worker → reintenta con backoff, no crash-loop silencioso.
- **Admin UI:** doble click en "Crear" (¿dos tenants?); paginación con 0 y con 201 tenants; token expirado a mitad de sesión → refresh o re-login limpio, no spinner infinito.
- **Passkey:** cancelar el prompt de passkey a mitad → la pantalla de login se recupera. Login con contraseña cuando existe passkey (¿lo permite la policy? ¿debe?). Registrar passkey en dos navegadores para el mismo usuario.
- **Seed:** correr `seed.sh` tres veces; borrar el tenant demo a mano y correrlo de nuevo.

### Criterio de integración — Etapa 4

(1) Los criterios 2 y 3 de Fase 0 del spec se demuestran en vivo ante el arquitecto: login con passkey en `vendi-tenant` y CRUD de tenant completo desde `vendi-admin` con su organización visible en KC; (2) el ataque de aislamiento end-to-end de QA quedó automatizado como test de API (no solo ejercicio manual); (3) `verify-setup.sh` 100% verde sin SKIP; (4) suite backend y frontend verdes; (5) `openapi-fase0.json` commiteado y el cliente generado no tiene ediciones manuales (regenerable: `codegen` + `git diff --exit-code`).

---

# Etapa 5 — CI, AAB, E2E y documentación

**Composición:** dos pistas. Backend: workflows de CI backend + documentación/ADRs/runbooks. Frontend: workflow Android (AAB) + Playwright. La documentación la cierra el arquitecto con insumos de ambas pistas.

### Tarea 5.1 (backend): workflows de CI cosechados

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/e2e.yml`, `.github/workflows/release-images.yml`, `.github/workflows/deploy.yml` — cosechados de `/Users/maoherran/BaseSaaS/.github/workflows/`, adaptados: rutas (`backend/`, `frontend/`, `infra/`), `uv sync`, servicios de test (PG17 con el init de roles, Redis, RabbitMQ, KC 26.6.4 con realm importado para los markers integration), imágenes `vendi-api`/`vendi-worker`.

- [ ] **Paso 1:** adaptar `ci.yml` (lint + tests backend y frontend). Los tests `integration` corren contra services del workflow. El grep-candado de la Etapa 3 (`base_saas|search_path|tenant_slug`) se añade como paso de CI.
- [ ] **Paso 2:** `release-images.yml` construye y publica `vendi-api` y `vendi-worker`. `deploy.yml` queda adaptado al despliegue por compose en la VM CO (secrets documentados, sin valores).
- [ ] **Paso 3:** push a una rama y verificar el run verde en Actions.
- [ ] **Paso 4: commit** — `git commit -m "CI cosechado: lint+tests con servicios reales, release de imágenes y deploy por compose"`

### Tarea 5.2 (frontend): workflow Android — el AAB del criterio 4

**Files:**
- Create: `.github/workflows/android.yml` (NUEVO — BaseSaaS no tiene build móvil; este es trabajo no cubierto por la cosecha)

- [ ] **Paso 1:**

```yaml
name: android
on:
  push: { branches: [main, master] }
  workflow_dispatch: {}
jobs:
  aab:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm, cache-dependency-path: frontend/package-lock.json }
      - uses: actions/setup-java@v4
        with: { distribution: temurin, java-version: 21 }
      - run: npm ci
        working-directory: frontend
      - run: npx ng build vendi-app --configuration production
        working-directory: frontend
      - run: npx cap sync android
        working-directory: frontend
      - run: ./gradlew bundleRelease
        working-directory: frontend/android
      # Fase 0: AAB de prueba sin firmar (o firmado con keystore de debug).
      # La firma de release llega con la publicación en Play (Fase 1).
      - uses: actions/upload-artifact@v4
        with:
          name: vendi-app-aab
          path: frontend/android/app/build/outputs/bundle/release/*.aab
```

- [ ] **Paso 2:** dispararlo con `workflow_dispatch` y descargar el artefacto `.aab`; validar con `bundletool validate` en local.
- [ ] **Paso 3: commit** — `git commit -m "Workflow android: el pipeline produce el AAB de prueba de vendi-app (criterio 4 de Fase 0)"`

### Tarea 5.3 (frontend): Playwright — smoke E2E de Fase 0

**Files:**
- Create: `frontend/e2e/` — cosechar el harness (config, fixtures) de BaseSaaS; escribir DOS specs nuevos (los 11 de BaseSaaS cubren flujos que Vendi descartó — signup, invitaciones — no se portan): `login-passkey.spec.ts` (authenticator virtual WebAuthn vía CDP en Chromium: registrar passkey y re-loguear sin contraseña) y `tenants-crud.spec.ts` (vendi-admin: crear → suspender → eliminar tenant, verificando estados en la UI).

- [ ] **Paso 1:** harness + specs contra el stack local (`dev.sh` + `seed.sh`).
- [ ] **Paso 2:** cablear en `e2e.yml` (de 5.1). Verde en CI.
- [ ] **Paso 3: commit** — `git commit -m "E2E de humo: login con passkey (authenticator virtual) y CRUD de tenants"`

### Tarea 5.4 (backend/arquitecto): documentación de desarrollador, ADRs y correcciones

**Files:**
- Create: `README.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/getting-started.md`, `docs/env-reference.md`, `docs/estado.md`
- Create: `docs/adr/adr-001-capacitor.md` … `docs/adr/adr-016-backend-api-worker.md` (los 10 del plan maestro migrados + los 6 nuevos del spec)
- Create: `docs/runbooks/` — adaptar de los 33 de BaseSaaS los que aplican
- Modify: `docs/plan-maestro.md`, `docs/analisis-comparativo-socios.md`, `docs/plan-tecnico.md` (correcciones §8.1 del spec)

- [ ] **Paso 1: ADRs.** Un archivo por decisión con contexto y consecuencias. Contenido no negociable que sale de este plan:
  - **ADR-013**: el idiom de policy REAL (NULLIF + missing_ok, verificado en el spike 1.2 — el SQL del spec §4.1 se corrige), los dos roles, el reset por `SET vendi.tenant_id=''`, la lista de tablas de plataforma sin RLS, y la nota PgBouncer: si algún día se añade, solo modo transaction pooling (SET LOCAL es compatible; `SET` de sesión no lo es).
  - **ADR-014**: resultados del spike 1.1 (claim, scope default, alias=tenant_id, dominios sintéticos), la consecuencia "suspensión de tenant es app-level, no del IdP", la existencia de Organization Groups (26.6) como alternativa futura NO adoptada, y la decisión sucursales-como-datos.
  - **ADR-016**: bucket único por región con prefijo por tenant; el catálogo §5.3 pendiente como backlog con su porqué.
  - **ADR-003**: consecuencia nueva — Terraform diferido a Fase 2; el compose de producción versionado + `deploy.yml` + runbook de VM son la reproducibilidad interina.
- [ ] **Paso 2: correcciones de documentos.** Las cuatro del spec §8.1 **más una que el spec omitió**: `plan-maestro.md` §7 y `plan-tecnico.md` §8 dicen que Fase 0 incluye "IaC por región" — se corrige a "IaC diferido a Fase 2 (ADR-003); Fase 0 entrega compose versionado", para que la fuente canónica no contradiga la fundación.
- [ ] **Paso 3: runbooks.** Adaptar (lista inicial, ajustar según los 33 reales): incidentes de KC, backup/restore de PG, rotación de certificados, DLQ de RabbitMQ, deploy por compose en la VM, "cómo añadir una tabla de negocio" (usar `enable_rls` SIEMPRE; el test de cobertura te delata), reconcile de organizations. NO portar `orm-alembic-sync.md` (RLS eliminó el problema — dejar una nota de una línea en ARCHITECTURE diciendo por qué no existe).
- [ ] **Paso 4: `docs/estado.md`** — el roadmap de Fase 0→1 con lo realmente entregado, incluida la medición final de la cosecha (LOC reales por categoría vs. la estimación del spec).
- [ ] **Paso 5: commit** — `git commit -m "Documentación de fundación: ADRs 001-016, runbooks adaptados, getting-started y correcciones al plan maestro"`

### Superficie de ataque para QA — Etapa 5

- **CI:** romper un test a propósito en una rama → el workflow falla (verificar que los markers integration de verdad corren y no están silenciosamente skipped: buscar `SKIPPED` en el log de CI). Borrar el cache de npm/uv y medir el run frío.
- **AAB:** instalar el artefacto en un emulador (`bundletool build-apks` + install) y abrir la app. Verificar que el AAB no empaqueta `environment.development.ts` ni URLs de dev (inspeccionar el bundle).
- **E2E:** correr los specs 5 veces seguidas (`--repeat-each=5`): ¿flakes? El spec de passkey debe limpiar su usuario o ser re-entrante.
- **getting-started.md:** seguirlo AL PIE DE LA LETRA en una máquina/carpeta limpia midiendo el tiempo; cada desvío del documento es un bug de la tarea 5.4. Es la prueba de fuego de toda la fundación.
- **Docs:** cada enlace de los ADRs y runbooks resuelve (linkcheck con `grep -o '\[.*\](.*)'` + verificación); `docs/estado.md` no promete nada que un comando no demuestre.

### Criterio de integración — Etapa 5 (= cierre de Fase 0)

Los cuatro criterios del spec §9, demostrados en una sesión de cierre:
1. `verify-setup.sh` pasa todos sus checks en verde.
2. Login con passkey funcionando (manual + spec Playwright verde en CI).
3. CRUD de tenant funcionando (manual + tests de API + spec Playwright verdes).
4. El pipeline de CI produce un AAB de prueba descargable.

Más los del plan: getting-started reproducido en limpio por alguien que no lo escribió; ADRs 001–016 publicados; correcciones a los planes mergeadas; `docs/estado.md` refleja la medición final de la cosecha.

---

## Autorrevisión contra el spec (hecha al escribir el plan)

- §3 cosecha quirúrgica → Etapas 3 (lib), 2 (infra/scripts). El paquete `app/` de base_saas (240 LOC, no listado en el spec) se cubre en 4.1.
- §4.1 RLS → Etapa 1 (spike corrige el idiom), 3.3/3.8 (implementación + candados). §4.2 Organizations → Etapa 1 (spike), 3.4/3.5, 4.2.
- §5.1 layout → 2.1. §5.2 tabla de cosecha → 3.1–3.8 (con las desviaciones anotadas: audit/messaging/storage no son 100% "sin cambios"). §5.3 → solo `tenants|auth|audit|platform` en Fase 0; resto backlog en ADR-016. §5.4 → fuera de alcance (subproyectos).
- §6 frontend → 1.3, 2.4, 3.9–3.12, 4.5–4.7. §6.3 contradicción ESLint → 1.3. §6.4 i18n → 2.4.
- §7 infra/CI → 2.2, 2.3, 5.1, 5.2 (el AAB es workflow nuevo, no cosecha). Terraform diferido → ADR-003 en 5.4.
- §8 documentación → 5.4 (incluida la corrección extra del roadmap "IaC por región").
- §9 verificación → tests candado en 3.8, E2E en 5.3, criterios en el cierre de Etapa 5.
- §10 riesgos → cada riesgo tiene tarea: claim KC (1.1), SET LOCAL olvidado (3.3/3.8), supuestos de schema-per-tenant (grep-candado 3/5.1), keycloak_admin (1.1 + 3.5 temprano), Terraform (5.4).
