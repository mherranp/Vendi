#!/usr/bin/env bash
# =============================================================================
# codegen-api-client.sh
#
# Regenera el cliente TypeScript tipado de la API de Vendi a partir del esquema
# OpenAPI, dentro de la librería `data-access` (spec §6.2: `data-access` es la
# capa HTTP del monorepo y es quien recibe el cliente generado).
#
# Salidas (ambas se commitean; el cliente NO se edita a mano):
#   frontend/projects/libs/data-access/src/lib/api-client/openapi.json
#   frontend/projects/libs/data-access/src/lib/api-client/index.ts
#
# Consumo desde las apps, una vez `data-access` reexporte el barril:
#   import type { paths, components } from 'data-access';
#
# Dos fuentes de esquema, en este orden de precedencia:
#
#   1. CODEGEN_SCHEMA_FILE — un openapi.json congelado (p. ej.
#      `docs/api/openapi-fase0.json`, que la Tarea 4.2 deja fijado). Es el modo
#      reproducible: no necesita stack levantado y da el mismo resultado en CI.
#   2. La API viva en CODEGEN_API_URL. Es el modo de desarrollo, para iterar
#      sobre endpoints recién escritos.
#
# Uso:
#   ./scripts/codegen-api-client.sh                                   # API viva
#   CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json ./scripts/codegen-api-client.sh
#   CODEGEN_DRY_RUN=1 ./scripts/codegen-api-client.sh                 # solo el plan
#
# Variables:
#   CODEGEN_API_URL      base de la API      (por defecto https://api.${BASE_DOMAIN})
#   CODEGEN_SCHEMA_FILE  esquema congelado   (si se define, no se toca la red)
#   CODEGEN_TOKEN        bearer para /openapi.json si queda tras autenticación
#   CODEGEN_RESOLVE_IP   IP a la que se ancla la resolución de api.${BASE_DOMAIN}
#                        (por defecto 127.0.0.1). Vaciarla usa el DNS público,
#                        que para vendi.co es el servidor de un TERCERO.
#   CODEGEN_DRY_RUN      imprime lo que haría y sale 0, sin escribir nada
#   CODEGEN_INSECURE     apaga la verificación TLS. Rara vez es lo que quieres:
#                        el script ya ancla a la CA de mkcert por defecto, así
#                        que un certificado local válido verifica sin esto.
#
# Compatible con bash 3.2 (el que trae macOS).
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
avisa() { echo -e "${YELLOW}[AVISO]${NC} $*"; }
falla() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/frontend"
DEST_DIR="${FRONTEND_DIR}/projects/libs/data-access/src/lib/api-client"
ESQUEMA_OUT="${DEST_DIR}/openapi.json"
TIPOS_OUT="${DEST_DIR}/index.ts"

# El .env aporta BASE_DOMAIN; lo que ya venga en el entorno gana.
BASE_DOMAIN_PREVIO="${BASE_DOMAIN:-}"
if [ -f "${REPO_ROOT}/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "${REPO_ROOT}/.env"
    set +a
fi
if [ -n "${BASE_DOMAIN_PREVIO}" ]; then
    BASE_DOMAIN="${BASE_DOMAIN_PREVIO}"
fi
BASE_DOMAIN="${BASE_DOMAIN:-vendi.co}"

API_URL="${CODEGEN_API_URL:-https://api.${BASE_DOMAIN}}"
API_URL="${API_URL%/}"
ESQUEMA_FILE="${CODEGEN_SCHEMA_FILE:-}"

# Array, no cadena. Era una cadena expandida sin comillas (`curl ${CURL_OPTS}`),
# y el CAROOT por defecto de mkcert en macOS es
# `~/Library/Application Support/mkcert`: el espacio partía el argumento en dos y
# curl recibía `--cacert .../Application` + `Support/mkcert/rootCA.pem` como URL.
# Resultado: el script fallaba SIEMPRE en macOS con el mensaje "la API no
# responde", que apunta al sitio equivocado. Con un array cada elemento se cita
# por separado. `bash 3.2` —el de macOS— soporta arrays indexados; solo los
# asociativos exigen bash 4.
CURL_OPTS=(-sS --connect-timeout 5 --max-time 30)

# Anclar a la CA de mkcert por defecto. El certificado del borde lo emite esa CA,
# así que esto hace que el camino normal valide sin que nadie tenga que recurrir
# a CODEGEN_INSECURE — que es el objetivo: la salida de este script se convierte
# en el cliente de la API, y generar código a partir de un esquema descargado sin
# verificar de quién viene no es un riesgo teórico. `api.${BASE_DOMAIN}` resuelve
# a un host público cuando falta /etc/resolver/${BASE_DOMAIN}.
for _RAIZ_CA in \
    "${VENDI_MKCERT_CAROOT:-}" \
    "$(command -v mkcert >/dev/null 2>&1 && mkcert -CAROOT 2>/dev/null || true)" \
    "${HOME}/Library/Application Support/mkcert" \
    "${HOME}/.local/share/mkcert"; do
    if [ -n "${_RAIZ_CA}" ] && [ -f "${_RAIZ_CA}/rootCA.pem" ]; then
        CURL_OPTS+=(--cacert "${_RAIZ_CA}/rootCA.pem")
        break
    fi
done

# --------------------------------------------- anclaje de la resolución DNS --
#
# `${BASE_DOMAIN}` (vendi.co) **no nos pertenece**: está registrado por un
# tercero desde 2010 y resuelve públicamente a una IP suya. El stack local se
# alcanza porque `/etc/resolver/${BASE_DOMAIN}` reescribe esa resolución a
# 127.0.0.1 — y ese archivo exige sudo, así que puede no existir (es el caso hoy
# en la máquina de desarrollo).
#
# Sin anclar la resolución, este script abría una conexión a un servidor ajeno y,
# con `CODEGEN_TOKEN` definido, le mandaba un bearer de administrador de
# plataforma. Que hasta ahora fallara antes de enviarlo era suerte: el
# `--cacert` de mkcert aborta el TLS con un certificado público. Basta un
# `CODEGEN_INSECURE=1` —la escotilla documentada tres líneas más abajo— para que
# esa suerte se acabe.
#
# Por eso el anclaje es el comportamiento POR DEFECTO y no una opción:
# `CODEGEN_RESOLVE_IP` vale 127.0.0.1 salvo que se vacíe explícitamente para
# apuntar a una API remota de verdad.
API_HOST="$(printf '%s' "${API_URL}" | sed -e 's#^[a-z]*://##' -e 's#[:/].*$##')"
API_PUERTO="$(printf '%s' "${API_URL}" | sed -n 's#^[a-z]*://[^:/]*:\([0-9]*\).*$#\1#p')"
case "${API_URL}" in
    https://*) API_PUERTO="${API_PUERTO:-443}" ;;
    *)         API_PUERTO="${API_PUERTO:-80}" ;;
esac

RESOLUCION_ANCLADA=""
CODEGEN_RESOLVE_IP="${CODEGEN_RESOLVE_IP-127.0.0.1}"
case "${API_HOST}" in
    *".${BASE_DOMAIN}"|"${BASE_DOMAIN}")
        if [ -n "${CODEGEN_RESOLVE_IP}" ]; then
            CURL_OPTS+=(--resolve "${API_HOST}:${API_PUERTO}:${CODEGEN_RESOLVE_IP}")
            RESOLUCION_ANCLADA="si"
            info "Resolución anclada: ${API_HOST}:${API_PUERTO} -> ${CODEGEN_RESOLVE_IP}"
        else
            avisa "CODEGEN_RESOLVE_IP vacío: ${API_HOST} se resolverá por DNS público."
            avisa "${BASE_DOMAIN} pertenece a un tercero; asegúrate de que es lo que quieres."
        fi
        ;;
esac

# Un bearer solo sale hacia un destino cuya resolución controlamos. Es la regla
# que se saltó una vez y costó rotar los secretos de dos clientes de Keycloak.
if [ -n "${CODEGEN_TOKEN:-}" ] && [ -z "${RESOLUCION_ANCLADA}" ]; then
    falla "CODEGEN_TOKEN está definido y la resolución de ${API_HOST} NO está anclada.
       Este script no envía credenciales a un host cuya IP no controla.
       Opciones:
         1. Deja CODEGEN_RESOLVE_IP en su valor por defecto (127.0.0.1).
         2. Si la API es remota de verdad, quita CODEGEN_TOKEN o usa un esquema
            congelado: CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json"
fi

if [ -n "${CODEGEN_INSECURE:-}" ]; then
    # Se conserva como escotilla, pero deja rastro: apagar la verificación aquí
    # significa aceptar como esquema de la API lo que conteste cualquiera.
    avisa "CODEGEN_INSECURE=1: se DESACTIVA la verificación TLS. El esquema se aceptará"
    avisa "venga de donde venga. Si es por el certificado local, lo correcto es"
    avisa "'mkcert -install' y no esta variable."
    CURL_OPTS+=(-k)
fi

# ---------------------------------------------------------------- preflight --

for BIN in curl node; do
    command -v "${BIN}" >/dev/null 2>&1 \
        || falla "Falta '${BIN}' en el PATH. Es un requisito de este script."
done

GENERADOR="${FRONTEND_DIR}/node_modules/.bin/openapi-typescript"
if [ ! -x "${GENERADOR}" ]; then
    falla "No encuentro openapi-typescript en ${GENERADOR}.
       El generador está fijado en frontend/package.json como devDependency
       (no se usa 'npx --yes', que descargaría una versión distinta en cada
       máquina y haría irreproducible el cliente generado).
       Solución: cd frontend && npm ci"
fi

# --------------------------------------------------------------- dry run ----

if [ -n "${CODEGEN_DRY_RUN:-}" ]; then
    info "CODEGEN_DRY_RUN activo: no se toca la red ni se escribe nada."
    if [ -n "${ESQUEMA_FILE}" ]; then
        echo "  Fuente del esquema : archivo congelado ${ESQUEMA_FILE}"
    else
        echo "  Fuente del esquema : API viva ${API_URL}/openapi.json"
        echo "  Comprobación previa: GET ${API_URL}/health"
    fi
    echo "  Generador          : ${GENERADOR} ($("${GENERADOR}" --version 2>/dev/null || echo 'versión desconocida'))"
    echo "  Escribiría         : ${ESQUEMA_OUT}"
    echo "                       ${TIPOS_OUT}"
    ok "Plan impreso. Sin cambios en el árbol de trabajo."
    exit 0
fi

mkdir -p "${DEST_DIR}"
# Plantilla explícita con 6 X en lugar de `mktemp -t nombre`: la forma `-t` con
# un prefijo sin X solo la acepta el mktemp de BSD/macOS; el de GNU coreutils
# (cualquier runner Linux del CI) falla con "too few X's in template" y, con
# `set -e`, mata el script antes de generar nada.
TMP_ESQUEMA="$(mktemp "${TMPDIR:-/tmp}/vendi-openapi.XXXXXX")"
TMP_CABECERA=""
trap 'rm -f "${TMP_ESQUEMA}" ${TMP_CABECERA:+"${TMP_CABECERA}"}' EXIT

# -------------------------------------------------- obtención del esquema ----

if [ -n "${ESQUEMA_FILE}" ]; then
    # Ruta relativa → relativa a la raíz del repo, no al cwd de quien invoca.
    case "${ESQUEMA_FILE}" in
        /*) ;;
        *) ESQUEMA_FILE="${REPO_ROOT}/${ESQUEMA_FILE}" ;;
    esac
    [ -f "${ESQUEMA_FILE}" ] \
        || falla "CODEGEN_SCHEMA_FILE apunta a ${ESQUEMA_FILE}, que no existe."
    info "Esquema congelado: ${ESQUEMA_FILE}"
    cp "${ESQUEMA_FILE}" "${TMP_ESQUEMA}"
else
    info "Comprobando que la API responde en ${API_URL}/health ..."
    if ! curl "${CURL_OPTS[@]}" -f -o /dev/null "${API_URL}/health" 2>/dev/null; then
        falla "La API no responde en ${API_URL}/health.
       El cliente se genera desde el esquema que sirve la API: sin API no hay
       nada que generar y este script NO inventa tipos ni reutiliza en silencio
       el cliente anterior.
       Opciones:
         1. Levanta el stack:  ./scripts/dev.sh
         2. Apunta a otra API: CODEGEN_API_URL=https://otra.host $0
         3. Usa un esquema congelado (no necesita stack):
            CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json $0
       Si la API sí está arriba y lo que falla es el certificado, el arreglo es
       'mkcert -install && ./scripts/setup-certs.sh', no CODEGEN_INSECURE=1:
       este script ya valida contra la CA de mkcert."
    fi
    ok "La API responde."

    info "Descargando ${API_URL}/openapi.json ..."
    if [ -n "${CODEGEN_TOKEN:-}" ]; then
        curl "${CURL_OPTS[@]}" -f -H "Accept: application/json" \
             -H "Authorization: Bearer ${CODEGEN_TOKEN}" \
             -o "${TMP_ESQUEMA}" "${API_URL}/openapi.json" \
            || falla "No se pudo descargar ${API_URL}/openapi.json (¿token inválido o expirado?)."
    else
        curl "${CURL_OPTS[@]}" -f -H "Accept: application/json" \
             -o "${TMP_ESQUEMA}" "${API_URL}/openapi.json" \
            || falla "No se pudo descargar ${API_URL}/openapi.json.
       Si el endpoint está detrás de autenticación, exporta CODEGEN_TOKEN con un
       bearer de administrador de plataforma y reintenta."
    fi
fi

# ------------------------------------------------------------- validación ----

# Un HTML de error o una redirección a login también devuelven 200 en algunos
# proxys: se comprueba que lo descargado es OpenAPI de verdad antes de generar.
node -e '
const fs = require("fs");
let doc;
try {
  doc = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
} catch (e) {
  console.error("El esquema no es JSON válido: " + e.message);
  process.exit(2);
}
if (!doc.openapi) { console.error("Al JSON descargado le falta la clave \"openapi\"."); process.exit(3); }
if (!doc.paths || Object.keys(doc.paths).length === 0) { console.error("El esquema no declara ni un solo path."); process.exit(4); }
' "${TMP_ESQUEMA}" \
    || falla "El esquema obtenido no es un documento OpenAPI utilizable (ver el detalle arriba). No se ha escrito nada."

ok "Esquema válido."

# --------------------------------------------------------------- salida -----

# `cat >` en vez de `cp`: `cp` hereda los permisos 0600 del temporal de mktemp
# y dejaría un artefacto versionado que solo puede leer quien lo generó.
cat "${TMP_ESQUEMA}" > "${ESQUEMA_OUT}"

info "Generando tipos con openapi-typescript ..."
"${GENERADOR}" "${ESQUEMA_OUT}" --output "${TIPOS_OUT}"

# Cabecera en español delante de la del generador: quien abra el archivo por
# accidente tiene que ver en la primera línea que no debe editarlo.
# Misma plantilla portable que arriba: `-t vendi-cabecera` reventaba en GNU.
TMP_CABECERA="$(mktemp "${TMPDIR:-/tmp}/vendi-cabecera.XXXXXX")"
{
    echo '/* eslint-disable */'
    echo '/**'
    echo ' * ARCHIVO GENERADO — NO EDITAR A MANO.'
    echo ' *'
    echo ' * Lo produce `scripts/codegen-api-client.sh` a partir del esquema OpenAPI de'
    echo ' * la API de Vendi (`./openapi.json`, en este mismo directorio). Cualquier'
    echo ' * edición manual se pierde en la siguiente regeneración, y el CI la detecta'
    echo ' * con `codegen + git diff --exit-code`.'
    echo ' */'
    cat "${TIPOS_OUT}"
} > "${TMP_CABECERA}"
# `cat` en vez de `mv`: mktemp crea con permisos 0600 y un `mv` desde /tmp
# dejaría el archivo generado ilegible para el resto del equipo y para el CI.
cat "${TMP_CABECERA}" > "${TIPOS_OUT}"
rm -f "${TMP_CABECERA}"
TMP_CABECERA=""

ok "Esquema  → ${ESQUEMA_OUT}"
ok "Tipos    → ${TIPOS_OUT}"
avisa "Recuerda reexportar el barril desde data-access/src/public-api.ts si aún no lo está, y recompilar: cd frontend && npm run build:libs"
