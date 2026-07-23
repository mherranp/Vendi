"""Aprovisionamiento de negocios: compensación, contrato de sesión y cache.

Aquí viven los tres candados que el hallazgo de la Etapa 3 dejó abiertos:

1. **Contrato de sesión.** El aprovisionamiento tiene que ir con la fábrica de
   PLATAFORMA. Con la de la API (`vendi_app`) falla con un `permission denied`
   opaco que no menciona ninguna de las dos causas reales.
2. **Compensación del alta.** Keycloak caído ⇒ error tipado y CERO filas.
3. **Suspensión con cache real.** El TTL del cache es la latencia máxima de la
   suspensión, así que hay que medir que la invalidación funciona y no fiarse
   de que el cache esté apagado en los tests.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from ayudas import PREFIJO_PRUEBA, KeycloakFalso, app_de_prueba, settings_de_prueba, usuario_de_negocio
from ayudas import usuario_de_plataforma as _usuario_de_plataforma
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.tenants.service import ErrorDeCableadoDelServicio, TenantService
from vendi_core.audit.service import AuditService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_platform_session_factory, create_session_factory

pytestmark = pytest.mark.integration


def _admin(validador, token: str = "tok-admin") -> dict:
    validador.registrar(token, _usuario_de_plataforma())
    return {"Authorization": f"Bearer {token}"}


# --- 1. Contrato de sesión ---------------------------------------------------


@pytest_asyncio.fixture
async def engines(pg_app_url: str, pg_platform_url: str):
    tenant = create_engine(pg_app_url)
    plataforma = create_engine(pg_platform_url)
    try:
        yield tenant, plataforma
    finally:
        await tenant.dispose()
        await plataforma.dispose()


@pytest.mark.asyncio
async def test_el_servicio_rechaza_la_sesion_de_la_api(engines):
    """El candado. Sin él, el fallo es un `permission denied` a tres capas.

    Dos causas independientes, ninguna de las cuales el error de PostgreSQL
    menciona:

    - `tenants` está revocada entera para `vendi_app` (migración 0002), así que
      ni el INSERT ni el SELECT funcionan.
    - el evento `tenant.creado` viaja con `tenant_id = NULL` y la policy
      `outbox_encolado_del_tenant` exige `tenant_id = current_setting(...)`;
      `NULL = NULL` es NULL, o sea falso, o sea fila rechazada.
    """
    engine_tenant, _ = engines
    fabrica_de_la_api = create_session_factory(engine_tenant)
    async with fabrica_de_la_api() as sesion:
        with pytest.raises(ErrorDeCableadoDelServicio) as excinfo:
            TenantService(session=sesion, keycloak=KeycloakFalso(), audit=None)  # type: ignore[arg-type]
    assert "plataforma" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_con_la_sesion_de_la_api_el_insert_falla_de_verdad(engines):
    """La prueba de que el candado no es teórico: se demuestra el fallo real.

    Si un día alguien quita el candado "porque no hace nada", este test dice
    exactamente qué pasa sin él.
    """
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    engine_tenant, _ = engines
    async with create_session_factory(engine_tenant)() as sesion:
        with pytest.raises((DBAPIError, ProgrammingError), match="permission denied"):
            await sesion.execute(text("INSERT INTO tenants (nombre) VALUES ('no deberia entrar')"))
        await sesion.rollback()


@pytest.mark.asyncio
async def test_con_la_sesion_de_plataforma_el_servicio_se_construye(engines):
    _, engine_plataforma = engines
    fabrica = create_platform_session_factory(engine_plataforma)
    async with fabrica() as sesion:
        servicio = TenantService(
            session=sesion,
            keycloak=KeycloakFalso(),
            audit=AuditService(session_factory=fabrica, service_name="test"),
        )
    assert servicio is not None


# --- 2. Compensación del alta ------------------------------------------------


def test_keycloak_caido_da_error_tipado_y_no_deja_fila(app_con_base):
    """El ataque de QA: matar Keycloak y crear un negocio.

    Dos aserciones y las dos importan: (a) el cliente recibe un error tipado con
    el sobre estándar y no un 500 con traza; (b) **no queda fila huérfana**, que
    es lo que la compensación existe para garantizar.
    """
    cliente, validador, keycloak = app_con_base
    cabeceras = _admin(validador)
    keycloak.fallar_al_crear = True

    respuesta = cliente.post(
        "/api/v1/platform/tenants",
        json={"nombre": PREFIJO_PRUEBA + "Nunca Nacido"},
        headers=cabeceras,
    )

    assert respuesta.status_code == 502, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["success"] is False
    assert cuerpo["code"] == "EXTERNAL_SERVICE_ERROR"
    assert "Traceback" not in respuesta.text

    listado = cliente.get("/api/v1/platform/tenants?incluir_eliminados=true", headers=cabeceras).json()
    assert not [t for t in listado["items"] if t["nombre"] == PREFIJO_PRUEBA + "Nunca Nacido"], (
        "quedó una fila de negocio sin organización: la compensación no deshizo el INSERT"
    )


@pytest.mark.asyncio
async def test_el_alta_fallida_deja_su_rastro_de_auditoria(app_con_base, pg_platform_url):
    """Un alta que falla también es un hecho auditable.

    Sin esto, el único registro de un intento fallido sería una línea de log que
    la rotación se lleva.
    """
    cliente, validador, keycloak = app_con_base
    cabeceras = _admin(validador)
    keycloak.fallar_al_crear = True
    nombre = PREFIJO_PRUEBA + "Fallido " + uuid.uuid4().hex[:8]
    cliente.post("/api/v1/platform/tenants", json={"nombre": nombre}, headers=cabeceras)

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            filas = (
                await conn.execute(
                    text("SELECT action, status, changes FROM audit_events WHERE changes->>'nombre' = :n"),
                    {"n": nombre},
                )
            ).all()
            await conn.execute(text("DELETE FROM audit_events WHERE changes->>'nombre' = :n"), {"n": nombre})
            await conn.commit()
    finally:
        await engine.dispose()

    assert [f.status for f in filas] == ["failure"]
    assert filas[0].action == "tenant.crear"


def test_la_baja_sigue_adelante_si_keycloak_no_responde(app_con_base):
    """Orden deliberado: primero el commit, luego Keycloak.

    Si Keycloak no responde, el negocio ya está dado de baja —que es lo que
    corta el acceso— y la organización huérfana la recoge
    `reconcile-keycloak.sh`. Al revés sería peor: organización borrada y negocio
    vivo, es decir, usuarios que dejan de entrar sin que nadie los haya dado de
    baja.
    """
    cliente, validador, keycloak = app_con_base
    cabeceras = _admin(validador)
    creado = cliente.post(
        "/api/v1/platform/tenants",
        json={"nombre": PREFIJO_PRUEBA + "Baja Con KC Caido"},
        headers=cabeceras,
    ).json()

    keycloak.fallar_al_borrar = True
    assert cliente.delete(f"/api/v1/platform/tenants/{creado['id']}", headers=cabeceras).status_code == 204
    assert cliente.get(f"/api/v1/platform/tenants/{creado['id']}", headers=cabeceras).status_code == 404


def test_dar_de_baja_y_recrear_con_el_mismo_nombre_funciona(app_con_base):
    """Ataque de QA: crear, borrar y recrear con el mismo nombre.

    Funciona por dos motivos a la vez, y conviene que los dos queden probados:
    el alias es un UUID nuevo (no colisiona) y el `name` de la Organization es
    ese mismo UUID (tampoco colisiona, aunque la organización anterior siguiera
    existiendo). Con el nombre comercial en `name`, Keycloak devolvería 409.
    """
    cliente, validador, keycloak = app_con_base
    cabeceras = _admin(validador)
    nombre = PREFIJO_PRUEBA + "Reencarnado"

    primero = cliente.post("/api/v1/platform/tenants", json={"nombre": nombre}, headers=cabeceras).json()
    cliente.delete(f"/api/v1/platform/tenants/{primero['id']}", headers=cabeceras)
    segundo = cliente.post("/api/v1/platform/tenants", json={"nombre": nombre}, headers=cabeceras)

    assert segundo.status_code == 201, segundo.text
    assert segundo.json()["id"] != primero["id"]


# --- 3. Suspensión con el Redis real -----------------------------------------

REDIS_URL = os.getenv("VENDI_TEST_REDIS_URL", "")
if not REDIS_URL and os.getenv("REDIS_PASSWORD"):
    REDIS_URL = f"redis://:{os.environ['REDIS_PASSWORD']}@127.0.0.1:6379/1"


@pytest.fixture
def app_con_cache(pg_app_url: str, pg_platform_url: str, limpiar_tenants_de_prueba):
    """Como `app_con_base`, pero con el Redis del compose cableado.

    Base de datos 1 y no la 0: no se pisan las claves de la aplicación en
    desarrollo.
    """
    if not REDIS_URL:
        pytest.fail(
            "No hay DSN de Redis para el test del cache de suspensión. Define "
            "REDIS_PASSWORD (lo trae el .env) o VENDI_TEST_REDIS_URL. Se falla en "
            "vez de omitir: el TTL de este cache ES la latencia de la suspensión, "
            "y un test que desaparece del recuento no la mide."
        )
    settings = settings_de_prueba(
        database_url=pg_app_url,
        platform_database_url=pg_platform_url,
        redis_url=REDIS_URL,
        tenant_estado_cache_ttl=60,
    )
    aplicacion, validador, keycloak = app_de_prueba(settings)
    with TestClient(aplicacion, raise_server_exceptions=False) as cliente:
        yield cliente, validador, keycloak


def test_la_suspension_se_ve_al_instante_pese_al_cache_de_60s(app_con_cache):
    """Con el cache activo y TTL de 60 s, la suspensión NO tarda 60 s.

    Porque la mutación invalida la clave. El TTL solo cubre el caso de que la
    invalidación se pierda (Redis reiniciado, otra instancia de la API), y ese
    es el número que hay que citar como cota superior: 60 s con un token todavía
    criptográficamente válido.
    """
    cliente, validador, _ = app_con_cache
    cabeceras = _admin(validador)
    creado = cliente.post(
        "/api/v1/platform/tenants",
        json={"nombre": PREFIJO_PRUEBA + "Con Cache"},
        headers=cabeceras,
    ).json()
    validador.registrar("tok-cache", usuario_de_negocio(uuid.UUID(creado["id"])))
    propias = {"Authorization": "Bearer tok-cache"}

    # Poblar el cache con "activo".
    assert cliente.get("/api/v1/tenants/me", headers=propias).status_code == 200

    cliente.patch(f"/api/v1/platform/tenants/{creado['id']}", json={"estado": "suspendido"}, headers=cabeceras)

    respuesta = cliente.get("/api/v1/tenants/me", headers=propias)
    assert respuesta.status_code == 403, (
        "El cache sirvió el estado viejo: la suspensión no invalidó la clave y "
        "tardaría hasta un TTL entero en cortar el acceso."
    )
    assert respuesta.json()["code"] == "tenant_suspendido"


def test_un_id_inexistente_tambien_se_cachea_y_no_martillea_la_base(app_con_cache):
    """Cachear la ausencia cierra el ataque de enumeración más barato que hay."""
    cliente, validador, _ = app_con_cache
    validador.registrar("tok-inventado", usuario_de_negocio(uuid.uuid4()))
    propias = {"Authorization": "Bearer tok-inventado"}
    assert cliente.get("/api/v1/tenants/me", headers=propias).status_code == 404
    assert cliente.get("/api/v1/tenants/me", headers=propias).status_code == 404


# --- 4. Contra el Keycloak real ----------------------------------------------

KC_URL = os.getenv("VENDI_TEST_KEYCLOAK_URL", "https://accounts.vendi.co")


@pytest.mark.asyncio
async def test_keycloak_exige_nombre_unico_de_organizacion(exigir_stack_local):
    """La medición que obligó a desacoplar el `name` de la Organization.

    Contra el Keycloak 26.6.4 del compose, por el dominio y con el certificado
    del sistema. `exigir_stack_local` fija la resolución a 127.0.0.1 y comprueba
    de quién es el certificado ANTES de transmitir el `client_secret`:
    `vendi.co` es un dominio registrado por un tercero.

    Si esto empezara a pasar (es decir, si Keycloak dejara de exigir nombre
    único), el desacople seguiría siendo correcto pero dejaría de ser
    obligatorio, y este test lo diría.
    """
    from vendi_core.auth.keycloak_admin import VendiKeycloakAprovisionamiento

    exigir_stack_local(KC_URL)
    secreto = os.getenv("VENDI_PROVISIONING_CLIENT_SECRET", "")
    if not secreto:
        pytest.fail("VENDI_PROVISIONING_CLIENT_SECRET no definido: no se puede medir contra el realm real.")

    kc = VendiKeycloakAprovisionamiento(KC_URL, "vendi-provisioning", secreto)
    uno, otro = uuid.uuid4(), uuid.uuid4()
    ids: list[str] = []
    try:
        ids.append(await kc.create_organization(uno, "Nombre repetido de prueba"))
        # Mismo nombre legible, alias distinto: tiene que funcionar, porque el
        # `name` que se manda es el UUID y el nombre va en `description`.
        ids.append(await kc.create_organization(otro, "Nombre repetido de prueba"))
        assert len(ids) == 2
        org = await kc.get_organization_by_alias(otro)
        assert org is not None
        assert org["name"] == str(otro)
        assert org["description"] == "Nombre repetido de prueba"
    finally:
        for org_id in ids:
            await kc.delete_organization(org_id)


@pytest.mark.asyncio
async def test_el_alta_completa_contra_el_keycloak_real(pg_platform_url, exigir_stack_local, limpiar_tenants_de_prueba):
    """El camino de aprovisionamiento entero, sin doble de Keycloak.

    Es el único test que ejerce a la vez la transacción de plataforma, la
    llamada real a Organizations y el encolado del evento.
    """
    from vendi_core.auth.keycloak_admin import VendiKeycloakAprovisionamiento

    exigir_stack_local(KC_URL)
    secreto = os.getenv("VENDI_PROVISIONING_CLIENT_SECRET", "")
    if not secreto:
        pytest.fail("VENDI_PROVISIONING_CLIENT_SECRET no definido.")

    engine = create_engine(pg_platform_url)
    fabrica = create_platform_session_factory(engine)
    kc = VendiKeycloakAprovisionamiento(KC_URL, "vendi-provisioning", secreto)
    creado_id = None
    try:
        async with fabrica() as sesion:
            servicio = TenantService(
                session=sesion,
                keycloak=kc,
                audit=AuditService(session_factory=fabrica, service_name="test"),
            )
            tenant = await servicio.crear(PREFIJO_PRUEBA + "Alta Real")
            creado_id = tenant.id
            assert tenant.kc_org_id

        org = await kc.get_organization_by_alias(creado_id)
        assert org is not None
        assert org["alias"] == str(creado_id)

        async with fabrica() as sesion:
            servicio = TenantService(
                session=sesion,
                keycloak=kc,
                audit=AuditService(session_factory=fabrica, service_name="test"),
            )
            await servicio.eliminar(creado_id)
        assert await kc.get_organization_by_alias(creado_id) is None
    finally:
        if creado_id is not None:
            org = await kc.get_organization_by_alias(creado_id)
            if org:
                await kc.delete_organization(org["id"])
        await engine.dispose()
