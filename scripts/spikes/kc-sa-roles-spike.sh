#!/usr/bin/env bash
# =============================================================================
# kc-sa-roles-spike.sh
#
# ¿Cuál es el conjunto MÍNIMO de roles de `realm-management` con el que la
# cuenta de servicio de `vendi-backend` puede aprovisionar tenants?
#
# El QA de la Etapa 2 marcó como bloqueante que la cuenta llevara `manage-realm`
# e `impersonation`. Este spike no discute: mide. Levanta un Keycloak 26.6.4
# efímero con el realm real (infra/keycloak/realm-vendi-co.json), y para cada
# conjunto candidato de roles ejecuta la secuencia completa de aprovisionamiento
# más las operaciones que NUNCA deben permitirse, imprimiendo el código HTTP de
# cada una.
#
# Uso:
#   bash scripts/spikes/kc-sa-roles-spike.sh
#
# Deja el contenedor `kc-sa-spike` vivo para inspección; bórralo con:
#   docker rm -f kc-sa-spike
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

KC_IMG="quay.io/keycloak/keycloak:26.6.4"
PUERTO="${KC_SPIKE_PUERTO:-8091}"
SECRETO="secreto-de-spike-123"

docker rm -f kc-sa-spike >/dev/null 2>&1 || true
docker run -d --name kc-sa-spike -p "${PUERTO}:8080" \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  -e KC_SPI_IMPORT_SINGLE_FILE_REPLACE_PLACEHOLDERS=true \
  -e VENDI_BACKEND_CLIENT_SECRET="${SECRETO}" \
  -e VENDI_BASE_DOMAIN=vendi.local \
  -v "${REPO_ROOT}/infra/keycloak/realm-vendi-co.json:/opt/keycloak/data/import/realm-vendi-co.json:ro" \
  "${KC_IMG}" start-dev --import-realm >/dev/null

echo "Esperando a Keycloak en http://127.0.0.1:${PUERTO} ..."
until curl -sf "http://127.0.0.1:${PUERTO}/realms/vendi-co/.well-known/openid-configuration" >/dev/null; do
  sleep 2
done
echo "Keycloak listo con el realm vendi-co importado."
echo ""

KC_URL="http://127.0.0.1:${PUERTO}" KC_SECRETO="${SECRETO}" python3 - <<'PY'
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

KC = os.environ["KC_URL"]
REALM = "vendi-co"
SECRETO = os.environ["KC_SECRETO"]


def llamar(metodo, ruta, token, cuerpo=None):
    """Devuelve (codigo_http, cuerpo_json_o_texto)."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(
        KC + ruta,
        data=datos,
        method=metodo,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(peticion) as respuesta:
            crudo = respuesta.read()
            cabecera_loc = respuesta.headers.get("Location")
            try:
                cuerpo_resp = json.loads(crudo) if crudo else None
            except ValueError:
                cuerpo_resp = crudo.decode(errors="replace")[:200]
            return respuesta.status, cuerpo_resp, cabecera_loc
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:160], None


def token_admin():
    datos = urllib.parse.urlencode(
        {"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "admin"}
    ).encode()
    with urllib.request.urlopen(KC + "/realms/master/protocol/openid-connect/token", data=datos) as r:
        return json.load(r)["access_token"]


def token_cuenta_servicio():
    datos = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "client_id": "vendi-backend", "client_secret": SECRETO}
    ).encode()
    with urllib.request.urlopen(KC + f"/realms/{REALM}/protocol/openid-connect/token", data=datos) as r:
        return json.load(r)["access_token"]


ADMIN = token_admin()
CID = llamar("GET", f"/admin/realms/{REALM}/clients?clientId=vendi-backend", ADMIN)[1][0]["id"]
SAU = llamar("GET", f"/admin/realms/{REALM}/clients/{CID}/service-account-user", ADMIN)[1]["id"]
RM = llamar("GET", f"/admin/realms/{REALM}/clients?clientId=realm-management", ADMIN)[1][0]["id"]
DISPONIBLES = {r["name"]: r for r in llamar("GET", f"/admin/realms/{REALM}/roles", ADMIN)[1]}
ROLES_RM = {r["name"]: r for r in llamar("GET", f"/admin/realms/{REALM}/clients/{RM}/roles", ADMIN)[1]}


def fijar_roles(nombres):
    actuales = llamar("GET", f"/admin/realms/{REALM}/users/{SAU}/role-mappings/clients/{RM}", ADMIN)[1]
    if actuales:
        llamar("DELETE", f"/admin/realms/{REALM}/users/{SAU}/role-mappings/clients/{RM}", ADMIN, actuales)
    deseados = [ROLES_RM[n] for n in nombres]
    if deseados:
        llamar("POST", f"/admin/realms/{REALM}/users/{SAU}/role-mappings/clients/{RM}", ADMIN, deseados)
    efectivos = llamar("GET", f"/admin/realms/{REALM}/users/{SAU}/role-mappings/clients/{RM}", ADMIN)[1]
    return sorted(r["name"] for r in efectivos)


def secuencia_aprovisionamiento(token):
    """La secuencia REAL del alta de un tenant (tarea 4.2) + las prohibidas."""
    tid = str(uuid.uuid4())
    resultados = []
    org_id = None
    usuario_id = None

    st, cuerpo, loc = llamar(
        "POST",
        f"/admin/realms/{REALM}/organizations",
        token,
        {
            "name": f"Negocio {tid[:8]}",
            "alias": tid,
            "enabled": True,
            "domains": [{"name": f"{tid}.tenants.vendi.local", "verified": True}],
        },
    )
    resultados.append(("POST /organizations (alta de tenant)", st))
    if loc:
        org_id = loc.rsplit("/", 1)[-1]

    st, cuerpo, _ = llamar("GET", f"/admin/realms/{REALM}/organizations?first=0&max=100", token)
    resultados.append(("GET /organizations (reconcile)", st))

    if org_id:
        resultados.append(("GET /organizations/{id}", llamar("GET", f"/admin/realms/{REALM}/organizations/{org_id}", token)[0]))

    st, cuerpo, loc = llamar(
        "POST",
        f"/admin/realms/{REALM}/users",
        token,
        {
            "username": f"duena-{tid[:8]}",
            "email": f"duena-{tid[:8]}@ejemplo.local",
            "enabled": True,
            "emailVerified": True,
            "credentials": [{"type": "password", "value": "clave-de-spike", "temporary": False}],
        },
    )
    resultados.append(("POST /users (alta de la dueña)", st))
    if loc:
        usuario_id = loc.rsplit("/", 1)[-1]

    resultados.append(
        ("GET /users?username= (búsqueda)", llamar("GET", f"/admin/realms/{REALM}/users?username=duena-{tid[:8]}", token)[0])
    )

    if org_id and usuario_id:
        resultados.append(
            (
                "POST /organizations/{id}/members (alta de miembro)",
                llamar("POST", f"/admin/realms/{REALM}/organizations/{org_id}/members", token, usuario_id)[0],
            )
        )
        resultados.append(
            ("GET /organizations/{id}/members", llamar("GET", f"/admin/realms/{REALM}/organizations/{org_id}/members", token)[0])
        )

    # Rol de realm de negocio: crear si falta y asignarlo (lo hará seed.sh / la API).
    st_rol, cuerpo_rol, _ = llamar("GET", f"/admin/realms/{REALM}/roles/dueno", token)
    if st_rol == 404:
        st_rol_crear, _, _ = llamar("POST", f"/admin/realms/{REALM}/roles", token, {"name": "dueno"})
        resultados.append(("POST /roles (rol de negocio 'dueno')", st_rol_crear))
        st_rol, cuerpo_rol, _ = llamar("GET", f"/admin/realms/{REALM}/roles/dueno", token)
    resultados.append(("GET /roles/dueno", st_rol))
    if usuario_id and isinstance(cuerpo_rol, dict) and "id" in cuerpo_rol:
        resultados.append(
            (
                "POST /users/{id}/role-mappings/realm (asignar 'dueno')",
                llamar(
                    "POST",
                    f"/admin/realms/{REALM}/users/{usuario_id}/role-mappings/realm",
                    token,
                    [{"id": cuerpo_rol["id"], "name": "dueno"}],
                )[0],
            )
        )
        resultados.append(
            ("GET /users/{id}/groups (grupos del usuario)", llamar("GET", f"/admin/realms/{REALM}/users/{usuario_id}/groups", token)[0])
        )

    # Grupos de negocio: seed.sh (tarea 4.4) los crea y mete usuarios en ellos.
    st_grupo, _, loc_grupo = llamar("POST", f"/admin/realms/{REALM}/groups", token, {"name": f"grupo-{tid[:8]}"})
    resultados.append(("POST /groups (grupo de negocio)", st_grupo))
    grupo_id = loc_grupo.rsplit("/", 1)[-1] if loc_grupo else None
    resultados.append(("GET /groups (listado)", llamar("GET", f"/admin/realms/{REALM}/groups", token)[0]))
    if grupo_id and usuario_id:
        resultados.append(
            (
                "PUT /users/{id}/groups/{gid} (meter al usuario en el grupo)",
                llamar("PUT", f"/admin/realms/{REALM}/users/{usuario_id}/groups/{grupo_id}", token)[0],
            )
        )

    # --- Operaciones que NO deben permitirse -------------------------------
    if usuario_id:
        resultados.append(
            (
                "!! POST /users/{id}/impersonation (DEBE ser 403)",
                llamar("POST", f"/admin/realms/{REALM}/users/{usuario_id}/impersonation", token, {})[0],
            )
        )
    resultados.append(
        (
            "!! POST /clients (DEBE ser 403)",
            llamar("POST", f"/admin/realms/{REALM}/clients", token, {"clientId": f"colado-{tid[:8]}"})[0],
        )
    )
    resultados.append(
        (
            "!! GET /authentication/flows (DEBE ser 403)",
            llamar("GET", f"/admin/realms/{REALM}/authentication/flows", token)[0],
        )
    )
    resultados.append(
        (
            "!! PUT /realms/vendi-co (riesgo residual de manage-realm)",
            llamar("PUT", f"/admin/realms/{REALM}", token, {"realm": REALM, "displayName": "Vendi"})[0],
        )
    )

    # Limpieza de lo que se haya podido crear.
    if grupo_id:
        llamar("DELETE", f"/admin/realms/{REALM}/groups/{grupo_id}", token)
    if org_id:
        llamar("DELETE", f"/admin/realms/{REALM}/organizations/{org_id}", token)
    if usuario_id:
        llamar("DELETE", f"/admin/realms/{REALM}/users/{usuario_id}", token)
    return resultados


CANDIDATOS = [
    ("S0 · el conjunto original (con manage-realm e impersonation)",
     ["manage-realm", "view-realm", "manage-users", "view-users", "query-users", "query-groups", "impersonation"]),
    ("S1 · lo que pedía el QA: solo manage-users/view-*/query-*",
     ["view-realm", "manage-users", "view-users", "query-users", "query-groups"]),
    ("S2 · propuesta: S0 SIN impersonation",
     ["manage-realm", "view-realm", "manage-users", "view-users", "query-users", "query-groups"]),
    ("S3 · mínimo teórico: manage-realm + manage-users",
     ["manage-realm", "manage-users"]),
    ("S4 · solo lectura: view-realm + view-users + query-users",
     ["view-realm", "view-users", "query-users"]),
]

for titulo, roles in CANDIDATOS:
    efectivos = fijar_roles(roles)
    token = token_cuenta_servicio()
    carga = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    en_token = sorted(carga.get("resource_access", {}).get("realm-management", {}).get("roles", []))
    print("=" * 78)
    print(titulo)
    print("  roles asignados : " + ", ".join(efectivos))
    print("  roles en el token: " + ", ".join(en_token))
    print("-" * 78)
    for operacion, codigo in secuencia_aprovisionamiento(token):
        marca = "OK " if codigo < 400 else "NO "
        print(f"  {marca} {codigo}  {operacion}")
    print("")

# Se deja el conjunto QUE SE ENTREGA (S3, el mismo del realm del repositorio)
# para que el contenedor de inspección termine igual que el sistema real y
# nadie copie de aquí un conjunto más amplio. El contenedor es efímero
# (kc-sa-spike, puerto propio): nada de esto toca el Keycloak del stack.
fijar_roles(["manage-realm", "manage-users"])
print("Estado final del contenedor: cuenta de servicio con el conjunto S3 (manage-realm + manage-users), el mismo que entrega el realm del repositorio.")
PY
