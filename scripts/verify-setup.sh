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

BASE_DOMAIN="${BASE_DOMAIN:-vendi.local}"
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
# sistema no enrutarle las consultas de *.vendi.local por faltar
# /etc/resolver/vendi.local. Se usa para diagnosticar el check 11.
resuelve_a_loopback() {
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
    case "${salida}" in
        *127.0.0.1*|*::1*) return 0 ;;
        *) return 1 ;;
    esac
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
# Este es el único check que ejercita la cadena completa de borde: resolución
# del nombre por el resolver del sistema + bind de :443 + terminación TLS +
# enrutado de Traefik hasta el contenedor api. Un «devolvió 000» pelado no
# distingue cuál de los cuatro eslabones se rompió, así que se diagnostican por
# separado y cada rama trae el comando que lo arregla.
if ! resuelve_a_loopback "api.${BASE_DOMAIN}"; then
    falla "api.${BASE_DOMAIN} no resuelve a 127.0.0.1 por el resolver del sistema (ni siquiera se intentó la conexión). Ejecuta: ./scripts/setup-dnsmasq.sh"
else
    # Deliberadamente SIN -k: así el check cubre también que el certificado sea
    # de confianza para el sistema (mkcert -install), no solo que exista
    # handshake. Sin `|| echo 000`: curl ya imprime 000 cuando no conecta, y
    # encadenar el echo produce el confuso "000000" que vio el QA.
    CODIGO="$(curl -s "${CURL_TOPES[@]}" -o /dev/null -w '%{http_code}' "https://api.${BASE_DOMAIN}/health" 2>/dev/null)"
    CODIGO="${CODIGO:-000}"
    if [ "${CODIGO}" = "200" ]; then
        ok "https://api.${BASE_DOMAIN}/health devuelve 200 con certificado de confianza"
    else
        # ¿Es solo la confianza en el certificado, o no hay servicio detrás?
        CODIGO_INSEGURO="$(curl -ks "${CURL_TOPES[@]}" -o /dev/null -w '%{http_code}' "https://api.${BASE_DOMAIN}/health" 2>/dev/null)"
        CODIGO_INSEGURO="${CODIGO_INSEGURO:-000}"
        if [ "${CODIGO_INSEGURO}" = "200" ]; then
            falla "https://api.${BASE_DOMAIN}/health responde 200 pero su certificado no es de confianza para el sistema. Ejecuta: mkcert -install && ./scripts/setup-certs.sh && docker compose restart traefik"
        else
            falla "https://api.${BASE_DOMAIN}/health devolvió ${CODIGO_INSEGURO}; el nombre SÍ resuelve, así que mira el bind de :443 (docker ps | grep traefik) y el router 'api' en http://127.0.0.1:8088/dashboard/"
        fi
    fi
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
# 15-16. Checks que dependen de código que aún no existe. OMITIDOS con motivo.
# ---------------------------------------------------------------------------
info "15. Sonda de disponibilidad de la API (/health/ready con PG, Redis y KC)"
omite "15: /health/ready llega con la tarea 4.1 del plan de Fase 0"

info "16. Tenant de demostración provisionado"
omite "16: el módulo tenants y seed.sh llegan con las tareas 4.2 y 4.4"

# ---------------------------------------------------------------------------
# 17. Secretos: en producción, ningún valor puede ser el del .env.example.
# ---------------------------------------------------------------------------
info "17. Secretos de ejemplo fuera de producción"
if [ "${APP_ENV}" = "production" ]; then
    SOSPECHOSAS=""
    for VAR in POSTGRES_PASSWORD VENDI_PLATFORM_DB_PASSWORD VENDI_APP_DB_PASSWORD \
               REDIS_PASSWORD RABBITMQ_PASSWORD MINIO_SECRET_KEY \
               KEYCLOAK_ADMIN_PASSWORD VENDI_BACKEND_CLIENT_SECRET GRAFANA_ADMIN_PASSWORD; do
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
