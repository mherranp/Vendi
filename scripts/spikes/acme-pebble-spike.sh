#!/usr/bin/env bash
# =============================================================================
# acme-pebble-spike.sh
#
# Demuestra que el camino ACME de producción FUNCIONA, sin exponer nada a
# internet y sin gastar el cupo de Let's Encrypt.
#
# El QA de la Etapa 2 tenía razón: el resolver `letsencrypt` estaba declarado
# pero ningún router lo referenciaba, así que ACME_ENABLED/ACME_STAGING eran
# variables muertas y el camino de producción nunca se había ejercido. Tras
# cablearlo (infra/traefik/entrypoint.sh), este spike lo prueba de punta a
# punta contra Pebble, la CA ACME de pruebas del propio Let's Encrypt:
#
#   1. Levanta Pebble en la red del compose, con el desafío HTTP-01 en el
#      puerto 80 y `api.<BASE_DOMAIN>` apuntando al contenedor de Traefik.
#   2. Recrea Traefik con ACME_ENABLED=true y ACME_CA_SERVER=Pebble.
#   3. Pide https://api.<BASE_DOMAIN>/health y comprueba que el certificado que
#      sirve Traefik lo emitió Pebble (y no mkcert).
#   4. Deja el stack como estaba (Traefik sin ACME, certificados de mkcert).
#
# Requisitos: el stack de Vendi arriba (scripts/dev.sh) y mkcert instalado.
#
# Uso:  bash scripts/spikes/acme-pebble-spike.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[AVISO]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INFRA_DIR="${REPO_ROOT}/infra"
COMPOSE=(docker compose -f "${INFRA_DIR}/docker-compose.yml" -f "${INFRA_DIR}/docker-compose.override.dev.yml")

if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a; . "${REPO_ROOT}/.env"; set +a
fi
BASE_DOMAIN="${BASE_DOMAIN:-vendi.co}"
DOMINIO="api.${BASE_DOMAIN}"
RED_DOCKER="vendi_vendi-net"
IMG_PEBBLE="ghcr.io/letsencrypt/pebble:latest"

command -v mkcert >/dev/null || error "hace falta mkcert (brew install mkcert)"
docker network inspect "${RED_DOCKER}" >/dev/null 2>&1 || error "la red ${RED_DOCKER} no existe: levanta el stack con scripts/dev.sh"

TRAEFIK_IP="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${RED_DOCKER}\").IPAddress}}" vendi-traefik-1 2>/dev/null || true)"
[[ -n "${TRAEFIK_IP}" ]] || error "no encuentro el contenedor vendi-traefik-1 en ${RED_DOCKER}"
info "Traefik está en ${TRAEFIK_IP} dentro de ${RED_DOCKER}"

TMP="$(mktemp -d)"
limpiar() {
    info "Limpiando: borro Pebble y devuelvo Traefik a su configuración de desarrollo"
    docker rm -f pebble >/dev/null 2>&1 || true
    rm -rf "${TMP}"
    # El acme.json guarda la CUENTA de la CA local y el certificado emitido por
    # ella. Dejarlo ahí haría que un futuro arranque con Let's Encrypt de verdad
    # arrancase con estado de otra CA. Se borra siempre.
    docker run --rm -v vendi_letsencrypt_data:/le alpine:3.20 rm -f /le/acme.json >/dev/null 2>&1 || true
    rm -f "${INFRA_DIR}/certs/pebble.pem" "${INFRA_DIR}/certs/pebble-key.pem" "${INFRA_DIR}/certs/ca-pruebas.pem"
    (cd "${REPO_ROOT}" && ACME_ENABLED=false "${COMPOSE[@]}" up -d --force-recreate traefik >/dev/null 2>&1) || true
}
trap limpiar EXIT

# ---------------------------------------------------------------------------
# 1. Certificado del propio Pebble (su API ACME va por HTTPS) y la CA que
#    Traefik tendrá que confiar para hablar con él.
# ---------------------------------------------------------------------------
info "Emitiendo con mkcert el certificado del servidor Pebble"
(cd "${TMP}" && mkcert -cert-file pebble.pem -key-file pebble-key.pem pebble localhost 127.0.0.1 >/dev/null 2>&1)
cp "${TMP}/pebble.pem" "${TMP}/pebble-key.pem" "${INFRA_DIR}/certs/"
cp "$(mkcert -CAROOT)/rootCA.pem" "${INFRA_DIR}/certs/ca-pruebas.pem"

cat > "${TMP}/pebble-config.json" <<'JSON'
{
  "pebble": {
    "listenAddress": "0.0.0.0:14000",
    "managementListenAddress": "0.0.0.0:15000",
    "certificate": "/pebble/pebble.pem",
    "privateKey": "/pebble/pebble-key.pem",
    "httpPort": 80,
    "tlsPort": 443,
    "ocspResponderURL": "",
    "externalAccountBindingRequired": false
  }
}
JSON

# ---------------------------------------------------------------------------
# 2. Pebble en la red del compose. El --add-host es el "DNS público" del
#    experimento: cuando Pebble valide el desafío HTTP-01 de api.<dominio>,
#    acabará llamando al contenedor de Traefik.
# ---------------------------------------------------------------------------
info "Levantando Pebble en ${RED_DOCKER} (HTTP-01 → ${DOMINIO} → ${TRAEFIK_IP})"
docker rm -f pebble >/dev/null 2>&1 || true
docker run -d --name pebble --network "${RED_DOCKER}" \
    --add-host "${DOMINIO}:${TRAEFIK_IP}" \
    -e PEBBLE_VA_NOSLEEP=1 \
    -v "${TMP}:/pebble:ro" \
    "${IMG_PEBBLE}" -config /pebble/pebble-config.json >/dev/null

sleep 3
docker logs pebble 2>&1 | head -5

# ---------------------------------------------------------------------------
# 3. Traefik con ACME encendido apuntando a Pebble.
# ---------------------------------------------------------------------------
info "Recreando Traefik con ACME_ENABLED=true contra la CA local"
(cd "${REPO_ROOT}" && \
  ACME_ENABLED=true \
  ACME_EMAIL="ops@${BASE_DOMAIN}" \
  ACME_CA_SERVER="https://pebble:14000/dir" \
  LEGO_CA_CERTIFICATES=/certs/ca-pruebas.pem \
  "${COMPOSE[@]}" up -d --force-recreate traefik >/dev/null)

info "Esperando a que Traefik pida y reciba el certificado..."
EMISOR=""
for _ in $(seq 1 30); do
    sleep 2
    curl -sk --connect-timeout 3 --max-time 8 "https://${DOMINIO}/health" >/dev/null 2>&1 || true
    EMISOR="$(echo | openssl s_client -connect 127.0.0.1:443 -servername "${DOMINIO}" 2>/dev/null \
        | openssl x509 -noout -issuer -subject 2>/dev/null || true)"
    case "${EMISOR}" in
        *Pebble*) break ;;
    esac
done

echo ""
echo "--- certificado que sirve Traefik para ${DOMINIO} ---"
echo "${EMISOR:-(no pude leer el certificado)}"
echo "--- líneas de ACME en el log de Traefik ---"
"${COMPOSE[@]}" logs traefik 2>/dev/null | grep -iE 'acme|certificate|entrypoint' | tail -12
echo ""

case "${EMISOR}" in
    *Pebble*)
        success "El certificado de ${DOMINIO} lo emitió la CA ACME: el camino de producción funciona."
        success "Con ACME_STAGING=true/false la única diferencia es la URL del directorio de Let's Encrypt."
        ;;
    *)
        error "Traefik NO sirvió un certificado emitido por Pebble. Revisa el log de arriba y 'docker logs pebble'."
        ;;
esac
