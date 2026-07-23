#!/usr/bin/env bash
# =====================================================================
# kc-orgs-spike.sh — Spike de Keycloak 26.6.4 Organizations.
#
# Verifica contra la imagen exacta que se va a usar en producción los
# supuestos de ADR-014 (§4.2 del spec de Fase 0). Cubre las 10 preguntas
# del paso 2 de la tarea 1.1 del plan más la superficie de ataque de QA
# (cero organizaciones, dos organizaciones, alias inexistente, alias y
# dominio duplicados, supervivencia del claim al refresh token, creación
# sin dominio).
#
# Uso:
#   bash scripts/spikes/kc-orgs-spike.sh                # de cero a tokens
#   SPIKE_MANTENER=0 bash scripts/spikes/kc-orgs-spike.sh   # borra el contenedor al final
#
# NO cubre: el registro y el login con passkey, que necesitan un
# autenticador WebAuthn real. Eso lo reproduce scripts/spikes/kc-passkey-spike.mjs
# (Playwright + autenticador virtual de Chrome vía CDP) contra el mismo
# contenedor que deja vivo este script.
#
# El script es re-ejecutable: borra y recrea el contenedor en cada corrida.
# =====================================================================
set -euo pipefail

KC_IMG="quay.io/keycloak/keycloak:26.6.4"
CONT="kc-spike"
PORT="${SPIKE_KC_PORT:-8089}"
KC="http://localhost:${PORT}"
REALM="vendi-co"

# Alias de organización = tenant_id (hipótesis de diseño que este spike verifica)
T1="1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e"
T2="2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f"

titulo() { printf '\n\n=====================================================================\n%s\n=====================================================================\n' "$*"; }
sub()    { printf '\n--- %s ---\n' "$*"; }

# El token de admin de master vive 60 s: se pide fresco en cada uso.
adm() {
  curl -s "$KC/realms/master/protocol/openid-connect/token" \
    -d grant_type=password -d client_id=admin-cli -d username=admin -d password=admin \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}

# api METODO RUTA [cuerpo-json] → imprime "HTTP <code>" y el cuerpo de respuesta
api() {
  local metodo="$1" ruta="$2" cuerpo="${3:-}" tok
  tok="$(adm)"
  if [[ -n "$cuerpo" ]]; then
    curl -s -o /tmp/kcspike-resp.json -w "HTTP %{http_code}\n" -X "$metodo" \
      -H "Authorization: Bearer $tok" -H "Content-Type: application/json" \
      "$KC$ruta" -d "$cuerpo"
  else
    curl -s -o /tmp/kcspike-resp.json -w "HTTP %{http_code}\n" -X "$metodo" \
      -H "Authorization: Bearer $tok" -H "Content-Type: application/json" "$KC$ruta"
  fi
  [[ -s /tmp/kcspike-resp.json ]] && cat /tmp/kcspike-resp.json && echo
  return 0
}

get() { curl -s -H "Authorization: Bearer $(adm)" "$KC$1"; }

# Decodifica el access_token de una respuesta de /token y muestra los claims que importan.
cat > /tmp/kcspike-dec.py <<'PY'
import sys, json, base64
raw = sys.stdin.read()
try:
    t = json.loads(raw)
except Exception:
    print("RESPUESTA NO JSON:", raw[:300]); raise SystemExit
if "access_token" not in t:
    print("SIN TOKEN →", json.dumps(t, ensure_ascii=False)); raise SystemExit
p = t["access_token"].split(".")[1]; p += "=" * (-len(p) % 4)
c = json.loads(base64.urlsafe_b64decode(p))
print(json.dumps(
    {k: c.get(k) for k in ("iss", "azp", "preferred_username", "scope", "organization", "acr")},
    indent=2, ensure_ascii=False))
PY

token() {   # token USUARIO SCOPE
  curl -s "$KC/realms/$REALM/protocol/openid-connect/token" \
    -d grant_type=password -d client_id=vendi-web -d "username=$1" -d password=spike \
    --data-urlencode "scope=$2" | python3 /tmp/kcspike-dec.py
}

# ---------------------------------------------------------------------
titulo "P0. Keycloak $KC_IMG efímero"
docker rm -f "$CONT" >/dev/null 2>&1 || true
docker run -d --name "$CONT" -p "${PORT}:8080" \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  "$KC_IMG" start-dev >/dev/null
echo "Esperando a Keycloak en $KC ..."
for _ in $(seq 1 120); do curl -sf "$KC/realms/master" >/dev/null && break; sleep 2; done
curl -sf "$KC/realms/master" >/dev/null || { echo "Keycloak no arrancó"; exit 1; }
echo "Keycloak arriba."

# ---------------------------------------------------------------------
titulo "P1 · PREGUNTA 8 — ¿Hace falta un feature flag de arranque para Organizations?"
get /admin/serverinfo | python3 -c '
import sys,json
d=json.load(sys.stdin)
print("versión del servidor:", d["systemInfo"]["version"])
for f in d.get("features", []):
    if f["name"] == "ORGANIZATION":
        print("feature ORGANIZATION:", json.dumps(f, ensure_ascii=False))'

# ---------------------------------------------------------------------
titulo "P2. Realm regional y cliente público PKCE"
sub "crear realm $REALM con organizationsEnabled=true"
api POST /admin/realms "{\"realm\":\"$REALM\",\"enabled\":true,\"organizationsEnabled\":true,
  \"bruteForceProtected\":true,\"defaultLocale\":\"es\",\"internationalizationEnabled\":true,
  \"supportedLocales\":[\"es\"]}"

sub "crear cliente vendi-web (público, PKCE S256, direct grant para el spike)"
api POST "/admin/realms/$REALM/clients" '{"clientId":"vendi-web","publicClient":true,
  "standardFlowEnabled":true,"directAccessGrantsEnabled":true,
  "redirectUris":["*"],"webOrigins":["*"],
  "attributes":{"pkce.code.challenge.method":"S256"}}'

CID="$(get "/admin/realms/$REALM/clients?clientId=vendi-web" | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["id"])')"
echo "id interno de vendi-web: $CID"

# ---------------------------------------------------------------------
titulo "P3 · PREGUNTA 2 (parte 1) — ¿El scope 'organization' es default u opcional?"
sub "client scope 'organization' del realm (definición y mapper)"
get "/admin/realms/$REALM/client-scopes" | python3 -c '
import sys,json
for s in json.load(sys.stdin):
    if s["name"]=="organization" and s["protocol"]=="openid-connect":
        print(json.dumps(s, indent=2, ensure_ascii=False))'
sub "default-client-scopes de vendi-web"
get "/admin/realms/$REALM/clients/$CID/default-client-scopes" | python3 -c 'import sys,json;[print(" ",s["name"]) for s in json.load(sys.stdin)]'
sub "optional-client-scopes de vendi-web"
get "/admin/realms/$REALM/clients/$CID/optional-client-scopes" | python3 -c 'import sys,json;[print(" ",s["name"]) for s in json.load(sys.stdin)]'

SCID="$(get "/admin/realms/$REALM/client-scopes" | python3 -c '
import sys,json
print([s["id"] for s in json.load(sys.stdin) if s["name"]=="organization" and s["protocol"]=="openid-connect"][0])')"
MID="$(get "/admin/realms/$REALM/client-scopes/$SCID/protocol-mappers/models" | python3 -c '
import sys,json
print([m["id"] for m in json.load(sys.stdin) if m["protocolMapper"]=="oidc-organization-membership-mapper"][0])')"
echo "client-scope organization=$SCID · mapper=$MID"

sub "propiedades configurables del mapper (nombres exactos de las opciones)"
get /admin/serverinfo | python3 -c '
import sys,json
d=json.load(sys.stdin)
for m in d["protocolMapperTypes"]["openid-connect"]:
    if m["id"]=="oidc-organization-membership-mapper":
        print([p["name"]+"="+str(p.get("defaultValue")) for p in m["properties"]])'

# ---------------------------------------------------------------------
titulo "P4 · PREGUNTAS 4 y 5 — alias en formato UUID, dominio sintético, duplicados"
sub "org 1: alias = tenant_id ($T1) + dominio sintético"
api POST "/admin/realms/$REALM/organizations" \
  "{\"name\":\"Tienda Don Carlos\",\"alias\":\"$T1\",
    \"domains\":[{\"name\":\"$T1.tenants.vendi.co\",\"verified\":true}]}"

sub "¿es OBLIGATORIO el dominio? (crear una org sin 'domains')"
api POST "/admin/realms/$REALM/organizations" \
  '{"name":"Prueba Sin Dominio","alias":"aaaaaaaa-0000-0000-0000-00000000000a"}'

sub "alias DUPLICADO (debe fallar)"
api POST "/admin/realms/$REALM/organizations" \
  "{\"name\":\"Duplicada\",\"alias\":\"$T1\",\"domains\":[{\"name\":\"otro.tenants.vendi.co\"}]}"

sub "dominio DUPLICADO (debe fallar)"
api POST "/admin/realms/$REALM/organizations" \
  "{\"name\":\"Duplicada2\",\"alias\":\"bbbbbbbb-0000-0000-0000-00000000000b\",
    \"domains\":[{\"name\":\"$T1.tenants.vendi.co\"}]}"

sub "borrar la org de prueba sin dominio"
ORG_SIN_DOM="$(get "/admin/realms/$REALM/organizations" | python3 -c '
import sys,json
print([o["id"] for o in json.load(sys.stdin) if o["alias"].startswith("aaaaaaaa")][0])')"
api DELETE "/admin/realms/$REALM/organizations/$ORG_SIN_DOM"

ORG1="$(get "/admin/realms/$REALM/organizations" | python3 -c "
import sys,json
print([o['id'] for o in json.load(sys.stdin) if o['alias']=='$T1'][0])")"
echo "ORG1=$ORG1"

# ---------------------------------------------------------------------
titulo "P5. Usuarios y membresías"
echo "HALLAZGO: sin firstName/lastName el realm exige VERIFY_PROFILE y el login"
echo "falla con 'Account is not fully set up'. VendiKeycloakAdmin.create_user()"
echo "debe enviarlos siempre."
for U in cajera1 sinorg; do
  sub "crear usuario $U"
  api POST "/admin/realms/$REALM/users" \
    "{\"username\":\"$U\",\"enabled\":true,\"firstName\":\"Nombre\",\"lastName\":\"Apellido\",
      \"email\":\"$U@vendi.co\",\"emailVerified\":true,
      \"credentials\":[{\"type\":\"password\",\"value\":\"spike\",\"temporary\":false}]}"
done
U1="$(get "/admin/realms/$REALM/users?username=cajera1&exact=true" | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["id"])')"
echo "cajera1 = $U1"

sub "añadir cajera1 a la org 1 (cuerpo = string JSON con el id de usuario)"
api POST "/admin/realms/$REALM/organizations/$ORG1/members" "\"$U1\""
sub "miembros de la org 1"
get "/admin/realms/$REALM/organizations/$ORG1/members" | python3 -c 'import sys,json;[print(" ",m["username"]) for m in json.load(sys.stdin)]'

# ---------------------------------------------------------------------
titulo "P6 · PREGUNTAS 1 y 2 — shape del claim por defecto y sin pedir el scope"
sub "token SIN pedir el scope organization (scope=openid)"
token cajera1 "openid"
sub "token CON scope=organization — shape POR DEFECTO del claim"
token cajera1 "openid organization"

# ---------------------------------------------------------------------
titulo "P7 · PREGUNTA 7 — activar 'Add organization id' en el mapper"
get "/admin/realms/$REALM/client-scopes/$SCID/protocol-mappers/models/$MID" > /tmp/kcspike-mapper.json
python3 - <<'PY'
import json
m = json.load(open("/tmp/kcspike-mapper.json"))
m["config"]["addOrganizationId"] = "true"
json.dump(m, open("/tmp/kcspike-mapper-id.json", "w"))
print("config del mapper tras el cambio:", json.dumps(m["config"], indent=2))
PY
curl -s -o /dev/null -w "PUT mapper HTTP %{http_code}\n" -X PUT -H "Authorization: Bearer $(adm)" \
  -H "Content-Type: application/json" \
  "$KC/admin/realms/$REALM/client-scopes/$SCID/protocol-mappers/models/$MID" \
  --data @/tmp/kcspike-mapper-id.json
sub "token con addOrganizationId=true — shape de MAPA alias → {id}"
token cajera1 "openid organization"

sub "addOrganizationAttributes=true (extra: ¿aporta algo con org sin atributos?)"
python3 - <<'PY'
import json
m = json.load(open("/tmp/kcspike-mapper-id.json"))
m["config"]["addOrganizationAttributes"] = "true"
json.dump(m, open("/tmp/kcspike-mapper-attrs.json", "w"))
PY
curl -s -o /dev/null -w "PUT mapper HTTP %{http_code}\n" -X PUT -H "Authorization: Bearer $(adm)" \
  -H "Content-Type: application/json" \
  "$KC/admin/realms/$REALM/client-scopes/$SCID/protocol-mappers/models/$MID" \
  --data @/tmp/kcspike-mapper-attrs.json
token cajera1 "openid organization"
curl -s -o /dev/null -w "volver a solo addOrganizationId HTTP %{http_code}\n" -X PUT \
  -H "Authorization: Bearer $(adm)" -H "Content-Type: application/json" \
  "$KC/admin/realms/$REALM/client-scopes/$SCID/protocol-mappers/models/$MID" \
  --data @/tmp/kcspike-mapper-id.json

# ---------------------------------------------------------------------
titulo "P8 · PREGUNTA 2 (decisión) — 'organization' como DEFAULT client scope"
api DELETE "/admin/realms/$REALM/clients/$CID/optional-client-scopes/$SCID"
api PUT    "/admin/realms/$REALM/clients/$CID/default-client-scopes/$SCID"
sub "token pidiendo SOLO 'openid': el claim ya viaja sin cooperación del frontend"
token cajera1 "openid"

# ---------------------------------------------------------------------
titulo "P9 · PREGUNTA 3 — usuario en DOS organizaciones"
sub "crear org 2 (alias = $T2) y añadir a cajera1"
api POST "/admin/realms/$REALM/organizations" \
  "{\"name\":\"Minimercado Andrea\",\"alias\":\"$T2\",
    \"domains\":[{\"name\":\"$T2.tenants.vendi.co\",\"verified\":true}]}"
ORG2="$(get "/admin/realms/$REALM/organizations" | python3 -c "
import sys,json
print([o['id'] for o in json.load(sys.stdin) if o['alias']=='$T2'][0])")"
api POST "/admin/realms/$REALM/organizations/$ORG2/members" "\"$U1\""

sub "scope=openid (organization es DEFAULT) — ¡CLAIM AUSENTE con 2 orgs!"
token cajera1 "openid"
sub "scope=openid organization — mismo resultado: claim ausente"
token cajera1 "openid organization"
sub "scope=openid organization:*  — TODAS las organizaciones"
token cajera1 "openid organization:*"
sub "scope=openid organization:<alias concreto> — solo esa"
token cajera1 "openid organization:$T2"
sub "scope=openid organization:<alias inexistente>"
token cajera1 "openid organization:99999999-9999-9999-9999-999999999999"

# ---------------------------------------------------------------------
titulo "P10 · QA — usuario en CERO organizaciones"
sub "sinorg · scope=openid organization"
token sinorg "openid organization"
sub "sinorg · scope=openid organization:*"
token sinorg "openid organization:*"

# ---------------------------------------------------------------------
titulo "P11 · QA — ¿sobrevive el claim al refresh_token?"
RESP="$(curl -s "$KC/realms/$REALM/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=vendi-web -d username=cajera1 -d password=spike \
  --data-urlencode "scope=openid organization:*")"
echo "$RESP" > /tmp/kcspike-tok.json
sub "access_token inicial"
python3 /tmp/kcspike-dec.py < /tmp/kcspike-tok.json
RT="$(python3 -c 'import json;print(json.load(open("/tmp/kcspike-tok.json"))["refresh_token"])')"
sub "tras grant_type=refresh_token SIN reenviar el scope"
curl -s "$KC/realms/$REALM/protocol/openid-connect/token" \
  -d grant_type=refresh_token -d client_id=vendi-web -d "refresh_token=$RT" \
  | python3 /tmp/kcspike-dec.py

# ---------------------------------------------------------------------
titulo "P12 · QA — 'organization:*' cuando el scope NO está asignado al cliente"
api DELETE "/admin/realms/$REALM/clients/$CID/default-client-scopes/$SCID"
token cajera1 "openid organization:*"
api PUT "/admin/realms/$REALM/clients/$CID/default-client-scopes/$SCID"

# ---------------------------------------------------------------------
titulo "P13 · PREGUNTA 6 — ¿deshabilitar una organización bloquea el login?"
get "/admin/realms/$REALM/organizations/$ORG2" > /tmp/kcspike-org2.json
python3 -c 'import json;o=json.load(open("/tmp/kcspike-org2.json"));o["enabled"]=False;json.dump(o,open("/tmp/kcspike-org2-off.json","w"))'
curl -s -o /dev/null -w "deshabilitar org2 HTTP %{http_code}\n" -X PUT -H "Authorization: Bearer $(adm)" \
  -H "Content-Type: application/json" "$KC/admin/realms/$REALM/organizations/$ORG2" \
  --data @/tmp/kcspike-org2-off.json
sub "cajera1 (org1 activa + org2 deshabilitada)"
token cajera1 "openid organization:*"

sub "usuario cuya ÚNICA organización está deshabilitada"
api POST "/admin/realms/$REALM/users" \
  '{"username":"solodeshab","enabled":true,"firstName":"Nombre","lastName":"Apellido",
    "email":"solodeshab@vendi.co","emailVerified":true,
    "credentials":[{"type":"password","value":"spike","temporary":false}]}'
U3="$(get "/admin/realms/$REALM/users?username=solodeshab&exact=true" | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["id"])')"
api POST "/admin/realms/$REALM/organizations/$ORG2/members" "\"$U3\""
token solodeshab "openid organization:*"
sub "reactivar org2"
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X PUT -H "Authorization: Bearer $(adm)" \
  -H "Content-Type: application/json" "$KC/admin/realms/$REALM/organizations/$ORG2" \
  --data @/tmp/kcspike-org2.json

# ---------------------------------------------------------------------
titulo "P14 · PREGUNTA 9 — login identity-first y flujo PKCE de navegador"
sub "realm de control SIN organizations, para comparar la pantalla de login"
api POST /admin/realms '{"realm":"control-sin-orgs","enabled":true,"organizationsEnabled":false}'
api POST /admin/realms/control-sin-orgs/clients \
  '{"clientId":"vendi-web","publicClient":true,"standardFlowEnabled":true,"redirectUris":["*"],"webOrigins":["*"]}'

VER="$(python3 -c 'print("a"*64)')"
CH="$(python3 -c '
import base64,hashlib
print(base64.urlsafe_b64encode(hashlib.sha256(("a"*64).encode()).digest()).rstrip(b"=").decode())')"

sub "campos de la PRIMERA pantalla — realm control-sin-orgs"
curl -s "$KC/realms/control-sin-orgs/protocol/openid-connect/auth?client_id=vendi-web&response_type=code&scope=openid&redirect_uri=http://localhost/cb" \
  | grep -oE 'name="(username|password|login)"' | sort -u

sub "campos de la PRIMERA pantalla — realm $REALM (organizations ON)"
rm -f /tmp/kcspike-ck.txt
AUTH="$KC/realms/$REALM/protocol/openid-connect/auth?client_id=vendi-web&response_type=code&scope=openid+organization:*&redirect_uri=http://localhost/cb&code_challenge=$CH&code_challenge_method=S256"
curl -s -c /tmp/kcspike-ck.txt -o /tmp/kcspike-p1.html "$AUTH"
grep -oE 'name="(username|password|login)"' /tmp/kcspike-p1.html | sort -u

sub "PKCE obligatorio: la misma petición sin code_challenge"
curl -s -o /dev/null -D - "$KC/realms/$REALM/protocol/openid-connect/auth?client_id=vendi-web&response_type=code&scope=openid&redirect_uri=http://localhost/cb" \
  | grep -i '^location:' | tr -d '\r'

sub "completar el flujo: usuario → contraseña → code → token"
ACT1="$(python3 -c '
import re,html
h=open("/tmp/kcspike-p1.html").read()
m=re.search(r"action=\"([^\"]+)\"", h); print(html.unescape(m.group(1)))')"
curl -s -b /tmp/kcspike-ck.txt -c /tmp/kcspike-ck.txt -o /tmp/kcspike-p2.html \
  -d "username=cajera1" -d "login=Sign+In" "$ACT1"
echo "campos de la SEGUNDA pantalla:"
grep -oE 'name="(username|password|login)"' /tmp/kcspike-p2.html | sort -u
ACT2="$(python3 -c '
import re,html
h=open("/tmp/kcspike-p2.html").read()
m=re.search(r"action=\"([^\"]+)\"", h); print(html.unescape(m.group(1)))')"
LOC="$(curl -s -b /tmp/kcspike-ck.txt -c /tmp/kcspike-ck.txt -o /dev/null -D - \
  -d "password=spike" -d "credentialId=" "$ACT2" | grep -i '^location:' | tr -d '\r')"
CODE="$(echo "$LOC" | grep -oE 'code=[^&]+' | cut -d= -f2)"
echo "code recibido: ${CODE:0:24}..."
curl -s "$KC/realms/$REALM/protocol/openid-connect/token" \
  -d grant_type=authorization_code -d client_id=vendi-web -d "code=$CODE" \
  -d "redirect_uri=http://localhost/cb" -d "code_verifier=$VER" \
  | python3 /tmp/kcspike-dec.py

# ---------------------------------------------------------------------
titulo "P15 · PREGUNTA 10 — WebAuthn Passwordless (passkeys) junto a Organizations"
sub "política WebAuthn Passwordless del realm"
get "/admin/realms/$REALM" > /tmp/kcspike-realm.json
python3 - <<'PY'
import json
r = json.load(open("/tmp/kcspike-realm.json"))
r.update({
    "webAuthnPolicyPasswordlessRpEntityName": "Vendi",
    "webAuthnPolicyPasswordlessRpId": "",          # vacío = host de la petición
    "webAuthnPolicyPasswordlessSignatureAlgorithms": ["ES256", "RS256"],
    "webAuthnPolicyPasswordlessRequireResidentKey": "Yes",
    "webAuthnPolicyPasswordlessUserVerificationRequirement": "required",
    "webAuthnPolicyPasswordlessAttestationConveyancePreference": "none",
    "webAuthnPolicyPasswordlessCreateTimeout": 60,
})
json.dump(r, open("/tmp/kcspike-realm-wa.json", "w"))
print(json.dumps({k: v for k, v in r.items() if k.startswith("webAuthnPolicyPasswordless")}, indent=2))
PY
curl -s -o /dev/null -w "PUT policy HTTP %{http_code}\n" -X PUT -H "Authorization: Bearer $(adm)" \
  -H "Content-Type: application/json" "$KC/admin/realms/$REALM" --data @/tmp/kcspike-realm-wa.json

sub "required actions de webauthn (¿vienen habilitadas de fábrica?)"
get "/admin/realms/$REALM/authentication/required-actions" | python3 -c '
import sys,json
for a in json.load(sys.stdin):
    if "webauthn" in a["alias"]: print(" ", a["alias"], "enabled=", a["enabled"], "default=", a["defaultAction"])'

sub "flujo browser de fábrica: ya trae el subflujo de Organizations (identity-first)"
get "/admin/realms/$REALM/authentication/flows/browser/executions" | python3 -c '
import sys,json
for e in json.load(sys.stdin):
    print(" " + "  "*e["level"], e["displayName"], "|", e["requirement"])'

sub "construir el flujo browser-passwordless (passkey con fallback a contraseña)"
api POST "/admin/realms/$REALM/authentication/flows/browser/copy" '{"newName":"browser-passwordless"}'
EX_UPF="$(get "/admin/realms/$REALM/authentication/flows/browser-passwordless/executions" | python3 -c '
import sys,json
print([e["id"] for e in json.load(sys.stdin) if e.get("providerId")=="auth-username-password-form"][0])')"
api DELETE "/admin/realms/$REALM/authentication/executions/$EX_UPF"
api POST "/admin/realms/$REALM/authentication/flows/browser-passwordless%20forms/executions/execution" \
  '{"provider":"auth-username-form"}'
api POST "/admin/realms/$REALM/authentication/flows/browser-passwordless%20forms/executions/flow" \
  '{"alias":"passkey-o-password","type":"basic-flow","provider":"registration-page-form","description":"Passkey si la tiene; contrasena si no"}'
api POST "/admin/realms/$REALM/authentication/flows/passkey-o-password/executions/execution" \
  '{"provider":"webauthn-authenticator-passwordless"}'
api POST "/admin/realms/$REALM/authentication/flows/passkey-o-password/executions/execution" \
  '{"provider":"auth-password-form"}'

get "/admin/realms/$REALM/authentication/flows/browser-passwordless/executions" > /tmp/kcspike-ex.json
ID_SUB="$(python3 -c 'import json;print([e["id"] for e in json.load(open("/tmp/kcspike-ex.json")) if e["displayName"]=="passkey-o-password"][0])')"
ID_WA="$(python3  -c 'import json;print([e["id"] for e in json.load(open("/tmp/kcspike-ex.json")) if e.get("providerId")=="webauthn-authenticator-passwordless"][0])')"
ID_PW="$(python3  -c 'import json;print([e["id"] for e in json.load(open("/tmp/kcspike-ex.json")) if e.get("providerId")=="auth-password-form"][0])')"
ID_UF="$(python3  -c 'import json;print([e["id"] for e in json.load(open("/tmp/kcspike-ex.json")) if e.get("providerId")=="auth-username-form"][0])')"
for par in "$ID_SUB:REQUIRED" "$ID_WA:ALTERNATIVE" "$ID_PW:ALTERNATIVE" "$ID_UF:REQUIRED"; do
  api PUT "/admin/realms/$REALM/authentication/flows/browser-passwordless/executions" \
    "{\"id\":\"${par%%:*}\",\"requirement\":\"${par##*:}\"}" >/dev/null
done
# Username Form debe ir antes que el subflujo passkey-o-password.
api POST "/admin/realms/$REALM/authentication/executions/$ID_UF/raise-priority" >/dev/null
api POST "/admin/realms/$REALM/authentication/executions/$ID_UF/raise-priority" >/dev/null
echo "estructura final del flujo:"
get "/admin/realms/$REALM/authentication/flows/browser-passwordless/executions" | python3 -c '
import sys,json
for e in json.load(sys.stdin):
    print(" " + "  "*e["level"], e["displayName"], "|", e["requirement"])'

sub "vincular browser-passwordless como browserFlow del realm"
get "/admin/realms/$REALM" > /tmp/kcspike-realm.json
python3 -c 'import json;r=json.load(open("/tmp/kcspike-realm.json"));r["browserFlow"]="browser-passwordless";json.dump(r,open("/tmp/kcspike-realm-bf.json","w"))'
curl -s -o /dev/null -w "PUT browserFlow HTTP %{http_code}\n" -X PUT -H "Authorization: Bearer $(adm)" \
  -H "Content-Type: application/json" "$KC/admin/realms/$REALM" --data @/tmp/kcspike-realm-bf.json

sub "fallback verificado por HTTP: usuario SIN passkey sigue pudiendo entrar con contraseña"
rm -f /tmp/kcspike-ck2.txt
curl -s -c /tmp/kcspike-ck2.txt -o /tmp/kcspike-q1.html "$AUTH"
echo "pantalla 1: $(grep -oE 'name="(username|password|login)"' /tmp/kcspike-q1.html | sort -u | tr '\n' ' ')"
A1="$(python3 -c '
import re,html
h=open("/tmp/kcspike-q1.html").read()
m=re.search(r"action=\"([^\"]+)\"", h); print(html.unescape(m.group(1)))')"
curl -s -b /tmp/kcspike-ck2.txt -c /tmp/kcspike-ck2.txt -o /tmp/kcspike-q2.html \
  -d "username=sinorg" -d "login=Sign+In" "$A1"
echo "pantalla 2: $(grep -oE 'name="(username|password|login)"' /tmp/kcspike-q2.html | sort -u | tr '\n' ' ')"

sub "pedir la passkey a cajera1 en el próximo login (required action)"
get "/admin/realms/$REALM/users/$U1" > /tmp/kcspike-u1.json
python3 -c 'import json;u=json.load(open("/tmp/kcspike-u1.json"));u["requiredActions"]=["webauthn-register-passwordless"];json.dump(u,open("/tmp/kcspike-u1b.json","w"))'
curl -s -o /dev/null -w "PUT requiredActions HTTP %{http_code}\n" -X PUT -H "Authorization: Bearer $(adm)" \
  -H "Content-Type: application/json" "$KC/admin/realms/$REALM/users/$U1" --data @/tmp/kcspike-u1b.json

# ---------------------------------------------------------------------
titulo "Spike listo"
cat <<EOF
El realm '$REALM' queda configurado como lo dejará infra/keycloak/realm-vendi-co.json:
  · organizationsEnabled=true, brute force ON, locale es
  · organization como DEFAULT client scope de vendi-web, con addOrganizationId=true
  · organizaciones: $T1 (Tienda Don Carlos) y $T2 (Minimercado Andrea)
  · usuarios: cajera1/spike (2 orgs, con required action de passkey pendiente),
              sinorg/spike (0 orgs), solodeshab/spike (1 org)
  · flujo browser-passwordless vinculado, con fallback a contraseña

Registro y login con passkey (pregunta 10) — necesita un autenticador WebAuthn:
  node scripts/spikes/kc-passkey-spike.mjs

Consola: $KC (admin/admin) · borrar: docker rm -f $CONT
EOF

if [[ "${SPIKE_MANTENER:-1}" != "1" ]]; then
  docker rm -f "$CONT" >/dev/null
  echo "Contenedor '$CONT' eliminado (SPIKE_MANTENER=0)."
fi
