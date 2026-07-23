#!/usr/bin/env bash
# =============================================================================
# setup-dnsmasq.sh
#
# Hace que todos los dominios *.${BASE_DOMAIN} resuelvan a 127.0.0.1 usando
# dnsmasq, para poder abrir api.vendi.co, accounts.vendi.co, etc. sin
# editar /etc/hosts a mano.
#
# Plataformas: macOS (Homebrew) y Linux (apt/systemd).
#
# Uso:
#   ./scripts/setup-dnsmasq.sh
#   ./scripts/setup-dnsmasq.sh --hosts-only    # alternativa con /etc/hosts
#
# Diferencia con BaseSaaS: Vendi NO enruta por subdominio de tenant (el tenant
# sale del claim `organization` del token, no del host). El conjunto de
# subdominios es fijo y conocido, así que el modo --hosts-only es una
# alternativa COMPLETA, no una degradación: no se pierde nada.
# =============================================================================

set -euo pipefail

HOSTS_ONLY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hosts-only) HOSTS_ONLY=1; shift ;;
        -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
        *)            echo "Argumento desconocido: $1" >&2; exit 2 ;;
    esac
done

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[AVISO]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "${REPO_ROOT}/.env"
    set +a
fi

DOMAIN="${BASE_DOMAIN:-vendi.co}"
RESOLVE_IP="127.0.0.1"
# 1 en cuanto se toca algo del sistema. Gobierna si hace falta reiniciar
# dnsmasq y vaciar la caché de DNS (ver setup_macos/setup_linux).
CAMBIO=0
DNSMASQ_ENTRY="address=/${DOMAIN}/${RESOLVE_IP}"
# Subdominios de Vendi. `app` = vendi-tenant, `admin` = vendi-admin,
# `accounts` = Keycloak, `mail` = MailHog (solo desarrollo).
SUBDOMINIOS="www api accounts app admin grafana mail"

detect_os() {
    case "$(uname -s)" in
        Darwin) OS="macos" ;;
        Linux)  OS="linux" ;;
        *)      error "Sistema operativo no soportado: $(uname -s)" ;;
    esac
    info "Sistema detectado: ${OS}"
}

setup_macos() {
    command -v brew &>/dev/null || error "Hace falta Homebrew. https://brew.sh"

    if brew list dnsmasq &>/dev/null; then
        success "dnsmasq ya está instalado"
    else
        info "Instalando dnsmasq con Homebrew..."
        brew install dnsmasq
        success "dnsmasq instalado"
    fi

    if [[ -d "/opt/homebrew" ]]; then
        DNSMASQ_CONF="/opt/homebrew/etc/dnsmasq.conf"
    else
        DNSMASQ_CONF="/usr/local/etc/dnsmasq.conf"
    fi

    if grep -qF "${DNSMASQ_ENTRY}" "${DNSMASQ_CONF}" 2>/dev/null; then
        success "dnsmasq ya está configurado para *.${DOMAIN}"
    else
        info "Añadiendo la entrada comodín a ${DNSMASQ_CONF}..."
        echo "${DNSMASQ_ENTRY}" | sudo tee -a "${DNSMASQ_CONF}" >/dev/null
        success "Entrada añadida"
        CAMBIO=1
    fi

    RESOLVER_FILE="/etc/resolver/${DOMAIN}"
    if [[ -f "${RESOLVER_FILE}" ]] && grep -qF "nameserver ${RESOLVE_IP}" "${RESOLVER_FILE}" 2>/dev/null; then
        success "El resolver ya existe en ${RESOLVER_FILE}"
    else
        info "Creando el resolver en ${RESOLVER_FILE}..."
        sudo mkdir -p /etc/resolver
        echo "nameserver ${RESOLVE_IP}" | sudo tee "${RESOLVER_FILE}" >/dev/null
        success "Resolver creado"
        CAMBIO=1
    fi

    # El reinicio solo si algo cambió. Antes era incondicional, y eso hacía que
    # re-ejecutar el script —lo que hace cualquiera que dude de su DNS— pidiera
    # sudo y bounceara el resolver de TODA la máquina (dnsmasq sirve también
    # los demás dominios locales del desarrollador) sin necesidad. Idempotente
    # de verdad: segunda ejecución = cero privilegios, cero interrupción.
    if [[ "${CAMBIO}" -eq 1 ]]; then
        info "Reiniciando dnsmasq..."
        sudo brew services restart dnsmasq
        success "dnsmasq reiniciado"

        # Sin vaciar la caché, mDNSResponder sigue sirviendo el NXDOMAIN que
        # cacheó antes de existir el resolver, y la comprobación de abajo falla
        # aunque la configuración ya sea correcta.
        info "Vaciando la caché de DNS del sistema..."
        sudo dscacheutil -flushcache 2>/dev/null || true
        sudo killall -HUP mDNSResponder 2>/dev/null || true
    else
        info "Nada que cambiar: no reinicio dnsmasq"
    fi
}

setup_linux() {
    if command -v dnsmasq &>/dev/null; then
        success "dnsmasq ya está instalado"
    else
        info "Instalando dnsmasq..."
        sudo apt update -qq
        sudo apt install -y dnsmasq
        success "dnsmasq instalado"
    fi

    DNSMASQ_CONF="/etc/dnsmasq.d/${DOMAIN}.conf"
    if [[ -f "${DNSMASQ_CONF}" ]] && grep -qF "${DNSMASQ_ENTRY}" "${DNSMASQ_CONF}" 2>/dev/null; then
        success "dnsmasq ya está configurado para *.${DOMAIN}"
    else
        info "Escribiendo ${DNSMASQ_CONF}..."
        echo "${DNSMASQ_ENTRY}" | sudo tee "${DNSMASQ_CONF}" >/dev/null
        success "Configuración escrita"
        CAMBIO=1
    fi

    if [[ "${CAMBIO}" -eq 1 ]]; then
        info "Reiniciando dnsmasq..."
        sudo systemctl restart dnsmasq
        success "dnsmasq reiniciado"
        sudo systemd-resolve --flush-caches 2>/dev/null || true
    else
        info "Nada que cambiar: no reinicio dnsmasq"
    fi
}

# Alternativa sin dnsmasq: bloque delimitado en /etc/hosts, reescrito en cada
# ejecución (idempotente, no se acumulan líneas).
setup_hosts_only() {
    local marca_inicio="# >>> vendi ${DOMAIN} inicio >>>"
    local marca_fin="# <<< vendi ${DOMAIN} fin <<<"

    info "Escribiendo /etc/hosts para *.${DOMAIN} (modo --hosts-only)"

    local tmp
    tmp="$(mktemp)"
    awk -v b="${marca_inicio}" -v e="${marca_fin}" '
        $0 == b {skip=1; next}
        $0 == e {skip=0; next}
        !skip   {print}
    ' /etc/hosts > "${tmp}"

    {
        echo "${marca_inicio}"
        echo "${RESOLVE_IP} ${DOMAIN}"
        for s in ${SUBDOMINIOS}; do
            echo "${RESOLVE_IP} ${s}.${DOMAIN}"
        done
        echo "${marca_fin}"
    } >> "${tmp}"

    sudo cp "${tmp}" /etc/hosts
    rm -f "${tmp}"
    success "/etc/hosts actualizado con ${DOMAIN} y sus subdominios"

    # macOS cachea el NXDOMAIN anterior en mDNSResponder; sin vaciar la caché,
    # verify() fallaría con /etc/hosts ya correcto.
    if [[ "$(uname -s)" == "Darwin" ]]; then
        info "Vaciando la caché de DNS del sistema..."
        sudo dscacheutil -flushcache 2>/dev/null || true
        sudo killall -HUP mDNSResponder 2>/dev/null || true
    fi
}

# Resolución por la MISMA vía que usarán curl, el navegador, dev.sh y
# verify-setup.sh: el resolver del sistema (getaddrinfo). Preguntarle
# directamente a dnsmasq con `dig @127.0.0.1` NO sirve como comprobación: en
# macOS dnsmasq puede estar perfecto y el sistema no enrutarle las consultas
# de *.${DOMAIN} porque falta /etc/resolver/${DOMAIN} o porque la caché
# todavía tiene el NXDOMAIN anterior. Esa era la brecha por la que este script
# decía «Listo» y luego el check 11 de verify-setup.sh devolvía 000.
resuelve_a_loopback() {
    local nombre="$1" salida=""
    if command -v getent &>/dev/null; then
        salida="$(getent hosts "${nombre}" 2>/dev/null || true)"
    elif command -v dscacheutil &>/dev/null; then
        salida="$(dscacheutil -q host -a name "${nombre}" 2>/dev/null | awk '/^ip(v6)?_address:/ {print $2}')"
    elif command -v python3 &>/dev/null; then
        salida="$(python3 -c 'import socket,sys
try: print(socket.gethostbyname(sys.argv[1]))
except OSError: pass' "${nombre}" 2>/dev/null || true)"
    fi
    [[ "${salida}" == *"${RESOLVE_IP}"* || "${salida}" == *"::1"* ]]
}

verify() {
    info "Comprobando la resolución por el resolver del sistema..."
    # Los nombres reales que el stack necesita, no un nombre de prueba: si
    # alguno faltara (modo --hosts-only con la lista desactualizada), aquí se
    # ve.
    local fallidos=""
    for s in ${SUBDOMINIOS}; do
        local intentos=0
        until resuelve_a_loopback "${s}.${DOMAIN}"; do
            intentos=$((intentos + 1))
            [[ ${intentos} -ge 5 ]] && { fallidos="${fallidos} ${s}.${DOMAIN}"; break; }
            sleep 1
        done
    done

    if [[ -z "${fallidos}" ]]; then
        success "todos los subdominios resuelven a ${RESOLVE_IP}: ${SUBDOMINIOS}"
        return 0
    fi

    warn "estos nombres NO resuelven a ${RESOLVE_IP}:${fallidos}"
    warn "Vacía la caché de DNS y reintenta:"
    warn "  macOS: sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder"
    warn "  Linux: sudo systemd-resolve --flush-caches"
    error "el DNS local no quedó operativo; dev.sh fallaría igualmente en su comprobación previa"
}

main() {
    echo ""
    info "=== DNS local de Vendi (*.${DOMAIN} -> ${RESOLVE_IP}) ==="
    echo ""
    detect_os

    if [[ "${HOSTS_ONLY}" -eq 1 ]]; then
        setup_hosts_only
        echo ""
        # Misma comprobación que en el camino de dnsmasq: «Listo» solo se
        # imprime si los nombres resuelven de verdad.
        verify
        echo ""
        success "Listo (modo --hosts-only)."
        return
    fi

    case "${OS}" in
        macos) setup_macos ;;
        linux) setup_linux ;;
    esac

    echo ""
    verify
    echo ""
    success "Listo. Todos los *.${DOMAIN} resuelven a ${RESOLVE_IP}."
}

main "$@"
