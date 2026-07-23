#!/usr/bin/env bash
# =============================================================================
# migrate.sh
#
# Ejecuta las migraciones de Alembic dentro de un contenedor efímero de la API.
#
# DECISIÓN CRÍTICA (informe 2026-07-22-verificacion-rls.md, decisión 6):
# Alembic corre SIEMPRE con el rol `vendi_platform`, no con `vendi_app`. Bajo
# `FORCE ROW LEVEL SECURITY`, cualquier rol sin BYPASSRLS —incluido el dueño de
# la tabla— ve CERO filas. Un backfill hecho con vendi_app no fallaría: se
# ejecutaría "correctamente" sobre cero filas y dejaría los datos a medias sin
# un solo error en el log. Por eso el DSN se fija aquí y no se hereda del
# entorno de la API.
#
# A diferencia de BaseSaaS, no hay bucle por schemas de tenant: Vendi es un
# schema único regional con RLS, así que es una sola pasada.
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

# ---------------------------------------------------------------------------
# Alembic llega en la tarea 3.8. Hasta entonces esto falla con un mensaje
# claro en vez de con un traceback de "no such file" o, peor, con un éxito
# vacío que haría pensar que las migraciones se aplicaron.
# ---------------------------------------------------------------------------
if [[ ! -f "${REPO_ROOT}/backend/services/api/alembic.ini" ]]; then
    error "Todavía no hay migraciones: backend/services/api/alembic.ini no existe (llega con la tarea 3.8 del plan de Fase 0)."
fi

: "${VENDI_PLATFORM_DB_PASSWORD:?falta VENDI_PLATFORM_DB_PASSWORD; copia .env.example a .env}"

info "Asegurando que postgres está arriba y sano..."
"${COMPOSE[@]}" up -d postgres

INTENTOS=30
for i in $(seq 1 "${INTENTOS}"); do
    if "${COMPOSE[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER:-postgres}" >/dev/null 2>&1; then
        success "postgres listo"
        break
    fi
    [[ "$i" == "${INTENTOS}" ]] && error "postgres no llegó a estar listo a tiempo"
    sleep 2
done

info "Ejecutando 'alembic upgrade head' con el rol vendi_platform..."
set +e
"${COMPOSE[@]}" run --rm --no-deps \
    -e DATABASE_URL="postgresql+asyncpg://vendi_platform:${VENDI_PLATFORM_DB_PASSWORD}@postgres:5432/vendi" \
    api \
    uv run --project /src --no-sync alembic upgrade head
rc=$?
set -e

[[ ${rc} -ne 0 ]] && error "alembic upgrade head falló con código ${rc}"

info "Revisión actual tras la migración:"
"${COMPOSE[@]}" run --rm --no-deps \
    -e DATABASE_URL="postgresql+asyncpg://vendi_platform:${VENDI_PLATFORM_DB_PASSWORD}@postgres:5432/vendi" \
    api \
    uv run --project /src --no-sync alembic current 2>&1 || true

success "Migraciones aplicadas."
