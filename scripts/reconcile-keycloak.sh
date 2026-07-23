#!/usr/bin/env bash
# =============================================================================
# reconcile-keycloak.sh
#
# Detecta y reporta DOS derivas distintas. Se ejecuta después de tocar cosas a
# mano en la consola de Keycloak, o cuando se sospecha que un alta de tenant se
# quedó a medias:
#
#   1. Deriva de CONFIGURACIÓN: clientes, flujos de autenticación, ajustes de
#      seguridad del realm y roles de la cuenta de servicio de `vendi-backend`,
#      comparados contra infra/keycloak/realm-vendi-co.json. Solo informa: la
#      corrección de configuración la aplica el operador (ver
#      scripts/lib/kc_deriva_config.py).
#   2. Deriva de DATOS: organizaciones de Keycloak contra la tabla `tenants`.
#      Es la que sabrá corregir la API con RECONCILE_APLICAR=1 (tarea 4.2).
#
# Por qué existe (y por qué no basta con reiniciar Keycloak): `--import-realm`
# importa el realm SOLO si no existe. Verificado contra 26.6.4:
#
#     INFO [ImportUtils] Realm 'vendi-co' already exists. Import skipped
#
# O sea: el realm como código es la semilla del día 1, no el estado deseado
# continuo. Este script es el que mantiene el estado deseado continuo.
#
# Diferencia con BaseSaaS: allí se recorrían los REALMS (uno por tenant); aquí
# se recorren las ORGANIZACIONES del único realm regional `vendi-co`, con
# paginación, y se comparan con la tabla `tenants`. La correspondencia es
# directa porque alias = str(tenant_id) (decisión 3 del informe del spike KC).
#
# Variables:
#   KEYCLOAK_URL              base de la Admin API (por defecto http://127.0.0.1:8080,
#                             el puerto que el compose publica en loopback)
#   KEYCLOAK_ADMIN_USER/_PASSWORD
#   RECONCILE_APLICAR=1       aplica las correcciones en vez de solo informar
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

if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "${REPO_ROOT}/.env"
    set +a
fi

REALM="vendi-co"
KC_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KC_ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:?falta KEYCLOAK_ADMIN_PASSWORD; copia .env.example a .env}"
PAGINA=100

# La imagen oficial de Keycloak 26 es UBI-micro: NO trae curl ni python, así
# que no se puede llamar a la Admin API con `docker compose exec keycloak
# curl`. Se llama desde el anfitrión al puerto que el compose publica en
# loopback, que además funciona igual sin tener resuelto vendi.local.
KC_URL_BASE="${KEYCLOAK_URL:-http://127.0.0.1:8080}"
kc_curl() {
    curl -s --connect-timeout 5 --max-time 30 "$@"
}

info "Obteniendo token de administración del realm master..."
TOKEN="$(kc_curl -X POST "${KC_URL_BASE}/realms/master/protocol/openid-connect/token" \
    -d client_id=admin-cli -d "username=${KC_ADMIN_USER}" \
    -d "password=${KC_ADMIN_PASS}" -d grant_type=password \
    | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')"
if [[ -z "${TOKEN}" ]]; then
    error "no pude obtener el token de administración de Keycloak (¿está arriba el contenedor? ¿son correctas KEYCLOAK_ADMIN_USER/PASSWORD?)"
fi
success "token obtenido"

# ---------------------------------------------------------------------------
# 0. Deriva de CONFIGURACIÓN del realm: clientes, flujos, ajustes de seguridad
#    y roles de la cuenta de servicio, contra infra/keycloak/realm-vendi-co.json.
#
#    Esto es lo que se rompe cuando alguien "prueba una cosa" en la consola:
#    `--import-realm` no vuelve a correr sobre un realm existente, así que sin
#    esta comparación el JSON del repositorio y el realm vivo divergen para
#    siempre y nadie se entera. El caso que más duele: que la cuenta de
#    servicio de vendi-backend acabe con más roles de los que declara el JSON.
#
#    Es solo DETECCIÓN. Corregir configuración de realm a ciegas puede tirar
#    sesiones y credenciales, así que la corrección es del operador.
# ---------------------------------------------------------------------------
REALM_JSON="${INFRA_DIR}/keycloak/realm-vendi-co.json"
DERIVA_CONFIG=0
if [[ -f "${REALM_JSON}" ]]; then
    info "Comparando la configuración del realm con $(basename "${REALM_JSON}")..."
    SALIDA_CONFIG="$(KC_URL_BASE="${KC_URL_BASE}" KC_TOKEN="${TOKEN}" KC_REALM="${REALM}" \
        REALM_JSON="${REALM_JSON}" python3 "${SCRIPT_DIR}/lib/kc_deriva_config.py")" || DERIVA_CONFIG=$?
    printf '%s\n' "${SALIDA_CONFIG}"
else
    warn "no encuentro ${REALM_JSON}: me salto la comparación de clientes y flujos"
fi

# ---------------------------------------------------------------------------
# 1. Organizaciones de Keycloak (paginado: la Admin API devuelve 10 por
#    defecto, y con 200 negocios eso serían 20 páginas silenciosamente
#    truncadas a la primera).
# ---------------------------------------------------------------------------
info "Listando las organizaciones del realm ${REALM}..."
PRIMERO=0
ALIAS_KC=""
while :; do
    LOTE="$(kc_curl -H "Authorization: Bearer ${TOKEN}" \
        "${KC_URL_BASE}/admin/realms/${REALM}/organizations?first=${PRIMERO}&max=${PAGINA}" \
        | python3 -c 'import sys,json
try:
    datos = json.load(sys.stdin)
except Exception:
    datos = []
print("\n".join(o.get("alias","") for o in datos))')"
    [[ -z "${LOTE}" ]] && break
    ALIAS_KC="${ALIAS_KC}${LOTE}"$'\n'
    N=$(printf '%s\n' "${LOTE}" | grep -c . || true)
    [[ "${N}" -lt "${PAGINA}" ]] && break
    PRIMERO=$((PRIMERO + PAGINA))
done
N_KC=$(printf '%s' "${ALIAS_KC}" | grep -c . || true)
success "${N_KC} organización(es) en Keycloak"

# ---------------------------------------------------------------------------
# 2. Tenants de la base de datos. La tabla llega con la tarea 4.2; hasta
#    entonces el script informa y sale sin fingir que reconcilió nada.
# ---------------------------------------------------------------------------
EXISTE_TABLA="$("${COMPOSE[@]}" exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -d vendi -tAc \
    "SELECT to_regclass('public.tenants') IS NOT NULL" 2>/dev/null | tr -d '[:space:]')"

if [[ "${EXISTE_TABLA}" != "t" ]]; then
    warn "La tabla 'tenants' todavía no existe (llega con la tarea 4.2 del plan de Fase 0)."
    # Solo tiene sentido listar organizaciones si las hay: con el realm recién
    # sembrado (0 organizaciones) el mensaje afirmaría un hecho falso.
    if [[ "${N_KC}" -gt 0 ]]; then
        warn "Organizaciones encontradas en Keycloak, sin nada contra qué compararlas:"
        printf '%s' "${ALIAS_KC}" | sed 's/^/    /'
    fi
    error "Reconciliación imposible: la API aún no tiene el módulo tenants."
fi

info "Listando los tenants activos de la base de datos..."
ALIAS_BD="$("${COMPOSE[@]}" exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -d vendi -tAc \
    "SELECT id::text FROM public.tenants WHERE estado <> 'eliminado'" 2>/dev/null | tr -d '\r')"
N_BD=$(printf '%s' "${ALIAS_BD}" | grep -c . || true)
success "${N_BD} tenant(s) en la base de datos"

# ---------------------------------------------------------------------------
# 3. Diferencias en los dos sentidos. Los dos son bugs distintos:
#    - tenant sin organización: el alta se cayó tras el INSERT (los usuarios
#      del negocio no pueden entrar).
#    - organización sin tenant: el alta se cayó tras crear la organización, o
#      alguien la creó a mano (huérfana, ocupa un alias).
# ---------------------------------------------------------------------------
TMP_KC="$(mktemp)"; TMP_BD="$(mktemp)"
printf '%s' "${ALIAS_KC}" | grep . | sort > "${TMP_KC}"
printf '%s' "${ALIAS_BD}" | grep . | sort > "${TMP_BD}"

SIN_ORG="$(comm -23 "${TMP_BD}" "${TMP_KC}")"
SIN_TENANT="$(comm -13 "${TMP_BD}" "${TMP_KC}")"
rm -f "${TMP_KC}" "${TMP_BD}"

DERIVA=0
if [[ -n "${SIN_ORG}" ]]; then
    DERIVA=1
    warn "Tenants SIN organización en Keycloak (sus usuarios no pueden entrar):"
    printf '%s' "${SIN_ORG}" | sed 's/^/    /'
fi
if [[ -n "${SIN_TENANT}" ]]; then
    DERIVA=1
    warn "Organizaciones HUÉRFANAS en Keycloak (sin tenant en la base de datos):"
    printf '%s' "${SIN_TENANT}" | sed 's/^/    /'
fi

# La deriva de CONFIGURACIÓN pesa igual que la de organizaciones. Antes se
# calculaba, se imprimía como [AVISO] y no se leía nunca: en cuanto los tenants
# cuadraran, el script salía 0 con la deriva en pantalla, y para cualquier
# automatización eso es «verde». Un detector que no puede suspender no detecta.
if [[ "${DERIVA}" -eq 0 && "${DERIVA_CONFIG}" -eq 0 ]]; then
    success "Sin deriva: ${N_BD} tenant(s) y ${N_KC} organización(es) cuadran, y la configuración del realm coincide con el JSON."
    exit 0
fi

if [[ "${DERIVA}" -eq 0 && "${DERIVA_CONFIG}" -ne 0 ]]; then
    warn "Los tenants cuadran (${N_BD} y ${N_KC}), pero el realm vivo NO coincide con $(basename "${REALM_JSON}") (ver arriba)."
    warn "La configuración de realm no se corrige automáticamente: hacerlo a ciegas tira sesiones y credenciales. Es del operador."
    exit 1
fi

if [[ "${RECONCILE_APLICAR:-0}" != "1" ]]; then
    warn "Modo informe. Para aplicar las correcciones: RECONCILE_APLICAR=1 $0"
    exit 1
fi

# La corrección crea organizaciones faltantes vía la API (no directamente en
# Keycloak) para que pase por el mismo código de provisionamiento, con su
# auditoría y su compensación. Ese endpoint llega con la tarea 4.2.
error "La aplicación automática de correcciones necesita el endpoint de reconciliación de la API (tarea 4.2)."
