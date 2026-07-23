# Runbook · Certificados TLS

Dos mundos distintos con problemas distintos: **local** (mkcert) y **producción**
(ACME / Let's Encrypt). El interruptor entre ambos es `ACME_ENABLED`.

## Local — mkcert

Los certificados están en `infra/certs/vendi.co.pem` y `vendi.co-key.pem`, y los
emite `scripts/setup-certs.sh` a partir de la CA local que instaló
`mkcert -install`.

**Caducan** (mkcert emite a ~27 meses, pero la CA se puede reinstalar antes).
Síntoma: el navegador avisa, `curl` falla con `certificate has expired`, y
`verify-setup.sh` distingue el caso — dice si valida contra la CA de mkcert pero
no contra el almacén del sistema, que es «falta `mkcert -install`», de si no hay
servicio detrás.

```bash
mkcert -install                 # una vez por máquina
./scripts/setup-certs.sh        # reemite
docker compose -f infra/docker-compose.yml restart traefik
```

El `restart` es necesario: Traefik lee los certificados al arrancar, y el
entrypoint reescribe `dynamic/certificados-locales.yml` en cada arranque.

**Nunca** la salida fácil: `curl -k`, `--insecure` o `ignoreHTTPSErrors`. Con un
dominio real como `vendi.co`, apagar la validación significa que una petición mal
resuelta llega a un servidor ajeno y nadie se entera. La CA está instalada
precisamente para que no haga falta.

## Producción — ACME

```
ACME_ENABLED=true → el entrypoint de Traefik declara el resolver `letsencrypt`
                    y TODOS los routers pasan a `certResolver: letsencrypt`
ACME_STAGING=true → CA de pruebas. EMPIEZA SIEMPRE AQUÍ.
ACME_EMAIL=…      → obligatorio con ACME activo
```

La renovación es automática (Traefik renueva a los 30 días de la caducidad) y el
estado vive en `acme.json`, dentro del volumen de Traefik.

**Empieza siempre en staging.** La CA de producción limita a 5 fallos por hora y
**los cuenta**: un DNS mal apuntado en el primer intento te deja sin
certificado el resto de la hora. Cuando el certificado de staging se emita bien:

```bash
docker compose ... run --rm -T traefik sh -c 'rm -f /letsencrypt/acme.json'
# ACME_STAGING=false en el .env
docker compose ... up -d --force-recreate traefik
```

Hay que **borrar** `acme.json`: guarda la cuenta y los certificados de la CA de
pruebas, y sin borrarlo Traefik sigue usándolos.

## Probar el camino de ACME sin exponer nada a Internet

```bash
bash scripts/spikes/acme-pebble-spike.sh
```

Levanta una CA ACME local (Pebble) y recorre la emisión entera. Sirve para
verificar la configuración de Traefik sin gastar intentos contra Let's Encrypt.

## Un router nuevo sin certificado

Si añades un router a `infra/traefik/templates/dynamic.yml.tpl` y **olvidas**
`tls: ${TLS_OPCIONES}`, funcionará en local (donde el certificado es comodín) y
**no tendrá certificado en producción**. Es el único punto donde se elige el
origen de los certificados; no hay red de seguridad.
