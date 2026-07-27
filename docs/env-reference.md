# Referencia de variables de entorno

Dos capas, y conviene no confundirlas:

- **El `.env` de la raíz** lo lee `docker compose`. Sus variables componen los
  DSN, las contraseñas de los contenedores y los nombres de host. Plantilla:
  [`.env.example`](../.env.example).
- **La configuración de cada servicio** (`app.settings.Settings` y
  `worker.settings.Settings`) se lee del entorno **del proceso**, que el compose
  rellena. Un servicio puede tener campos que el `.env` no menciona; entonces
  vale su valor por defecto del código.

Regla que este diseño hace cumplir: **ningún secreto ni ningún DSN de producción
tiene valor por defecto.** Un defecto plausible (`postgresql://localhost/vendi`)
convierte un despliegue mal configurado en un despliegue que arranca y apunta al
sitio equivocado. Los campos obligatorios se declaran sin defecto y pydantic
aborta el arranque diciendo exactamente cuál falta.

---

## General

| Variable | Defecto | Qué hace |
|---|---|---|
| `APP_ENV` | `development` | `production` activa el check 17 de `verify-setup.sh`, que falla si encuentra secretos de ejemplo |
| `BASE_DOMAIN` | `vendi.co` | Renombra los hosts de Traefik y los `redirectUris` del realm. Cambiarlo **no** reimporta el realm existente: hay que reconciliar |

## PostgreSQL — los dos roles son el aislamiento

| Variable | Qué hace |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | superusuario del clúster; solo el `initdb` y el mantenimiento |
| `VENDI_PLATFORM_DB_PASSWORD` | rol `vendi_platform`: **con** `BYPASSRLS`, owner de las tablas. Migraciones, worker, consola de plataforma |
| `VENDI_APP_DB_PASSWORD` | rol `vendi_app`: **sin** `BYPASSRLS`. Es el que usan los handlers |

Los dos DSN son campos **distintos y ambos obligatorios** en la configuración de
la API (`DATABASE_URL` y `PLATFORM_DATABASE_URL`), no un campo con una bandera.
El error que el diseño tiene que hacer imposible es usar el segundo donde tocaba
el primero, y para eso hay que poder verlos separados en el arranque: `lifespan`
comprueba **contra la base** que el primero no tiene `BYPASSRLS` y se niega a
arrancar si lo tiene. Ver [ADR-013](adr/adr-013-rls-schema-unico.md).

## Redis y RabbitMQ

| Variable | Defecto | Qué hace |
|---|---|---|
| `REDIS_PASSWORD` | — **obligatoria** | contraseña de Redis. El compose la inyecta en el `requirepass` del servidor y en el `REDIS_URL` de la API: cambiarla exige recrear los dos, no solo uno |
| `RABBITMQ_USER` | `vendi` | usuario del broker |
| `RABBITMQ_PASSWORD` | — **obligatoria** | contraseña del broker. Va en `RABBITMQ_URL` de la API y del worker |

Las tres son de las que el paso 1 de
[getting-started](getting-started.md) manda cambiar antes de levantar nada:
`.env.example` las trae con valores `cambiar_*` a propósito para que un
despliegue con las de fábrica se note a simple vista.

## Keycloak

| Variable | Defecto | Qué hace |
|---|---|---|
| `KEYCLOAK_ADMIN_USER` / `KEYCLOAK_ADMIN_PASSWORD` | `admin` / — | administrador del **realm `master`**. Lo usan `reconcile-keycloak.sh` y `verify-setup.sh`; la aplicación **no** |
| `VENDI_BACKEND_CLIENT_SECRET` | — | credencial de la API general. Solo `manage-users` |
| `VENDI_PROVISIONING_CLIENT_SECRET` | — | credencial del servicio `provisioner` (alta y baja de negocios). `manage-realm` + `manage-users`. **La API ya no la recibe** (ADR-027): solo la tienen el contenedor `provisioner` y el import del realm. **Tiene que ser distinta de la anterior**: dos credenciales con el mismo valor son una credencial |
| `KEYCLOAK_AUDIENCE` | `vendi-backend` | audiencia exigida en el claim `aud`. **Vaciarla apaga la comprobación** |

Sobre `KEYCLOAK_AUDIENCE`: el defecto no está vacío a propósito. Un despliegue
que olvide la variable debe **fallar cerrado** —rechazar tokens sin audiencia—,
no abrir la puerta. La audiencia la emite el client scope `vendi-audiencia` del
realm en los tokens de `vendi-web` y `vendi-admin`. Sin esta comprobación,
cualquier token firmado por el realm sirve contra la API aunque se emitiera para
otro público: por ejemplo el de la consola de cuenta de Keycloak, que un usuario
obtiene sin pasar por ninguna aplicación de Vendi.

## API

| Variable | Defecto | Qué hace |
|---|---|---|
| `DOCS_PUBLICOS` | `false` | `true` registra `/docs`, `/redoc` y `/openapi.json`. Con `false` las rutas **no existen**: el 404 es real, no un middleware que las tapa |
| `METRICS_TOKEN` | — | credencial de `/metrics`. **Sin valor la ruta responde 503 y no se abre** |
| `CORS_ORIGINS` | vacío | orígenes que gestiona **la aplicación**. Vacío no es un olvido: el CORS lo termina Traefik. Declarar aquí un origen sin quitarlo del borde produce la cabecera `Access-Control-Allow-Origin` **duplicada** y el navegador rechaza la respuesta entera — un fallo que se ve como «CORS error» en las cuatro SPAs y no deja ni un log en el backend |
| `CORS_ORIGIN_REGEX` | vacío | ídem, por expresión regular |
| `TRUSTED_PROXIES` | CIDR privados en el compose | de quién se acepta `X-Forwarded-For`. Con la lista vacía se ignora la cabecera y se usa el peer: **falla cerrado** |
| `TENANT_ESTADO_CACHE_TTL` | `60` | latencia máxima entre suspender un negocio y que sus tokens dejen de servir |

## Worker

| Variable | Defecto | Qué hace |
|---|---|---|
| `WORKER_HEARTBEAT_SECONDS` | `30` | el healthcheck da por muerto al worker si el archivo de latido pasa 3 intervalos sin tocarse |
| `OUTBOX_POLL_INTERVAL` | `2.0` | cada cuánto se drena el outbox |
| `OUTBOX_BATCH_SIZE` | `100` | mensajes por pasada |
| `OUTBOX_MAX_RETRIES` | `5` | reintentos antes de marcar `failed` |
| `RETENTION_HOUR_UTC` | `3` | hora UTC de la pasada de retención |
| `RABBITMQ_BACKOFF_MAX` | `30.0` | tope del backoff de reconexión. Sin tope, un RabbitMQ lento deja al worker durmiendo horas; sin backoff, entra en crash-loop |

## Siembra de desarrollo

| Variable | Qué hace |
|---|---|
| `SEED_ADMIN_PASSWORD` | contraseña de `admin@vendi.co` (consola de plataforma) |
| `SEED_DUENO_PASSWORD` | contraseña de `dueno@demo.vendi.co` (negocio demo) |

Ninguna tiene defecto **en el código**: `seed.sh` aborta si faltan. Una
contraseña por defecto en un script de siembra acaba siendo una contraseña en
producción el día que alguien lo ejecute donde no debía.

## Borde y TLS

| Variable | Defecto | Qué hace |
|---|---|---|
| `TRAEFIK_BIND` | `127.0.0.1` | interfaz donde el borde publica 80/443. Solo loopback en desarrollo; el override de producción publica en `0.0.0.0` |
| `ACME_ENABLED` | `false` | `true` hace que todos los routers usen `certResolver: letsencrypt`. Exige `ACME_EMAIL` |
| `ACME_STAGING` | `true` | **empieza siempre aquí**: la CA de producción de Let's Encrypt limita a 5 fallos por hora y los cuenta |
| `ACME_EMAIL` | vacío | obligatorio con ACME activo |

## Producción

| Variable | Defecto | Qué hace |
|---|---|---|
| `VENDI_IMAGE_REGISTRY` | — **obligatoria** | registro donde `release-images.yml` publica las seis imágenes propias (p. ej. `ghcr.io/mi-org`). El override de producción compone con ella `…/vendi-api`, `…/vendi-worker`, `…/vendi-keycloak`, `…/vendi-portal`, `…/vendi-tenant` y `…/vendi-admin` |
| `VENDI_IMAGE_TAG` | — **obligatoria** | etiqueta concreta a desplegar: `v0.1.0` para un tag, `sha-1a2b3c4` para un commit. `deploy.yml` la fija al SHA del commit que pasó `ci` y `e2e`. No se usa `latest`: es móvil y deja el rollback sin destino |

Las dos son obligatorias a propósito. Con un valor por defecto tipo
`vendi-api:local`, un `.env` incompleto fallaba con «pull access denied for
vendi-api, repository does not exist» —que suena a credenciales del registro— en
vez de decir lo que de verdad pasaba: que nadie dijo qué versión desplegar.

En la VM no existen `backend/` ni `frontend/` (el `rsync` de `deploy.yml` solo
copia `infra/`), así que **no hay camino alternativo**: sin estas dos variables
no se despliega. Para probar el camino en local se construyen las imágenes a
mano y se etiquetan con lo que digan estas variables.

## Observabilidad

| Variable | Defecto | Qué hace |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | vacío | **vacío desactiva el SDK de OpenTelemetry por completo** (coste cero, no «exporta a ninguna parte») |
| `GRAFANA_ADMIN_PASSWORD` | — | administrador de Grafana |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `true` | JSON estructurado por defecto; en local `seed.sh` y los scripts lo ponen legible |

## Almacenamiento

| Variable | Defecto | Qué hace |
|---|---|---|
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | — | credenciales del almacén de objetos |
| `MINIO_BUCKET` | `vendi-co-media` | **un solo bucket por región**, con las claves prefijadas por `tenant_id`. Ver [ADR-016](adr/adr-016-backend-api-worker.md) |
| `STORAGE_PROVIDER` | `minio` | `minio` o `s3` |
| `STORAGE_SECURE` | `false` | TLS hacia el almacén |
