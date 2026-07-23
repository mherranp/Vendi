# Deuda técnica de Fase 0

Registro de las decisiones que se toman **a sabiendas de que están mal**, con
quién las tomó, por qué, y **cuándo dejan de ser aceptables**. Una deuda sin
fecha de vencimiento no es deuda: es una decisión permanente que nadie firmó.

Cada entrada se cierra borrándola de aquí y dejando la evidencia de que el
arreglo funciona (comando + salida), no marcándola como "hecha".

| # | Deuda | Vence | Dueño |
|---|---|---|---|
| D-01 | ROPC activo en `vendi-web` | Etapa 5 (cierre de Fase 0) | backend |
| D-02 | `manage-realm` en la cuenta de servicio de `vendi-backend` | Fase 1 (o cuando Keycloak permita acotar Organizations) | backend |
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
# → {'vendi-web': True, 'vendi-admin': False, 'vendi-backend': False}
```

---

## D-02 · `manage-realm` en la cuenta de servicio de `vendi-backend`

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
Mitigación mientras tanto: el secreto de `vendi-backend` se rota en cada
despliegue y `verify-setup.sh` (check 21) falla si aparece un rol de más.

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

---

## D-04 · Keycloak arranca sin `--optimized` en producción

**Qué es.** `docker-compose.override.prod.yml` usa `start --import-realm` sin
`--optimized`: cada arranque hace un build implícito (decenas de segundos).

**Por qué está.** `--optimized` exige una imagen sobre la que ya se ejecutó
`kc.sh build`; con la imagen oficial tal cual, el servidor se niega a arrancar.

**Vencimiento: Etapa 5**, cuando `release-images.yml` construya la imagen de
Keycloak de Vendi. Entonces aquí van `image:` propia y `start --optimized`.
