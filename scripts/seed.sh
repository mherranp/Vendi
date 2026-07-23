#!/usr/bin/env bash
# =============================================================================
# seed.sh
#
# Siembra de desarrollo, idempotente. Lo que hará cuando esté completo
# (tarea 4.4 del plan de Fase 0):
#
#   - roles y grupos de realm: dueno, cajero, almacenista + los permisos de
#     policies.py (no están en el realm como código a propósito: --import-realm
#     no vuelve a ejecutarse sobre un realm existente, ver infra/keycloak/README.md)
#   - usuario admin@vendi.co con el permiso platform:admin
#   - un tenant de demostración "Tienda Don Carlos" creado VÍA LA API, para que
#     pase por el mismo camino de provisionamiento que producción (fila en
#     `tenants` + organización en Keycloak con alias = tenant_id)
#   - un usuario dueno@demo.vendi.co, miembro de esa organización
#
# Estado actual: el módulo `tenants` de la API no existe todavía (tarea 4.2),
# así que este script falla limpio en vez de fingir que sembró algo.
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
COMPOSE=(docker compose -f "${INFRA_DIR}/docker-compose.yml")

# Mismo criterio que dev.sh: en desarrollo el override forma PARTE de la
# definición de los servicios. Con solo el archivo base, un `up -d` o un `run`
# recrean cualquier servicio personalizado por el override —y los que arrastre
# el cierre de dependencias— perdiendo sus ajustes de desarrollo, en silencio.
OVERRIDE_DEV="${INFRA_DIR}/docker-compose.override.dev.yml"
if [[ "${VENDI_COMPOSE_SIN_OVERRIDE:-0}" != "1" && -f "${OVERRIDE_DEV}" ]]; then
    COMPOSE+=(-f "${OVERRIDE_DEV}")
fi

if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "${REPO_ROOT}/.env"
    set +a
fi
BASE_DOMAIN="${BASE_DOMAIN:-vendi.co}"

if [[ ! -d "${REPO_ROOT}/backend/services/api/app/modules/tenants" ]]; then
    error "La API todavía no tiene el módulo 'tenants' (llega con la tarea 4.2 del plan de Fase 0). No hay nada que sembrar."
fi

info "Asegurando que la API y Keycloak están arriba..."
"${COMPOSE[@]}" up -d api keycloak

info "Esperando a /health de la API..."
INTENTOS=60
for i in $(seq 1 "${INTENTOS}"); do
    if "${COMPOSE[@]}" exec -T api \
        python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" >/dev/null 2>&1; then
        success "la API responde"
        break
    fi
    [[ "$i" == "${INTENTOS}" ]] && error "la API no respondió a tiempo (mira: docker compose logs api)"
    sleep 2
done

info "Ejecutando la siembra..."
"${COMPOSE[@]}" exec -T api uv run --project /src --no-sync python -m app.scripts.seed

success "Siembra completa. Entra en https://app.${BASE_DOMAIN}"
