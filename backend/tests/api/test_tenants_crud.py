"""CRUD de negocios contra el PostgreSQL real, con los dos roles reales.

`integration` porque la base **no** se dobla: los privilegios por rol, el
`REVOKE` sobre `tenants` y la policy de INSERT del outbox solo existen en
PostgreSQL. Un doble los daría siempre por buenos, que es justo lo contrario de
lo que estos tests miden.
"""

from __future__ import annotations

import uuid

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_de_negocio, usuario_de_plataforma
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


def _admin(cliente, validador, token: str = "tok-admin") -> dict:
    validador.registrar(token, usuario_de_plataforma())
    return {"Authorization": f"Bearer {token}"}


def _crear(cliente, cabeceras, nombre: str) -> dict:
    respuesta = cliente.post("/api/v1/platform/tenants", json={"nombre": nombre}, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# --- Alta -------------------------------------------------------------------


def test_crear_devuelve_201_con_id_nombre_y_estado(app_con_base):
    cliente, validador, keycloak = app_con_base
    cabeceras = _admin(cliente, validador)

    cuerpo = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Tienda Don Carlos")

    assert cuerpo["nombre"] == PREFIJO_PRUEBA + "Tienda Don Carlos"
    assert cuerpo["estado"] == "activo"
    assert uuid.UUID(cuerpo["id"])
    assert cuerpo["kc_org_id"], "el alta tiene que dejar registrado el id de la organización"


def test_el_alta_crea_la_organizacion_con_alias_igual_al_tenant_id(app_con_base):
    """La propiedad de la que depende todo el diseño: `alias = str(tenant_id)`.

    Es lo que permite que `TenantMiddleware` resuelva el negocio del token sin
    ninguna consulta —ni a Keycloak ni a la base—. Si el alias dejara de ser el
    id, la resolución del tenant pasaría a costar un lookup por request.
    """
    cliente, validador, keycloak = app_con_base
    cabeceras = _admin(cliente, validador)

    cuerpo = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Panadería La Espiga")

    assert cuerpo["id"] in keycloak.organizaciones
    org = keycloak.organizaciones[cuerpo["id"]]
    assert org["id"] == cuerpo["kc_org_id"]
    # El `name` de la Organization es el UUID y NO el nombre comercial: Keycloak
    # exige nombre único por realm (medido: 409). Ver `create_organization`.
    assert org["name"] == cuerpo["id"]
    assert org["description"] == PREFIJO_PRUEBA + "Panadería La Espiga"


def test_dos_negocios_pueden_llamarse_igual(app_con_base):
    """Decisión de producto, y no es gratuita.

    Dos "Tienda Don Carlos" en la misma región son dos negocios distintos: la
    identidad es el UUID. Si el nombre fuera único, el alta de un negocio podría
    fallar por lo que otro eligió llamarse, y los 409 permitirían enumerar los
    nombres de los demás negocios de la región.

    Que esto funcione es consecuencia directa de que el `name` de la
    Organization sea el `tenant_id`: con el nombre comercial ahí, Keycloak
    devolvería 409 y este test fallaría.
    """
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)

    uno = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Tienda Don Carlos")
    otro = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Tienda Don Carlos")

    assert uno["id"] != otro["id"]
    assert uno["kc_org_id"] != otro["kc_org_id"]


def test_el_nombre_se_valida(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    assert cliente.post("/api/v1/platform/tenants", json={"nombre": "x"}, headers=cabeceras).status_code == 422
    assert cliente.post("/api/v1/platform/tenants", json={"nombre": "  "}, headers=cabeceras).status_code == 422
    assert cliente.post("/api/v1/platform/tenants", json={"nombre": "z" * 200}, headers=cabeceras).status_code == 422


# --- Listado ----------------------------------------------------------------


def test_listar_pagina_y_cuenta(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    for i in range(3):
        _crear(cliente, cabeceras, f"{PREFIJO_PRUEBA}Negocio {i}")

    respuesta = cliente.get("/api/v1/platform/tenants?skip=0&limit=2", headers=cabeceras)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo["items"]) == 2
    assert cuerpo["total"] >= 3
    assert cuerpo["skip"] == 0 and cuerpo["limit"] == 2


def test_listar_con_limit_cero_se_rechaza_no_devuelve_todo(app_con_base):
    """`limit=0` es la forma barata de pedir "dámelo todo" sin que nadie lo note."""
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    assert cliente.get("/api/v1/platform/tenants?limit=0", headers=cabeceras).status_code == 422
    assert cliente.get("/api/v1/platform/tenants?limit=100000", headers=cabeceras).status_code == 422


def test_listar_con_skip_mas_alla_del_total_devuelve_vacio_no_error(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Único")
    respuesta = cliente.get("/api/v1/platform/tenants?skip=100000&limit=25", headers=cabeceras)
    assert respuesta.status_code == 200
    assert respuesta.json()["items"] == []


# --- Modificación y baja -----------------------------------------------------


def test_renombrar(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Antes")

    respuesta = cliente.patch(
        f"/api/v1/platform/tenants/{creado['id']}",
        json={"nombre": PREFIJO_PRUEBA + "Despues"},
        headers=cabeceras,
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["nombre"] == PREFIJO_PRUEBA + "Despues"


def test_renombrar_no_toca_keycloak(app_con_base):
    """Propiedad buscada: el rename no puede fallar porque el IdP esté caído.

    Es la consecuencia útil de que el `name` de la Organization sea el UUID.
    """
    cliente, validador, keycloak = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Antes")
    antes = dict(keycloak.organizaciones[creado["id"]])

    keycloak.fallar_al_crear = True  # cualquier llamada de escritura fallaría
    respuesta = cliente.patch(
        f"/api/v1/platform/tenants/{creado['id']}",
        json={"nombre": PREFIJO_PRUEBA + "Despues"},
        headers=cabeceras,
    )
    assert respuesta.status_code == 200
    assert keycloak.organizaciones[creado["id"]] == antes


def test_suspender(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Suspendible")

    respuesta = cliente.patch(
        f"/api/v1/platform/tenants/{creado['id']}",
        json={"estado": "suspendido"},
        headers=cabeceras,
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "suspendido"


def test_no_se_puede_eliminar_por_patch(app_con_base):
    """La baja tiene efectos en Keycloak; no puede ser efecto colateral de un PATCH."""
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Intocable")
    respuesta = cliente.patch(
        f"/api/v1/platform/tenants/{creado['id']}",
        json={"estado": "eliminado"},
        headers=cabeceras,
    )
    assert respuesta.status_code == 422


def test_eliminar_es_borrado_logico_y_borra_la_organizacion(app_con_base):
    cliente, validador, keycloak = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Baja")
    org_id = creado["kc_org_id"]

    assert cliente.delete(f"/api/v1/platform/tenants/{creado['id']}", headers=cabeceras).status_code == 204

    # Ya no aparece por los caminos normales…
    assert cliente.get(f"/api/v1/platform/tenants/{creado['id']}", headers=cabeceras).status_code == 404
    ids = [t["id"] for t in cliente.get("/api/v1/platform/tenants", headers=cabeceras).json()["items"]]
    assert creado["id"] not in ids
    # …pero la fila sobrevive para la auditoría, y se ve pidiéndola.
    con_eliminados = cliente.get("/api/v1/platform/tenants?incluir_eliminados=true", headers=cabeceras).json()
    assert creado["id"] in [t["id"] for t in con_eliminados["items"]]
    # Y la organización de Keycloak se borra: deshabilitarla no impide el login
    # (medido en el spike) y solo dejaría basura en el realm.
    assert org_id in keycloak.borradas
    assert creado["id"] not in keycloak.organizaciones


def test_eliminar_dos_veces_da_404_la_segunda(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Doble baja")
    assert cliente.delete(f"/api/v1/platform/tenants/{creado['id']}", headers=cabeceras).status_code == 204
    assert cliente.delete(f"/api/v1/platform/tenants/{creado['id']}", headers=cabeceras).status_code == 404


def test_operar_sobre_un_id_inexistente_da_404_no_500(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    fantasma = uuid.uuid4()
    assert cliente.get(f"/api/v1/platform/tenants/{fantasma}", headers=cabeceras).status_code == 404
    assert (
        cliente.patch(
            f"/api/v1/platform/tenants/{fantasma}", json={"nombre": "Otro nombre"}, headers=cabeceras
        ).status_code
        == 404
    )
    assert cliente.delete(f"/api/v1/platform/tenants/{fantasma}", headers=cabeceras).status_code == 404


def test_un_id_mal_formado_da_422_no_500(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    assert cliente.get("/api/v1/platform/tenants/no-soy-un-uuid", headers=cabeceras).status_code == 422


# --- Permisos ---------------------------------------------------------------


def test_sin_platform_admin_todo_el_router_responde_403(app_con_base):
    cliente, validador, _ = app_con_base
    validador.registrar("tok-dueno", usuario_de_negocio(uuid.uuid4()))
    cabeceras = {"Authorization": "Bearer tok-dueno"}

    assert cliente.get("/api/v1/platform/tenants", headers=cabeceras).status_code == 403
    assert cliente.post("/api/v1/platform/tenants", json={"nombre": "X Y"}, headers=cabeceras).status_code == 403
    assert cliente.delete(f"/api/v1/platform/tenants/{uuid.uuid4()}", headers=cabeceras).status_code == 403


# --- /tenants/me ------------------------------------------------------------


def test_tenants_me_devuelve_el_negocio_del_token(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Mi Negocio")

    validador.registrar("tok-mio", usuario_de_negocio(uuid.UUID(creado["id"])))
    respuesta = cliente.get("/api/v1/tenants/me", headers={"Authorization": "Bearer tok-mio"})

    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == creado["id"]
    assert respuesta.json()["nombre"] == PREFIJO_PRUEBA + "Mi Negocio"


def test_tenants_me_de_un_negocio_suspendido_da_403_tipado(app_con_base):
    """La suspensión es app-level: el token sigue siendo criptográficamente válido.

    El spike midió que deshabilitar la Organization NO impide el login ni
    invalida los tokens emitidos, así que el único control es este.
    """
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Moroso")
    validador.registrar("tok-moroso", usuario_de_negocio(uuid.UUID(creado["id"])))
    propias = {"Authorization": "Bearer tok-moroso"}

    assert cliente.get("/api/v1/tenants/me", headers=propias).status_code == 200

    cliente.patch(f"/api/v1/platform/tenants/{creado['id']}", json={"estado": "suspendido"}, headers=cabeceras)

    respuesta = cliente.get("/api/v1/tenants/me", headers=propias)
    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "tenant_suspendido"

    # Reactivar devuelve el acceso SIN volver a iniciar sesión: el mismo token.
    cliente.patch(f"/api/v1/platform/tenants/{creado['id']}", json={"estado": "activo"}, headers=cabeceras)
    assert cliente.get("/api/v1/tenants/me", headers=propias).status_code == 200


def test_tenants_me_de_un_negocio_dado_de_baja_da_404(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Cerrado")
    validador.registrar("tok-cerrado", usuario_de_negocio(uuid.UUID(creado["id"])))
    propias = {"Authorization": "Bearer tok-cerrado"}

    cliente.delete(f"/api/v1/platform/tenants/{creado['id']}", headers=cabeceras)

    respuesta = cliente.get("/api/v1/tenants/me", headers=propias)
    assert respuesta.status_code == 404
    assert respuesta.json()["code"] == "tenant_no_encontrado"


def test_un_token_con_una_organizacion_fantasma_no_entra(app_con_base):
    """Organización huérfana en Keycloak (la ventana de la compensación).

    El claim trae un alias que no existe en `tenants`. No puede ser un 500 ni,
    mucho menos, un acceso: es un 404 tipado.
    """
    cliente, validador, _ = app_con_base
    validador.registrar("tok-fantasma", usuario_de_negocio(uuid.uuid4()))
    respuesta = cliente.get("/api/v1/tenants/me", headers={"Authorization": "Bearer tok-fantasma"})
    assert respuesta.status_code == 404


# --- Auditoría --------------------------------------------------------------


@pytest.mark.asyncio
async def test_cada_mutacion_deja_su_fila_de_auditoria(app_con_base, pg_platform_url):
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Auditado")
    cliente.patch(f"/api/v1/platform/tenants/{creado['id']}", json={"estado": "suspendido"}, headers=cabeceras)
    cliente.delete(f"/api/v1/platform/tenants/{creado['id']}", headers=cabeceras)

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            filas = (
                await conn.execute(
                    text(
                        "SELECT action, user_id, correlation_id, status "
                        "FROM audit_events WHERE tenant_id = :t ORDER BY timestamp"
                    ),
                    {"t": creado["id"]},
                )
            ).all()
    finally:
        await engine.dispose()

    acciones = [f.action for f in filas]
    assert acciones == ["tenant.crear", "tenant.actualizar", "tenant.eliminar"]
    for fila in filas:
        assert fila.user_id == "admin-plataforma", "falta el actor en el rastro"
        assert fila.correlation_id, "falta el id de correlación en el rastro"
        assert fila.status == "success"


@pytest.mark.asyncio
async def test_el_alta_encola_el_evento_de_dominio_en_el_outbox(app_con_base, pg_platform_url):
    """El evento viaja en la MISMA transacción que el INSERT (patrón outbox).

    Y con `tenant_id` NULL: el alta de un negocio es un evento de PLATAFORMA. La
    clave de enrutado que publicará el dispatcher es `plataforma.tenant.creado`.
    """
    cliente, validador, _ = app_con_base
    cabeceras = _admin(cliente, validador)
    creado = _crear(cliente, cabeceras, PREFIJO_PRUEBA + "Con Evento")

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            fila = (
                await conn.execute(
                    text(
                        "SELECT tenant_id, exchange, routing_key, payload, status "
                        "FROM outbox_messages WHERE payload->>'resource_id' = :r"
                    ),
                    {"r": creado["id"]},
                )
            ).first()
    finally:
        await engine.dispose()

    assert fila is not None, "el alta no encoló ningún evento: el outbox no viajó con el INSERT"
    assert fila.tenant_id is None
    assert fila.exchange == "events.tenant"
    assert fila.routing_key == "plataforma.tenant.creado"
    assert fila.payload["event"] == "tenant.creado"
