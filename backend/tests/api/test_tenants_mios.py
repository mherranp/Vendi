"""`GET /api/v1/tenants/mios`: los negocios del token, con nombre.

Existe para el selector de negocio de la consola web: el claim `organization`
del token lleva alias que SON el tenant_id (UUID), y elegir entre UUIDs no es
elegir. La ruta se sirve con el token validado y SIN resolver tenant (es la
excepción `RUTAS_SIN_TENANT` del middleware): quien tiene varios negocios y
todavía no ha elegido ninguno es exactamente su usuario.
"""

from __future__ import annotations

import uuid

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_de_negocio, usuario_de_plataforma

pytestmark = pytest.mark.integration


def _admin(cliente, validador, token: str = "tok-admin") -> dict:
    validador.registrar(token, usuario_de_plataforma())
    return {"Authorization": f"Bearer {token}"}


def _crear(cliente, cabeceras_admin, nombre: str) -> str:
    respuesta = cliente.post(
        "/api/v1/platform/tenants",
        json={"nombre": PREFIJO_PRUEBA + nombre},
        headers=cabeceras_admin,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def test_mios_devuelve_los_negocios_del_token_con_nombre(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras_admin = _admin(cliente, validador)
    id_a = _crear(cliente, cabeceras_admin, "Tienda A")
    id_b = _crear(cliente, cabeceras_admin, "Tienda B")

    validador.registrar("tok-mios", usuario_de_negocio(uuid.UUID(id_a), uuid.UUID(id_b)))
    # SIN cabecera X-Tenant-Id a propósito: el usuario aún no ha elegido.
    respuesta = cliente.get("/api/v1/tenants/mios", headers={"Authorization": "Bearer tok-mios"})

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    nombres = {fila["nombre"] for fila in cuerpo}
    assert nombres == {PREFIJO_PRUEBA + "Tienda A", PREFIJO_PRUEBA + "Tienda B"}
    for fila in cuerpo:
        assert set(fila) == {"id", "nombre", "estado"}
        assert fila["estado"] == "activo"


def test_mios_no_incluye_negocios_que_no_estan_en_el_token(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras_admin = _admin(cliente, validador)
    mio = _crear(cliente, cabeceras_admin, "La mia")
    _crear(cliente, cabeceras_admin, "La ajena")

    validador.registrar("tok-uno", usuario_de_negocio(uuid.UUID(mio)))
    respuesta = cliente.get("/api/v1/tenants/mios", headers={"Authorization": "Bearer tok-uno"})

    assert respuesta.status_code == 200, respuesta.text
    assert [fila["nombre"] for fila in respuesta.json()] == [PREFIJO_PRUEBA + "La mia"]


def test_mios_sin_organizaciones_devuelve_lista_vacia(app_con_base):
    cliente, validador, _ = app_con_base
    validador.registrar("tok-cero", usuario_de_negocio())
    respuesta = cliente.get("/api/v1/tenants/mios", headers={"Authorization": "Bearer tok-cero"})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == []


def test_mios_sin_token_es_401(app_con_base):
    cliente, _, _ = app_con_base
    respuesta = cliente.get("/api/v1/tenants/mios")
    assert respuesta.status_code == 401
