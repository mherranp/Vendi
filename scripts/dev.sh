#!/usr/bin/env bash
# =============================================================================
# dev.sh
#
# Construye y levanta el stack completo de Vendi en Docker:
#   - Traefik (borde, TLS en :443)
#   - PostgreSQL 17 (con los roles vendi_platform / vendi_app), Redis,
#     RabbitMQ, MinIO, Keycloak 26.6.4 (realm vendi-co importado)
#   - api, worker
#   - Prometheus, Grafana, MailHog
#
# Requisitos, una sola vez:
#   ./scripts/setup-dnsmasq.sh      # *.${BASE_DOMAIN} -> 127.0.0.1
#   mkcert -install                 # confiar en la CA local
#   ./scripts/setup-certs.sh        # generar los certificados TLS
#   cp .env.example .env            # y cambiar las contraseñas
#
# Las apps Angular NO están en el compose: en desarrollo se sirven con
# `cd frontend && npm start`. Ver infra/traefik/templates/dynamic.yml.tpl.
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[AVISO]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${REPO_ROOT}/infra"
COMPOSE=(docker compose -f "${INFRA_DIR}/docker-compose.yml" -f "${INFRA_DIR}/docker-compose.override.dev.yml")

# ---------------------------------------------------------------------------
# .env obligatorio. Se copia del ejemplo si falta, pero se avisa: las
# contraseñas del ejemplo NO valen para nada que se exponga.
# ---------------------------------------------------------------------------
if [[ ! -f "${REPO_ROOT}/.env" ]]; then
    warn "No hay .env — lo copio de .env.example. CAMBIA LAS CONTRASEÑAS."
    cp "${REPO_ROOT}/.env.example" "${REPO_ROOT}/.env"
fi

set -a
# shellcheck disable=SC1091
. "${REPO_ROOT}/.env"
set +a
BASE_DOMAIN="${BASE_DOMAIN:-vendi.local}"

# ---------------------------------------------------------------------------
# Comprobaciones previas: fallar pronto y con el comando exacto que arregla.
# ---------------------------------------------------------------------------
info "Comprobaciones previas (BASE_DOMAIN=${BASE_DOMAIN})"

if ! docker info >/dev/null 2>&1; then
    error "El demonio de Docker no responde. Arranca Docker Desktop (macOS) o 'sudo systemctl start docker' (Linux)."
fi
success "demonio de docker accesible"

CERT_FILE="${INFRA_DIR}/certs/${BASE_DOMAIN}.pem"
KEY_FILE="${INFRA_DIR}/certs/${BASE_DOMAIN}-key.pem"
if [[ ! -f "${CERT_FILE}" || ! -f "${KEY_FILE}" ]]; then
    error "Faltan los certificados de ${BASE_DOMAIN} en infra/certs/. Ejecuta: ./scripts/setup-certs.sh"
fi
success "certificados TLS presentes"

# Los puertos 80 y 443 son de Traefik. Si otro stack local los tiene cogidos,
# `docker compose up` falla con un error de bind poco explicativo.
#
# La versión anterior de esta comprobación daba un falso verde: se saltaba el
# error si existía CUALQUIER contenedor cuyo nombre contuviera «vendi-traefik»,
# aunque el puerto lo tuviera otro proceso. Con el Traefik de otro stack en
# :443 y el nuestro publicado en puertos alternativos, imprimía «puertos 80 y
# 443 disponibles» y luego el bind fallaba — justo el error críptico que la
# comprobación existe para evitar. Ahora se le pregunta a Docker QUIÉN publica
# ese puerto concreto.
for PUERTO in 80 443; do
    if ! lsof -nP -iTCP:"${PUERTO}" -sTCP:LISTEN >/dev/null 2>&1; then
        continue
    fi
    EN_USO="$(lsof -nP -iTCP:"${PUERTO}" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1}')"
    DUENYO="$(docker ps --filter "publish=${PUERTO}" --format '{{.Names}}' 2>/dev/null | head -n1)"
    if [[ "${DUENYO}" == *vendi-traefik* ]]; then
        info "el puerto ${PUERTO} ya lo publica ${DUENYO} (nuestro Traefik): se reutiliza"
        continue
    fi
    if [[ -n "${DUENYO}" ]]; then
        error "El puerto ${PUERTO} lo publica el contenedor '${DUENYO}', que no es de Vendi. Párala antes de levantar Vendi:  docker stop ${DUENYO}"
    fi
    error "El puerto ${PUERTO} ya lo está usando el proceso '${EN_USO}'. Párala antes de levantar Vendi (suele ser otro stack de docker con su propio Traefik)."
done
success "puertos 80 y 443 disponibles"

# Resolución de nombres. Se comprueba por la MISMA vía que usarán curl, el
# navegador y verify-setup.sh (getaddrinfo del sistema), no solo preguntando a
# dnsmasq con `dig @127.0.0.1`. En macOS son dos cosas distintas: dnsmasq puede
# tener su `address=/vendi.local/127.0.0.1` y aun así el sistema no enrutarle
# las consultas si falta /etc/resolver/vendi.local. Con la comprobación vieja
# eso daba verde aquí y 000 en el check 11 de verify-setup.sh.
resuelve_a_loopback() {
    local nombre="$1" salida=""
    if command -v getent >/dev/null 2>&1; then
        salida="$(getent hosts "${nombre}" 2>/dev/null || true)"
    elif command -v dscacheutil >/dev/null 2>&1; then
        salida="$(dscacheutil -q host -a name "${nombre}" 2>/dev/null | awk '/^ip(v6)?_address:/ {print $2}')"
    elif command -v python3 >/dev/null 2>&1; then
        salida="$(python3 -c 'import socket,sys
try: print(socket.gethostbyname(sys.argv[1]))
except OSError: pass' "${nombre}" 2>/dev/null || true)"
    fi
    [[ "${salida}" == *127.0.0.1* || "${salida}" == *::1* ]]
}

if ! resuelve_a_loopback "api.${BASE_DOMAIN}"; then
    error "api.${BASE_DOMAIN} no resuelve a 127.0.0.1 por el resolver del sistema. Ejecuta: ./scripts/setup-dnsmasq.sh  (o --hosts-only)"
fi
success "el DNS del sistema resuelve *.${BASE_DOMAIN} -> 127.0.0.1"

# docker compose busca el .env en el directorio desde el que se invoca. El
# canónico vive en la raíz del repo, así que se enlaza una vez.
if [[ ! -e "${INFRA_DIR}/.env" ]]; then
    info "Enlazando infra/.env → ../.env para que docker compose vea las variables"
    ln -s ../.env "${INFRA_DIR}/.env"
fi

info "Construyendo las imágenes (la primera vez tarda unos minutos)..."
"${COMPOSE[@]}" build

info "Levantando el stack..."
"${COMPOSE[@]}" up -d

echo ""
success "Stack levantado. Estado: docker compose -f infra/docker-compose.yml ps"
echo ""
echo "URLs:"
echo "  API:                 https://api.${BASE_DOMAIN}/health"
echo "  Keycloak:            https://accounts.${BASE_DOMAIN}  (realm vendi-co)"
echo "  Grafana:             https://grafana.${BASE_DOMAIN}"
echo "  MailHog:             https://mail.${BASE_DOMAIN}"
echo "  Dashboard de Traefik: http://127.0.0.1:8088/dashboard/"
echo "  Consola de MinIO:     http://127.0.0.1:9001"
echo "  RabbitMQ:             http://127.0.0.1:15672"
echo ""
echo "Siguientes pasos:"
echo "  ./scripts/verify-setup.sh   # comprobar que todo responde"
echo "  ./scripts/migrate.sh        # migraciones de Alembic (rol vendi_platform)"
echo "  ./scripts/seed.sh           # datos de demostración"
echo "  cd frontend && npm start    # las apps Angular no van en el compose"
