#!/usr/bin/env bash
# =============================================================================
# seed.sh
#
# Siembra de desarrollo, idempotente. Deja montado:
#
#   - los permisos de Vendi como roles de realm (policies.py) y los roles de
#     negocio (dueno, cajero, almacenista) como grupos de Keycloak con sus
#     permisos mapeados. NO están en el realm como código a propósito:
#     --import-realm no se vuelve a ejecutar sobre un realm existente, así que
#     el realm JSON es semilla y no estado deseado (D-03).
#   - el usuario admin@vendi.co con el permiso platform:admin y SIN ninguna
#     organización: es empleado de Vendi, no dueño de un negocio.
#   - el negocio de demostración «Tienda Don Carlos» con su organización de
#     Keycloak (alias = tenant_id), creado por el MISMO servicio de
#     aprovisionamiento que usa la consola.
#   - el usuario dueno@demo.vendi.co, en el grupo `dueno` y miembro de esa
#     organización.
#
# CORRERLO DOS VECES ES UN NO-OP LIMPIO. Cada paso comprueba antes de crear.
#
# La lógica vive en backend/services/api/app/scripts/seed.py y se ejecuta
# DENTRO del contenedor de la API: así usa exactamente el mismo código, la
# misma configuración y los mismos DSN que sirve producción, en vez de una
# reimplementación en bash que se desincroniza en cuanto cambie el modelo.
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

: "${SEED_ADMIN_PASSWORD:?falta SEED_ADMIN_PASSWORD; copia .env.example a .env}"
: "${SEED_DUENO_PASSWORD:?falta SEED_DUENO_PASSWORD; copia .env.example a .env}"

info "Asegurando que postgres, la API y Keycloak están arriba..."
"${COMPOSE[@]}" up -d postgres api keycloak

# Las migraciones son requisito, no cortesía: sin la tabla `tenants` la siembra
# reventaría a mitad, dejando el realm sembrado y la base no.
if ! "${COMPOSE[@]}" exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -d vendi -tAc \
        "SELECT to_regclass('public.tenants')" 2>/dev/null | grep -q '^tenants$'; then
    error "La tabla 'tenants' no existe. Ejecuta primero: bash scripts/migrate.sh"
fi

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
# Las contraseñas se pasan con -e y no viven en el entorno del servicio: el
# contenedor de la API no tiene por qué llevarlas puestas el 100% del tiempo
# solo para que un script las use durante un minuto.
"${COMPOSE[@]}" exec -T \
    -e SEED_ADMIN_PASSWORD="${SEED_ADMIN_PASSWORD}" \
    -e SEED_DUENO_PASSWORD="${SEED_DUENO_PASSWORD}" \
    api uv run --project /src --no-sync python -m app.scripts.seed

success "Siembra completa."
echo ""
echo "  Consola de plataforma  : https://admin.${BASE_DOMAIN}   admin@vendi.co"
echo "  Aplicación del negocio : https://app.${BASE_DOMAIN}     dueno@demo.vendi.co"
echo "  Negocio de demostración: «Tienda Don Carlos»"
echo ""
