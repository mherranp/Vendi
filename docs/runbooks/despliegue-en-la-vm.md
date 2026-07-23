# Runbook · Despliegue en la VM de la región

Fase 0 despliega con **docker compose sobre una VM**, no con Terraform ni
Kubernetes. El porqué —y cuándo deja de valer— está en
[ADR-003](../adr/adr-003-multi-region.md).

## Lo que hay en la VM

```
/opt/vendi/infra/          ← lo sincroniza deploy.yml desde el repositorio
  docker-compose.yml
  docker-compose.override.prod.yml
  traefik/  postgres/  keycloak/  prometheus/  grafana/
/opt/vendi/infra/.env      ← NO viene del repositorio. Lo pone el operador.
```

**El `.env` nunca se sincroniza desde GitHub.** Las contraseñas de la base, los
secretos de los clientes de Keycloak y el token de métricas viven en el servidor.
Un workflow que los copiara desde secretos de GitHub convertiría cualquier acceso
al repositorio en acceso a producción.

## Despliegue automático

`release-images.yml` publica las **seis** imágenes propias —`vendi-api`,
`vendi-worker`, `vendi-keycloak`, `vendi-portal`, `vendi-tenant` y
`vendi-admin`— **solo después** de que `ci` y `e2e` hayan terminado en verde para
ese mismo commit. Al terminar, dispara `deploy.yml`, que sincroniza la
infraestructura, hace `pull` + `up -d --no-build` y comprueba
`https://api.<dominio>/health/ready` y las tres SPAs por el borde, **sin `-k`**:
si el certificado no valida, el despliegue no está bien.

Secretos que hay que configurar una vez: `DEPLOY_HOST`, `DEPLOY_USER`,
`DEPLOY_SSH_KEY`, `DEPLOY_DOMAIN`, `REGISTRY_URL` (+ usuario y contraseña del
registro). Sin ellos el workflow se salta el despliegue en vez de fallar.

### En la VM no se construye nada

El `rsync` de `deploy.yml` copia **solo** `infra/`. En el servidor no existen
`backend/` ni `frontend/`, que son los contextos de construcción del compose. Por
eso el `up` lleva `--no-build` y el override de producción exige dos variables en
el `.env` de la VM:

| Variable | Ejemplo | Quién la pone |
|---|---|---|
| `VENDI_IMAGE_REGISTRY` | `ghcr.io/mi-org` | el operador, una vez |
| `VENDI_IMAGE_TAG` | `sha-1a2b3c4` | `deploy.yml` la exporta con el SHA corto del commit desplegado; a mano se fija para revertir |

Si faltan, el compose se niega a arrancar nombrando la variable que falta. Antes
respondía «pull access denied for vendi-api, repository does not exist», que
suena a credenciales del registro y no a lo que de verdad pasaba.

## Despliegue a mano

```bash
ssh deploy@<host>
cd /opt/vendi/infra
export VENDI_IMAGE_TAG=sha-1a2b3c4   # la que publicó release-images
docker compose -f docker-compose.yml -f docker-compose.override.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.override.prod.yml up -d --no-build --remove-orphans
curl -f --retry 5 --retry-delay 5 https://api.<dominio>/health/ready
```

## Migraciones: a mano, con el runbook delante

`deploy.yml` **no** migra. Una migración automática en el mismo paso que el
despliegue no tiene punto de vuelta atrás: si la migración es destructiva y el
despliegue falla después, ya no puedes revertir el código sin revertir el
esquema.

```bash
# 1. Copia de seguridad ANTES. Ver docs/respaldo-y-restauracion.md.
# 2. Ver qué se va a aplicar:
docker compose ... run --rm api uv run --project /src --no-sync alembic history -r current:head
# 3. Aplicar:
bash scripts/migrate.sh
```

## Revertir

```bash
# La etiqueta de la imagen anterior está en el historial de release-images.
# El `pull` va primero: si la poda de Docker (o una VM recreada) se llevó la
# imagen local, el `up` a secas moriría con «No such image» justo cuando se
# está revirtiendo bajo presión.
VENDI_IMAGE_TAG=sha-abc1234 docker compose -f docker-compose.yml \
  -f docker-compose.override.prod.yml pull
VENDI_IMAGE_TAG=sha-abc1234 docker compose -f docker-compose.yml \
  -f docker-compose.override.prod.yml up -d --no-build
```

Revertir el **código** es rápido. Revertir el **esquema** no siempre es posible:
por eso la copia va antes de migrar, no después.

## Qué mirar cuando algo va mal

```bash
docker compose -f docker-compose.yml -f docker-compose.override.prod.yml ps
docker compose ... logs --tail=200 api
curl -f https://api.<dominio>/health/ready     # PG + Redis + Keycloak
```

`/health/ready` y no `/health`: el primero comprueba las dependencias, así que un
contenedor que arrancó pero no alcanza la base sale rojo. `/health` a secas
diría que todo va bien.

## Primer despliegue

Lo que no automatiza nada y hay que hacer una vez, en este orden:

1. VM con Docker y `docker compose`; usuario `deploy` con su clave SSH.
2. DNS: `A` de `<dominio>`, `api.`, `accounts.`, `app.`, `admin.` apuntando a la
   IP de la VM. **Antes** de activar ACME, o la validación falla y Let's Encrypt
   cuenta los fallos (5 por hora).
3. `/opt/vendi/infra/.env` con secretos reales. `APP_ENV=production`,
   `ACME_ENABLED=true`, `ACME_STAGING=true`, `ACME_EMAIL=…`.
4. `docker login` contra el registro, con el usuario `deploy`.
5. Primer `up -d`. Cuando el certificado de staging se emita bien:
   `ACME_STAGING=false`, borrar `acme.json` del volumen (guarda la cuenta y los
   certificados de la CA de pruebas) y recrear Traefik.
6. `bash scripts/migrate.sh`. **`seed.sh` NO**: es de desarrollo.
7. `APP_ENV=production bash scripts/verify-setup.sh`. El check 17 deja de
   omitirse y falla si quedó algún secreto de ejemplo.
