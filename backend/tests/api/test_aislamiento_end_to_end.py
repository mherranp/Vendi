"""EL test de la etapa: con dos negocios sembrados, el token de uno no alcanza al otro.

El criterio de integración de la Etapa 4 pide que el ataque de aislamiento de QA
quede **automatizado**, no como ejercicio manual. Esto es ese ataque, por todos
los caminos por los que un identificador de negocio puede entrar en la API:

- el claim `organization` del token (la vía legítima),
- la cabecera `X-Tenant-Id` (la vía de desempate para usuarios multi-negocio),
- el path (`/platform/tenants/{id}`),
- y la conexión a la base con el rol de la API, saltándose la aplicación entera.

Ninguno devuelve datos ajenos. Cada bloque dice qué mecanismo concreto lo
impide, porque un test de aislamiento que solo comprueba el código de estado no
distingue "está protegido" de "la ruta no existe todavía".
"""

from __future__ import annotations

import uuid

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_de_negocio, usuario_de_plataforma
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.tenant.middleware import HEADER_TENANT

pytestmark = pytest.mark.integration


@pytest.fixture
def dos_negocios(app_con_base):
    """Siembra A y B y devuelve el cliente con los dos ids."""
    cliente, validador, aprovisionamiento = app_con_base
    validador.registrar("tok-admin", usuario_de_plataforma())
    cabeceras = {"Authorization": "Bearer tok-admin"}

    def _crear(nombre: str) -> uuid.UUID:
        respuesta = cliente.post("/api/v1/platform/tenants", json={"nombre": nombre}, headers=cabeceras)
        assert respuesta.status_code == 201, respuesta.text
        return uuid.UUID(respuesta.json()["id"])

    a = _crear(PREFIJO_PRUEBA + "Negocio A")
    b = _crear(PREFIJO_PRUEBA + "Negocio B")

    # Dueño de A, y de nadie más. Es el atacante de todo este archivo.
    validador.registrar("tok-a", usuario_de_negocio(a, user_id="dueno-de-a"))
    return cliente, validador, a, b


def _como_a() -> dict:
    return {"Authorization": "Bearer tok-a"}


# --- El camino legítimo ------------------------------------------------------


def test_el_dueno_de_a_ve_a(dos_negocios):
    cliente, _, a, _ = dos_negocios
    respuesta = cliente.get("/api/v1/tenants/me", headers=_como_a())
    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == str(a)


# --- Ataque por la cabecera X-Tenant-Id --------------------------------------


def test_la_cabecera_con_el_alias_de_b_se_ignora_cuando_a_es_la_unica_org(dos_negocios):
    """Con UNA sola organización en el token, el header no decide nada.

    `TenantMiddleware` solo lo mira para desempatar entre negocios que ya están
    en el token. Este test comprueba lo importante: que el resultado sigue
    siendo A, y no que "no explota".
    """
    cliente, _, a, b = dos_negocios
    respuesta = cliente.get("/api/v1/tenants/me", headers={**_como_a(), HEADER_TENANT: str(b)})
    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == str(a)
    assert respuesta.json()["nombre"] == PREFIJO_PRUEBA + "Negocio A"


def test_un_usuario_multiorganizacion_no_puede_elegir_un_negocio_ajeno(dos_negocios):
    """El caso que sí depende del header: miembro de A y de C, pide B.

    Lo que se compara es el header contra los alias DEL TOKEN, no contra la
    tabla `tenants`. Un negocio que existe pero del que no eres miembro es
    exactamente igual de inalcanzable que uno inventado.
    """
    cliente, validador, a, b = dos_negocios
    otro_propio = uuid.uuid4()
    validador.registrar("tok-multi", usuario_de_negocio(a, otro_propio, user_id="dueno-multi"))
    cabeceras = {"Authorization": "Bearer tok-multi", HEADER_TENANT: str(b)}

    respuesta = cliente.get("/api/v1/tenants/me", headers=cabeceras)
    assert respuesta.status_code == 400
    assert respuesta.json()["code"] == "tenant_no_especificado"
    assert str(b) not in respuesta.text or "pertenece a varios" in respuesta.text


def test_una_cabecera_con_basura_no_produce_500(dos_negocios):
    """Un GUC con basura aborta la transacción en PostgreSQL; se corta antes."""
    cliente, validador, a, _ = dos_negocios
    validador.registrar("tok-multi2", usuario_de_negocio(a, uuid.uuid4(), user_id="dueno-multi2"))
    for basura in ["'; DROP TABLE tenants; --", "../../etc/passwd", "*", ""]:
        respuesta = cliente.get(
            "/api/v1/tenants/me",
            headers={"Authorization": "Bearer tok-multi2", HEADER_TENANT: basura},
        )
        assert respuesta.status_code == 400, f"con {basura!r} devolvió {respuesta.status_code}"


# --- Ataque por el path ------------------------------------------------------


def test_el_dueno_de_a_no_puede_leer_b_por_la_consola(dos_negocios):
    """Lo que lo impide no es que el id sea ajeno: es que falta `platform:admin`.

    El detalle importa. La consola es cross-tenant por diseño, así que su única
    defensa es el permiso — y por eso el permiso no lo tiene ningún rol de
    negocio (`vendi_core.auth.policies`: el dueño tiene tenant:read y
    tenant:update, nunca platform:admin).
    """
    cliente, _, a, b = dos_negocios
    for ruta in (f"/api/v1/platform/tenants/{b}", f"/api/v1/platform/tenants/{a}", "/api/v1/platform/tenants"):
        respuesta = cliente.get(ruta, headers=_como_a())
        assert respuesta.status_code == 403, f"{ruta} devolvió {respuesta.status_code}"
        assert respuesta.json()["code"] == "requiere_platform_admin"
        assert "Negocio B" not in respuesta.text


def test_el_dueno_de_a_no_puede_suspender_ni_borrar_b(dos_negocios):
    cliente, _, _, b = dos_negocios
    assert (
        cliente.patch(f"/api/v1/platform/tenants/{b}", json={"estado": "suspendido"}, headers=_como_a()).status_code
        == 403
    )
    assert cliente.delete(f"/api/v1/platform/tenants/{b}", headers=_como_a()).status_code == 403


def test_suspender_b_no_afecta_a_a(dos_negocios):
    """La suspensión es por negocio, no un interruptor global."""
    cliente, validador, a, b = dos_negocios
    admin = {"Authorization": "Bearer tok-admin"}
    cliente.patch(f"/api/v1/platform/tenants/{b}", json={"estado": "suspendido"}, headers=admin)
    assert cliente.get("/api/v1/tenants/me", headers=_como_a()).status_code == 200


# --- Ataque saltándose la aplicación -----------------------------------------


@pytest.mark.asyncio
async def test_el_rol_de_la_api_no_alcanza_la_tabla_de_negocios(pg_app_url):
    """Aunque un handler quisiera, `vendi_app` no puede leer `tenants`.

    Es la defensa que sobrevive a un bug de la aplicación: `tenants` es tabla de
    plataforma y NO lleva policy RLS, así que si el rol de la API tuviera SELECT
    podría listar todos los negocios de la región. La migración 0002 se lo
    revoca entero.
    """
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    engine = create_async_engine(pg_app_url)
    try:
        async with engine.connect() as conn:
            for sentencia in (
                "SELECT count(*) FROM tenants",
                "INSERT INTO tenants (nombre) VALUES ('intruso')",
                "UPDATE tenants SET estado = 'activo'",
                "DELETE FROM tenants",
            ):
                with pytest.raises((DBAPIError, ProgrammingError), match="permission denied"):
                    await conn.execute(text(sentencia))
                await conn.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_el_rol_de_la_api_no_puede_encolar_eventos_de_otro_negocio(pg_app_url, dos_negocios):
    """La policy de INSERT del outbox, ejercida con los dos ids reales.

    Con el GUC de A, encolar con `tenant_id = B` se rechaza. Es la mitad que sí
    defiende la base; la otra mitad —que la CLAVE DE ENRUTADO tampoco pueda ser
    la de B— la cierra el dispatcher derivándola de la columna (D-05, ver
    `tests/worker/test_outbox_dispatch.py`).
    """
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    _, _, a, b = dos_negocios
    engine = create_async_engine(pg_app_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT set_config('vendi.tenant_id', :t, false)"), {"t": str(a)})
            with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
                await conn.execute(
                    text(
                        "INSERT INTO outbox_messages (tenant_id, exchange, routing_key, payload) "
                        "VALUES (:t, 'events.tenant', :k, '{}'::jsonb)"
                    ),
                    {"t": str(b), "k": f"{b}.venta.creada"},
                )
            await conn.rollback()
    finally:
        await engine.dispose()
