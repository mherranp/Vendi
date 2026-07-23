# Keycloak de Vendi — realm como código

El archivo `realm-vendi-co.json` es la definición completa del realm regional
`vendi-co`. Se monta en `/opt/keycloak/data/import/` y se importa con
`start-dev --import-realm` (ver `infra/docker-compose.yml`).

Se derivó del realm que dejó el **spike 1.1** (`scripts/spikes/kc-orgs-spike.sh`)
mediante `POST /admin/realms/vendi-co/partial-export`, de modo que la
configuración que el informe
`docs/superpowers/specs/2026-07-22-verificacion-kc-organizations.md` verificó
con evidencia es literalmente la que se despliega — no una reconstrucción a
mano que "debería" comportarse igual.

## Lo que fija este realm

| Decisión del spike | Dónde se ve en el JSON |
|---|---|
| `organizationsEnabled: true` (sin feature flag de arranque) | raíz |
| Claim `organization` como **mapa** alias→`{id}` | `clientScopes[organization].protocolMappers[0].config.addOrganizationId = "true"` |
| `addOrganizationAttributes: false` (no engordar el token) | mismo mapper |
| Scope `organization` como **default** del realm y de los clientes | `defaultDefaultClientScopes` y `defaultClientScopes` de `vendi-web` / `vendi-admin` |
| Alias = `str(tenant_id)` | no es configuración: lo aplica el servicio de alta (tarea 4.2) |
| Passkeys: policy `webAuthnPolicyPasswordless*` | raíz (`ES256`/`RS256`, resident key `Yes`, user verification `required`, attestation `none`, 60 s) |
| Flujo `browser-passwordless` con `passkey-o-password` (ambos ALTERNATIVE) | `authenticationFlows` + `browserFlow` |
| Login identity-first de **dos pantallas** | consecuencia del subflujo `Organization` en el flujo de navegador |
| `bruteForceProtected: true` | raíz (`failureFactor: 10`, más estricto que el default 30) |
| `loginTheme: vendi`, `defaultLocale: es` | raíz |

## Clientes

| Cliente | Tipo | Para qué | ROPC (`directAccessGrants`) |
|---|---|---|---|
| `vendi-web` | público, PKCE S256 | `vendi-tenant` (web) y `vendi-app` (Capacitor) | **sí** — ver más abajo |
| `vendi-admin` | público, PKCE S256 | consola de plataforma | no |
| `vendi-backend` | confidencial, cuenta de servicio | la API administra organizaciones y usuarios | no |

### Roles de la cuenta de servicio de `vendi-backend`

**Exactamente dos**: `manage-realm` y `manage-users`. Ni uno más. No lleva
`impersonation`, ni `realm-admin`, ni los `view-*`/`query-*` (son redundantes:
`manage-users` ya cubre buscar y leer usuarios).

Ese conjunto no se eligió a ojo: se **midió** con
`scripts/spikes/kc-sa-roles-spike.sh`, que levanta un Keycloak 26.6.4 con este
mismo realm y ejecuta la secuencia completa de alta de un tenant con cinco
conjuntos de roles distintos. Resultados relevantes:

```
S1 · solo manage-users/view-*/query-*   (lo "mínimo" intuitivo)
  NO  403  POST /organizations (alta de tenant)
  NO  403  GET /organizations (reconcile)     ← ni siquiera puede LEER

S3 · manage-realm + manage-users        (el mínimo real, el que se usa)
  OK  201  POST /organizations · OK 201 POST /users · OK 201 members
  OK  201  POST /groups · OK 204 role-mappings/realm
  NO  403  !! POST /users/{id}/impersonation
  NO  403  !! POST /clients
  OK  204  !! PUT /realms/vendi-co             ← riesgo residual documentado
```

Conclusión que hay que tener presente antes de "recortar más": en Keycloak
26.6.4 **la API de Organizations exige `manage-realm` incluso para GET**. No hay
rol intermedio. El riesgo residual (poder reescribir ajustes del realm) está
registrado como deuda **D-02** en `docs/deuda-tecnica.md`, con su mitigación.

`verify-setup.sh` (check 21) falla si la cuenta de servicio acumula un rol de
más, y `reconcile-keycloak.sh` lo reporta como deriva.

> **Endurecimiento pendiente para producción — deuda D-01, vence en la Etapa 5.**
> `vendi-web` tiene el grant de contraseña (ROPC) habilitado a propósito: los
> scripts de siembra y los tests de integración necesitan un camino
> determinista para obtener un token de usuario, y el flujo de navegador es de
> dos pantallas con passkey opcional — no se automatiza sin navegador. El
> arquitecto lo ratificó como temporal. La fecha de vencimiento, las dos
> opciones de cierre y cómo se verifica están en `docs/deuda-tecnica.md`.

## Sustitución de variables

El JSON contiene `${VENDI_BACKEND_CLIENT_SECRET}` y `${VENDI_BASE_DOMAIN}`.
**No funcionan solas**: Keycloak solo sustituye placeholders si se arranca con

```
KC_SPI_IMPORT_SINGLE_FILE_REPLACE_PLACEHOLDERS=true
```

que el compose ya pone. Medido contra 26.6.4: sin ese flag el cliente
`vendi-backend` acaba con el **literal** `${VENDI_BACKEND_CLIENT_SECRET}` como
secreto, y nadie se entera hasta que falla la primera llamada de la API.

```
$ docker exec kc /opt/keycloak/bin/kcadm.sh get clients -r vendi-co -q clientId=vendi-backend --fields secret
# sin el flag:
[ { "secret" : "${VENDI_BACKEND_CLIENT_SECRET}" } ]
# con el flag:
[ { "secret" : "secreto-de-prueba-123" } ]
```

Los `${...}` que Keycloak no sabe resolver (`${client_account}`,
`${organizationScopeConsentText}`, ... que son claves de mensajes del propio
Keycloak) se quedan intactos: el flag no los rompe. También verificado.

## Drift: `--import-realm` NO reconcilia

`--import-realm` importa **solo si el realm no existe**. Verificado:

```
2026-07-23 05:30:38 INFO  [ImportUtils] Realm 'vendi-co' imported
   (reinicio del contenedor)
2026-07-23 05:31:36 INFO  [ImportUtils] Realm 'vendi-co' already exists. Import skipped
```

Consecuencias operativas, en orden de probabilidad de morderte:

1. Si alguien borra o cambia un cliente desde la consola de Keycloak,
   **reiniciar no lo arregla**. `scripts/reconcile-keycloak.sh` lo **detecta**
   (clientes, flujos, ajustes del realm y roles de la cuenta de servicio) y
   dice exactamente qué cambió; **corregirlo es del operador**: con `kcadm`
   reflejando el cambio en el JSON, o borrando el realm para que se reimporte
   (y perdiendo usuarios y organizaciones). La corrección automática de
   configuración NO existe y no está prevista en Fase 0 — deuda D-03 en
   `docs/deuda-tecnica.md`. Ejemplo de salida real tras tocar cosas a mano:

   ```
   [AVISO] deriva de configuración (3 hallazgo(s)):
       - cliente 'vendi-admin'.directAccessGrantsEnabled: el JSON dice False y el realm vivo tiene True
       - cliente 'colado-a-mano': existe en el realm y NO está en el JSON (creado a mano)
       - cuenta de servicio de 'vendi-backend' · roles de realm-management: sobran ['impersonation']
   ```
2. Si editas `realm-vendi-co.json`, un `docker compose restart keycloak` no
   aplica el cambio. Para desarrollo: `docker compose down -v` (destruye TODO,
   incluidos usuarios y organizaciones) o aplicar el cambio con `kcadm` y
   reflejarlo también en el JSON.
3. En producción el JSON es la semilla del día 1, no el estado deseado
   continuo. El estado deseado continuo lo mantiene `reconcile-keycloak.sh`.
   Los usuarios, credenciales y organizaciones creados en caliente viven solo
   en la base `keycloak` de Postgres: su respaldo y restauración están en
   `docs/respaldo-y-restauracion.md`.

## Roles y grupos de negocio

`dueno`, `cajero` y `almacenista` **no** están en este archivo. Los crea
`scripts/seed.sh` de forma idempotente (tarea 4.4) precisamente por el punto
anterior: tienen que poder crearse también sobre un realm ya arrancado, donde
el import ya no vuelve a correr.

## Tema

`vendi-theme/` es una cosecha **solo de la capa de estilos** del tema
`basesaas-theme` de BaseSaaS. El porqué está comentado en
`vendi-theme/login/theme.properties`: con Organizations el login es
identity-first (dos pantallas), y las plantillas FreeMarker de BaseSaaS están
escritas para una sola pantalla con usuario y contraseña juntos.

Dos cosas que costaron sangre y conviene no volver a romper:

1. **`styles=` reemplaza, no acumula.** `styles=css/vendi.css` a secas dejaba
   fuera el `css/login.css` del tema padre y la pantalla se veía con PatternFly
   crudo. La línea correcta es `styles=css/login.css css/vendi.css`, con la
   nuestra al final para ganar en cascada.
2. **El marcado es PatternFly v4 + clases heredadas de v3**, no v5. Los
   selectores válidos son `pf-c-*`, `card-pf`, `login-pf-page`, `form-group` y
   los `#kc-*`. Los `pf-v5-c-*` no casan con nada en 26.6.4.

Comprobación rápida de que el tema se está aplicando de verdad (no basta con
que el CSS cargue: hay que mirar el estilo calculado):

```js
// en la consola del navegador, sobre la pantalla de login
getComputedStyle(document.querySelector('#kc-login')).backgroundColor
// → "rgb(0, 92, 187)"   (--vd-primario). Si sale gris, el tema no se aplicó.
[...document.styleSheets].map(s => (s.href||'').split('/').pop())
// → [..., "login.css", "vendi.css"]
```
