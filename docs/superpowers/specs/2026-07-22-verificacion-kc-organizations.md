# Verificación del spike de Keycloak 26.6.4 Organizations

**Tarea:** 1.1 (backend) del plan `2026-07-22-fundacion-fase-0-plan.md`
**Fecha de ejecución:** 2026-07-22
**Entorno:** `quay.io/keycloak/keycloak:26.6.4` efímero (`start-dev`), realm `vendi-co`
**Reproducir:**

```bash
bash scripts/spikes/kc-orgs-spike.sh          # preguntas 1–9 + superficie de QA
node scripts/spikes/kc-passkey-spike.mjs      # pregunta 10 (necesita Playwright/Chromium)
```

El primero corre de cero a tokens decodificados sin intervención manual y deja el
contenedor vivo; el segundo se apoya en el estado que aquel deja.

> **Aviso de lectura.** Este informe **refuta dos supuestos** que el plan daba por
> "hechos ya verificados". Están marcados con ⚠ y son entrada obligatoria de las tareas
> 3.4 y 3.5.

---

## Pregunta 1 — ¿El claim se llama `organization`? ¿Es un mapa por alias?

El claim se llama `organization`, sí. **Su shape es polimórfico y depende de la
configuración del mapper.** Con el mapper tal como viene de fábrica:

```
--- token CON scope=organization — shape POR DEFECTO del claim ---
{
  "iss": "http://localhost:8089/realms/vendi-co",
  "azp": "vendi-web",
  "preferred_username": "cajera1",
  "scope": "openid profile email organization",
  "organization": [
    "1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e"
  ],
  "acr": "1"
}
```

⚠ **Refutación 1.** El plan afirma como hecho verificado que "el claim `organization` es
un **mapa por alias**". Es falso por defecto: es una **lista JSON de alias**. Solo se
convierte en mapa cuando se activa `addOrganizationId` (o `addOrganizationAttributes`)
en el mapper — ver pregunta 7. La configuración de fábrica del mapper es:

```json
{
  "id.token.claim": "true",
  "introspection.token.claim": "true",
  "access.token.claim": "true",
  "claim.name": "organization",
  "jsonType.label": "String",
  "multivalued": "true"
}
```

Consecuencia para la tarea 3.5: `_build_user_context` **debe aceptar las dos formas**.
No basta con fijar el mapper en el realm como código: un despliegue con drift, un realm
importado a medias o un cliente distinto devolverían la lista y el parser reventaría con
`AttributeError` sobre un `list`. El parser correcto:

```python
crudo = claims.get("organization") or {}
if isinstance(crudo, list):          # mapper sin addOrganizationId
    organizations = {alias: "" for alias in crudo}
elif isinstance(crudo, dict):        # mapper con addOrganizationId
    organizations = {alias: (v or {}).get("id", "") for alias, v in crudo.items()}
else:
    organizations = {}
```

## Pregunta 2 — ¿Aparece el claim sin pedir el scope? ¿Se pone como default?

No aparece. El scope `organization` es un client scope **opcional** del realm y del
cliente recién creado:

```
--- default-client-scopes de vendi-web ---
  web-origins / acr / profile / roles / basic / email
--- optional-client-scopes de vendi-web ---
  address / phone / offline_access / organization / microprofile-jwt
```

```
--- token SIN pedir el scope organization (scope=openid) ---
{ ..., "scope": "openid profile email", "organization": null }
```

Tras moverlo a `default-client-scopes`:

```
--- token pidiendo SOLO 'openid': el claim ya viaja sin cooperación del frontend ---
{
  "scope": "openid profile email organization",
  "organization": { "1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e": { "id": "8f6114a3-..." } }
}
```

**Decisión: `organization` va como default client scope de `vendi-web` y `vendi-admin`.**
Pero eso **no es suficiente** — ver pregunta 3.

Y hay una razón técnica adicional para hacerlo default: el scope dinámico
`organization:*` **solo se acepta si el client scope `organization` está asignado al
cliente** (default u opcional). Con el scope desasignado:

```
=== P12 · QA — 'organization:*' cuando el scope NO está asignado al cliente ===
SIN TOKEN → {"error": "invalid_scope", "error_description": "Invalid scopes: openid organization:*"}
```

## Pregunta 3 — Usuario en dos organizaciones

⚠ **Refutación 2, y es la más importante del spike.** Con el usuario en **dos**
organizaciones, el scope `organization` a secas —que es el que se aplica cuando va como
default client scope— devuelve el claim **ausente**:

```
--- scope=openid (organization es DEFAULT) — ¡CLAIM AUSENTE con 2 orgs! ---
{ "scope": "openid profile email organization", "organization": null }

--- scope=openid organization — mismo resultado: claim ausente ---
{ "scope": "openid profile email organization", "organization": null }

--- scope=openid organization:*  — TODAS las organizaciones ---
{
  "scope": "openid profile email organization:*",
  "organization": {
    "1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e": { "id": "8f6114a3-42df-4627-a715-9c9a3cd8da06" },
    "2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f": { "id": "8ae4dbc7-b74e-4190-93d8-50b8fd536725" }
  }
}

--- scope=openid organization:<alias concreto> — solo esa ---
{
  "scope": "openid profile organization:2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f email",
  "organization": { "2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f": { "id": "8ae4dbc7-..." } }
}
```

Interpretación: `organization` a secas significa "la organización en cuyo contexto se
autenticó el usuario". Con una sola membresía se resuelve sola; con dos, no hay contexto
que resolver por grant directo y Keycloak omite el claim en vez de elegir por su cuenta.
No hay pantalla de selección ni error.

Alias inexistente:

```
--- scope=openid organization:<alias inexistente> ---
SIN TOKEN → {"error": "invalid_scope",
             "error_description": "Invalid scopes: openid organization:99999999-9999-9999-9999-999999999999"}
```

**Consecuencias de diseño (entran en ADR-014 y en las tareas 3.4/3.5/4.x):**

1. Los cuatro frontends piden **siempre** `scope=organization:*` (en `keycloak-js`,
   `KeycloakInitOptions.scope`). Depender de `organization` a secas rompe en silencio al
   segundo negocio del mismo dueño — que es justo la persona "Andrea, minimercado ×3"
   del plan maestro.
2. `organization` sigue yendo como **default** client scope, por dos motivos: habilita el
   `organization:*` (probado arriba) y cubre el caso mono-organización aunque el cliente
   no pida nada.
3. El fallo es **cerrado**, no abierto: un usuario multi-org que no pida `organization:*`
   llega al backend con `organizations == {}` y el `TenantMiddleware` responde 403 en
   rutas de tenant. Nadie ve datos de otro. Es un bug de usabilidad, no de aislamiento.
4. **Recomendación para la tarea 3.5 (no la implemento aquí, es de la Etapa 3):** que
   `VendiKeycloakAdmin` exponga un *fallback* `get_user_organizations(user_id)` (existe en
   python-keycloak 7.1.1) con cache corta, que el middleware use **solo** cuando el claim
   venga vacío. Dejar la resolución del tenant a merced de que el frontend recuerde un
   parámetro de scope es frágil para algo de lo que depende el aislamiento.

## Pregunta 4 — ¿Acepta el alias un string con formato UUID?

Sí, con guiones incluidos, sin normalizar ni rechazar:

```
--- org 1: alias = tenant_id (1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e) + dominio sintético ---
HTTP 201
```

Y el alias vuelve literal en el claim y en el listado de la Admin API. **La hipótesis de
diseño `alias = str(tenant_id)` queda confirmada.** No hace falta la alternativa con
columna `kc_org_alias` ni cache de resolución.

Alias duplicado:

```
--- alias DUPLICADO (debe fallar) ---
HTTP 409
{"errorMessage":"A organization with the same alias already exists"}
```

409 limpio, no 500. La creación de tenants es idempotente-friendly: el servicio puede
tratar el 409 como "ya existe" sin parsear stack traces.

## Pregunta 5 — ¿Es obligatorio el dominio?

**No.** La organización se crea sin `domains`:

```
--- ¿es OBLIGATORIO el dominio? (crear una org sin 'domains') ---
HTTP 201
```

El dominio sintético `<tenant_id>.tenants.vendi.local` se acepta sin verificación DNS de
ningún tipo, y el duplicado se rechaza con 400:

```
--- dominio DUPLICADO (debe fallar) ---
HTTP 400
{"errorMessage":"Domain 1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e.tenants.vendi.local is already linked to another organization in realm vendi-co"}
```

**Decisión: se mantiene el dominio sintético `<tenant_id>.tenants.vendi.local`.** No es
obligatorio, pero (a) el patrón es único por construcción, así que el 400 por duplicado
nunca se dispara salvo por un bug de doble alta, y sirve de segunda red; (b) deja abierta
sin migración la puerta al login identity-first por dominio de email corporativo, que
Fase 0 no usa pero el MVP podría querer. Coste: cero.

## Pregunta 6 — ¿Deshabilitar una organización bloquea el login de sus miembros?

**No bloquea el login, pero sí saca a la organización del claim.** Es un matiz que la
hipótesis del plan no anticipaba.

Usuario en org1 (activa) + org2 (deshabilitada):

```
--- cajera1 (org1 activa + org2 deshabilitada) ---
{ "organization": { "1b8e0d4e-...": { "id": "8f6114a3-..." } } }     ← solo la activa
```

Usuario cuya **única** organización está deshabilitada:

```
--- usuario cuya ÚNICA organización está deshabilitada ---
{ "preferred_username": "solodeshab", "scope": "openid profile email", "organization": null }
```

Es decir: el usuario **autentica correctamente** (recibe access token y refresh token,
sesión SSO válida), pero llega al backend sin tenant → el `TenantMiddleware` le dará 403
en rutas de tenant.

**Decisión (se confirma la del plan, con la consecuencia precisada):** la suspensión de
un tenant es un **estado en la tabla `tenants`** que la API consulta, no un switch en el
IdP. Motivos:

- Deshabilitar la organización en Keycloak produce un 403 genérico e indistinguible de
  "no tienes tenant". El usuario merece "tu negocio está suspendido por falta de pago",
  y eso solo lo puede decir la aplicación.
- El efecto **no es inmediato**: un access token ya emitido sigue siendo válido y sigue
  llevando el claim hasta que expira. El estado en `tenants` se consulta por request.
- Sigue habiendo login: la suspensión por IdP no evita el consumo de recursos de
  autenticación ni el brute force.

Deshabilitar la organización queda como **freno complementario** para casos de abuso,
documentado en el runbook, nunca como el mecanismo primario.

## Pregunta 7 — "Add organization id" en el mapper

La opción se llama `addOrganizationId` (y su hermana `addOrganizationAttributes`). Las
propiedades configurables del mapper `oidc-organization-membership-mapper` son:

```
['claim.name=None', 'id.token.claim=true', 'access.token.claim=true',
 'lightweight.claim=false', 'userinfo.token.claim=true', 'introspection.token.claim=true',
 'jsonType.label=String', 'multivalued=true',
 'addOrganizationAttributes=false', 'addOrganizationId=false']
```

Con `addOrganizationId=true` el claim pasa de lista a mapa:

```
--- token con addOrganizationId=true — shape de MAPA alias → {id} ---
{
  "organization": {
    "1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e": { "id": "8f6114a3-42df-4627-a715-9c9a3cd8da06" }
  }
}
```

`addOrganizationAttributes=true` **no aporta nada** cuando la organización no tiene
atributos personalizados: el claim sale idéntico. Se deja en `false` para no engordar el
token (importa en móvil, donde el token viaja en cada request sobre red 3G).

**Decisión:** `addOrganizationId=true` en el realm como código. El `id` interno de la
organización se necesita para las llamadas de la Admin API (`organizations/{id}/members`)
sin un lookup por alias en cada operación.

## Pregunta 8 — ¿Basta `organizationsEnabled=true`?

Sí. La feature es `DEFAULT` y ya viene habilitada; no hay flag de arranque:

```
versión del servidor: 26.6.4
feature ORGANIZATION: {"name": "ORGANIZATION", "label": "Organization support within realms",
                       "type": "DEFAULT", "dependencies": [], "enabled": true}
```

## Pregunta 9 — Login identity-first: ¿cambia la pantalla? ¿Afecta al PKCE?

**Cambia la pantalla; no afecta al protocolo.** Comparativa contra un realm de control
idéntico con `organizationsEnabled=false`:

```
--- campos de la PRIMERA pantalla — realm control-sin-orgs ---
name="login"  name="password"  name="username"

--- campos de la PRIMERA pantalla — realm vendi-co (organizations ON) ---
name="login"  name="username"
```

Con Organizations el flujo `browser` de fábrica ya trae el subflujo que lo provoca:

```
  Organization | ALTERNATIVE
    Browser - Conditional Organization | CONDITIONAL
      Condition - user configured | REQUIRED
      Organization Identity-First Login | ALTERNATIVE
  forms | ALTERNATIVE
    Username Password Form | REQUIRED
```

El login pasa a **dos pantallas**: usuario, luego contraseña. El flujo PKCE estándar
funciona sin cambios de extremo a extremo, incluido un usuario que no llega por dominio
de email:

```
--- completar el flujo: usuario → contraseña → code → token ---
campos de la SEGUNDA pantalla: name="login" name="password"
code recibido: 9d7e9a7d-fcff-ed95-96fd-...
{
  "iss": "http://localhost:8089/realms/vendi-co",
  "azp": "vendi-web",
  "scope": "openid organization:* profile email",
  "organization": { "1b8e0d4e-...": {...}, "2c9f1e5f-...": {...} },
  "acr": "1"
}
```

Y el PKCE es obligatorio de verdad con `pkce.code.challenge.method=S256` en el cliente:

```
--- PKCE obligatorio: la misma petición sin code_challenge ---
Location: http://localhost/cb?error=invalid_request&error_description=Missing+parameter%3A+code_challenge_method&...
```

**Consecuencias:** (a) el tema `vendi` de la tarea 2.2 tiene que maquetar **dos**
pantallas, no una; (b) los E2E de la Etapa 5 tienen que teclear usuario, enviar, y
teclear contraseña — cualquier test escrito contra una pantalla única fallará; (c) para
`vendi-app` (móvil) son dos pasos en el navegador del sistema.

## Pregunta 10 — WebAuthn passwordless (passkeys) junto a Organizations

**Conviven sin fricción.** Verificado con un autenticador virtual de Chrome vía CDP
(`WebAuthn.addVirtualAuthenticator`, `transport: internal`, resident key + user
verification), que es el equivalente automatizable de `chrome://webauthn-internals`.

Configuración del realm (la aplica `kc-orgs-spike.sh`):

```json
{
  "webAuthnPolicyPasswordlessRpEntityName": "Vendi",
  "webAuthnPolicyPasswordlessRpId": "",
  "webAuthnPolicyPasswordlessSignatureAlgorithms": ["ES256", "RS256"],
  "webAuthnPolicyPasswordlessRequireResidentKey": "Yes",
  "webAuthnPolicyPasswordlessUserVerificationRequirement": "required",
  "webAuthnPolicyPasswordlessAttestationConveyancePreference": "none",
  "webAuthnPolicyPasswordlessCreateTimeout": 60
}
```

Las required actions vienen habilitadas de fábrica:

```
  webauthn-register enabled= True default= False
  webauthn-register-passwordless enabled= True default= False
```

El flujo `browser` de fábrica **no** sirve tal cual: hay que construir uno que combine el
subflujo de Organizations con passkey y fallback a contraseña. Estructura final que deja
el spike (y que replicará `infra/keycloak/realm-vendi-co.json`):

```
  Cookie | ALTERNATIVE
  Kerberos | DISABLED
  Identity Provider Redirector | ALTERNATIVE
  browser-passwordless Organization | ALTERNATIVE
    browser-passwordless Browser - Conditional Organization | CONDITIONAL
      Condition - user configured | REQUIRED
      Organization Identity-First Login | ALTERNATIVE
  browser-passwordless forms | ALTERNATIVE
    Username Form | REQUIRED
    passkey-o-password | REQUIRED
      WebAuthn Passwordless Authenticator | ALTERNATIVE
      Password Form | ALTERNATIVE
    browser-passwordless Browser - Conditional 2FA | CONDITIONAL
      ...
```

**Camino equivocado que se descartó con evidencia:** poner `WebAuthn Passwordless
Authenticator` como `REQUIRED` en lugar del subflujo con alternativas. Un usuario sin
passkey queda encerrado fuera:

```
"We are sorry... Cannot login, credential setup required."
```

Con el subflujo de alternativas, el usuario sin passkey entra con contraseña sin tocar
nada (verificado por HTTP en el propio `kc-orgs-spike.sh`):

```
--- fallback verificado por HTTP: usuario SIN passkey sigue pudiendo entrar con contraseña ---
pantalla 1: name="login" name="username"
pantalla 2: name="login" name="password"
```

Salida de `kc-passkey-spike.mjs` (registro + login sin contraseña + claim intacto):

```
Autenticador virtual: 4fbec6d7-06ff-4ce0-b648-99724227f227

=== 1. Registro de la passkey (entrando con contraseña) ===
pantalla 1 — campos: [ 'username:text' ]
pantalla 2 — campos: [ ':text', 'password:password' ]
pantalla 3 — texto: VENDI-CO | Registro de Passkey | Cerrar sesión en otros dispositivos | Registrarse
registro completado, redirigido a: https://localhost/cb?session_state=8WdiKIwSDm--YfocfQYbx23s&...
credenciales del usuario: password(-), webauthn-passwordless(Passkey del spike)

=== 2. Login SIN contraseña con la passkey ===
pantalla 2 — pide contraseña: true
   → Keycloak ofrece primero la credencial por defecto del usuario;
     se cambia con "Try Another Way".
opciones: VENDI-CO | Seleccione el método de inicio de sesión | Usuario o email |
          Contraseña | Inicie sesión ingresando su contraseña. |
          Passkey | Use su Passkey para iniciar sesión sin contraseña.
LOGIN PASSWORDLESS OK · claims relevantes:
{
  "scope": "openid profile email organization:*",
  "acr": "1",
  "organization": {
    "1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e": { "id": "8f6114a3-42df-4627-a715-9c9a3cd8da06" },
    "2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f": { "id": "8ae4dbc7-b74e-4190-93d8-50b8fd536725" }
  }
}

=== 3. Passkey como credencial por defecto (moveToFirst) ===
moveToFirst → 204
pantalla 2 — pide contraseña: false
pantalla 2 — ofrece passkey: true
LOGIN PASSWORDLESS DIRECTO OK · organization: {"1b8e0d4e-...":{...},"2c9f1e5f-...":{...}}
```

**Hallazgo de UX con consecuencia operativa:** cuando el usuario tiene contraseña *y*
passkey, Keycloak ofrece en la segunda pantalla la credencial que esté **primera en la
lista de credenciales del usuario**, y deja la otra tras "Try Another Way". Como la
contraseña se crea antes, por defecto gana la contraseña. La passkey solo se convierte en
el camino por defecto tras
`POST /admin/realms/vendi-co/users/{id}/credentials/{credId}/moveToFirst`.

**Decisión:** el servicio de alta de usuario (Etapa 4) llama a `moveToFirst` justo
después de que se registre una passkey, y la required action
`webauthn-register-passwordless` se asigna al usuario en su alta para que la registre en
el primer login. La contraseña se conserva como recuperación.

---

## Superficie de ataque de QA — cobertura

| Ataque pedido en el plan | Dónde se responde | Resultado |
|---|---|---|
| Usuario en **cero** organizaciones | `P10` del script | Claim ausente, login OK |
| Usuario en **dos** organizaciones | `P9` | ⚠ claim ausente sin `organization:*` |
| `scope=organization:<alias inexistente>` | `P9` | `invalid_scope`, sin token |
| Alias duplicado | `P4` | HTTP 409 |
| Dominio duplicado | `P4` | HTTP 400 |
| Organización **sin** dominio | `P4` | HTTP 201 — no es obligatorio |
| Claim tras **refresh token** | `P11` | Sobrevive íntegro sin reenviar el scope |

Evidencia del refresh:

```
--- access_token inicial ---
{ "scope": "openid profile email organization:*",
  "organization": { "1b8e0d4e-...": {...}, "2c9f1e5f-...": {...} } }
--- tras grant_type=refresh_token SIN reenviar el scope ---
{ "scope": "openid profile email organization:*",
  "organization": { "1b8e0d4e-...": {...}, "2c9f1e5f-...": {...} } }
```

## Hallazgo no previsto: `Account is not fully set up`

Los usuarios creados por la Admin API **sin `firstName`/`lastName`** no pueden
autenticarse: el perfil de usuario declarativo del realm los exige y dispara
`VERIFY_PROFILE`.

```
SIN TOKEN → {"error": "invalid_grant", "error_description": "Account is not fully set up"}
```

Consecuencia para la tarea 3.5: `VendiKeycloakAdmin.create_user()` envía siempre
`firstName`, `lastName`, `email` y `emailVerified`, o el alta produce usuarios que no
pueden entrar y el error no dice por qué.

## Dependencia verificada: python-keycloak

`/Users/maoherran/BaseSaaS/backend/.venv` → `python_keycloak 7.1.1`. Métodos presentes en
`keycloak_admin.py` (versión síncrona y `a_*` asíncrona de cada uno):

```
get_organizations · create_organization · delete_organization
get_user_organizations · get_organization_members · get_organization_members_count
organization_user_add · organization_user_remove
```

No hay que bajar a REST crudo para nada de lo que Fase 0 necesita.

---

## Decisiones que fija este spike

1. **Claim:** `organization`. **Shape: polimórfico.** Lista de alias por defecto; mapa
   `alias → {"id": ...}` con `addOrganizationId=true`. El realm como código fija
   `addOrganizationId=true`; el parser de `vendi-core` acepta ambas formas.
2. **Scope:** `organization` como **default client scope** de `vendi-web` y `vendi-admin`
   (requisito técnico para poder usar `organization:*`). Los frontends piden **siempre**
   `scope=organization:*` en `keycloak-js`; sin él, un usuario multi-organización llega
   sin claim.
3. **Alias = `str(tenant_id)`.** Confirmado: Keycloak acepta el UUID con guiones como
   alias y lo devuelve literal. No hace falta columna `kc_org_alias` ni cache de
   resolución.
4. **Dominio:** `<tenant_id>.tenants.vendi.local`, sintético y verified. No es
   obligatorio; se mantiene por unicidad y por dejar abierta la puerta al identity-first
   por dominio de email.
5. **Suspensión de tenant: a nivel de aplicación**, estado en la tabla `tenants`.
   Deshabilitar la organización en Keycloak no impide el login (solo saca la organización
   del claim) y no surte efecto hasta que expira el access token vigente.
6. **`addOrganizationAttributes`: `false`.** No aporta nada sin atributos personalizados y
   engorda el token.
7. **Passkeys:** policy `webAuthnPolicyPasswordless*` con ES256/RS256, resident key `Yes`,
   user verification `required`, attestation `none`, timeout 60 s. Flujo
   `browser-passwordless` = `Username Form` (REQUIRED) + subflujo `passkey-o-password`
   (REQUIRED) con `WebAuthn Passwordless Authenticator` y `Password Form` ambos
   ALTERNATIVE. **Nunca** WebAuthn como REQUIRED suelto. Tras registrar la passkey, se
   llama a `moveToFirst` para que sea la credencial por defecto.
8. **Feature flag:** ninguno. `organizationsEnabled=true` en el realm basta en 26.6.4.
9. **Login identity-first:** dos pantallas. El tema y los E2E se diseñan para dos pasos.
   PKCE S256 obligatorio y funcionando.
10. **Alta de usuarios:** `firstName` y `lastName` obligatorios o el login falla con
    `Account is not fully set up`.

Sin pendientes.

## Correcciones que la Etapa 3 debe aplicar a ADR-014

1. Sustituir "el claim `organization` es un mapa por alias" por "el claim es una lista de
   alias; se vuelve mapa solo con `addOrganizationId=true`; el parser acepta ambos".
2. Añadir: "`scope=organization` a secas no resuelve nada cuando el usuario pertenece a
   más de una organización; todos los clientes piden `organization:*`".
3. Precisar la consecuencia de la suspensión: deshabilitar la organización **no** bloquea
   el login, solo elimina la organización del claim, y no invalida tokens ya emitidos.
