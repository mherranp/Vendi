#!/usr/bin/env python3
"""Detecta deriva entre `infra/keycloak/realm-vendi-co.json` y el realm vivo.

Lo usa `scripts/reconcile-keycloak.sh`. Compara solo lo que Vendi declara —no
todo el realm—, porque el JSON exportado trae cientos de valores por defecto
que Keycloak recalcula y que compararlos produciría ruido permanente.

Qué compara, y por qué justo esto:

* **Clientes de Vendi** (`vendi-web`, `vendi-admin`, `vendi-backend`): que
  existan y que no hayan cambiado los interruptores con consecuencias de
  seguridad — público/confidencial, ROPC, flujo estándar, cuenta de servicio,
  redirect URIs, orígenes web, PKCE y los client scopes por defecto (ahí vive
  el claim `organization`).
* **Roles de la cuenta de servicio** de `vendi-backend`: un rol de más aquí es
  una escalada de privilegios silenciosa.
* **Flujos de autenticación** declarados y sus enlaces (`browserFlow`, ...):
  es donde vive el login con passkey.
* **Ajustes de realm** que sostienen decisiones de diseño:
  `organizationsEnabled`, `loginTheme`, `bruteForceProtected`, `defaultLocale`
  y la policy de WebAuthn passwordless.

Salida: líneas legibles. Código de salida 0 si no hay deriva, 2 si la hay.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

AZUL = "\033[0;34m"
VERDE = "\033[0;32m"
AMARILLO = "\033[1;33m"
NC = "\033[0m"

KC = os.environ["KC_URL_BASE"].rstrip("/")
TOKEN = os.environ["KC_TOKEN"]
REALM = os.environ.get("KC_REALM", "vendi-co")
RUTA_JSON = os.environ["REALM_JSON"]

# Clientes que crea Keycloak solo: no se comparan (los recalcula el servidor).
CLIENTES_INTERNOS = {
    "account",
    "account-console",
    "admin-cli",
    "broker",
    "realm-management",
    "security-admin-console",
}

# Ajustes de realm cuyo valor sostiene una decisión del diseño.
AJUSTES_REALM = [
    "organizationsEnabled",
    "loginTheme",
    "bruteForceProtected",
    "defaultLocale",
    "sslRequired",
    "registrationAllowed",
    "browserFlow",
    "directGrantFlow",
    "webAuthnPolicyPasswordlessRpId",
    "webAuthnPolicyPasswordlessUserVerificationRequirement",
    "webAuthnPolicyPasswordlessRequireResidentKey",
]

# Campos de cliente que importan. `attributes` se compara por claves elegidas.
CAMPOS_CLIENTE = [
    "publicClient",
    "standardFlowEnabled",
    "directAccessGrantsEnabled",
    "serviceAccountsEnabled",
    "implicitFlowEnabled",
    "enabled",
]
ATRIBUTOS_CLIENTE = ["pkce.code.challenge.method", "post.logout.redirect.uris"]

hallazgos: list[str] = []


def obtener(ruta: str):
    peticion = urllib.request.Request(
        f"{KC}/admin/realms/{REALM}{ruta}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            return json.load(respuesta)
    except urllib.error.HTTPError as e:
        hallazgos.append(f"la Admin API devolvió {e.code} en {ruta}")
        return None


def compara(etiqueta: str, esperado, real) -> None:
    if isinstance(esperado, list) and isinstance(real, list):
        if sorted(map(str, esperado)) != sorted(map(str, real)):
            faltan = sorted(set(map(str, esperado)) - set(map(str, real)))
            sobran = sorted(set(map(str, real)) - set(map(str, esperado)))
            detalle = []
            if faltan:
                detalle.append(f"faltan {faltan}")
            if sobran:
                detalle.append(f"sobran {sobran}")
            hallazgos.append(f"{etiqueta}: " + " · ".join(detalle))
        return
    if esperado != real:
        hallazgos.append(f"{etiqueta}: el JSON dice {esperado!r} y el realm vivo tiene {real!r}")


with open(RUTA_JSON, encoding="utf-8") as f:
    crudo = f.read()

# El JSON lleva placeholders que Keycloak sustituye AL IMPORTAR (con
# KC_SPI_IMPORT_SINGLE_FILE_REPLACE_PLACEHOLDERS=true). Si no se sustituyen aquí
# también, cada redirect URI se reporta como deriva y el informe se vuelve ruido
# que nadie lee.
for marcador, variable, defecto in (
    ("${VENDI_BASE_DOMAIN}", "BASE_DOMAIN", "vendi.co"),
    ("${VENDI_BACKEND_CLIENT_SECRET}", "VENDI_BACKEND_CLIENT_SECRET", ""),
):
    crudo = crudo.replace(marcador, os.environ.get(variable) or defecto)

deseado = json.loads(crudo)

print(f"{AZUL}[INFO]{NC}  comparando realm '{REALM}' contra {os.path.basename(RUTA_JSON)}")

# --- 1. Ajustes del realm ---------------------------------------------------
vivo = obtener("")
if vivo is not None:
    for clave in AJUSTES_REALM:
        if clave in deseado:
            compara(f"realm.{clave}", deseado[clave], vivo.get(clave))

# --- 2. Clientes ------------------------------------------------------------
clientes_vivos = obtener("/clients") or []
por_id = {c.get("clientId"): c for c in clientes_vivos}

for cliente in deseado.get("clients", []):
    cid = cliente.get("clientId")
    if cid in CLIENTES_INTERNOS:
        continue
    real = por_id.get(cid)
    if real is None:
        hallazgos.append(f"cliente '{cid}': declarado en el JSON y AUSENTE del realm")
        continue
    for campo in CAMPOS_CLIENTE:
        if campo in cliente:
            compara(f"cliente '{cid}'.{campo}", cliente[campo], real.get(campo))
    for lista in ("redirectUris", "webOrigins", "defaultClientScopes", "optionalClientScopes"):
        if lista in cliente:
            compara(f"cliente '{cid}'.{lista}", cliente[lista], real.get(lista, []))
    atributos_deseados = cliente.get("attributes", {})
    atributos_reales = real.get("attributes", {})
    for atributo in ATRIBUTOS_CLIENTE:
        if atributo in atributos_deseados:
            compara(
                f"cliente '{cid}'.attributes[{atributo}]",
                atributos_deseados[atributo],
                atributos_reales.get(atributo),
            )

# Clientes que NO están en el JSON y sí en el realm: alguien los creó a mano.
declarados = {c.get("clientId") for c in deseado.get("clients", [])} | CLIENTES_INTERNOS
for cid in sorted(set(por_id) - declarados):
    hallazgos.append(f"cliente '{cid}': existe en el realm y NO está en el JSON (creado a mano)")

# --- 3. Roles de la cuenta de servicio de vendi-backend ---------------------
# Un rol de más aquí no es un detalle de configuración: es una escalada de
# privilegios que no aparece en ninguna revisión de código.
for usuario in deseado.get("users", []):
    cliente_sa = usuario.get("serviceAccountClientId")
    if not cliente_sa:
        continue
    real_cliente = por_id.get(cliente_sa)
    if real_cliente is None:
        continue
    sa = obtener(f"/clients/{real_cliente['id']}/service-account-user")
    if not sa:
        continue
    for nombre_cliente_rol, roles_deseados in usuario.get("clientRoles", {}).items():
        cliente_rol = por_id.get(nombre_cliente_rol)
        if cliente_rol is None:
            continue
        asignados = obtener(f"/users/{sa['id']}/role-mappings/clients/{cliente_rol['id']}") or []
        compara(
            f"cuenta de servicio de '{cliente_sa}' · roles de {nombre_cliente_rol}",
            roles_deseados,
            [r.get("name") for r in asignados],
        )

# --- 4. Flujos de autenticación --------------------------------------------
# GET /authentication/flows devuelve SOLO los flujos de primer nivel; los
# subflujos aparecen dentro de las ejecuciones del flujo que los contiene. Por
# eso los subflujos NO se buscan en esa lista (hacerlo daba veinte falsos
# positivos: 'forms', 'Organization', 'passkey-o-password'...), sino dentro del
# árbol de ejecuciones de su flujo raíz.
flujos_json = {f.get("alias"): f for f in deseado.get("authenticationFlows", [])}
flujos_vivos = obtener("/authentication/flows") or []
alias_vivos = {f.get("alias") for f in flujos_vivos}


def piezas_declaradas(alias: str, vistos: set[str] | None = None) -> set[str]:
    """Nombres (autenticador o alias de subflujo) del árbol declarado en el JSON."""
    vistos = vistos or set()
    if alias in vistos or alias not in flujos_json:
        return set()
    vistos.add(alias)
    nombres: set[str] = set()
    for ejecucion in flujos_json[alias].get("authenticationExecutions", []):
        subflujo = ejecucion.get("flowAlias")
        if subflujo:
            nombres.add(subflujo)
            nombres |= piezas_declaradas(subflujo, vistos)
        elif ejecucion.get("authenticator"):
            nombres.add(ejecucion["authenticator"])
    return nombres


# Flujos que el realm ENLAZA (los que se ejecutan de verdad) + los que no son
# built-in (los que escribió Vendi). Un flujo built-in y sin enlazar —el caso de
# 'saml ecp', que la importación ni siquiera crea— no se compara: reportarlo
# sería ruido sobre algo que Vendi no usa.
ENLACES = (
    "browserFlow",
    "directGrantFlow",
    "registrationFlow",
    "resetCredentialsFlow",
    "clientAuthenticationFlow",
    "dockerAuthenticationFlow",
    "firstBrokerLoginFlow",
)
flujos_enlazados = {deseado.get(e) for e in ENLACES if deseado.get(e)}

for alias, flujo in flujos_json.items():
    if not flujo.get("topLevel", False):
        continue
    if flujo.get("builtIn", False) and alias not in flujos_enlazados:
        continue
    if alias not in alias_vivos:
        hallazgos.append(f"flujo de autenticación '{alias}': declarado en el JSON y AUSENTE del realm")
        continue
    ejecuciones = obtener(f"/authentication/flows/{urllib.parse.quote(alias, safe='')}/executions")
    if ejecuciones is None:
        continue
    presentes = set()
    for e in ejecuciones:
        if e.get("providerId"):
            presentes.add(e["providerId"])
        if e.get("displayName"):
            presentes.add(e["displayName"])
    faltan = sorted(piezas_declaradas(alias) - presentes)
    if faltan:
        hallazgos.append(f"flujo '{alias}': le faltan pasos declarados en el JSON: {faltan}")

# --- Resultado --------------------------------------------------------------
if not hallazgos:
    print(f"{VERDE}[OK]{NC}    sin deriva de configuración: clientes, flujos, roles de servicio y ajustes cuadran")
    sys.exit(0)

print(f"{AMARILLO}[AVISO]{NC} deriva de configuración ({len(hallazgos)} hallazgo(s)):")
for h in hallazgos:
    print(f"    - {h}")
print(f"{AMARILLO}[AVISO]{NC} corrección: aplica el cambio con kcadm y refléjalo en el JSON, o")
print("          reimporta el realm desde cero (docker compose down -v, y pierdes usuarios).")
sys.exit(2)
