#!/usr/bin/env bash
# =============================================================================
# verify-setup.sh
#
# Prueba de humo de los primeros cinco minutos. Comprueba, uno por uno, que
# cada pieza del stack de Vendi responde, e imprime OK / FALLO / OMITIDO.
#
# Reglas de diseño (las impuso el QA adversarial del plan):
#
#   1. Un check que no se puede evaluar todavía se marca OMITIDO con el motivo
#      y la tarea que lo habilita. NUNCA verde falso.
#   2. Todo check tiene tope de tiempo. Con el stack entero caído, el script
#      termina en segundos, no se cuelga.
#   3. El resumen distingue fallos de omisiones. El código de salida es 0 solo
#      si no hubo NINGÚN fallo.
#
# Uso:
#   ./scripts/verify-setup.sh
#   BASE_DOMAIN=otro.local ./scripts/verify-setup.sh
#
# Compatible con bash 3.2 (el que trae macOS).
# =============================================================================

set -uo pipefail   # sin -e: un check que falla no debe abortar el resto

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; PASADAS=$((PASADAS + 1)); }
falla(){ echo -e "${RED}[FALLO]${NC} $*"; FALLIDAS=$((FALLIDAS + 1)); }
omite(){ echo -e "${YELLOW}[OMITIDO]${NC} $*"; OMITIDAS=$((OMITIDAS + 1)); }

PASADAS=0; FALLIDAS=0; OMITIDAS=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${REPO_ROOT}/infra"
COMPOSE=(docker compose -f "${INFRA_DIR}/docker-compose.yml")

# El .env aporta los valores por defecto, pero lo que venga YA en el entorno
# gana. Sin esto, `APP_ENV=production ./scripts/verify-setup.sh` se ignoraba en
# silencio (el `. .env` pisaba la variable) y el check 17 nunca se ejecutaba:
# el script prometía un modo de uso que no funcionaba.
ANULABLES="APP_ENV BASE_DOMAIN POSTGRES_USER KEYCLOAK_ADMIN_USER KEYCLOAK_ADMIN_PASSWORD"
for VAR in ${ANULABLES}; do
    eval "PREVIO_${VAR}=\${${VAR}:-}"
done

if [ -f "${REPO_ROOT}/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "${REPO_ROOT}/.env"
    set +a
fi

for VAR in ${ANULABLES}; do
    eval "VALOR_PREVIO=\${PREVIO_${VAR}}"
    if [ -n "${VALOR_PREVIO}" ]; then
        eval "${VAR}=\${VALOR_PREVIO}"
    fi
done

BASE_DOMAIN="${BASE_DOMAIN:-vendi.co}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
APP_ENV="${APP_ENV:-development}"
CURL_TOPES=(--connect-timeout 3 --max-time 8)

# Ejecuta un comando dentro de un servicio del compose. Si el servicio no está
# arriba, docker devuelve error de inmediato (no hay riesgo de cuelgue).
en_servicio() {
    servicio="$1"; shift
    "${COMPOSE[@]}" exec -T "${servicio}" "$@" 2>/dev/null
}

# ¿Este nombre resuelve a loopback POR EL RESOLVER DEL SISTEMA? Es la misma
# vía que usan curl y el navegador. Preguntarle directamente a dnsmasq con
# `dig @127.0.0.1` no vale: en macOS dnsmasq puede estar bien configurado y el
# sistema no enrutarle las consultas de *.vendi.co por faltar
# /etc/resolver/vendi.co. Se usa para diagnosticar el check 11.
resolucion_de() {
    nombre="$1"; salida=""
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
    salida="$(resolucion_de "$1")"
    case "${salida}" in
        *127.0.0.1*|*::1*) return 0 ;;
        *) return 1 ;;
    esac
}

# ¿Este nombre resuelve a algo que NO es esta máquina? Es la condición peligrosa
# y merece su propia función porque es distinta de "no resuelve": la primera
# manda el tráfico a un tercero, la segunda no lo manda a ninguna parte.
resuelve_fuera() {
    salida="$(resolucion_de "$1")"
    [ -n "${salida}" ] && ! resuelve_a_loopback "$1"
}

# CA de mkcert: el ancla de confianza para diagnosticar TLS sin recurrir a -k.
ca_de_mkcert() {
    if [ -n "${VENDI_MKCERT_CAROOT:-}" ] && [ -f "${VENDI_MKCERT_CAROOT}/rootCA.pem" ]; then
        echo "${VENDI_MKCERT_CAROOT}/rootCA.pem"; return 0
    fi
    if command -v mkcert >/dev/null 2>&1; then
        raiz="$(mkcert -CAROOT 2>/dev/null)"
        if [ -n "${raiz}" ] && [ -f "${raiz}/rootCA.pem" ]; then
            echo "${raiz}/rootCA.pem"; return 0
        fi
    fi
    for raiz in "${HOME}/Library/Application Support/mkcert" "${HOME}/.local/share/mkcert"; do
        if [ -f "${raiz}/rootCA.pem" ]; then echo "${raiz}/rootCA.pem"; return 0; fi
    done
    return 1
}

echo ""
info "Verificando el stack de Vendi (BASE_DOMAIN=${BASE_DOMAIN}, APP_ENV=${APP_ENV})"
echo ""

# ---------------------------------------------------------------------------
# 1. PostgreSQL acepta conexiones.
# ---------------------------------------------------------------------------
info "1. PostgreSQL acepta conexiones"
if en_servicio postgres pg_isready -U "${POSTGRES_USER}" >/dev/null; then
    ok "postgres responde a pg_isready"
else
    falla "postgres no responde (docker compose logs postgres)"
fi

# ---------------------------------------------------------------------------
# 2. Los dos roles de RLS existen con los atributos correctos.
#    Este es EL check del aislamiento multi-tenant: si vendi_app tuviera
#    BYPASSRLS, todas las policies del producto serían decorativas.
# ---------------------------------------------------------------------------
info "2. Roles de RLS: vendi_app sin BYPASSRLS, vendi_platform con BYPASSRLS"
APP_BYPASS="$(en_servicio postgres psql -U "${POSTGRES_USER}" -d vendi -tAc \
    "SELECT rolbypassrls FROM pg_roles WHERE rolname='vendi_app'" | tr -d '[:space:]')"
PLAT_BYPASS="$(en_servicio postgres psql -U "${POSTGRES_USER}" -d vendi -tAc \
    "SELECT rolbypassrls FROM pg_roles WHERE rolname='vendi_platform'" | tr -d '[:space:]')"
if [ "${APP_BYPASS}" = "f" ] && [ "${PLAT_BYPASS}" = "t" ]; then
    ok "vendi_app.rolbypassrls=f · vendi_platform.rolbypassrls=t"
elif [ -z "${APP_BYPASS}" ] || [ -z "${PLAT_BYPASS}" ]; then
    falla "no pude leer pg_roles (¿existe la base 'vendi'? ¿corrió infra/postgres/init/01-roles.sh?)"
else
    falla "atributos incorrectos: vendi_app=${APP_BYPASS} (debe ser f), vendi_platform=${PLAT_BYPASS} (debe ser t)"
fi

# ---------------------------------------------------------------------------
# 3. vendi_app no puede crear objetos en `public`.
# ---------------------------------------------------------------------------
info "3. vendi_app no puede crear tablas en el schema public"
if [ -n "${VENDI_APP_DB_PASSWORD:-}" ]; then
    SALIDA_DDL="$("${COMPOSE[@]}" exec -T -e PGPASSWORD="${VENDI_APP_DB_PASSWORD}" postgres \
        psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U vendi_app -d vendi -c \
        "CREATE TABLE verify_setup_no_deberia_existir(id int)" 2>&1)"
    RC_DDL=$?
    # Las tres ramas son distintas y hay que distinguirlas. La versión anterior
    # solo miraba si la salida contenía «permission denied for schema public»;
    # cualquier otra cosa —contenedor parado, DNS de docker, base inexistente—
    # se anunciaba como «¡vendi_app pudo crear una tabla!», es decir, una brecha
    # crítica de aislamiento que no existía. Un verificador que grita lobo es
    # peor que no tenerlo.
    if echo "${SALIDA_DDL}" | grep -q "permission denied for schema public"; then
        ok "el DDL de vendi_app se rechaza como debe"
    elif [ "${RC_DDL}" -ne 0 ]; then
        # psql falló por OTRA razón: el check no se pudo evaluar. Es un fallo
        # del stack, no un hallazgo de seguridad.
        falla "no pude evaluar el DDL de vendi_app (psql salió ${RC_DDL}, no por 'permission denied'): $(echo "${SALIDA_DDL}" | grep -v '^$' | head -1)"
    else
        # psql salió 0: la tabla se creó de verdad. Esto sí es la brecha.
        falla "¡vendi_app pudo crear una tabla en public! salida: $(echo "${SALIDA_DDL}" | head -1)"
        en_servicio postgres psql -U "${POSTGRES_USER}" -d vendi -c \
            "DROP TABLE IF EXISTS verify_setup_no_deberia_existir" >/dev/null
    fi
else
    omite "3: falta VENDI_APP_DB_PASSWORD en el .env"
fi

# ---------------------------------------------------------------------------
# 4. Redis.
# ---------------------------------------------------------------------------
info "4. Redis responde a PING"
if [ -n "${REDIS_PASSWORD:-}" ]; then
    if en_servicio redis redis-cli -a "${REDIS_PASSWORD}" ping | grep -q PONG; then
        ok "redis responde PONG"
    else
        falla "redis no responde (docker compose logs redis)"
    fi
else
    omite "4: falta REDIS_PASSWORD en el .env"
fi

# ---------------------------------------------------------------------------
# 5. RabbitMQ.
# ---------------------------------------------------------------------------
info "5. RabbitMQ está corriendo"
if en_servicio rabbitmq rabbitmq-diagnostics -q check_running >/dev/null; then
    ok "rabbitmq operativo"
else
    falla "rabbitmq no responde (docker compose logs rabbitmq)"
fi

# ---------------------------------------------------------------------------
# 6. MinIO.
# ---------------------------------------------------------------------------
info "6. MinIO reporta salud"
if en_servicio minio curl -fs "${CURL_TOPES[@]}" http://127.0.0.1:9000/minio/health/live >/dev/null; then
    ok "minio vivo"
else
    falla "minio no responde (docker compose logs minio)"
fi

# ---------------------------------------------------------------------------
# 7. Keycloak: el realm vendi-co sirve su descubrimiento OIDC.
# ---------------------------------------------------------------------------
# La imagen oficial de Keycloak 26 NO trae curl ni python (es UBI-micro), así
# que estos dos checks se hacen desde el anfitrión contra el puerto que el
# compose publica en loopback (127.0.0.1:8080), no con `exec` dentro.
KC_LOCAL="http://127.0.0.1:8080"

info "7. Keycloak sirve el .well-known del realm vendi-co"
WELLKNOWN="$(curl -fs "${CURL_TOPES[@]}" \
    "${KC_LOCAL}/realms/vendi-co/.well-known/openid-configuration" 2>/dev/null)"
if echo "${WELLKNOWN}" | grep -q '"issuer"'; then
    ok "realm vendi-co descubierto en ${KC_LOCAL}"
else
    falla "el realm vendi-co no responde en ${KC_LOCAL} (¿se importó? mira: docker compose logs keycloak | grep -i import)"
fi

# ---------------------------------------------------------------------------
# 8. Keycloak: Organizations habilitado en el realm.
# ---------------------------------------------------------------------------
info "8. El realm vendi-co tiene Organizations habilitado"
if [ -n "${KEYCLOAK_ADMIN_PASSWORD:-}" ]; then
    KC_TOKEN="$(curl -fs "${CURL_TOPES[@]}" \
        -X POST "${KC_LOCAL}/realms/master/protocol/openid-connect/token" \
        -d grant_type=password -d client_id=admin-cli \
        -d "username=${KEYCLOAK_ADMIN_USER:-admin}" -d "password=${KEYCLOAK_ADMIN_PASSWORD}" 2>/dev/null \
        | sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    if [ -z "${KC_TOKEN}" ]; then
        falla "no pude obtener token de admin de Keycloak (revisa KEYCLOAK_ADMIN_USER/PASSWORD)"
    else
        REALM_JSON="$(curl -fs "${CURL_TOPES[@]}" \
            -H "Authorization: Bearer ${KC_TOKEN}" \
            "${KC_LOCAL}/admin/realms/vendi-co" 2>/dev/null)"
        if echo "${REALM_JSON}" | grep -q '"organizationsEnabled"[[:space:]]*:[[:space:]]*true'; then
            ok "organizationsEnabled=true en vendi-co"
        else
            falla "vendi-co NO tiene organizationsEnabled=true"
        fi
    fi
else
    omite "8: falta KEYCLOAK_ADMIN_PASSWORD en el .env"
fi

# ---------------------------------------------------------------------------
# 9. Traefik.
# ---------------------------------------------------------------------------
info "9. Traefik está sirviendo"
if en_servicio traefik traefik healthcheck --ping >/dev/null; then
    ok "traefik responde a /ping"
else
    falla "traefik no responde (docker compose logs traefik). Causa típica: faltan los certificados — ./scripts/setup-certs.sh"
fi

# ---------------------------------------------------------------------------
# 10. La API responde a /health desde dentro de su contenedor.
# ---------------------------------------------------------------------------
info "10. La API responde /health"
if en_servicio api python -c \
    "import urllib.request,sys; b=urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read(); sys.exit(0 if b'\"ok\"' in b else 1)"; then
    ok "la API responde {\"status\":\"ok\"}"
else
    falla "la API no responde /health (docker compose logs api)"
fi

# ---------------------------------------------------------------------------
# 11. La API a través de Traefik (prueba la cadena TLS + enrutado + DNS).
# ---------------------------------------------------------------------------
info "11. La API responde a través de Traefik en https://api.${BASE_DOMAIN}/health"
# Este check ejercita el borde: bind de :443 + terminación TLS con certificado
# de confianza + enrutado de Traefik por Host hasta el contenedor api.
#
# La resolución del nombre se fija con --resolve en vez de depender del resolver
# del sistema, y eso NO afloja nada: el hostname, el SNI, la cabecera Host y el
# enrutado de Traefik son los reales, y la validación del certificado contra la
# CA de mkcert sigue siendo completa (sin -k). Lo único que se sustituye es la
# consulta DNS —que es exactamente lo que el check 11b mide por separado—, de
# modo que un DNS pendiente ya no oculta si el borde funciona o no.
#
# Un «devolvió 000» pelado no distingue qué eslabón se rompió, así que se
# diagnostican por separado y cada rama trae el comando que lo arregla.
FIJA_DNS="--resolve api.${BASE_DOMAIN}:443:127.0.0.1"
# Sin `|| echo 000`: curl ya imprime 000 cuando no conecta, y encadenar el echo
# produce el confuso "000000" que vio el QA.
# shellcheck disable=SC2086
CODIGO="$(curl -s ${FIJA_DNS} "${CURL_TOPES[@]}" -o /dev/null -w '%{http_code}' "https://api.${BASE_DOMAIN}/health" 2>/dev/null)"
CODIGO="${CODIGO:-000}"
if [ "${CODIGO}" = "200" ]; then
    ok "https://api.${BASE_DOMAIN}/health devuelve 200 con certificado de confianza (TLS validado contra la CA de mkcert)"
else
    # ¿Es solo la confianza en el certificado, o no hay servicio detrás?
    #
    # Esta rama usaba `curl -ks`. No podía producir un verde —solo corre después
    # de que la comprobación estricta ya falló, y las dos salidas son `falla`—
    # pero mantenía `--insecure` vivo dentro del verificador, que es justo la
    # herramienta que no debería tenerlo a mano: basta un copy-paste para que
    # acabe en la rama que sí decide. Se ancla a la CA de mkcert en su lugar,
    # que distingue exactamente lo mismo (¿hay servicio detrás?) sin apagar
    # nada. Si la CA no aparece, se dice y no se diagnostica a ciegas.
    CA_MKCERT="$(ca_de_mkcert || true)"
    if [ -n "${CA_MKCERT}" ]; then
        # shellcheck disable=SC2086
        CODIGO_CA="$(curl -s --cacert "${CA_MKCERT}" ${FIJA_DNS} "${CURL_TOPES[@]}" -o /dev/null -w '%{http_code}' "https://api.${BASE_DOMAIN}/health" 2>/dev/null)"
        CODIGO_CA="${CODIGO_CA:-000}"
        if [ "${CODIGO_CA}" = "200" ]; then
            falla "https://api.${BASE_DOMAIN}/health valida contra la CA de mkcert pero NO contra el almacén del sistema: la CA no está instalada. Ejecuta: mkcert -install"
        else
            falla "https://api.${BASE_DOMAIN}/health devolvió ${CODIGO_CA} incluso anclando a la CA de mkcert; mira el bind de :443 (docker ps | grep traefik) y el router 'api' en http://127.0.0.1:8088/dashboard/"
        fi
    else
        falla "https://api.${BASE_DOMAIN}/health devolvió ${CODIGO} y no se encontró el rootCA.pem de mkcert para diagnosticar. Ejecuta: mkcert -install && ./scripts/setup-certs.sh && docker compose restart traefik"
    fi
fi

# ---------------------------------------------------------------------------
# 11b. El resolver del sistema, medido aparte del borde.
#
# Separarlo del check 11 no es un truco para poner verdes las cosas: son dos
# fallos con dos causas y dos arreglos distintos, y antes uno tapaba al otro (si
# el nombre no resolvía, del borde no se sabía NADA). Aquí se mide solo el DNS.
#
# CORRECCIÓN (bloqueante de QA). Este check tenía una rama OMITIDA —"el resolver
# todavía no existe, necesita sudo"— que se activaba EXACTAMENTE en el estado
# peligroso, de modo que la única comprobación capaz de detectar la fuga se
# apagaba sola justo cuando había algo que detectar. El check 11 tampoco podía
# verlo: fija la resolución con --resolve, así que por construcción nunca sale
# a Internet. Resultado: «18 en verde · 4 omitidos · 0 fallos», exit 0, con
# accounts.${BASE_DOMAIN} apuntando a un host de terceros.
#
# Lo que se omitía era la premisa equivocada, no la conclusión. "Falta el
# resolver" NO es una condición; son dos, y solo una es benigna:
#
#   · el nombre no resuelve  → falla CERRADO, no se filtra nada  → OMITIDO
#   · el nombre resuelve fuera → falla ABIERTO, se filtran secretos → FALLO
#
# Con `vendi.local` (TLD inexistente) solo existía la primera, y por eso la
# omisión parecía razonable. Con un TLD real existe la segunda.
# ---------------------------------------------------------------------------
info "11b. El resolver del sistema manda *.${BASE_DOMAIN} a 127.0.0.1"
RESOLVER_SISTEMA="/etc/resolver/${BASE_DOMAIN}"
if resuelve_a_loopback "api.${BASE_DOMAIN}"; then
    ok "api.${BASE_DOMAIN} resuelve a loopback por el resolver del sistema"
elif resuelve_fuera "api.${BASE_DOMAIN}"; then
    falla "api.${BASE_DOMAIN} resuelve a $(resolucion_de "api.${BASE_DOMAIN}" | tr '\n' ' '), que NO es esta máquina: ${BASE_DOMAIN} es un dominio real y sin ${RESOLVER_SISTEMA} el tráfico sale a Internet. Completa el procedimiento A de docs/runbooks/dns-y-tls-local.md."
elif [ "$(uname -s)" = "Darwin" ] && [ ! -f "${RESOLVER_SISTEMA}" ]; then
    omite "11b: api.${BASE_DOMAIN} no resuelve y falta ${RESOLVER_SISTEMA}, que necesita sudo. Falla cerrado (ningún cliente llega a ninguna parte), así que se omite en vez de suspender. Ver docs/runbooks/dns-y-tls-local.md (procedimiento A)."
else
    falla "api.${BASE_DOMAIN} no resuelve a 127.0.0.1 y ${RESOLVER_SISTEMA} sí existe: el DNS local está roto, no solo pendiente. Ejecuta: ./scripts/setup-dnsmasq.sh"
fi

# ---------------------------------------------------------------------------
# 11c. Ningún nombre de la familia *.${BASE_DOMAIN} sale de esta máquina.
#
# El 11b mira un solo nombre (api). No basta: la evidencia de QA mostró que
# dentro de la MISMA familia unos nombres fallan cerrados y otros abiertos,
# según tengan o no certificado público. api/app/admin daban 000 (cierran);
# accounts —el IdP, el que recibe los client_secret— y el ápice daban 436 con
# cadena TLS válida (abren). Comprobar solo `api` es mirar precisamente donde
# el problema NO se ve.
#
# Se comprueban por nombre, con especial atención a `accounts`, que es el que
# convierte un error de DNS en una fuga de credenciales.
# ---------------------------------------------------------------------------
info "11c. Ningún *.${BASE_DOMAIN} resuelve fuera de esta máquina"
NOMBRES_FUERA=""
for SUB in accounts api app admin grafana mail; do
    if resuelve_fuera "${SUB}.${BASE_DOMAIN}"; then
        NOMBRES_FUERA="${NOMBRES_FUERA} ${SUB}.${BASE_DOMAIN}->$(resolucion_de "${SUB}.${BASE_DOMAIN}" | tr '\n' ' ' | awk '{print $1}')"
    fi
done
if resuelve_fuera "${BASE_DOMAIN}"; then
    NOMBRES_FUERA="${NOMBRES_FUERA} ${BASE_DOMAIN}->$(resolucion_de "${BASE_DOMAIN}" | tr '\n' ' ' | awk '{print $1}')"
fi
if [ -z "${NOMBRES_FUERA}" ]; then
    ok "ningún nombre de ${BASE_DOMAIN} resuelve a un host externo"
else
    falla "estos nombres salen a Internet en vez de a Traefik:${NOMBRES_FUERA}. accounts.${BASE_DOMAIN} es el IdP: un POST al endpoint de token entrega el client_secret a un tercero, y como ese host tiene certificado público VÁLIDO la verificación TLS no avisa. Completa el procedimiento A de docs/runbooks/dns-y-tls-local.md antes de seguir."
fi

# ---------------------------------------------------------------------------
# 12. El worker late.
# ---------------------------------------------------------------------------
info "12. El worker está latiendo"
if en_servicio worker python -c \
    "import os,sys,time; f=os.environ['WORKER_HEARTBEAT_FILE']; sys.exit(0 if os.path.exists(f) and time.time()-os.path.getmtime(f) < 3*float(os.environ.get('WORKER_HEARTBEAT_SECONDS','30')) else 1)"; then
    ok "el archivo de latido del worker está fresco"
else
    falla "el worker no late (docker compose logs worker)"
fi

# ---------------------------------------------------------------------------
# 13. Prometheus y Grafana.
# ---------------------------------------------------------------------------
info "13. Prometheus responde"
if en_servicio prometheus wget -q -O /dev/null http://127.0.0.1:9090/-/healthy; then
    ok "prometheus sano"
else
    falla "prometheus no responde (docker compose logs prometheus)"
fi

info "14. Grafana responde"
if en_servicio grafana curl -fs "${CURL_TOPES[@]}" http://127.0.0.1:3000/api/health >/dev/null; then
    ok "grafana sano"
else
    falla "grafana no responde (docker compose logs grafana)"
fi

# ---------------------------------------------------------------------------
# 15. Sonda de disponibilidad: /health/ready con PostgreSQL, Redis y Keycloak.
#
#     Se pide POR EL DOMINIO, a través de Traefik, con --resolve fijando el
#     nombre a esta máquina. Es una sonda pública: si pidiera credenciales, el
#     orquestador no podría usarla.
# ---------------------------------------------------------------------------
info "15. La API reporta disponibilidad en https://api.${BASE_DOMAIN}/health/ready"
# shellcheck disable=SC2086
CUERPO_READY="$(curl -s ${FIJA_DNS} "${CURL_TOPES[@]}" "https://api.${BASE_DOMAIN}/health/ready" 2>/dev/null)"
# shellcheck disable=SC2086
CODIGO_READY="$(curl -s ${FIJA_DNS} "${CURL_TOPES[@]}" -o /dev/null -w '%{http_code}' "https://api.${BASE_DOMAIN}/health/ready" 2>/dev/null)"
CODIGO_READY="${CODIGO_READY:-000}"
if [ "${CODIGO_READY}" = "200" ]; then
    ok "/health/ready devuelve 200: PostgreSQL, Redis y Keycloak responden"
elif [ "${CODIGO_READY}" = "503" ]; then
    CAIDAS="$(echo "${CUERPO_READY}" | sed -n 's/.*"caidas":\[\([^]]*\)\].*/\1/p')"
    falla "/health/ready devuelve 503; dependencias caídas: ${CAIDAS:-(no reportadas)}"
else
    falla "/health/ready devolvió ${CODIGO_READY} (esperaba 200 o 503). ¿Responde la API por el borde? Mira el check 11."
fi

# ---------------------------------------------------------------------------
# 15b. /metrics NO es alcanzable sin credenciales desde fuera.
#
#      La exposición de Prometheus lleva el mapa de rutas internas, los
#      contadores de error por endpoint y —en cuanto haya métricas por
#      negocio— identificadores de negocio. El router `api` de Traefik enruta
#      por Host y no por path, así que sin una defensa explícita quedaría
#      servida en https://api.<dominio>/metrics a cualquiera.
#
#      Dos capas: el borde responde 403 (router `api-metrics-bloqueado`) y la
#      ruta exige su propia credencial (METRICS_TOKEN). Aquí se comprueba que
#      NINGUNA de las dos deja pasar; 401 y 403 son los dos desenlaces
#      aceptables, 200 es el fallo.
# ---------------------------------------------------------------------------
info "15b. /metrics no es alcanzable sin credenciales desde fuera"
# shellcheck disable=SC2086
CODIGO_METRICS="$(curl -s ${FIJA_DNS} "${CURL_TOPES[@]}" -o /dev/null -w '%{http_code}' "https://api.${BASE_DOMAIN}/metrics" 2>/dev/null)"
CODIGO_METRICS="${CODIGO_METRICS:-000}"
case "${CODIGO_METRICS}" in
    403) ok "el borde bloquea /metrics (403): la exposición de Prometheus no sale del perímetro" ;;
    401) ok "/metrics exige credencial (401). El bloqueo del borde no está activo: reinicia traefik para que re-renderice el dinámico" ;;
    200) falla "¡https://api.${BASE_DOMAIN}/metrics responde 200 SIN credenciales! Revisa el router api-metrics-bloqueado y METRICS_TOKEN" ;;
    *)   falla "/metrics devolvió ${CODIGO_METRICS}; esperaba 403 (borde) o 401 (credencial)" ;;
esac

# ---------------------------------------------------------------------------
# 16. El negocio de demostración existe, con su organización en Keycloak.
#
#     Se comprueban las DOS mitades, y por separado: la fila en `tenants` y la
#     Organization cuyo alias es su id. Comprobar solo una daría verde
#     exactamente en el estado que `reconcile-keycloak.sh` existe para
#     detectar — un negocio cuyos usuarios no pueden entrar, o una
#     organización huérfana.
# ---------------------------------------------------------------------------
info "16. Negocio de demostración provisionado (fila en 'tenants' + Organization en Keycloak)"
ID_DEMO="$(en_servicio postgres psql -U "${POSTGRES_USER}" -d vendi -tAc \
    "SELECT id::text FROM tenants WHERE nombre = 'Tienda Don Carlos' AND deleted_at IS NULL LIMIT 1" | tr -d '[:space:]')"
if [ -z "${ID_DEMO}" ]; then
    falla "no hay negocio de demostración en la base de datos. Ejecuta: bash scripts/migrate.sh && bash scripts/seed.sh"
elif [ -z "${KC_TOKEN:-}" ]; then
    falla "16: hay negocio demo (${ID_DEMO}) pero no pude comprobar su organización sin token de admin de Keycloak (ver check 8)"
else
    ALIAS_DEMO="$(curl -fs "${CURL_TOPES[@]}" -H "Authorization: Bearer ${KC_TOKEN}" \
        "${KC_LOCAL}/admin/realms/vendi-co/organizations?search=${ID_DEMO}" 2>/dev/null \
        | python3 -c 'import sys,json
try:
    print("\n".join(o.get("alias","") for o in json.load(sys.stdin)))
except Exception:
    pass' 2>/dev/null | grep -Fx "${ID_DEMO}" || true)"
    if [ -n "${ALIAS_DEMO}" ]; then
        ok "«Tienda Don Carlos» = ${ID_DEMO}, con Organization de alias idéntico"
    else
        falla "el negocio demo ${ID_DEMO} NO tiene organización en Keycloak: sus usuarios no pueden entrar. Ejecuta: RECONCILE_APLICAR=1 bash scripts/reconcile-keycloak.sh"
    fi
fi

# ---------------------------------------------------------------------------
# 17. Secretos: en producción, ningún valor puede ser el del .env.example.
# ---------------------------------------------------------------------------
info "17. Secretos de ejemplo fuera de producción"
if [ "${APP_ENV}" = "production" ]; then
    SOSPECHOSAS=""
    for VAR in POSTGRES_PASSWORD VENDI_PLATFORM_DB_PASSWORD VENDI_APP_DB_PASSWORD \
               REDIS_PASSWORD RABBITMQ_PASSWORD MINIO_SECRET_KEY \
               KEYCLOAK_ADMIN_PASSWORD VENDI_BACKEND_CLIENT_SECRET \
               VENDI_PROVISIONING_CLIENT_SECRET METRICS_TOKEN GRAFANA_ADMIN_PASSWORD; do
        eval "VALOR=\${${VAR}:-}"
        case "${VALOR}" in
            cambiar_*|admin|admin_dev|"") SOSPECHOSAS="${SOSPECHOSAS} ${VAR}" ;;
        esac
    done
    if [ -n "${SOSPECHOSAS}" ]; then
        falla "APP_ENV=production con secretos de ejemplo o vacíos:${SOSPECHOSAS}"
    else
        ok "ningún secreto de ejemplo en producción"
    fi
else
    omite "17: solo aplica con APP_ENV=production (ahora: ${APP_ENV})"
fi

# ---------------------------------------------------------------------------
# 18. vendi_app NO puede conectarse a la base de Keycloak.
#     PostgreSQL da CONNECT a PUBLIC sobre cada base nueva; si alguien recrea
#     la base de Keycloak a mano, la puerta se vuelve a abrir sin avisar.
# ---------------------------------------------------------------------------
info "18. vendi_app no puede conectarse a la base de Keycloak"
if [ -n "${VENDI_APP_DB_PASSWORD:-}" ]; then
    SALIDA_KC_DB="$("${COMPOSE[@]}" exec -T -e PGPASSWORD="${VENDI_APP_DB_PASSWORD}" postgres \
        psql -h 127.0.0.1 -U vendi_app -d keycloak -tAc "SELECT 1" 2>&1)"
    if echo "${SALIDA_KC_DB}" | grep -q "permission denied for database"; then
        ok "la conexión de vendi_app a la base keycloak se rechaza"
    elif echo "${SALIDA_KC_DB}" | grep -q "^1$"; then
        falla "¡vendi_app SÍ se conecta a la base de Keycloak! Reejecuta infra/postgres/init/01-roles.sh"
    else
        falla "no pude evaluar la conexión de vendi_app a keycloak: $(echo "${SALIDA_KC_DB}" | head -1)"
    fi
else
    omite "18: falta VENDI_APP_DB_PASSWORD en el .env"
fi

# ---------------------------------------------------------------------------
# 19. La API y el worker no corren como root dentro de su contenedor.
# ---------------------------------------------------------------------------
info "19. Los contenedores de la API y del worker no corren como root"
UID_API="$(en_servicio api id -u | tr -d '[:space:]')"
UID_WORKER="$(en_servicio worker id -u | tr -d '[:space:]')"
if [ -z "${UID_API}" ] || [ -z "${UID_WORKER}" ]; then
    falla "no pude leer el UID de api/worker (¿están arriba?)"
elif [ "${UID_API}" != "0" ] && [ "${UID_WORKER}" != "0" ]; then
    ok "api corre con uid ${UID_API} y worker con uid ${UID_WORKER}"
else
    falla "algún contenedor corre como root: api=${UID_API}, worker=${UID_WORKER}"
fi

# ---------------------------------------------------------------------------
# 20. Hay un volcado reciente de la base. Que exista NO prueba que restaure;
#     eso lo prueba scripts/restore-backup.sh --simulacro, que es más caro y
#     no va en la prueba de humo.
# ---------------------------------------------------------------------------
info "20. El sidecar de respaldo ha dejado un volcado reciente y EMPAREJADO de las dos bases"
# El contrato que aplica restore-backup.sh es el PAR con la misma marca de
# tiempo: vendi-<ts>, keycloak-<ts> y vendi-roles-<ts>. Comprobar cada familia
# por separado bendeciría dos volcados de ciclos distintos que el restore
# rechaza. Se parte del volcado de `vendi` más nuevo y se exige su par exacto.
VOLCADO="$(en_servicio postgres-backup sh -c \
    "ls -1t /backups/vendi-2*.sql.gz 2>/dev/null | head -1" | tr -d '[:space:]')"
if [ -n "${VOLCADO}" ]; then
    VOLCADO_FRESCO="$(en_servicio postgres-backup sh -c \
        "find '${VOLCADO}' -mmin -1500 -size +0c 2>/dev/null" | tr -d '[:space:]')"
    MARCA="${VOLCADO#/backups/vendi-}"   # p. ej. 20260723T072001Z.sql.gz
    PAR_OK="$(en_servicio postgres-backup sh -c \
        "test -s '/backups/keycloak-${MARCA}' && test -s '/backups/vendi-roles-${MARCA}' && echo si" | tr -d '[:space:]')"
    if [ -z "${VOLCADO_FRESCO}" ]; then
        falla "el volcado más reciente de vendi ($(basename "${VOLCADO}")) tiene más de 25 h o está vacío (docker compose logs postgres-backup)"
    elif [ "${PAR_OK}" != "si" ]; then
        # Medio respaldo. La copia de `vendi` referencia organizaciones y
        # usuarios de Keycloak: sin la base del IdP, nadie se autentica contra
        # el sistema restaurado y la copia de datos es ilegible en la práctica.
        falla "el volcado vendi-${MARCA} no tiene su par exacto (keycloak-${MARCA} + vendi-roles-${MARCA}): restore-backup.sh lo rechazará"
    else
        ok "par completo y reciente: vendi-${MARCA} + keycloak-${MARCA} + vendi-roles-${MARCA}"
    fi
else
    falla "no hay ningún volcado en /backups (docker compose logs postgres-backup)"
fi

# ---------------------------------------------------------------------------
# 21. Las DOS cuentas de servicio llevan sus roles mínimos y ni uno más.
#
#     El privilegio está partido en dos credenciales (mitigación de D-02,
#     Etapa 3):
#       · vendi-backend      → manage-users. Es el cliente de la API general.
#       · vendi-provisioning → manage-realm + manage-users. Solo el camino de
#         alta y baja de negocios, que es el único que necesita Organizations.
#
#     Un rol de más en `vendi-backend` deshace la separación entera: con
#     `manage-realm`, quien comprometa el secreto de la API puede crear flujos
#     de autenticación, reenlazar el browserFlow (sacando la passkey), apagar
#     la protección de fuerza bruta y abrir el auto-registro. `impersonation`
#     en cualquiera de las dos significa poder suplantar a cualquier usuario de
#     cualquier negocio de la región; `manage-clients` o `realm-admin`,
#     reescribir el IdP.
# ---------------------------------------------------------------------------
info "21. Las cuentas de servicio de Keycloak tienen sus roles mínimos (split de D-02)"
if [ -n "${KC_TOKEN:-}" ]; then
    ROLES_SA="$(KC_LOCAL="${KC_LOCAL}" KC_TOKEN="${KC_TOKEN}" python3 - <<'PY' 2>/dev/null
import json, os, urllib.request

kc = os.environ["KC_LOCAL"]
cab = {"Authorization": "Bearer " + os.environ["KC_TOKEN"]}

ESPERADO = {
    "vendi-backend": "manage-users",
    "vendi-provisioning": "manage-realm,manage-users",
}


def get(ruta):
    return json.load(urllib.request.urlopen(urllib.request.Request(kc + ruta, headers=cab), timeout=8))


clientes = {c["clientId"]: c["id"] for c in get("/admin/realms/vendi-co/clients")}
problemas = []
for cid, esperado in ESPERADO.items():
    if cid not in clientes:
        problemas.append(f"{cid}: el cliente no existe en el realm")
        continue
    sa = get(f"/admin/realms/vendi-co/clients/{clientes[cid]}/service-account-user")["id"]
    roles = get(f"/admin/realms/vendi-co/users/{sa}/role-mappings/clients/{clientes['realm-management']}")
    real = ",".join(sorted(r["name"] for r in roles))
    if real != esperado:
        problemas.append(f"{cid}: {real or '(ninguno)'} (esperaba {esperado})")
print("OK" if not problemas else " · ".join(problemas))
PY
)"
    if [ "${ROLES_SA}" = "OK" ]; then
        ok "vendi-backend=manage-users · vendi-provisioning=manage-realm,manage-users"
    elif [ -z "${ROLES_SA}" ]; then
        falla "no pude leer los roles de las cuentas de servicio de Keycloak"
    else
        falla "roles inesperados: ${ROLES_SA}. Mira scripts/reconcile-keycloak.sh y D-02 en docs/deuda-tecnica.md"
    fi
else
    omite "21: sin token de admin de Keycloak (ver check 8)"
fi

# ---------------------------------------------------------------------------
# 22. Ningún cliente del realm de negocio acepta el grant de contraseña (D-01).
#
#     Se comprueba sobre el realm VIVO y no sobre el JSON: el JSON es la
#     semilla del día 1 y el realm existente no se reimporta (D-03), así que
#     preguntarle al archivo es preguntarle a quien no decide. Un cliente
#     público con ROPC anula la política de passkey del realm: con usuario y
#     contraseña se obtiene un token completo sin pasar por el navegador. Se
#     mide en `vendi-web` y también en `admin-cli`, que es el mismo agujero con
#     otro nombre —Keycloak lo trae encendido en todos los realms.
# ---------------------------------------------------------------------------
info "22. Ningún cliente de vendi-co acepta el grant de contraseña (D-01)"
if [ -n "${KC_TOKEN:-}" ]; then
    CON_ROPC="$(curl -fs "${CURL_TOPES[@]}" -H "Authorization: Bearer ${KC_TOKEN}" \
        "${KC_LOCAL}/admin/realms/vendi-co/clients" 2>/dev/null \
        | python3 -c 'import sys, json
try:
    clientes = json.load(sys.stdin)
except Exception:
    sys.exit(1)
print(",".join(sorted(c["clientId"] for c in clientes if c.get("directAccessGrantsEnabled"))))' 2>/dev/null)"
    CODIGO_ROPC=$?
    if [ "${CODIGO_ROPC}" -ne 0 ]; then
        falla "no pude listar los clientes del realm vendi-co"
    elif [ -z "${CON_ROPC}" ]; then
        ok "ningún cliente de vendi-co tiene directAccessGrantsEnabled"
    else
        falla "clientes con ROPC en vendi-co: ${CON_ROPC}. Es la deuda D-01: apágalo con RECONCILE_APLICAR_CONFIG=1 bash scripts/reconcile-keycloak.sh"
    fi
else
    omite "22: sin token de admin de Keycloak (ver check 8)"
fi

# ---------------------------------------------------------------------------
# 23. Los tokens del realm llevan la audiencia que la API exige.
#
#     Sin el claim `aud`, cualquier token firmado por `vendi-co` sirve contra
#     la API aunque se emitiera para otro público. Se usa el generador de
#     tokens de ejemplo de la Admin API, que produce exactamente los claims que
#     tendría un token real de ese cliente y ese usuario, sin necesitar
#     credenciales de nadie ni un navegador.
# ---------------------------------------------------------------------------
info "23. Los tokens de vendi-web llevan aud=${KEYCLOAK_AUDIENCE:-vendi-backend} y el rol de negocio"
if [ -n "${KC_TOKEN:-}" ]; then
    EJEMPLO="$(KC_LOCAL="${KC_LOCAL}" KC_TOKEN="${KC_TOKEN}" \
        AUD="${KEYCLOAK_AUDIENCE:-vendi-backend}" python3 - <<'PY' 2>/dev/null
import json, os, urllib.parse, urllib.request

kc = os.environ["KC_LOCAL"]
aud_esperada = os.environ["AUD"]
cab = {"Authorization": "Bearer " + os.environ["KC_TOKEN"]}


def get(ruta):
    return json.load(urllib.request.urlopen(urllib.request.Request(kc + ruta, headers=cab), timeout=8))


clientes = {c["clientId"]: c["id"] for c in get("/admin/realms/vendi-co/clients")}
if "vendi-web" not in clientes:
    print("no existe el cliente vendi-web")
    raise SystemExit(0)

usuarios = get("/admin/realms/vendi-co/users?" + urllib.parse.urlencode({"username": "dueno@demo.vendi.co", "exact": "true"}))
if not usuarios:
    print("no existe el usuario demo (¿falta scripts/seed.sh?)")
    raise SystemExit(0)

consulta = urllib.parse.urlencode({"userId": usuarios[0]["id"], "scope": "organization"})
claims = get(f"/admin/realms/vendi-co/clients/{clientes['vendi-web']}/evaluate-scopes/generate-example-access-token?{consulta}")

aud = claims.get("aud")
aud = [aud] if isinstance(aud, str) else list(aud or [])
roles = claims.get("realm_access", {}).get("roles", [])

problemas = []
if aud_esperada not in aud:
    problemas.append(f"aud={aud or '(ninguna)'}, esperaba {aud_esperada}")
if "dueno" not in roles:
    problemas.append("realm_access.roles no trae 'dueno' (deuda D-08: has_role() sería inerte)")
for permiso in ("producto:leer", "producto:editar", "venta:crear", "venta:anular", "inventario:ajustar", "compra:crear", "caja:leer", "caja:abrir", "caja:cerrar", "caja:movimiento", "reporte:leer", "cliente:gestionar", "fiado:crear", "fiado:abonar"):
    if permiso not in roles:
        problemas.append(
            f"realm_access.roles no trae '{permiso}' (ADR-023: el grupo dueno debe mapearlo; "
            "un permiso ausente del token del dueno es un bug de siembra, ejecuta scripts/seed.sh)"
        )
print("OK" if not problemas else " · ".join(problemas))
PY
)"
    if [ "${EJEMPLO}" = "OK" ]; then
        ok "aud=${KEYCLOAK_AUDIENCE:-vendi-backend}, rol de negocio y los 14 permisos de dominio en el token del dueño"
    elif [ -z "${EJEMPLO}" ]; then
        falla "no pude generar el token de ejemplo de vendi-web"
    else
        falla "${EJEMPLO}"
    fi
else
    omite "23: sin token de admin de Keycloak (ver check 8)"
fi

# ---------------------------------------------------------------------------
# 24. La documentación interactiva de la API no está abierta en el borde
#     cuando no se ha pedido, y el preflight de CORS no devuelve el comodín de
#     cabeceras junto a credenciales (combinación inválida en cuanto alguien
#     use withCredentials).
# ---------------------------------------------------------------------------
info "24. Borde: /docs según DOCS_PUBLICOS y CORS sin comodín de cabeceras"
PROBLEMAS_BORDE=""
# Misma fijación de DNS que el check 11: el hostname, el SNI, la cabecera Host
# y la validación TLS son los reales; solo se sustituye la consulta DNS.
FIJA_DNS_API=(--resolve "api.${BASE_DOMAIN}:443:127.0.0.1")
CODIGO_DOCS="$(curl -s -o /dev/null -w '%{http_code}' "${CURL_TOPES[@]}" "${FIJA_DNS_API[@]}" \
    "https://api.${BASE_DOMAIN}/docs" 2>/dev/null || echo "000")"
case "${DOCS_PUBLICOS:-false}" in
    true|1|True|TRUE)
        [ "${CODIGO_DOCS}" = "200" ] || PROBLEMAS_BORDE="${PROBLEMAS_BORDE}DOCS_PUBLICOS=true pero /docs devuelve ${CODIGO_DOCS}. " ;;
    *)
        [ "${CODIGO_DOCS}" = "404" ] || PROBLEMAS_BORDE="${PROBLEMAS_BORDE}DOCS_PUBLICOS no está activo y /docs devuelve ${CODIGO_DOCS} (debería ser 404). " ;;
esac

CABECERAS_CORS="$(curl -s -i -X OPTIONS "${CURL_TOPES[@]}" "${FIJA_DNS_API[@]}" \
    "https://api.${BASE_DOMAIN}/api/v1/tenants/me" \
    -H "Origin: https://app.${BASE_DOMAIN}" \
    -H 'Access-Control-Request-Method: GET' \
    -H 'Access-Control-Request-Headers: authorization' 2>/dev/null \
    | tr -d '\r' | awk 'BEGIN{IGNORECASE=1} /^access-control-allow-headers:/ {print $2}')"
case "${CABECERAS_CORS}" in
    "") PROBLEMAS_BORDE="${PROBLEMAS_BORDE}el preflight no devolvió Access-Control-Allow-Headers. " ;;
    \*) PROBLEMAS_BORDE="${PROBLEMAS_BORDE}Access-Control-Allow-Headers es '*' junto a Allow-Credentials: con credenciales el comodín se compara literalmente y el preflight de toda petición con Authorization se rechaza. " ;;
    *Authorization*) : ;;
    *) PROBLEMAS_BORDE="${PROBLEMAS_BORDE}Access-Control-Allow-Headers no incluye Authorization (${CABECERAS_CORS}). " ;;
esac

if [ -z "${PROBLEMAS_BORDE}" ]; then
    ok "/docs coherente con DOCS_PUBLICOS y CORS con lista explícita de cabeceras"
else
    falla "${PROBLEMAS_BORDE}"
fi

# ---------------------------------------------------------------------------
# 25. Las tres SPAs responden por su dominio a través de Traefik.
#     Hallazgo de QA de la Etapa 5: sin este check, un despliegue con portal,
#     tenant o admin caídos (o sirviendo la app equivocada) pasaba el gate en
#     verde. Misma fijación de DNS que los checks 11 y 24: hostname, SNI y
#     validación TLS reales; solo se sustituye la consulta DNS.
# ---------------------------------------------------------------------------
info "25. Las SPAs responden por su dominio (vendi.co, app., admin.)"
# Solo se evalúa si las SPAs forman parte del stack levantado. El job de
# integración de ci.yml no las construye a propósito (minutos de build que el
# backend no necesita), y sin esta guarda el check fallaba en rojo contra un
# stack que nunca pretendió tenerlas —la regla 1 de este script manda OMITIDO
# cuando un check no se puede evaluar todavía. La guarda NO afloja el check
# donde importa: un `docker compose up` crea SIEMPRE los contenedores (si el
# build de una SPA falla, el propio up aborta antes de llegar aquí), así que
# en un despliegue real las SPAs caídas siguen presentes —creadas pero sin
# servir— y el FALLO salta igual que antes.
SPAS_EN_STACK=1
for SERVICIO_SPA in portal tenant admin; do
    if [ -z "$("${COMPOSE[@]}" ps -aq "${SERVICIO_SPA}" 2>/dev/null)" ]; then
        SPAS_EN_STACK=0
        break
    fi
done
if [ "${SPAS_EN_STACK}" = 0 ]; then
    omite "25: las SPAs no forman parte de este stack (p. ej. el job de integración de ci.yml no las construye)"
else
PROBLEMAS_SPAS=""
for HOST_SPA in "${BASE_DOMAIN}" "www.${BASE_DOMAIN}" "app.${BASE_DOMAIN}" "admin.${BASE_DOMAIN}"; do
    CODIGO_SPA="$(curl -s -o /dev/null -w '%{http_code}' "${CURL_TOPES[@]}" \
        --resolve "${HOST_SPA}:443:127.0.0.1" "https://${HOST_SPA}/" 2>/dev/null || echo "000")"
    [ "${CODIGO_SPA}" = "200" ] || PROBLEMAS_SPAS="${PROBLEMAS_SPAS}${HOST_SPA} devuelve ${CODIGO_SPA}. "
done
if [ -z "${PROBLEMAS_SPAS}" ]; then
    ok "las cuatro URLs de SPA devuelven 200 por Traefik con TLS validado"
else
    falla "${PROBLEMAS_SPAS}(docker compose logs portal tenant admin)"
fi
fi

# ---------------------------------------------------------------------------
# 26. La credencial con manage-realm vive SOLO en el provisioner (D-02).
#
#     El cierre de D-02 (ADR-027) mueve `vendi-provisioning` a su propia
#     unidad de despliegue. Cuatro comprobaciones, y las cuatro importan:
#
#     a. La API NO tiene el secreto en su entorno. Si lo tuviera, toda la
#        separación sería decorativa: un RCE en la API volvería a alcanzar el
#        realm entero. Se comprueba el entorno del contenedor, no el compose:
#        es lo que hereda un proceso comprometido.
#     b. El provisioner SÍ la tiene y responde /health. Sin él, el alta y la
#        baja de negocios no tienen a quién llamar (PROVISIONER_URL).
#     c. El borde no lo conoce: `provisioner.<dominio>` tiene que ser 404 en
#        Traefik. Un router para este servicio lo expondría a Internet con
#        manage-realm detrás.
#     d. No publica puertos fuera de loopback. El override de desarrollo lo
#        expone en 127.0.0.1:8010 para los tests de integración, igual que
#        postgres o redis; cualquier otra cosa es un error de despliegue.
# ---------------------------------------------------------------------------
info "26. La credencial manage-realm vive solo en el provisioner y el borde no lo alcanza (D-02)"
PROBLEMAS_PROVISIONER=""
if [ -n "$(en_servicio api printenv KEYCLOAK_PROVISIONING_CLIENT_SECRET)" ]; then
    PROBLEMAS_PROVISIONER="${PROBLEMAS_PROVISIONER}la API TIENE KEYCLOAK_PROVISIONING_CLIENT_SECRET en su entorno: D-02 reabierta. "
fi
if [ -z "$(en_servicio api printenv PROVISIONER_URL)" ]; then
    PROBLEMAS_PROVISIONER="${PROBLEMAS_PROVISIONER}la API no tiene PROVISIONER_URL: el alta de negocios no tiene a quién llamar. "
fi
if [ -z "$(en_servicio provisioner printenv KEYCLOAK_PROVISIONING_CLIENT_SECRET)" ]; then
    PROBLEMAS_PROVISIONER="${PROBLEMAS_PROVISIONER}el provisioner NO tiene la credencial (¿está arriba? docker compose logs provisioner). "
fi
if ! en_servicio provisioner python -c \
    "import urllib.request,sys; b=urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read(); sys.exit(0 if b'\"ok\"' in b else 1)"; then
    PROBLEMAS_PROVISIONER="${PROBLEMAS_PROVISIONER}el provisioner no responde /health (docker compose logs provisioner). "
fi
# Misma fijación de DNS que los checks 11 y 24: hostname, SNI y validación TLS
# reales; solo se sustituye la consulta DNS. Lo que se mide es el ENRUTADO.
CODIGO_PROV="$(curl -s --resolve "provisioner.${BASE_DOMAIN}:443:127.0.0.1" "${CURL_TOPES[@]}" \
    -o /dev/null -w '%{http_code}' "https://provisioner.${BASE_DOMAIN}/health" 2>/dev/null)"
CODIGO_PROV="${CODIGO_PROV:-000}"
if [ "${CODIGO_PROV}" != "404" ]; then
    PROBLEMAS_PROVISIONER="${PROBLEMAS_PROVISIONER}el borde responde ${CODIGO_PROV} para provisioner.${BASE_DOMAIN} (debería ser 404): hay un router que no debería existir. "
fi
PUERTO_PROV="$("${COMPOSE[@]}" port provisioner 8000 2>/dev/null | tr -d '[:space:]')"
case "${PUERTO_PROV}" in
    ""|127.0.0.1:*|::1:*) : ;;
    *) PROBLEMAS_PROVISIONER="${PROBLEMAS_PROVISIONER}el provisioner publica su puerto fuera de loopback (${PUERTO_PROV}). " ;;
esac
if [ -z "${PROBLEMAS_PROVISIONER}" ]; then
    ok "la API no tiene el secreto, el provisioner sí y responde, el borde da 404 y no hay puertos expuestos"
else
    falla "${PROBLEMAS_PROVISIONER}"
fi

# ---------------------------------------------------------------------------
# Resumen.
# ---------------------------------------------------------------------------
echo ""
echo "-----------------------------------------------------------------"
TOTAL=$((PASADAS + FALLIDAS + OMITIDAS))
if [ "${FALLIDAS}" -eq 0 ]; then
    echo -e "${GREEN}[OK]${NC}    ${PASADAS} en verde · ${OMITIDAS} omitidos · 0 fallos (de ${TOTAL})"
    [ "${OMITIDAS}" -gt 0 ] && echo -e "${YELLOW}[AVISO]${NC} hay checks omitidos: el stack no está completo todavía, es lo esperado en esta etapa."
    exit 0
else
    echo -e "${RED}[FALLO]${NC} ${PASADAS} en verde · ${OMITIDAS} omitidos · ${FALLIDAS} FALLOS (de ${TOTAL})"
    exit 1
fi
