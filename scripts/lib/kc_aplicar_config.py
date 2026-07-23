#!/usr/bin/env python3
"""Aplica al realm vivo la parte de `realm-vendi-co.json` que se puede aplicar.

Lo usa `scripts/reconcile-keycloak.sh` con `RECONCILE_APLICAR_CONFIG=1`. Es la
otra mitad de `kc_deriva_config.py`: aquél **detecta** la deriva, éste la
**corrige**, y solo en el subconjunto donde corregir no puede tirar sesiones ni
credenciales.

## Por qué existe

`--import-realm` importa el realm SOLO si no existe (medido en 26.6.4:
`Realm 'vendi-co' already exists. Import skipped`). Sin este script, cada cambio
del JSON había que aplicarlo a mano contra la Admin API, cliente por cliente,
preservando el resto del objeto para no pisar los secretos — que es exactamente
lo que ocurrió en el renombrado de `vendi.local` a `vendi.co` y lo que dejó
anotado la deuda D-03.

## Qué aplica, y por qué justo esto

1. **Interruptores de cliente con consecuencias de seguridad**
   (`publicClient`, `standardFlowEnabled`, `directAccessGrantsEnabled`,
   `serviceAccountsEnabled`, `implicitFlowEnabled`, `enabled`) más
   `redirectUris` y `webOrigins`. Son idempotentes y no invalidan nada: cambiar
   un flag no revoca sesiones ni rota secretos.
2. **Client scopes declarados por Vendi** (los que no son de fábrica) con sus
   protocol mappers, y la lista de scopes por defecto y opcionales de cada
   cliente. Ahí viven el claim `organization` y la audiencia `vendi-backend`.

## Qué NO aplica, deliberadamente

- **Secretos de cliente.** El JSON los trae como placeholder y sobrescribirlos
  rotaría la credencial del backend en caliente. El `PUT` se hace sobre una
  copia del objeto VIVO con solo los campos declarados encima, precisamente
  para no tocar `secret`.
- **Flujos de autenticación y sus enlaces.** Reenlazar `browserFlow` mientras
  hay sesiones abiertas es la manera más rápida de dejar a todo el mundo fuera,
  y un flujo importado a medias deja el realm sin login. Sigue siendo trabajo
  del operador, con el informe de deriva delante.
- **Ajustes del realm, roles y usuarios.** Los roles de la cuenta de servicio
  se detectan pero no se tocan: un script que pueda *añadir* roles a una cuenta
  de servicio es un camino de escalada de privilegios con forma de herramienta
  de mantenimiento.

Variables de entorno: `KC_URL_BASE`, `KC_TOKEN` (token de admin del realm
master), `KC_REALM`, `REALM_JSON`. Salida: líneas legibles; 0 si todo fue bien,
1 si alguna llamada falló.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

AZUL = "\033[0;34m"
VERDE = "\033[0;32m"
AMARILLO = "\033[1;33m"
ROJO = "\033[0;31m"
NC = "\033[0m"

KC = os.environ["KC_URL_BASE"].rstrip("/")
TOKEN = os.environ["KC_TOKEN"]
REALM = os.environ.get("KC_REALM", "vendi-co")
RUTA_JSON = os.environ["REALM_JSON"]

# Los crea Keycloak solo. `admin-cli` es la excepción y está abajo, con su
# porqué: en el realm de negocio es un cliente público con ROPC, es decir, la
# misma puerta que D-01 cierra en `vendi-web` con otro nombre.
CLIENTES_INTERNOS = {
    "account",
    "account-console",
    "broker",
    "realm-management",
    "security-admin-console",
}

CAMPOS_CLIENTE = [
    "publicClient",
    "standardFlowEnabled",
    "directAccessGrantsEnabled",
    "serviceAccountsEnabled",
    "implicitFlowEnabled",
    "enabled",
    "redirectUris",
    "webOrigins",
]

# Scopes de fábrica de Keycloak: existen ya y sus mappers los mantiene el
# servidor. Solo se sincronizan los que Vendi declara de más.
SCOPES_DE_FABRICA = {
    "acr",
    "address",
    "basic",
    "email",
    "microprofile-jwt",
    "offline_access",
    "organization",
    "phone",
    "profile",
    "role_list",
    "roles",
    "saml_organization",
    "service_account",
    "web-origins",
}

cambios: list[str] = []
fallos: list[str] = []


def _peticion(metodo: str, ruta: str, cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(
        f"{KC}/admin/realms/{REALM}{ruta}",
        data=datos,
        method=metodo,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        crudo = respuesta.read()
        return json.loads(crudo) if crudo else None


def obtener(ruta: str):
    try:
        return _peticion("GET", ruta)
    except urllib.error.HTTPError as e:
        fallos.append(f"GET {ruta} devolvió {e.code}")
        return None


def escribir(metodo: str, ruta: str, cuerpo: dict, etiqueta: str) -> bool:
    try:
        _peticion(metodo, ruta, cuerpo)
    except urllib.error.HTTPError as e:
        detalle = e.read().decode(errors="replace")[:200]
        fallos.append(f"{metodo} {ruta} devolvió {e.code}: {detalle}")
        return False
    cambios.append(etiqueta)
    return True


def _difieren(esperado, real) -> bool:
    if isinstance(esperado, list) and isinstance(real, list):
        return sorted(map(str, esperado)) != sorted(map(str, real))
    return esperado != real


# --- Carga del JSON deseado -------------------------------------------------

with open(RUTA_JSON, encoding="utf-8") as f:
    crudo = f.read()

# Mismos placeholders que sustituye Keycloak al importar. Sin esto se
# escribirían redirect URIs con `${VENDI_BASE_DOMAIN}` literal.
for marcador, variable, defecto in (
    ("${VENDI_BASE_DOMAIN}", "BASE_DOMAIN", "vendi.co"),
    ("${VENDI_BACKEND_CLIENT_SECRET}", "VENDI_BACKEND_CLIENT_SECRET", ""),
    ("${VENDI_PROVISIONING_CLIENT_SECRET}", "VENDI_PROVISIONING_CLIENT_SECRET", ""),
):
    crudo = crudo.replace(marcador, os.environ.get(variable) or defecto)

deseado = json.loads(crudo)

print(f"{AZUL}[INFO]{NC}  aplicando la configuración declarada al realm '{REALM}'")

# --- 1. Client scopes declarados por Vendi ----------------------------------

scopes_vivos = {s["name"]: s for s in (obtener("/client-scopes") or [])}

for scope in deseado.get("clientScopes", []):
    nombre = scope.get("name")
    if nombre in SCOPES_DE_FABRICA:
        continue
    vivo = scopes_vivos.get(nombre)
    if vivo is None:
        if escribir("POST", "/client-scopes", scope, f"client scope '{nombre}' creado"):
            scopes_vivos = {s["name"]: s for s in (obtener("/client-scopes") or [])}
            vivo = scopes_vivos.get(nombre)
        if vivo is None:
            continue
    else:
        cuerpo = dict(vivo)
        cuerpo.update({k: v for k, v in scope.items() if k != "protocolMappers"})
        if _difieren({k: vivo.get(k) for k in scope if k != "protocolMappers"}, {k: scope[k] for k in scope if k != "protocolMappers"}):
            escribir("PUT", f"/client-scopes/{vivo['id']}", cuerpo, f"client scope '{nombre}' actualizado")

    # Mappers: se crean los que falten y se actualizan los que difieran. No se
    # borran los sobrantes — un mapper de más lo reporta la deriva y borrarlo a
    # ciegas puede quitarle un claim a un cliente que sí lo necesitaba.
    mappers_vivos = {m["name"]: m for m in (vivo.get("protocolMappers") or [])}
    for mapper in scope.get("protocolMappers", []):
        actual = mappers_vivos.get(mapper["name"])
        ruta_base = f"/client-scopes/{vivo['id']}/protocol-mappers/models"
        if actual is None:
            escribir("POST", ruta_base, mapper, f"mapper '{mapper['name']}' añadido a '{nombre}'")
        elif _difieren(mapper.get("config"), actual.get("config")):
            cuerpo = dict(actual)
            cuerpo.update(mapper)
            escribir("PUT", f"{ruta_base}/{actual['id']}", cuerpo, f"mapper '{mapper['name']}' actualizado en '{nombre}'")

# --- 2. Clientes -------------------------------------------------------------

clientes_vivos = {c.get("clientId"): c for c in (obtener("/clients") or [])}

for cliente in deseado.get("clients", []):
    cid = cliente.get("clientId")
    if cid in CLIENTES_INTERNOS:
        continue
    vivo = clientes_vivos.get(cid)
    if vivo is None:
        fallos.append(f"cliente '{cid}': declarado en el JSON y ausente del realm (crearlo NO es trabajo de este script)")
        continue

    pendientes = {campo: cliente[campo] for campo in CAMPOS_CLIENTE if campo in cliente and _difieren(cliente[campo], vivo.get(campo))}
    if pendientes:
        # Se parte del objeto VIVO: así el PUT conserva el secreto, los mappers
        # dedicados y todo lo que el JSON no declara.
        cuerpo = dict(vivo)
        cuerpo.update(pendientes)
        escribir("PUT", f"/clients/{vivo['id']}", cuerpo, f"cliente '{cid}': {', '.join(sorted(pendientes))}")

    # Scopes por defecto y opcionales: rutas propias, no van en el PUT.
    for clave, ruta in (("defaultClientScopes", "default-client-scopes"), ("optionalClientScopes", "optional-client-scopes")):
        if clave not in cliente:
            continue
        asignados = {s["name"]: s for s in (obtener(f"/clients/{vivo['id']}/{ruta}") or [])}
        for nombre in cliente[clave]:
            if nombre in asignados:
                continue
            scope = scopes_vivos.get(nombre) or {s["name"]: s for s in (obtener("/client-scopes") or [])}.get(nombre)
            if scope is None:
                fallos.append(f"cliente '{cid}': el scope '{nombre}' no existe en el realm")
                continue
            escribir("PUT", f"/clients/{vivo['id']}/{ruta}/{scope['id']}", {}, f"cliente '{cid}': scope '{nombre}' añadido a {clave}")

# --- Informe -----------------------------------------------------------------

if cambios:
    for c in cambios:
        print(f"{VERDE}[APLICADO]{NC} {c}")
else:
    print(f"{VERDE}[OK]{NC}    la configuración declarada ya estaba aplicada")

if fallos:
    for f_ in fallos:
        print(f"{ROJO}[ERROR]{NC} {f_}")
    sys.exit(1)

print(f"{AMARILLO}[AVISO]{NC} flujos de autenticación, ajustes del realm y roles NO se aplican: ver la cabecera del script")
