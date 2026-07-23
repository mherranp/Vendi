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
BASE_DOMAIN="${BASE_DOMAIN:-vendi.co}"

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
# tener su `address=/vendi.co/127.0.0.1` y aun así el sistema no enrutarle
# las consultas si falta /etc/resolver/vendi.co. Con la comprobación vieja
# eso daba verde aquí y 000 en el check 11 de verify-setup.sh.
resolucion_de() {
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
    echo "${salida}"
}

resuelve_a_loopback() {
    local salida
    salida="$(resolucion_de "$1")"
    [[ "${salida}" == *127.0.0.1* || "${salida}" == *::1* ]]
}

# El DNS del sistema NO es requisito para levantar el stack: Traefik hace bind
# en 127.0.0.1:443 y sirve igual. Pero la pregunta que importa NO es «¿resuelve?»
# sino «¿a dónde resuelve?», y hay que separar dos fallos que no se parecen en
# nada aunque los dos empiecen por "el nombre no apunta a 127.0.0.1":
#
#   · NO RESUELVE (NXDOMAIN). Falla CERRADO: los clientes no llegan a ninguna
#     parte, no se filtra nada. Es lo que pasaba con `vendi.local`, un TLD que
#     no existe. Molesto, inofensivo: se avisa y se sigue.
#
#   · RESUELVE FUERA DE ESTA MÁQUINA. Falla ABIERTO, y esto sí es grave.
#     `vendi.co` es un dominio REAL y registrado: sin el resolver local, cada
#     nombre sale a Internet. Hoy `accounts.vendi.co` —el IdP— responde desde
#     64.190.63.222 con un certificado DigiCert VÁLIDO para ese nombre exacto,
#     así que la validación TLS da cadena correcta y nadie se entera: un POST al
#     endpoint de token entrega el `client_secret` de `vendi-provisioning` a un
#     tercero. Aquí se ABORTA. Levantar el stack en este estado es justo lo que
#     no se debe hacer.
#
# La versión anterior de esta comprobación trataba los dos casos igual (avisar y
# seguir) porque venía de la época de `vendi.local`, cuando solo existía el
# primero. Con un TLD real esa equivalencia dejó de ser cierta.
RESOLVER_SISTEMA="/etc/resolver/${BASE_DOMAIN}"
RESOLUCION="$(resolucion_de "api.${BASE_DOMAIN}")"
if resuelve_a_loopback "api.${BASE_DOMAIN}"; then
    success "el DNS del sistema resuelve *.${BASE_DOMAIN} -> 127.0.0.1"
elif [[ -n "${RESOLUCION}" ]]; then
    echo "" >&2
    echo -e "${RED}  api.${BASE_DOMAIN} resuelve FUERA de esta máquina:${NC}" >&2
    echo "    ${RESOLUCION}" >&2
    echo "" >&2
    echo "  ${BASE_DOMAIN} es un dominio real. Sin ${RESOLVER_SISTEMA}, todo cliente que" >&2
    echo "  no fije la resolución a mano sale a Internet en vez de hablar con Traefik." >&2
    echo "  accounts.${BASE_DOMAIN} es el IdP y el host público tiene certificado válido," >&2
    echo "  así que TLS no avisa de nada y los secretos de cliente se transmiten a un" >&2
    echo "  tercero. No se levanta el stack en este estado." >&2
    echo "" >&2
    echo "  Arréglalo con los dos pasos de sudo (docs/runbooks/dns-y-tls-local.md, A):" >&2
    echo "    sudo tee ${RESOLVER_SISTEMA} <<<'nameserver 127.0.0.1'" >&2
    echo "    sudo brew services restart dnsmasq" >&2
    echo "    sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder" >&2
    echo "" >&2
    error "resolución insegura de *.${BASE_DOMAIN}: apunta a Internet, no a esta máquina."
elif [[ "$(uname -s)" == "Darwin" && ! -f "${RESOLVER_SISTEMA}" ]]; then
    warn "api.${BASE_DOMAIN} no resuelve y falta ${RESOLVER_SISTEMA} (necesita sudo)."
    warn "Esto falla CERRADO —ningún cliente llega a ninguna parte— así que se sigue,"
    warn "pero el nombre no se podrá teclear en el navegador hasta completar el"
    warn "procedimiento A de docs/runbooks/dns-y-tls-local.md. Mientras tanto:"
    warn "  curl --resolve api.${BASE_DOMAIN}:443:127.0.0.1 https://api.${BASE_DOMAIN}/health"
else
    error "api.${BASE_DOMAIN} no resuelve a 127.0.0.1 y ${RESOLVER_SISTEMA} SÍ existe: el DNS local está roto, no solo pendiente. Ejecuta: ./scripts/setup-dnsmasq.sh  (o --hosts-only)"
fi

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
