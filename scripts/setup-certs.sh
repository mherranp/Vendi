#!/usr/bin/env bash
# =============================================================================
# setup-certs.sh
#
# Genera el certificado TLS comodín de desarrollo para ${BASE_DOMAIN} y
# *.${BASE_DOMAIN} con mkcert. La CA local de mkcert tiene que estar instalada
# antes (`mkcert -install`).
#
# Los certificados se escriben en infra/certs/ (ignorado por git) con los
# nombres ${BASE_DOMAIN}.pem y ${BASE_DOMAIN}-key.pem, que son exactamente los
# que referencia el template de Traefik
# (infra/traefik/templates/dynamic.yml.tpl) por expansión de ${BASE_DOMAIN}.
#
# Cosechado de BaseSaaS: solo cambian las rutas (infrastructure/ → infra/) y
# el dominio por defecto.
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[AVISO]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CERTS_DIR="${REPO_ROOT}/infra/certs"

if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "${REPO_ROOT}/.env"
    set +a
fi

BASE_DOMAIN="${BASE_DOMAIN:-vendi.co}"

if ! command -v mkcert &>/dev/null; then
    error "mkcert no está instalado. macOS: brew install mkcert · otros: https://github.com/FiloSottile/mkcert"
fi

CA_ROOT="$(mkcert -CAROOT 2>/dev/null || true)"
if [[ -z "${CA_ROOT}" || ! -f "${CA_ROOT}/rootCA.pem" ]]; then
    warn "No se encuentra la CA de mkcert. Ejecuta \`mkcert -install\` una vez antes de esto."
    info "Continúo igualmente; puede que tengas que repetir el comando después."
fi

mkdir -p "${CERTS_DIR}"
cd "${CERTS_DIR}"

info "Generando certificado comodín para ${BASE_DOMAIN} y *.${BASE_DOMAIN}..."
mkcert \
    -cert-file "${BASE_DOMAIN}.pem" \
    -key-file "${BASE_DOMAIN}-key.pem" \
    "${BASE_DOMAIN}" "*.${BASE_DOMAIN}" "localhost" "127.0.0.1"

success "Certificados escritos en ${CERTS_DIR}/${BASE_DOMAIN}.pem y ${BASE_DOMAIN}-key.pem"
echo ""
info "Traefik los recoge solo: el template de configuración dinámica los"
info "referencia por \${BASE_DOMAIN} y se renderiza al arrancar el contenedor."
info "Si el navegador sigue avisando, reinícialo para que confíe en la CA."
