#!/bin/sh
# =============================================================================
# infra/traefik/entrypoint.sh
#
# Renderiza la configuración dinámica en cada arranque del contenedor, decide
# de dónde salen los certificados (mkcert en desarrollo · ACME en producción) y
# luego ejecuta Traefik. Así el template queda literal y legible y BASE_DOMAIN
# renombra toda la flota sin editar YAML.
#
# ¿Por qué un wrapper y no el `command` del compose? La imagen oficial de
# Traefik es mínima (no trae envsubst/gettext). Un sidecar que renderice antes
# complica el orden de arranque. Sobrescribir el entrypoint mantiene el
# renderizado pegado al arranque de Traefik: /bin/sh y sed ya están en la
# imagen. Y, sobre todo, permite decidir los flags de ACME con un `if` — cosa
# que el `command:` de docker compose no sabe hacer.
#
# Variables:
#   BASE_DOMAIN     dominio de la flota (por defecto vendi.local)
#   ACME_ENABLED    true → los certificados los emite una CA ACME
#                   false (por defecto) → los pone el operador en /certs
#   ACME_STAGING    true (por defecto) → CA de pruebas de Let's Encrypt.
#                   Ponerlo en false SOLO cuando la emisión ya funcione: la CA
#                   de producción tiene límite de 5 fallos por hora y cuenta.
#   ACME_EMAIL      obligatorio con ACME_ENABLED=true
#   ACME_CA_SERVER  fuerza un directorio ACME concreto (lo usa el spike de
#                   Pebble: scripts/spikes/acme-pebble-spike.sh)
# =============================================================================

set -eu

TEMPLATE="/etc/traefik/templates/dynamic.yml.tpl"
OUTPUT="/etc/traefik/dynamic/dynamic.yml"
CERTS_LOCALES="/etc/traefik/dynamic/certificados-locales.yml"
CONFIG_BASE="/etc/traefik/traefik.yml"
CONFIG_EFECTIVO="/etc/traefik/traefik-efectivo.yml"

: "${BASE_DOMAIN:=vendi.local}"
: "${ACME_ENABLED:=false}"
: "${ACME_STAGING:=true}"
: "${ACME_EMAIL:=}"

CA_STAGING="https://acme-staging-v02.api.letsencrypt.org/directory"
CA_PROD="https://acme-v02.api.letsencrypt.org/directory"

# Escapa el dominio para usarlo dentro de HostRegexp / regex de CORS. Solo el
# metacaracter `.` importa en nombres DNS.
#
# Formato objetivo en el archivo renderizado: DOS barras invertidas antes del
# punto. El escalar YAML entrecomillado colapsa `\\` a `\`, y el regex de Go
# ve `\.`. Para emitir dos barras vía sed hacen falta ocho en el argumento de
# reemplazo (sed las divide, y la segunda llamada a sed vuelve a dividirlas).
BASE_DOMAIN_REGEX="$(printf '%s' "${BASE_DOMAIN}" | sed 's|\.|\\\\\\\\.|g')"

if [ ! -f "${TEMPLATE}" ]; then
    echo "[entrypoint] ERROR: no existe el template en ${TEMPLATE}" >&2
    exit 1
fi

# --- Configuración ESTÁTICA efectiva ----------------------------------------
# Traefik NO mezcla fuentes de configuración estática: si se arranca con
# `--configFile`, los demás flags de línea de órdenes se IGNORAN en silencio.
# Comprobado en esta misma imagen (3.3.7): con
#
#   traefik --configFile=/etc/traefik/traefik.yml --api.insecure=true
#
# el dashboard devolvía 404 y los flags de `--certificatesResolvers.*` producían
#
#   ERR Router uses a nonexistent certificate resolver certificateResolver=letsencrypt
#
# Por eso ACME y el dashboard NO se pasan por CLI: se escriben en una copia del
# traefik.yml montado, que es la que Traefik lee de verdad. El archivo del
# repositorio sigue siendo la fuente legible; este es el derivado del entorno.
cp "${CONFIG_BASE}" "${CONFIG_EFECTIVO}"

if [ "${TRAEFIK_DASHBOARD:-false}" = "true" ]; then
    sed -i -e 's|^  insecure: false|  insecure: true|' -e 's|^  dashboard: false|  dashboard: true|' "${CONFIG_EFECTIVO}"
    echo "[entrypoint] dashboard ENCENDIDO (solo debe pasar en desarrollo, publicado en loopback)"
fi

# --- ¿De dónde salen los certificados? --------------------------------------
# Esta es la decisión que se cablea hasta el final: si ACME está encendido,
# TODOS los routers referencian el resolver `letsencrypt` (`certResolver`) y
# no se escribe el archivo de certificados locales; si está apagado, los
# routers usan `tls: {}` y los certificados salen de /certs (mkcert).
#
# Antes ni una cosa ni la otra: el resolver se declaraba por CLI y NINGÚN
# router lo referenciaba, así que ACME_ENABLED y ACME_STAGING no hacían nada y
# el camino de producción no existía.
if [ "${ACME_ENABLED}" = "true" ]; then
    if [ -z "${ACME_EMAIL}" ]; then
        echo "[entrypoint] ERROR: ACME_ENABLED=true exige ACME_EMAIL (la CA lo pide para avisar de caducidades)" >&2
        exit 1
    fi
    if [ -n "${ACME_CA_SERVER:-}" ]; then
        CA="${ACME_CA_SERVER}"
        ORIGEN_CA="ACME_CA_SERVER"
    elif [ "${ACME_STAGING}" = "true" ]; then
        CA="${CA_STAGING}"
        ORIGEN_CA="staging de Let's Encrypt"
    else
        CA="${CA_PROD}"
        ORIGEN_CA="PRODUCCIÓN de Let's Encrypt"
    fi
    TLS_OPCIONES='{ certResolver: letsencrypt }'
    rm -f "${CERTS_LOCALES}"
    cat >> "${CONFIG_EFECTIVO}" <<EOF

# --- Añadido por entrypoint.sh porque ACME_ENABLED=true ---
certificatesResolvers:
  letsencrypt:
    acme:
      email: "${ACME_EMAIL}"
      storage: /letsencrypt/acme.json
      caServer: "${CA}"
      httpChallenge:
        entryPoint: web
EOF
    echo "[entrypoint] ACME ACTIVO · CA: ${CA} (${ORIGEN_CA}) · contacto: ${ACME_EMAIL}"
    echo "[entrypoint] los routers de ${BASE_DOMAIN} usan certResolver=letsencrypt"
else
    TLS_OPCIONES='{}'
    echo "[entrypoint] ACME apagado: los certificados salen de /certs (scripts/setup-certs.sh)"
fi

sed \
    -e "s|\${BASE_DOMAIN_REGEX}|${BASE_DOMAIN_REGEX}|g" \
    -e "s|\${BASE_DOMAIN}|${BASE_DOMAIN}|g" \
    -e "s|\${TLS_OPCIONES}|${TLS_OPCIONES}|g" \
    "${TEMPLATE}" > "${OUTPUT}"

echo "[entrypoint] renderizado ${OUTPUT} (BASE_DOMAIN=${BASE_DOMAIN}, tls=${TLS_OPCIONES})"

# --- Certificados locales (solo sin ACME) -----------------------------------
if [ "${ACME_ENABLED}" != "true" ]; then
    cat > "${CERTS_LOCALES}" <<EOF
# Generado por infra/traefik/entrypoint.sh en cada arranque. NO editar.
# Solo existe cuando ACME_ENABLED != true: en desarrollo los certificados los
# emite mkcert (scripts/setup-certs.sh) y viven en /certs.
tls:
  certificates:
    - certFile: /certs/${BASE_DOMAIN}.pem
      keyFile: /certs/${BASE_DOMAIN}-key.pem
EOF

    # Verificación ruidosa: si falta algún certificado referenciado, se aborta
    # ANTES de arrancar Traefik. El comportamiento propio de Traefik es
    # reintentar en bucle con mensajes crípticos que entierran el problema real
    # (el operador no corrió scripts/setup-certs.sh).
    MISSING_CERTS=""
    for ref in $(grep -oE '(certFile|keyFile):[[:space:]]*/certs/[^[:space:]]+' "${CERTS_LOCALES}" | awk '{print $2}'); do
        if [ ! -f "${ref}" ]; then
            echo "[entrypoint] ERROR: no se encuentra el certificado ${ref}; no arranco" >&2
            MISSING_CERTS="${MISSING_CERTS} ${ref}"
        fi
    done
    if [ -n "${MISSING_CERTS}" ]; then
        echo "[entrypoint] pista: ejecuta ./scripts/setup-certs.sh en el anfitrión y reinicia el contenedor traefik." >&2
        exit 1
    fi
fi

exec /usr/local/bin/traefik "$@"
