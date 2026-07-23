#!/usr/bin/env bash
# =============================================================================
# restore-backup.sh
#
# Restaura un volcado del sidecar `postgres-backup` y VERIFICA que lo restaurado
# es un SISTEMA UTILIZABLE, no un montón de tablas:
#
#   base `vendi`     dueños y privilegios en su sitio, RLS activa y forzada,
#                    y lectura real con los dos roles del modelo.
#   base `keycloak`  el realm `vendi-co`, sus usuarios con credenciales, sus
#                    clientes y sus organizaciones.
#
# LAS DOS, SIEMPRE. Restaurar `vendi` sin `keycloak` produce una base cuyas
# filas apuntan —vía `alias = str(tenant_id)` y el claim `organization`— a
# organizaciones y usuarios que no existen: nadie puede autenticarse, así que
# nadie puede leer nada. Eso no es un respaldo restaurado, es un museo.
#
# Un respaldo que nunca se restauró no es un respaldo. Este script es el que
# convierte el sidecar en un respaldo de verdad, y se ejecuta con la misma
# facilidad en un simulacro que en un incidente.
#
# Uso:
#   scripts/restore-backup.sh                       # último par → vendi_restaurada + keycloak_restaurada
#   scripts/restore-backup.sh --archivo vendi-20260723T051500Z.sql.gz
#   scripts/restore-backup.sh --destino vendi_prueba --destino-kc kc_prueba
#   scripts/restore-backup.sh --simulacro           # restaura, verifica y BORRA las bases
#   scripts/restore-backup.sh --sin-keycloak        # restauración PARCIAL, solo datos
#   scripts/restore-backup.sh --listar
#
# Todo ocurre dentro del contenedor `postgres-backup`: es el único que tiene
# montado el volumen de respaldos y ya trae psql. No hace falta psql en el
# anfitrión.
#
# El procedimiento completo de recuperación —incluido qué NO se respalda y cómo
# se promueven las copias a bases vivas— está en docs/respaldo-y-restauracion.md.
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[AVISO]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
# Salida 2 = INCONCLUSO: no se pudo probar nada, que no es lo mismo que «el
# respaldo está roto» (1) ni, sobre todo, que «el respaldo sirve» (0). Antes
# este caso salía 0 declarando el volcado restaurable sin haber verificado
# nada; un verde así es peor que un rojo, porque nadie vuelve a mirarlo.
inconcluso() { echo -e "${YELLOW}[INCONCLUSO]${NC} $*" >&2; exit 2; }

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

SUPERUSUARIO="${POSTGRES_USER:-postgres}"

ARCHIVO=""
DESTINO="vendi_restaurada"
DESTINO_KC="keycloak_restaurada"
SIMULACRO=0
SOLO_LISTAR=0
SIN_KEYCLOAK=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --archivo)      ARCHIVO="${2:?falta el nombre del archivo}"; shift 2 ;;
        --destino)      DESTINO="${2:?falta el nombre de la base destino}"; shift 2 ;;
        --destino-kc)   DESTINO_KC="${2:?falta el nombre de la base destino de keycloak}"; shift 2 ;;
        --simulacro)    SIMULACRO=1; shift ;;
        --sin-keycloak) SIN_KEYCLOAK=1; shift ;;
        --listar)       SOLO_LISTAR=1; shift ;;
        -h|--help)      sed -n '2,33p' "$0"; exit 0 ;;
        *)              error "opción desconocida: $1 (usa --help)" ;;
    esac
done

# Las bases vivas nunca se pisan por accidente desde aquí.
if [[ "${DESTINO}" == "vendi" || "${DESTINO_KC}" == "keycloak" ]]; then
    error "los destinos 'vendi' y 'keycloak' son las bases vivas. Restaura a otro nombre y renómbralas a mano si de verdad quieres reemplazarlas."
fi

en_sidecar() { "${COMPOSE[@]}" exec -T postgres-backup "$@"; }

if ! en_sidecar sh -c 'test -d /backups'; then
    error "el contenedor postgres-backup no está arriba (docker compose up -d postgres-backup)"
fi

info "Volcados disponibles:"
en_sidecar sh -c "ls -1t /backups/*.sql.gz 2>/dev/null | head -30 | sed 's|/backups/|    |'" \
    || error "no hay ningún volcado en /backups todavía"

if [[ "${SOLO_LISTAR}" -eq 1 ]]; then
    exit 0
fi

if [[ -z "${ARCHIVO}" ]]; then
    ARCHIVO="$(en_sidecar sh -c "ls -1t /backups/vendi-2*.sql.gz 2>/dev/null | head -1" | tr -d '\r')"
    [[ -n "${ARCHIVO}" ]] || error "no encontré ningún volcado de la base vendi en /backups"
    ARCHIVO="$(basename "${ARCHIVO}")"
fi
info "Volcado de datos elegido: ${ARCHIVO}"

# El volcado de roles y el de Keycloak que acompañan al de datos llevan la
# MISMA marca de tiempo: es lo único que empareja las tres piezas.
MARCA="${ARCHIVO#vendi-}"; MARCA="${MARCA%.sql.gz}"
ARCHIVO_ROLES="vendi-roles-${MARCA}.sql.gz"
ARCHIVO_KC="keycloak-${MARCA}.sql.gz"

# ---------------------------------------------------------------------------
# 0. El par tiene que estar COMPLETO antes de tocar nada. Descubrir a mitad de
#    un incidente que falta la mitad de identidad es exactamente lo que este
#    script existe para impedir.
# ---------------------------------------------------------------------------
if [[ "${SIN_KEYCLOAK}" -eq 0 ]]; then
    if ! en_sidecar sh -c "test -f /backups/${ARCHIVO_KC}"; then
        error "falta ${ARCHIVO_KC}, el volcado de identidad emparejado con ${ARCHIVO}.
        Sin la base de Keycloak, la copia de 'vendi' referencia organizaciones y
        usuarios inexistentes: nadie podría autenticarse contra el sistema
        restaurado. Si de verdad quieres una restauración PARCIAL (solo datos,
        sin servicio) repítelo con --sin-keycloak."
    fi
    info "Volcado de identidad emparejado: ${ARCHIVO_KC}"
else
    warn "--sin-keycloak: restauración PARCIAL. Las bases resultantes NO forman un sistema utilizable."
fi

# ---------------------------------------------------------------------------
# 1. Roles. El volcado de datos referencia a vendi_platform/vendi_app por
#    nombre: si no existen, el primer ALTER OWNER revienta. En la misma máquina
#    ya están (los creó 01-roles.sh); en una máquina nueva los pone este paso.
# ---------------------------------------------------------------------------
if en_sidecar sh -c "test -f /backups/${ARCHIVO_ROLES}"; then
    info "Restaurando roles del clúster desde ${ARCHIVO_ROLES} (los que ya existan darán error y se ignoran)"
    en_sidecar sh -c "gunzip -c /backups/${ARCHIVO_ROLES} | psql -d postgres -v ON_ERROR_STOP=0 -q 2>&1 | grep -v 'ya existe\|already exists' | tail -5" || true
    success "roles aplicados"
else
    warn "no hay volcado de roles ${ARCHIVO_ROLES}; asumo que vendi_platform y vendi_app ya existen en este clúster"
fi

# ---------------------------------------------------------------------------
# 2. Base de datos destino, vacía y con el dueño correcto.
#
#    Los ACL de NIVEL DE BASE (el REVOKE CONNECT ... FROM PUBLIC de
#    01-roles.sh) NO viajan en el volcado: pg_dump solo los emite con --create,
#    y aquí la base la creamos nosotros. Sin reponerlos, la copia restaurada
#    devuelve a PUBLIC el CONNECT que la base viva tiene revocado — o sea, la
#    copia sería más laxa que el original. Se reponen a mano.
# ---------------------------------------------------------------------------
info "Creando la base ${DESTINO} (OWNER vendi_platform)"
en_sidecar psql -d postgres -q -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS ${DESTINO}" \
    -c "CREATE DATABASE ${DESTINO} OWNER vendi_platform"
en_sidecar psql -d postgres -q -v ON_ERROR_STOP=1 \
    -c "REVOKE CONNECT ON DATABASE ${DESTINO} FROM PUBLIC" \
    -c "GRANT CONNECT ON DATABASE ${DESTINO} TO vendi_app, vendi_platform"

# ---------------------------------------------------------------------------
# 3. Restauración de los datos.
# ---------------------------------------------------------------------------
info "Restaurando ${ARCHIVO} en ${DESTINO}"
if ! en_sidecar sh -c "gunzip -c /backups/${ARCHIVO} | psql -d ${DESTINO} -q -v ON_ERROR_STOP=1 >/dev/null"; then
    error "la restauración falló. Repite sin -q para ver el SQL exacto que rompió."
fi
success "restauración de datos terminada sin errores"

# ---------------------------------------------------------------------------
# 4. Verificación de los datos: la parte que convierte esto en una prueba y no
#    en un rito.
# ---------------------------------------------------------------------------
echo ""
info "Verificando la base de datos restaurada (${DESTINO})"

TABLAS="$(en_sidecar psql -d "${DESTINO}" -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname='public'" | tr -d '[:space:]')"
info "tablas en public: ${TABLAS:-0}"

# Cero tablas no es un aviso que se pasa de largo: sin tablas no se ejecuta
# NINGUNA de las comprobaciones que dan sentido al simulacro (dueños, GRANT,
# RLS, lectura por rol), así que el simulacro no ha probado nada. Se corta aquí
# con salida 2 (inconcluso), nunca 0.
if [[ "${TABLAS:-0}" -eq 0 ]]; then
    en_sidecar psql -d postgres -q -c "DROP DATABASE IF EXISTS ${DESTINO}" >/dev/null 2>&1 || true
    inconcluso "la base restaurada no tiene NI UNA tabla en public.
    El volcado ${ARCHIVO} está vacío. Hasta la tarea 4.2 del plan de Fase 0 (la
    que crea el esquema) esto es lo ESPERADO: no hay nada que respaldar todavía.
    Lo que no se puede decir es que el volcado sea restaurable, porque no se ha
    verificado ni un dueño, ni un GRANT, ni una política de RLS, ni una lectura.
    Repite este simulacro en cuanto exista la primera migración."
fi

# 4a. Dueño y privilegios: es LO que se perdía con --no-owner --no-privileges.
AJENAS="$(en_sidecar psql -d "${DESTINO}" -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner <> 'vendi_platform'" | tr -d '[:space:]')"
if [[ "${AJENAS:-1}" == "0" ]]; then
    success "las ${TABLAS} tablas son de vendi_platform"
else
    error "${AJENAS} tabla(s) con dueño distinto de vendi_platform: el volcado se hizo sin dueños"
fi

SIN_GRANT="$(en_sidecar psql -d "${DESTINO}" -tAc "
    SELECT count(*) FROM pg_tables t
     WHERE schemaname='public'
       AND NOT has_table_privilege('vendi_app', quote_ident(schemaname)||'.'||quote_ident(tablename), 'SELECT')" | tr -d '[:space:]')"
if [[ "${SIN_GRANT:-1}" == "0" ]]; then
    success "vendi_app tiene SELECT sobre las ${TABLAS} tablas restauradas"
else
    error "${SIN_GRANT} tabla(s) sin SELECT para vendi_app: el volcado se hizo sin privilegios"
fi

# 4b. El ACL de nivel de base repuesto en el paso 2.
if en_sidecar psql -d postgres -tAc \
    "SELECT has_database_privilege('public','${DESTINO}','CONNECT')" | grep -qi '^f'; then
    success "PUBLIC no tiene CONNECT sobre ${DESTINO} (el ACL de base se repuso)"
else
    error "PUBLIC conserva CONNECT sobre ${DESTINO}: el ACL de nivel de base no se repuso"
fi

# 4c. RLS: que siga activa y forzada donde lo estaba.
RLS="$(en_sidecar psql -d "${DESTINO}" -tAc \
    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity" | tr -d '[:space:]')"
POLITICAS="$(en_sidecar psql -d "${DESTINO}" -tAc "SELECT count(*) FROM pg_policies WHERE schemaname='public'" | tr -d '[:space:]')"
info "tablas con RLS activa: ${RLS:-0} · políticas: ${POLITICAS:-0}"

# 4d. Lectura real con los dos roles del modelo.
if [[ -n "${VENDI_APP_DB_PASSWORD:-}" ]]; then
    # vendi_app SIN el GUC de tenant tiene que poder consultar (privilegios) y
    # ver cero filas (RLS fail-closed). Cualquier otra cosa es un hallazgo.
    UNA_TABLA="$(en_sidecar psql -d "${DESTINO}" -tAc \
        "SELECT tablename FROM pg_tables t WHERE schemaname='public'
           AND EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename=t.tablename AND p.schemaname='public')
         ORDER BY tablename LIMIT 1" | tr -d '[:space:]')"
    if [[ -n "${UNA_TABLA}" ]]; then
        SALIDA="$("${COMPOSE[@]}" exec -T -e PGPASSWORD="${VENDI_APP_DB_PASSWORD}" postgres-backup \
            psql -U vendi_app -d "${DESTINO}" -tAc "SELECT count(*) FROM public.${UNA_TABLA}" 2>&1 | tr -d '[:space:]')"
        if [[ "${SALIDA}" == "0" ]]; then
            success "vendi_app consulta ${UNA_TABLA} sin el GUC y ve 0 filas (RLS fail-closed sobrevivió al restore)"
        else
            error "vendi_app sobre ${UNA_TABLA} devolvió «${SALIDA}» (esperaba 0 filas sin error)"
        fi
        # Y la lectura POSITIVA: vendi_platform (BYPASSRLS) tiene que ver los
        # datos de verdad. Sin esta mitad, una copia vacía pasaría el check
        # anterior con matrícula de honor.
        if [[ -n "${VENDI_PLATFORM_DB_PASSWORD:-}" ]]; then
            FILAS="$("${COMPOSE[@]}" exec -T -e PGPASSWORD="${VENDI_PLATFORM_DB_PASSWORD}" postgres-backup \
                psql -U vendi_platform -d "${DESTINO}" -tAc "SELECT count(*) FROM public.${UNA_TABLA}" 2>&1 | tr -d '[:space:]')"
            if [[ "${FILAS}" =~ ^[0-9]+$ ]] && [[ "${FILAS}" -gt 0 ]]; then
                success "vendi_platform lee ${FILAS} fila(s) de ${UNA_TABLA} en la copia (hay datos, no solo esquema)"
            else
                warn "vendi_platform leyó «${FILAS}» de ${UNA_TABLA}: la copia tiene el esquema pero esa tabla está vacía"
            fi
        fi
    else
        warn "no hay ninguna tabla con política RLS en la copia; me salto la prueba de lectura con vendi_app"
    fi
else
    warn "VENDI_APP_DB_PASSWORD no está en el entorno; me salto las pruebas de lectura por rol"
fi

# ---------------------------------------------------------------------------
# 5. Identidad: la base de Keycloak. Sin esto, lo de arriba no es un servicio.
# ---------------------------------------------------------------------------
if [[ "${SIN_KEYCLOAK}" -eq 0 ]]; then
    echo ""
    info "Creando la base ${DESTINO_KC} (OWNER ${SUPERUSUARIO}) y restaurando ${ARCHIVO_KC}"
    en_sidecar psql -d postgres -q -v ON_ERROR_STOP=1 \
        -c "DROP DATABASE IF EXISTS ${DESTINO_KC}" \
        -c "CREATE DATABASE ${DESTINO_KC} OWNER ${SUPERUSUARIO}"
    # Mismo criterio que en 01-roles.sh: la base del IdP no es de PUBLIC.
    en_sidecar psql -d postgres -q -v ON_ERROR_STOP=1 \
        -c "REVOKE CONNECT ON DATABASE ${DESTINO_KC} FROM PUBLIC" \
        -c "GRANT CONNECT ON DATABASE ${DESTINO_KC} TO ${SUPERUSUARIO}"

    if ! en_sidecar sh -c "gunzip -c /backups/${ARCHIVO_KC} | psql -d ${DESTINO_KC} -q -v ON_ERROR_STOP=1 >/dev/null"; then
        error "la restauración de la base de Keycloak falló. Repite sin -q para ver el SQL exacto que rompió."
    fi
    success "restauración de identidad terminada sin errores"

    echo ""
    info "Verificando la base de identidad restaurada (${DESTINO_KC})"

    TABLAS_KC="$(en_sidecar psql -d "${DESTINO_KC}" -tAc \
        "SELECT count(*) FROM pg_tables WHERE schemaname='public'" | tr -d '[:space:]')"
    info "tablas en public: ${TABLAS_KC:-0}"
    if [[ "${TABLAS_KC:-0}" -eq 0 ]]; then
        error "la base de Keycloak restaurada no tiene ni una tabla: el volcado ${ARCHIVO_KC} está vacío."
    fi

    # El realm tiene que estar, con nombre. Un esquema de Keycloak vacío se
    # restaura sin errores y no sirve absolutamente para nada.
    if en_sidecar psql -d "${DESTINO_KC}" -tAc \
        "SELECT count(*) FROM realm WHERE name='vendi-co'" | grep -q '^1'; then
        success "el realm vendi-co está en la copia"
    else
        error "el realm vendi-co NO está en la copia restaurada: sin él nadie puede autenticarse."
    fi

    USUARIOS="$(en_sidecar psql -d "${DESTINO_KC}" -tAc \
        "SELECT count(*) FROM user_entity u JOIN realm r ON r.id=u.realm_id WHERE r.name='vendi-co'" | tr -d '[:space:]')"
    CREDENCIALES="$(en_sidecar psql -d "${DESTINO_KC}" -tAc \
        "SELECT count(*) FROM credential c JOIN user_entity u ON u.id=c.user_id
          JOIN realm r ON r.id=u.realm_id WHERE r.name='vendi-co'" | tr -d '[:space:]')"
    CLIENTES="$(en_sidecar psql -d "${DESTINO_KC}" -tAc \
        "SELECT count(*) FROM client c JOIN realm r ON r.id=c.realm_id
          WHERE r.name='vendi-co' AND c.client_id LIKE 'vendi-%'" | tr -d '[:space:]')"
    # `org` es la tabla de Organizations de Keycloak 26: una fila por tenant,
    # con el alias que vale str(tenant_id). Es la bisagra entre las dos bases.
    ORGS="$(en_sidecar psql -d "${DESTINO_KC}" -tAc \
        "SELECT count(*) FROM org o JOIN realm r ON r.id=o.realm_id WHERE r.name='vendi-co'" | tr -d '[:space:]')"
    info "en vendi-co → usuarios: ${USUARIOS:-0} · credenciales: ${CREDENCIALES:-0} · clientes vendi-*: ${CLIENTES:-0} · organizaciones: ${ORGS:-0}"

    if [[ "${CLIENTES:-0}" -gt 0 ]]; then
        success "los clientes vendi-* viajan en la copia (con su secreto: la API puede volver a hablar con el IdP)"
    else
        error "no hay ni un cliente vendi-* en la copia: el backend no podría autenticarse contra el realm."
    fi

    # Ojo con leer de más aquí: las cuentas de servicio son `user_entity` sin
    # credencial (se autentican con el secreto del cliente). Que haya usuarios
    # no implica todavía que haya nadie que pueda teclear una contraseña.
    if [[ "${CREDENCIALES:-0}" -gt 0 ]]; then
        success "hay ${USUARIOS} usuario(s) y ${CREDENCIALES} credencial(es) en la copia: se puede iniciar sesión en el sistema restaurado"
    elif [[ "${USUARIOS:-0}" -gt 0 ]]; then
        warn "hay ${USUARIOS} usuario(s) pero NINGUNA credencial: en un realm recién sembrado son cuentas de servicio (entran con el secreto del cliente). En cuanto haya usuarios humanos, este contador tiene que subir."
    else
        warn "el realm restaurado no tiene usuarios (realm recién sembrado, sin nadie dado de alta todavía)"
    fi
fi

# ---------------------------------------------------------------------------
# 6. Cierre.
# ---------------------------------------------------------------------------
echo ""
if [[ "${SIMULACRO}" -eq 1 ]]; then
    info "Simulacro: borrando las bases restauradas"
    en_sidecar psql -d postgres -q -c "DROP DATABASE IF EXISTS ${DESTINO}"
    [[ "${SIN_KEYCLOAK}" -eq 0 ]] && en_sidecar psql -d postgres -q -c "DROP DATABASE IF EXISTS ${DESTINO_KC}"
    if [[ "${SIN_KEYCLOAK}" -eq 1 ]]; then
        warn "simulacro PARCIAL completo: ${ARCHIVO} restaura los datos, pero NO se probó la identidad (--sin-keycloak)."
    else
        success "simulacro completo: el par ${ARCHIVO} + ${ARCHIVO_KC} restaura un sistema utilizable (datos + identidad)."
    fi
else
    success "bases restauradas y verificadas. Bórralas cuando termines:"
    echo "    docker compose -f infra/docker-compose.yml exec postgres-backup psql -d postgres -c 'DROP DATABASE ${DESTINO}'"
    if [[ "${SIN_KEYCLOAK}" -eq 0 ]]; then
        echo "    docker compose -f infra/docker-compose.yml exec postgres-backup psql -d postgres -c 'DROP DATABASE ${DESTINO_KC}'"
    fi
fi

# Código de salida explícito. Una restauración parcial pedida con
# --sin-keycloak es un ÉXITO de lo que se pidió (con su [AVISO] ruidoso),
# no un respaldo roto: 1 queda reservado para fallos reales y 2 para
# simulacros inconcluyentes. Sin este exit, la última lista `[[ ]] && echo`
# devolvía 1 con --sin-keycloak y contradecía el runbook.
exit 0
