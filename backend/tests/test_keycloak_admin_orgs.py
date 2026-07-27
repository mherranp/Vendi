"""`VendiKeycloakAdmin` contra el Keycloak real del compose.

Va por `https://accounts.vendi.co` —el dominio, a través de Traefik, con el
certificado que instaló mkcert— y no por `localhost:8080`. La diferencia no es
estética: por el dominio se ejerce el enrutado de Traefik, las cabeceras que
inyecta y el TLS, que es donde viven los fallos que solo aparecen desplegado.
Si algo aquí funcionara por puerto y fallara por dominio, eso sería el defecto.

Este archivo también es la prueba viva del split de D-02: `test_el_cliente_de_la_api_no_alcanza_organizations`
falla si alguien devuelve `manage-realm` a `vendi-backend`.

## Ir «por el dominio» no basta, y esta suite lo aprendió por las malas

`vendi.co` está registrado de verdad. Pedir el nombre a secas no pide el stack
local: pide *lo que conteste*. Con `/etc/resolver/vendi.co` todavía pendiente de
`sudo`, quien contestaba era `64.190.63.222` —un host ajeno, con certificado
DigiCert válido para `accounts.vendi.co`— y esta suite le hacía POST del
`client_secret` de `vendi-provisioning`. La huella quedó en el propio informe de
QA: `405 Not Allowed` servido por `openresty`, que no es Keycloak ni Traefik.
Peor aún: `test_el_cliente_de_la_api_no_alcanza_organizations` interpretó ese
405 de un extraño como si fuera una respuesta del realm y siguió evaluando.

Por eso todo test de este módulo pasa por `stack_local` (autouse), que fija la
resolución a 127.0.0.1 y **comprueba de quién es el certificado** antes de que
se transmita ninguna credencial. Con `vendi.local` —un TLD inexistente— el
mismo despiste era inofensivo; con un TLD real no lo es.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import uuid

import pytest

from vendi_core.auth.keycloak_admin import VendiKeycloakAdmin
from vendi_core.auth.keycloak_aprovisionamiento import VendiKeycloakAprovisionamiento
from vendi_core.errors.domain import ConflictError, ExternalServiceError, PermissionDeniedError

pytestmark = pytest.mark.integration

KC_URL = os.getenv("VENDI_TEST_KEYCLOAK_URL", "https://accounts.vendi.co")


def _cargar_env() -> None:
    raiz = pathlib.Path(__file__).resolve().parents[2]
    archivo = raiz / ".env"
    if not archivo.exists():
        return
    for linea in archivo.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip())


_cargar_env()


@pytest.fixture(autouse=True)
def stack_local(exigir_stack_local):
    """Puerta de entrada de TODO test de este módulo.

    `autouse` a propósito: si esto fuera opcional, el primer test que se
    escribiera sin pedirlo volvería a mandar el secreto a Internet, y no habría
    forma de notarlo leyendo el diff. Al ser autouse, la única manera de saltarse
    la comprobación es borrarla, que sí se ve.

    Devuelve la identidad del peer por si un test quiere afirmar algo sobre ella.
    """
    return exigir_stack_local(KC_URL)


def test_el_otro_extremo_es_el_stack_local(stack_local):
    """La aserción de identidad del peer, explícita y no como efecto colateral.

    Que exista un test dedicado no es redundante con el fixture autouse: este es
    el que da un mensaje inteligible cuando la condición se rompe, en lugar de
    tumbar la suite entera con un error que parece «Keycloak está caído».
    """
    assert stack_local["ip"] in {"127.0.0.1", "::1"}
    emisor = stack_local["issuer"]
    assert "mkcert" in emisor.get("organizationName", "") + emisor.get("commonName", ""), (
        f"El emisor del certificado es {emisor}, no la CA local de mkcert"
    )


# Ámbito de función, no de módulo: `KeycloakOpenIDConnection` mantiene un pool
# de conexiones HTTP ligado al event loop en el que se usó por primera vez, y
# pytest-asyncio crea un loop nuevo por test. Un objeto compartido entre tests
# falla con `KeycloakConnectionError("Can't connect to server")` a partir del
# segundo — un error que parece "Keycloak está caído" y no lo es.
@pytest.fixture
def aprovisionamiento() -> VendiKeycloakAprovisionamiento:
    secreto = os.getenv("VENDI_PROVISIONING_CLIENT_SECRET", "")
    if not secreto:
        pytest.skip("VENDI_PROVISIONING_CLIENT_SECRET no definido")
    return VendiKeycloakAprovisionamiento(KC_URL, "vendi-provisioning", secreto)


@pytest.fixture
def api_general() -> VendiKeycloakAdmin:
    secreto = os.getenv("VENDI_BACKEND_CLIENT_SECRET", "")
    if not secreto:
        pytest.skip("VENDI_BACKEND_CLIENT_SECRET no definido")
    return VendiKeycloakAdmin(KC_URL, "vendi-backend", secreto)


@pytest.fixture
async def negocio(aprovisionamiento):
    """Crea una organización con alias = tenant_id y la borra al terminar."""
    tenant_id = uuid.uuid4()
    org_id = await aprovisionamiento.create_organization(tenant_id, f"Negocio {tenant_id.hex[:8]}")
    try:
        yield tenant_id, org_id
    finally:
        await aprovisionamiento.delete_organization(org_id)


# --- Organizations ----------------------------------------------------------


@pytest.mark.asyncio
async def test_alias_es_el_tenant_id_literal(aprovisionamiento, negocio):
    """La propiedad de la que depende todo: el alias vuelve tal cual.

    Si Keycloak normalizara el alias (minúsculas, quitar guiones, truncar), el
    middleware no podría resolver el tenant del token sin un lookup, y el diseño
    entero cambiaría de coste.
    """
    tenant_id, _ = negocio
    org = await aprovisionamiento.get_organization_by_alias(tenant_id)
    assert org is not None
    assert org["alias"] == str(tenant_id)


@pytest.mark.asyncio
async def test_dominio_sintetico(aprovisionamiento, negocio):
    tenant_id, org_id = negocio
    org = await aprovisionamiento.get_organization_by_alias(tenant_id)
    dominios = [d["name"] for d in org.get("domains", [])]
    assert f"{tenant_id}.tenants.vendi.co" in dominios


@pytest.mark.asyncio
async def test_alias_duplicado_da_conflicto_tipado(aprovisionamiento, negocio):
    """409 limpio, no traza: el servicio de alta puede tratarlo como "ya existe"."""
    tenant_id, _ = negocio
    with pytest.raises(ConflictError):
        await aprovisionamiento.create_organization(tenant_id, "Otro negocio")


@pytest.mark.asyncio
async def test_borrar_organizacion_inexistente_es_idempotente(aprovisionamiento):
    """Un 404 al borrar es "ya no está", no un fallo. Lo necesita la compensación
    del alta de negocio (tarea 4.2), que borra sin saber si llegó a crear."""
    await aprovisionamiento.delete_organization(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_ciclo_de_miembros(aprovisionamiento, negocio):
    tenant_id, org_id = negocio
    sufijo = uuid.uuid4().hex[:8]
    user_id = await aprovisionamiento.create_user(
        username=f"prueba{sufijo}",
        email=f"prueba{sufijo}@demo.vendi.co",
        first_name="Prueba",
        last_name="Integracion",
        password="prueba-integracion",
    )
    try:
        await aprovisionamiento.add_member(org_id, user_id)
        miembros = await aprovisionamiento.get_organization_members(org_id)
        assert user_id in [m["id"] for m in miembros]

        # Idempotencia: añadir dos veces no revienta.
        await aprovisionamiento.add_member(org_id, user_id)

        orgs = await aprovisionamiento.get_user_organizations(user_id)
        assert str(tenant_id) in [o["alias"] for o in orgs]

        await aprovisionamiento.remove_member(org_id, user_id)
        assert user_id not in [m["id"] for m in await aprovisionamiento.get_organization_members(org_id)]
        # Idempotencia también al quitar.
        await aprovisionamiento.remove_member(org_id, user_id)
    finally:
        await aprovisionamiento.delete_user(user_id)


# --- Usuarios ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_exige_nombre_y_apellido(api_general):
    """El hallazgo del spike, convertido en una firma que no deja equivocarse.

    Sin `firstName`/`lastName` el perfil declarativo del realm marca
    VERIFY_PROFILE y el usuario recibe `Account is not fully set up` al
    autenticarse — un mensaje que no menciona el perfil por ningún lado.
    """
    with pytest.raises(ValueError, match="first_name y last_name son obligatorios"):
        await api_general.create_user(username="sin-nombre", email="x@y.local", first_name="", last_name="")


@pytest.mark.asyncio
async def test_ensure_realm_role_es_idempotente(aprovisionamiento):
    nombre = f"prueba-rol-{uuid.uuid4().hex[:8]}"
    try:
        primero = await aprovisionamiento.ensure_realm_role(nombre, "rol de prueba")
        segundo = await aprovisionamiento.ensure_realm_role(nombre, "rol de prueba")
        assert primero["id"] == segundo["id"]
    finally:
        # El realm es un recurso compartido y persistente: sin esta limpieza,
        # cada corrida de la suite dejaba un rol nuevo. Se midió: 57 roles y 57
        # grupos `prueba-*` acumulados en el realm de desarrollo antes de
        # añadirla. La suite tiene que ser re-entrante Y no dejar basura.
        with contextlib.suppress(Exception):
            await aprovisionamiento._kc.a_delete_realm_role(nombre)  # noqa: SLF001


@pytest.mark.asyncio
async def test_ensure_group_es_idempotente(api_general):
    nombre = f"prueba-grupo-{uuid.uuid4().hex[:8]}"
    grupo_id = None
    try:
        primero = await api_general.ensure_group(nombre)
        segundo = await api_general.ensure_group(nombre)
        assert primero == segundo
        grupo_id = primero
    finally:
        if grupo_id:
            with contextlib.suppress(Exception):
                await api_general._kc.a_delete_group(grupo_id)  # noqa: SLF001


# --- El split de D-02, verificado ------------------------------------------


@pytest.mark.asyncio
async def test_el_cliente_de_la_api_no_alcanza_organizations(api_general):
    """La mitigación de D-02, como test que se puede romper.

    `VendiKeycloakAdmin` ni siquiera expone los métodos de Organizations, así
    que se prueba por debajo: con el token de `vendi-backend`, la Admin API
    responde 403. Si alguien devuelve `manage-realm` a esa cuenta de servicio,
    este test se pone rojo — y el check 21 de `verify-setup.sh` también.
    """
    assert not hasattr(api_general, "create_organization"), (
        "VendiKeycloakAdmin no debe exponer Organizations: para eso está VendiKeycloakAprovisionamiento"
    )
    from keycloak.exceptions import KeycloakError

    with pytest.raises(KeycloakError) as exc:
        await api_general._kc.a_get_organizations()
    assert getattr(exc.value, "response_code", None) == 403, (
        f"vendi-backend alcanzó la API de Organizations (status "
        f"{getattr(exc.value, 'response_code', None)}): el split de D-02 está deshecho"
    )


@pytest.mark.asyncio
async def test_keycloak_inalcanzable_da_error_tipado():
    """Un Keycloak caído no puede subir como traza cruda del cliente HTTP."""
    admin = VendiKeycloakAprovisionamiento("https://accounts-que-no-existe.vendi.co", "vendi-provisioning", "loquesea")
    with pytest.raises((ExternalServiceError, PermissionDeniedError, Exception)) as exc:
        await admin.list_organizations()
    # Lo único inaceptable es un fallo que no diga nada útil.
    assert str(exc.value)
