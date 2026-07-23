# Deuda técnica de Fase 0

Registro de las decisiones que se toman **a sabiendas de que están mal**, con
quién las tomó, por qué, y **cuándo dejan de ser aceptables**. Una deuda sin
fecha de vencimiento no es deuda: es una decisión permanente que nadie firmó.

Cada entrada se cierra borrándola de aquí y dejando la evidencia de que el
arreglo funciona (comando + salida), no marcándola como "hecha".

| # | Deuda | Vence | Dueño |
|---|---|---|---|
| D-01 | ROPC activo en `vendi-web` | Etapa 5 (cierre de Fase 0) | backend |
| D-02 | `manage-realm` en Keycloak (mitigado en la Etapa 3: partido en dos clientes) | Fase 1 (o cuando Keycloak permita acotar Organizations) | backend |
| D-03 | El realm es semilla, no estado deseado continuo | Fase 1 | backend |
| D-04 | Keycloak arranca sin `--optimized` en producción | Etapa 5 (imagen propia) | backend |

> Runbooks operativos relacionados: el procedimiento completo de respaldo y
> restauración (qué se vuelca, qué NO, y cómo se promueve una copia a base
> viva) está en [`docs/respaldo-y-restauracion.md`](respaldo-y-restauracion.md).

---

## D-01 · ROPC (`directAccessGrantsEnabled`) activo en el cliente `vendi-web`

**Qué es.** El cliente público `vendi-web` acepta el grant de contraseña: con
`client_id`, usuario y contraseña se obtiene un token sin pasar por el
navegador. Ratificado por el arquitecto como temporal.

**Por qué está.** Los tests de integración y `scripts/seed.sh` (tarea 4.4)
necesitan un camino determinista para obtener un token de usuario. El flujo de
navegador del realm es identity-first —dos pantallas— con passkey opcional, y
no se automatiza sin navegador.

**Qué lo hace tolerable hoy.** El realm tiene `bruteForceProtected: true` con
`failureFactor: 10`, el stack de desarrollo solo escucha en loopback
(`TRAEFIK_BIND` por defecto `127.0.0.1`) y no hay usuarios reales.

**Qué lo vuelve inaceptable.** El primer usuario real. Un cliente público con
ROPC convierte cualquier fuga de contraseña en acceso directo, sin segundo
factor y sin la protección del flujo de navegador (passkey, consentimiento,
detección de dispositivo).

**Vencimiento: Etapa 5 del plan de Fase 0.** Antes de abrir Vendi al público
hay que ejecutar una de estas dos, y dejarlo escrito:

1. Apagar `directAccessGrantsEnabled` en `vendi-web` y mover los tests y la
   siembra a un cliente `vendi-pruebas` que solo exista en el realm de
   desarrollo (no en el JSON de producción). **Opción preferida.**
2. Dejarlo con protección de fuerza bruta como única defensa, firmado
   explícitamente por el arquitecto y con una alerta en Grafana sobre
   `LOGIN_ERROR` del grant `password`.

**Cómo se verifica que sigue siendo cierto lo que dice este documento:**

```bash
docker compose -f infra/docker-compose.yml exec -T postgres true   # stack arriba
bash scripts/reconcile-keycloak.sh    # compara el realm vivo con el JSON
python3 -c "import json;d=json.load(open('infra/keycloak/realm-vendi-co.json'));\
print({c['clientId']:c.get('directAccessGrantsEnabled') for c in d['clients'] if c['clientId'].startswith('vendi')})"
# → {'vendi-web': True, 'vendi-admin': False, 'vendi-backend': False, 'vendi-provisioning': False}
```

---

## D-02 · `manage-realm` en la cuenta de servicio de Keycloak

> **Actualizado en la Etapa 3 (pista backend): mitigado parcialmente.** El
> privilegio está partido en dos credenciales. La deuda **no se cierra** —sigue
> existiendo una credencial con `manage-realm` en el mismo proceso— pero deja de
> estar en el cliente que usa toda la API. Lo nuevo está al final, en
> «Mitigación aplicada».

**Qué es.** La cuenta de servicio lleva dos roles de `realm-management`:
`manage-realm` y `manage-users`. `manage-realm` permite además modificar
ajustes del realm y leer los flujos de autenticación.

**Por qué está.** No es una elección: en Keycloak 26.6.4 **toda** la API de
Organizations exige `manage-realm`, incluso para leer. Medido con
`scripts/spikes/kc-sa-roles-spike.sh`:

```
S1 · lo que pedía el QA: solo manage-users/view-*/query-*
  NO  403  POST /organizations (alta de tenant)
  NO  403  GET /organizations (reconcile)

S3 · mínimo teórico: manage-realm + manage-users
  OK  201  POST /organizations (alta de tenant)
  OK  200  GET /organizations (reconcile)
  ...
  NO  403  !! POST /users/{id}/impersonation
  NO  403  !! POST /clients
  OK  204  !! PUT /realms/vendi-co   ← el riesgo residual
```

**Lo que sí se cerró** (esto ya no es deuda): `impersonation`, `view-realm`,
`view-users`, `query-users` y `query-groups` se quitaron. El backend ya **no
puede suplantar usuarios** ni crear clientes. De 7 roles a 2.

**Riesgo residual — medido, no estimado.** La redacción anterior de este
apartado («puede reescribir ajustes del realm y *leer* los flujos de
autenticación») se quedaba corta y hacía parecer el riesgo menor de lo que es.
Ejecutado contra el realm vivo con el secreto real de `vendi-backend`
(`grant_type=client_credentials`), y revertido después:

```
GET  /admin/realms/vendi-co/authentication/flows   -> 200   (lee los flujos)
POST /admin/realms/vendi-co/authentication/flows   -> 201   (CREA flujos)
PUT  /admin/realms/vendi-co                        -> 204   (bruteForceProtected:false + registrationAllowed:true)
```

Es decir, quien comprometa el secreto de `vendi-backend` **no solo lee**: puede
**crear flujos de autenticación y reenlazar `browserFlow`** (sacando el login
con passkey y poniendo uno propio), **apagar la protección de fuerza bruta** y
**abrir el auto-registro público** del realm. Combinado con `manage-users`, eso
es un camino completo a cuenta de administrador de cualquier tenant sin tocar
`realm-admin`.

Lo que sigue **sin** poder hacer: crear clientes (`POST /clients` → 403),
suplantar usuarios (`POST /users/{id}/impersonation` → 403) y asignarse
`realm-admin`.

Nota sobre el spike: `scripts/spikes/kc-sa-roles-spike.sh` marca
`GET /authentication/flows` como «DEBE ser 403» y devuelve 200 en los cinco
conjuntos, incluido el de solo lectura. La expectativa del spike es la
equivocada, no el resultado: en Keycloak 26.6.4 ese endpoint lo cubre
`view-realm`, que `manage-realm` incluye. Queda anotado para que nadie lo lea
como un fallo pendiente.

**Vencimiento: Fase 1**, o antes si Keycloak publica permisos granulares para
Organizations (`admin-fine-grained-authz:v2` todavía no cubre ese recurso).

---

### Mitigación aplicada en la Etapa 3: dos clientes confidenciales

**Lo que se midió primero.** La pregunta que decide todo es: ¿qué necesita de
verdad la API general, y se puede tener sin `manage-realm`? Matriz ejecutada
contra el realm vivo de `vendi-co` (Keycloak 26.6.4, por
`https://accounts.vendi.co`) creando un cliente sonda y rotándole los roles:

```
=== C1 · solo manage-users ===                     === C3 · manage-realm + manage-users ===
  NO 403  GET /organizations                         OK 200  GET /organizations
  NO 403  GET /organizations/{id}                    OK 200  GET /organizations/{id}
  NO 403  GET /organizations/members/{id}/organizations   OK 200  (idem)
  NO 403  GET /organizations/{id}/members            OK 200  GET /organizations/{id}/members
  OK 200  GET /users/{id}                            OK 200  GET /users/{id}
  NO 403  GET /roles                                 OK 200  GET /roles
  OK 200  GET /groups                                OK 200  GET /groups

=== C2 · manage-users + view-users + query-* ===   === C4 · solo manage-realm ===
  (idéntico a C1: los view-*/query-* no aportan       OK 200  GET /organizations …
   nada sobre Organizations)                          NO 403  GET /users/{id}
                                                      NO 403  GET /groups
```

Conclusión: se confirma que **no hay subconjunto de roles de `realm-management`
que dé acceso a Organizations sin `manage-realm`**, ni siquiera de lectura.

**El hallazgo que decidió el diseño.** `GET /organizations/members/{id}/organizations`
—el endpoint de `get_user_organizations`, que el informe del spike 1.1
recomendaba como *fallback* del `TenantMiddleware` cuando el claim viene
vacío— **también exige `manage-realm`**. Es decir: implementar ese fallback
costaba poner `manage-realm` en el camino de cada petición de la API. Se
descartó. Lo que arregla —un usuario multi-organización cuyo cliente olvidó
pedir `scope=organization:*`— ya **falla cerrado** (403, nadie ve datos ajenos);
lo que costaba es la capacidad de reescribir el realm entero desde cualquier
petición. En su lugar, el 403 lleva el código `sin_organizacion_en_token` y un
mensaje que dice qué falta, para que el frontend pueda reaccionar.

> Nota de ruta, por si alguien la busca: `GET /users/{id}/organizations` **no
> existe** en 26.6.4 y devuelve 404 con cualquier privilegio. La ruta buena es
> `/organizations/members/{user_id}/organizations`, que es la que usa
> python-keycloak 7.1.1.

**Qué se implementó.** El privilegio se parte en dos credenciales:

| Cliente | Roles de `realm-management` | Quién lo usa |
| --- | --- | --- |
| `vendi-backend` | `manage-users` | La API general (`VendiKeycloakAdmin`) |
| `vendi-provisioning` | `manage-realm` + `manage-users` | Solo el alta y baja de negocios (`VendiKeycloakAprovisionamiento`) y `reconcile-keycloak.sh` |

Efecto medido tras el cambio, con los secretos reales por
`grant_type=client_credentials`:

```
=== vendi-backend (API general) ===        === vendi-provisioning (alta de negocios) ===
  NO 403  GET  /organizations                OK 200  GET  /organizations
  OK 200  GET  /users                        OK 200  GET  /users
  NO 403  GET  /authentication/flows         OK 200  GET  /authentication/flows
  NO 403  PUT  /realms/vendi-co              OK 204  PUT  /realms/vendi-co
  NO 403  POST /clients                      NO 403  POST /clients
```

**Qué compra y qué no — sin adornos.** Compra: si el secreto de `vendi-backend`
se filtra por un canal estrecho (una línea de log, un volcado de configuración,
una traza de excepción sin sanear, un backup), el atacante obtiene gestión de
usuarios, **no** reescritura del realm — ni crear flujos de autenticación, ni
reenlazar `browserFlow` para sacar la passkey, ni apagar la protección de fuerza
bruta, ni abrir el auto-registro.

**No compra** protección contra ejecución de código en el proceso de la API: hoy
las dos credenciales viven en el mismo contenedor, así que un RCE se lleva las
dos. Decir lo contrario sería vender teatro. Cerrar eso exige mover el
aprovisionamiento a otra unidad de despliegue, y eso cambia el contrato de la
tarea 4.2 (el alta de negocio es síncrona y compensada), así que **queda como el
paso siguiente de esta deuda**, no como algo hecho.

**Qué lo mantiene honesto:**

- `verify-setup.sh` check 21 comprueba **las dos** cuentas de servicio y falla
  si a `vendi-backend` le aparece un rol de más.
- `backend/tests/test_keycloak_admin_orgs.py::test_el_cliente_de_la_api_no_alcanza_organizations`
  se pone rojo si alguien devuelve `manage-realm` a `vendi-backend`.
- `reconcile-keycloak.sh` detecta la deriva de roles contra el JSON del realm.
- El secreto de cada cliente se rota en cada despliegue, y **son distintos**:
  dos credenciales con el mismo valor son una credencial.

**Trampa de la que hay constancia:** la columna `description` de un cliente es
`varchar(255)` en Keycloak. Un texto más largo revienta el import del realm con
un 500 y un `BatchUpdateException` de JDBC, no con un error de validación. Las
descripciones de los dos clientes están recortadas por eso; el porqué largo vive
aquí.

---

## D-03 · El realm de Keycloak es semilla, no estado deseado continuo

**Qué es.** `--import-realm` importa `realm-vendi-co.json` **solo si el realm no
existe**. Un cambio en el JSON no se aplica reiniciando.

**Qué se hizo.** `scripts/reconcile-keycloak.sh` **detecta** la deriva de
clientes, flujos, ajustes del realm y roles de la cuenta de servicio
(`scripts/lib/kc_deriva_config.py`), y la de organizaciones contra la tabla
`tenants`.

**Qué falta.** Aplicar las correcciones de configuración automáticamente. Hoy
el script informa y el operador decide, porque corregir configuración de realm
a ciegas puede tirar sesiones y credenciales.

**Vencimiento: Fase 1**, cuando haya más de un entorno desplegado y la deriva
deje de ser hipotética.

**Ocurrencia real (2026-07-23).** El renombrado de `vendi.local` a `vendi.co`
lo demostró en vivo: cambiar `BASE_DOMAIN` y reiniciar el stack actualizó el
JSON, Traefik y las apps, pero el realm existente se quedó con
`https://app.vendi.local/*` y `https://admin.vendi.local/*` en los
`redirectUris` de `vendi-web` y `vendi-admin`. `reconcile-keycloak.sh` lo
detectó con exactitud (`faltan [...] · sobran [...]`) y la corrección hubo que
aplicarla a mano contra la Admin API, cliente por cliente, preservando el resto
del objeto para no pisar secretos. Es justo el trabajo manual que la parte
pendiente de esta deuda debe automatizar. Los `webOrigins` no hicieron falta:
valen `"+"`, que deriva de los `redirectUris` y por tanto es independiente del
dominio.

---

## D-04 · Keycloak arranca sin `--optimized` en producción

**Qué es.** `docker-compose.override.prod.yml` usa `start --import-realm` sin
`--optimized`: cada arranque hace un build implícito (decenas de segundos).

**Por qué está.** `--optimized` exige una imagen sobre la que ya se ejecutó
`kc.sh build`; con la imagen oficial tal cual, el servidor se niega a arrancar.

**Vencimiento: Etapa 5**, cuando `release-images.yml` construya la imagen de
Keycloak de Vendi. Entonces aquí van `image:` propia y `start --optimized`.

---

## D-06 · `alembic_version` escribible por `vendi_app` e invisible a los dos candados

**Qué es.** Medido por el QA de la Etapa 4: `vendi_app` conserva
SELECT/INSERT/UPDATE/DELETE sobre `alembic_version` (un `UPDATE version_num`
dentro de una transacción funcionó). Ni el candado de tablas de plataforma
(`test_rls_coverage.py`, que enumera nombres concretos) ni el de cobertura RLS
(que solo mira tablas con columna `tenant_id`) la ven. Es el mismo agujero que
la migración 0002 documenta y cierra para `tenants`, dejado abierto en la tabla
que decide qué DDL se ha aplicado.

**Vencimiento: Etapa 5.** REVOKE en una migración nueva + añadir
`alembic_version` a la lista del candado (o mejor: invertir el candado para que
enumere las tablas que `vendi_app` SÍ puede tocar y falle ante cualquier otra).

---

## D-07 · La columna `exchange` del outbox sigue sin defensa (resto de D-05)

**Qué es.** La mitigación de D-05 cubre `routing_key` y `payload`, pero la
policy tampoco acota `exchange` y el dispatcher lo usa literalmente en
`declare_exchange`. Medido por el QA: una fila insertada con `vendi_app` y
`exchange='amq.direct'` llevó al worker a intentar declarar ese exchange
(PRECONDITION_FAILED ×5 → `failed`); con un nombre nuevo lo habría **creado**.
Atenuante medido: no bloquea la cabecera de línea (el mensaje honesto posterior
se publicó igual).

**Vencimiento: Etapa 5.** Misma receta que D-05: el dispatcher ignora
`msg.exchange` y publica siempre en el exchange configurado del worker (o
valida contra una lista blanca), con test de dos exchanges reales.

---

## D-08 · El claim `groups` no se emite; `has_role()`/`require_role()` son inertes

**Qué es.** Token real de `dueno@demo.vendi.co`: `groups: None`. Ningún mapper
de grupo está en los default client scopes del realm. Los permisos llegan por
`realm_access.roles` (funciona), pero `UserContext.groups`, `has_role()` y
`require_role()` no ven nada. No se arregló en la Etapa 4 porque
`vendi-provisioning` no puede gestionar client scopes (403 medido en
`/client-scopes`) y tocar `realm-vendi-co.json` sin poder aplicarlo al realm
vivo crea justo la deriva de D-03. Relacionado: el seed no crea los roles de
negocio del plan (`dueno`, `cajero`, `almacenista`); el usuario demo lleva
`tenant:read`, `tenant:update`, `audit:read`.

**Vencimiento: Etapa 5** (decisión de infra: mapper de grupos en el realm JSON
+ re-import controlado, o retirar `groups` de `UserContext`).

---

## Cerradas en la Etapa 4

### D-05 · La policy de INSERT del outbox no restringía `routing_key` ni `payload`

**Qué era.** Medido por el QA de la Etapa 3 con sonda real: la policy
`outbox_encolado_del_tenant` solo acota la **columna** `tenant_id`. Una sesión
de `vendi_app` con el GUC del negocio A podía encolar legalmente una fila con
`tenant_id = A` y `routing_key = '<B>.venta.creada'`, y `payload` diciendo ser
de B. `OutboxDispatcher` publicaba `msg.routing_key` y `msg.payload`
literalmente, así que un consumidor ligado a `<B>.#` recibía un evento originado
en A.

**Cómo se cerró.** La primera de las dos mitigaciones propuestas, que es la que
cierra también el payload: el dispatcher **deriva** la clave de enrutado de
`msg.tenant_id` —la columna, que sí está defendida por la policy— en vez de
confiar en el texto almacenado, y reescribe el campo `tenant_id` del payload con
el mismo valor. Lo que aporta el llamante es solo el sufijo (el nombre del
evento), que no decide destinatario.

El primer segmento se descarta **solo si tiene forma de prefijo** (un UUID o el
literal `plataforma`, las dos únicas cosas que `DomainEventService.emit` puede
haber puesto ahí). Descartarlo a ciegas convertiría `venta.creada` en
`<tenant>.creada` y rompería el enrutado de los consumidores honestos mientras
intenta protegerlos.

Para el código correcto la derivación es un no-op; para el equivocado es un
candado. Implementación: `vendi_core.messaging.outbox.derivar_clave_de_enrutado`
y `_payload_saneado`. Cuando la clave almacenada y la derivada difieren, se
registra `outbox_clave_de_enrutado_corregida` con las dos, de modo que un
handler mal escrito se ve en el log en vez de fallar en silencio.

**Candados.** `backend/tests/worker/test_outbox_dispatch.py`:

- `test_la_clave_se_deriva_de_la_columna_tenant_id` — la tabla de casos.
- `test_una_clave_de_enrutado_ajena_no_llega_al_otro_negocio` — encola con el
  rol `vendi_app` y el GUC de A pero con la clave y el payload de B, contra el
  PostgreSQL y el RabbitMQ del compose, con **dos colas reales**, y afirma que
  el mensaje sale por `A.#` y nunca por `B.#`.

**Resto abierto.** La columna `exchange` quedó fuera de esta mitigación:
ver **D-07**.


---

## Cerradas en la Etapa 3 (ronda de corrección de QA)

Se dejan anotadas aquí, y no borradas, porque las dos eran decisiones de diseño
que llegaron a estar escritas en `docs/ARCHITECTURE.md` como si fueran
correctas. El registro de que se corrigieron —y de por qué la primera versión
parecía razonable— vale más que el hueco.

### `vendi_app` sin ningún privilegio sobre `outbox_messages`

**Qué era.** La migración `0001` hacía `REVOKE ALL` sobre las dos tablas de
plataforma, con el argumento de que «una tabla sin RLS a la que llega el rol de
la API es exactamente el agujero que este diseño existe para cerrar». El
argumento es bueno; la conclusión, no. `OutboxService.enqueue(session, ...)`
escribe en la sesión del llamante, que en un handler es la de tenant, así que el
patrón entero era inutilizable desde la API:

```
permission denied for table outbox_messages
```

**Por qué no se detectó.** Ningún test cubría el encolado, y el contrato del
módulo («la escritura de negocio y el encolado ocurren en la MISMA
transacción») era una afirmación sobre privilegios de Postgres que ningún test
de unidad con una sesión falsa podía comprobar.

**Cómo se cerró.** `GRANT INSERT` —y solo `INSERT`— más una policy de INSERT que
ata el `tenant_id` al GUC, más `eager_defaults=False` en el modelo para que el
`INSERT` no lleve `RETURNING`. La matriz completa está en
`docs/ARCHITECTURE.md`, sección «Tablas de plataforma». El candado es
`backend/tests/test_outbox_transaccional.py`.

`audit_events` **sigue completamente revocada** para `vendi_app`, y eso no es
una asimetría por olvido: la auditoría se escribe fuera de la transacción del
llamante a propósito, con la fábrica de sesión de plataforma.

### El runner de retención cerraba en éxito una pasada que no había borrado nada

**Qué era.** Todas las políticas del mismo ámbito comparten una transacción, y
en PostgreSQL un error la deja **abortada**: cualquier sentencia posterior falla
con `current transaction is aborted`. Como el runner traga los errores y
devuelve 0, una sola tabla mal escrita —o todavía sin migrar— hacía que todas
las políticas siguientes devolvieran 0 en silencio y que el ciclo se registrase
como `retention_run_finished` con una fila de auditoría `status='success'`. La
retención entera se convertía en un no-op que parecía funcionar.

Agravante: el estado se calculaba con `"success" if total >= 0 else "failure"`,
y una suma de conteos nunca es negativa. La fila decía «éxito» por construcción.

**Cómo se cerró.** Cada política corre dentro de un `SAVEPOINT`
(`session.begin_nested()`), así que un fallo revierte solo esa política y la
transacción sigue utilizable; los fallos se acumulan en `_failed_this_run` y
acaban en la fila de auditoría como `status='failure'` y
`changes.politicas_fallidas`. Candados:
`test_retention_runner.py::test_una_politica_rota_no_anula_las_siguientes` y
`::test_una_pasada_con_una_politica_rota_se_audita_como_fallida`.
