"""Los endpoints de clientes y del cuaderno contra el PostgreSQL real.

Misma regla que `test_caja_api.py`: la base no se dobla, cada test crea su
negocio por el camino real y opera con tokens de roles distintos, porque lo
que se mide aquí es quién puede hacer qué (ADR-023): el cajero gestiona
clientes, fía y cobra; el almacenista recibe 403 en todo lo del fiado.
"""

from __future__ import annotations

import uuid

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_con_rol, usuario_de_plataforma

from vendi_core.auth.policies import ROL_ALMACENISTA, ROL_CAJERO, ROL_DUENO

pytestmark = pytest.mark.integration


def _admin(validador, token: str = "tok-admin") -> dict:
    validador.registrar(token, usuario_de_plataforma())
    return {"Authorization": f"Bearer {token}"}


def _crear_negocio(cliente, validador, nombre: str) -> str:
    respuesta = cliente.post(
        "/api/v1/platform/tenants", json={"nombre": PREFIJO_PRUEBA + nombre}, headers=_admin(validador)
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _cabeceras_de(validador, rol: str, tenant_id: str, token: str) -> dict:
    validador.registrar(token, usuario_con_rol(rol, uuid.UUID(tenant_id)))
    return {"Authorization": f"Bearer {token}"}


def _cliente(cliente_http, cabeceras, **cambios) -> dict:
    datos = {"nombre": "Don Carlos", "telefono": "300 123 4567", "limite_credito": 100000, **cambios}
    respuesta = cliente_http.post("/api/v1/clientes", json=datos, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _fiado(dispositivo: str, cliente_id: str, total: int, consecutivo: int = 1) -> tuple[str, dict]:
    """Una venta fiada por el camino real del sync: es donde nace el crédito."""
    venta_id = str(uuid.uuid4())
    lote = {
        "dispositivo_id": dispositivo,
        "operaciones": [
            {
                "id": venta_id,
                "tipo": "venta.crear",
                "secuencia": 1,
                "datos": {
                    "consecutivo_local": consecutivo,
                    "medio_pago": "fiado",
                    "total_centavos": total,
                    "cliente_id": cliente_id,
                    "creada_en_cliente": "2026-07-28T10:00:00+00:00",
                    "fecha_vencimiento": "2026-08-15",
                    "items": [{"producto_id": None, "cantidad": "1", "precio_unitario_centavos": total}],
                },
            }
        ],
    }
    return venta_id, lote


def _alta_minima(cliente_http, cabeceras):
    """Producto + dispositivo + caja abierta: lo mínimo para fiar y cobrar."""
    producto = cliente_http.post(
        "/api/v1/productos",
        json={"nombre": "Arroz 500g", "precio_venta": 2500},
        headers=cabeceras,
    )
    assert producto.status_code == 201, producto.text
    dispositivo = cliente_http.post("/api/v1/dispositivos", json={"nombre": "Caja 1"}, headers=cabeceras)
    assert dispositivo.status_code == 201, dispositivo.text
    caja = cliente_http.post("/api/v1/caja/sesiones", json={"base_inicial": 0}, headers=cabeceras)
    assert caja.status_code == 201, caja.text
    return producto.json()["id"], dispositivo.json()["id"]


def test_el_cajero_gestiona_clientes_y_el_almacenista_no(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 1")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c1")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a1")

    creado = _cliente(cliente, cajero)
    assert creado["telefono"] == "3001234567"
    assert cliente.get("/api/v1/clientes", headers=cajero).json()["total"] == 1
    assert cliente.post("/api/v1/clientes", json={"nombre": "Otro"}, headers=almacenista).status_code == 403
    assert cliente.get("/api/v1/clientes", headers=almacenista).status_code == 403
    assert cliente.get(f"/api/v1/clientes/{creado['id']}", headers=almacenista).status_code == 403


def test_el_alta_de_cliente_es_idempotente_por_su_id(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 2")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d2")
    ancla = str(uuid.uuid4())
    datos = {"id": ancla, "nombre": "El pipe"}

    primero = cliente.post("/api/v1/clientes", json=datos, headers=dueno)
    assert primero.status_code == 201
    segundo = cliente.post("/api/v1/clientes", json=datos, headers=dueno)
    assert segundo.status_code == 201 and segundo.json()["id"] == ancla
    divergente = cliente.post("/api/v1/clientes", json={**datos, "nombre": "Otro"}, headers=dueno)
    assert divergente.status_code == 409 and divergente.json()["code"] == "cliente_id_divergente"


def test_la_ficha_trae_saldo_y_cupo(app_con_base):
    """El saldo se calcula en cada lectura (ADR-022) y el cupo viaja con él
    (decisión 8): 120.000 fiados con límite 100.000 → `cupo_excedido`."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 3")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d3")
    producto_id, dispositivo_id = _alta_minima(cliente, dueno)
    don_carlos = _cliente(cliente, dueno)

    venta_id, lote = _fiado(dispositivo_id, don_carlos["id"], 120000)
    lote["operaciones"][0]["datos"]["items"][0]["producto_id"] = producto_id
    sync = cliente.post("/api/v1/sync/lotes", json=lote, headers=dueno)
    assert sync.status_code == 200, sync.text
    assert sync.json()["resultados"][0]["resultado"] == "aceptada"
    assert sync.json()["resultados"][0]["detalles"] == {"cupo_excedido": True}

    ficha = cliente.get(f"/api/v1/clientes/{don_carlos['id']}", headers=dueno)
    assert ficha.status_code == 200
    cuerpo = ficha.json()
    assert cuerpo["saldo_pendiente_total"] == 120000 and cuerpo["cupo_excedido"] is True
    assert len(cuerpo["creditos"]) == 1 and cuerpo["creditos"][0]["estado"] == "vigente"


def test_el_abono_descuenta_y_el_cuaderno_lo_cuenta(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 4")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d4")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c4")
    producto_id, dispositivo_id = _alta_minima(cliente, dueno)
    don_carlos = _cliente(cliente, dueno, limite_credito=None)
    venta_id, lote = _fiado(dispositivo_id, don_carlos["id"], 100000)
    lote["operaciones"][0]["datos"]["items"][0]["producto_id"] = producto_id
    assert cliente.post("/api/v1/sync/lotes", json=lote, headers=dueno).status_code == 200

    cuaderno = cliente.get("/api/v1/fiado/creditos", headers=cajero)
    assert cuaderno.status_code == 200 and cuaderno.json()["total"] == 1
    credito = cuaderno.json()["items"][0]
    assert credito["cliente_nombre"] == "Don Carlos"

    abono_id = str(uuid.uuid4())
    abono = cliente.post(
        f"/api/v1/fiado/creditos/{credito['id']}/abonos",
        json={"id": abono_id, "monto": 30000, "metodo_pago": "efectivo"},
        headers=cajero,  # el cajero cobra (ADR-023)
    )
    assert abono.status_code == 201, abono.text
    reintento = cliente.post(
        f"/api/v1/fiado/creditos/{credito['id']}/abonos",
        json={"id": abono_id, "monto": 30000, "metodo_pago": "efectivo"},
        headers=cajero,
    )
    assert reintento.status_code == 201  # idempotente: no descuenta dos veces
    detalle = cliente.get(f"/api/v1/fiado/creditos/{credito['id']}", headers=dueno)
    assert detalle.json()["saldo_pendiente"] == 70000
    assert len(detalle.json()["abonos"]) == 1
    assert detalle.json()["whatsapp_url"].startswith("https://wa.me/573001234567?text=")


def test_el_abono_mayor_que_el_saldo_es_422(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 5")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d5")
    producto_id, dispositivo_id = _alta_minima(cliente, dueno)
    don_carlos = _cliente(cliente, dueno, limite_credito=None)
    venta_id, lote = _fiado(dispositivo_id, don_carlos["id"], 40000)
    lote["operaciones"][0]["datos"]["items"][0]["producto_id"] = producto_id
    assert cliente.post("/api/v1/sync/lotes", json=lote, headers=dueno).status_code == 200
    credito = cliente.get("/api/v1/fiado/creditos", headers=dueno).json()["items"][0]

    exceso = cliente.post(
        f"/api/v1/fiado/creditos/{credito['id']}/abonos",
        json={"id": str(uuid.uuid4()), "monto": 41000, "metodo_pago": "efectivo"},
        headers=dueno,
    )
    assert exceso.status_code == 422 and exceso.json()["code"] == "abono_excede_saldo"


def test_el_almacenista_recibe_403_en_todo_el_cuaderno(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 6")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a6")
    cualquiera = str(uuid.uuid4())
    assert cliente.get("/api/v1/fiado/creditos", headers=almacenista).status_code == 403
    assert cliente.get(f"/api/v1/fiado/creditos/{cualquiera}", headers=almacenista).status_code == 403
    assert (
        cliente.patch(
            f"/api/v1/fiado/creditos/{cualquiera}", json={"fecha_vencimiento": "2026-09-01"}, headers=almacenista
        ).status_code
        == 403
    )
    abono = cliente.post(
        f"/api/v1/fiado/creditos/{cualquiera}/abonos",
        json={"id": str(uuid.uuid4()), "monto": 1000, "metodo_pago": "efectivo"},
        headers=almacenista,
    )
    assert abono.status_code == 403 and abono.json()["code"] == "permiso_ausente"


def test_el_credito_del_vecino_es_invisible(app_con_base):
    cliente, validador, _ = app_con_base
    negocio_a = _crear_negocio(cliente, validador, "Fiado 7A")
    negocio_b = _crear_negocio(cliente, validador, "Fiado 7B")
    dueno_a = _cabeceras_de(validador, ROL_DUENO, negocio_a, "tok-d7a")
    dueno_b = _cabeceras_de(validador, ROL_DUENO, negocio_b, "tok-d7b")
    don_carlos = _cliente(cliente, dueno_a)

    assert cliente.get(f"/api/v1/clientes/{don_carlos['id']}", headers=dueno_b).status_code == 404
    assert cliente.get("/api/v1/clientes", headers=dueno_b).json()["total"] == 0
    assert cliente.get("/api/v1/fiado/creditos", headers=dueno_b).json()["total"] == 0
    abono_ajeno = cliente.post(
        f"/api/v1/fiado/creditos/{uuid.uuid4()}/abonos",
        json={"id": str(uuid.uuid4()), "monto": 1000, "metodo_pago": "otro"},
        headers=dueno_b,
    )
    assert abono_ajeno.status_code == 404


def test_las_cotas_son_422_nunca_500(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 8")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d8")
    assert cliente.post("/api/v1/clientes", json={"nombre": "X"}, headers=dueno).status_code == 422
    assert (
        cliente.post("/api/v1/clientes", json={"nombre": "Ok", "limite_credito": 2**31}, headers=dueno).status_code
        == 422
    )
    assert cliente.post("/api/v1/clientes", json={"nombre": "Ok", "telefono": "123"}, headers=dueno).status_code == 422
    assert (
        cliente.post(
            "/api/v1/clientes", json={"nombre": "Ok", "tenant_id": str(uuid.uuid4())}, headers=dueno
        ).status_code
        == 422
    )
    mal_metodo = cliente.post(
        f"/api/v1/fiado/creditos/{uuid.uuid4()}/abonos",
        json={"id": str(uuid.uuid4()), "monto": 100, "metodo_pago": "nequi"},
        headers=dueno,
    )
    assert mal_metodo.status_code == 422
