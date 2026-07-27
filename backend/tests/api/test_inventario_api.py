"""Los endpoints de inventario y compras contra el PostgreSQL real.

Misma regla que `test_ventas_sync.py`: la base no se dobla, y cada test crea
su negocio por el camino real y opera con tokens de roles distintos, porque
lo que se mide aquí es quién puede hacer qué (ADR-023): el cajero NO ajusta
ni compra ni ve costos; el almacenista y el dueño sí.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_con_rol, usuario_de_plataforma

from vendi_core.auth.policies import ROL_ALMACENISTA, ROL_CAJERO, ROL_DUENO

pytestmark = pytest.mark.integration


def _dec(valor) -> Decimal:
    """Las cantidades viajan como número JSON (`1.0`, no `"1.000"`): se
    comparan como Decimal, que es lo que son (mismo helper que
    `test_catalogo_productos.py`)."""
    return Decimal(str(valor))


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


def _alta_producto(cliente, cabeceras, stock_minimo: str = "0") -> str:
    respuesta = cliente.post(
        "/api/v1/productos",
        json={"nombre": "Arroz 500g", "precio_venta": 2500, "stock_minimo": stock_minimo},
        headers=cabeceras,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _compra(producto_id: str, **cambios) -> dict:
    cuerpo = {
        "proveedor_nombre": "Distribuidora La 33",
        "items": [{"producto_id": producto_id, "cantidad": "10", "costo_unitario_centavos": 2000}],
        **cambios,
    }
    return cuerpo


def _ajuste(producto_id: str, **cambios) -> dict:
    cuerpo = {
        "id": str(uuid.uuid4()),
        "tipo": "ajuste",
        "producto_id": producto_id,
        "stock_contado": "8",
        "motivo": "Conteo de cierre",
        **cambios,
    }
    return cuerpo


# --- Compras ---------------------------------------------------------------------


def test_registrar_compra_devuelve_201_con_total_calculado(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 1")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d1")
    producto = _alta_producto(cliente, cabeceras)

    respuesta = cliente.post("/api/v1/compras", json=_compra(producto), headers=cabeceras)

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["proveedor_nombre"] == "Distribuidora La 33"
    assert cuerpo["total_centavos"] == 20000  # lo calculó el servidor: el cliente no lo envió
    assert cuerpo["items"][0]["costo_unitario_centavos"] == 2000


def test_la_compra_es_idempotente_por_el_id_del_cliente(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 2")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d2")
    producto = _alta_producto(cliente, cabeceras)
    el_id = str(uuid.uuid4())

    primero = cliente.post("/api/v1/compras", json=_compra(producto, id=el_id), headers=cabeceras)
    segundo = cliente.post("/api/v1/compras", json=_compra(producto, id=el_id), headers=cabeceras)

    assert primero.status_code == 201 and segundo.status_code == 201
    assert segundo.json()["id"] == el_id
    detalle = cliente.get(f"/api/v1/compras/{el_id}", headers=cabeceras)
    assert detalle.status_code == 200 and detalle.json()["total_centavos"] == 20000


def test_el_cajero_no_compra_ni_ve_compras(app_con_base):
    """ADR-023: el cajero no tiene `compra:crear`, y como los costos son el
    margen del negocio, la consulta usa el MISMO permiso (decisión 10)."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 3")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c3")

    alta = cliente.post("/api/v1/compras", json=_compra(str(uuid.uuid4())), headers=cajero)
    assert alta.status_code == 403 and alta.json()["code"] == "permiso_ausente"
    lista = cliente.get("/api/v1/compras", headers=cajero)
    assert lista.status_code == 403 and lista.json()["code"] == "permiso_ausente"
    detalle = cliente.get(f"/api/v1/compras/{uuid.uuid4()}", headers=cajero)
    assert detalle.status_code == 403


def test_el_almacenista_compra_y_consulta(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 4")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a4")
    producto = _alta_producto(cliente, almacenista)

    alta = cliente.post("/api/v1/compras", json=_compra(producto), headers=almacenista)
    assert alta.status_code == 201
    lista = cliente.get("/api/v1/compras", headers=almacenista)
    assert lista.status_code == 200 and lista.json()["total"] == 1


def test_la_compra_cuyo_total_desborda_la_columna_es_422(app_con_base):
    """El ejemplo literal de la revisión final (I1): una sola línea VÁLIDA
    (cantidad=10, costo=2^31-1) cuyo total no cabe en el `Integer` de
    `compras.total_centavos`. Sin la cota del servicio esto era un 500 del
    `DataError` de Postgres."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 12")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d12")
    producto = _alta_producto(cliente, cabeceras)

    respuesta = cliente.post(
        "/api/v1/compras",
        json=_compra(
            producto,
            items=[{"producto_id": producto, "cantidad": "10", "costo_unitario_centavos": 2_147_483_647}],
        ),
        headers=cabeceras,
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "total_fuera_de_rango"
    assert respuesta.json()["success"] is False


def test_la_compra_de_otro_negocio_es_404_sin_fuga(app_con_base):
    cliente, validador, _ = app_con_base
    negocio_a = _crear_negocio(cliente, validador, "Inv 5A")
    negocio_b = _crear_negocio(cliente, validador, "Inv 5B")
    cab_a = _cabeceras_de(validador, ROL_DUENO, negocio_a, "tok-d5a")
    cab_b = _cabeceras_de(validador, ROL_DUENO, negocio_b, "tok-d5b")
    producto = _alta_producto(cliente, cab_a)
    compra_id = cliente.post("/api/v1/compras", json=_compra(producto), headers=cab_a).json()["id"]

    assert cliente.get(f"/api/v1/compras/{compra_id}", headers=cab_b).status_code == 404
    assert cliente.get("/api/v1/compras", headers=cab_b).json()["total"] == 0


def test_la_compra_valida_cotas_y_forma(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 6")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d6")
    producto = _alta_producto(cliente, cabeceras)

    # Costo que desborda Integer → 422, nunca 500 (lección BUG-2).
    assert (
        cliente.post(
            "/api/v1/compras",
            json=_compra(
                producto, items=[{"producto_id": producto, "cantidad": "1", "costo_unitario_centavos": 2**31}]
            ),
            headers=cabeceras,
        ).status_code
        == 422
    )
    # El mismo producto en dos líneas → 422 (decisión 8).
    assert (
        cliente.post(
            "/api/v1/compras",
            json=_compra(
                producto,
                items=[
                    {"producto_id": producto, "cantidad": "1", "costo_unitario_centavos": 100},
                    {"producto_id": producto, "cantidad": "2", "costo_unitario_centavos": 100},
                ],
            ),
            headers=cabeceras,
        ).status_code
        == 422
    )
    # Un tenant_id inyectado → 422 por extra="forbid".
    assert (
        cliente.post(
            "/api/v1/compras", json=_compra(producto, tenant_id=str(uuid.uuid4())), headers=cabeceras
        ).status_code
        == 422
    )


# --- Ajustes ---------------------------------------------------------------------


def test_registrar_ajuste_devuelve_201_con_delta_y_nivel(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 7")
    cabeceras = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a7")
    producto = _alta_producto(cliente, cabeceras, stock_minimo="4")
    cliente.post("/api/v1/compras", json=_compra(producto), headers=cabeceras)  # stock 10, mínimo 4

    respuesta = cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto, stock_contado="3"), headers=cabeceras)

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert _dec(cuerpo["delta"]) == Decimal("-7") and _dec(cuerpo["stock_resultante"]) == Decimal("3")
    assert cuerpo["nivel"] == "bajo"


def test_el_cajero_no_ajusta_ni_ve_ajustes(app_con_base):
    """ADR-023: ajustar stock es un gesto con el que se desfalca una tienda."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 8")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d8")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c8")
    producto = _alta_producto(cliente, dueno)

    assert cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto), headers=cajero).status_code == 403
    assert cliente.get("/api/v1/inventario/ajustes", headers=cajero).status_code == 403
    # Y el dueño sí ajusta (distingue «deniega porque no lo tiene» de «deniega siempre»).
    assert cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto), headers=dueno).status_code == 201


def test_el_ajuste_exige_motivo_y_la_forma_de_su_tipo(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 9")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d9")
    producto = _alta_producto(cliente, cabeceras)

    assert (
        cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto, motivo="  "), headers=cabeceras).status_code
        == 422
    )
    assert (
        cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto, cantidad="2"), headers=cabeceras).status_code
        == 422
    )
    merma = _ajuste(producto, tipo="merma", cantidad="2", stock_contado=None, motivo="Se dañó")
    assert cliente.post("/api/v1/inventario/ajustes", json=merma, headers=cabeceras).status_code == 201


def test_el_ajuste_de_un_producto_desconocido_es_422(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 10")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d10")

    respuesta = cliente.post("/api/v1/inventario/ajustes", json=_ajuste(str(uuid.uuid4())), headers=cabeceras)
    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "producto_no_encontrado"


# --- Estado de stock ------------------------------------------------------------------


def test_el_estado_de_stock_lo_lee_cualquier_rol_con_nivel_derivado(app_con_base):
    """`producto:leer` (decisión 10): el cajero también ve los niveles — ya los
    ve en el POS vía delta. El nivel lo deriva el servidor."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 11")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d11")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c11")
    producto = _alta_producto(cliente, dueno, stock_minimo="4")
    cliente.post("/api/v1/compras", json=_compra(producto), headers=dueno)  # stock 10
    cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto, stock_contado="1"), headers=dueno)  # → 1: crítico

    respuesta = cliente.get("/api/v1/inventario/stock", headers=cajero)
    assert respuesta.status_code == 200
    (item,) = respuesta.json()["items"]
    assert item["nivel"] == "critico" and _dec(item["stock_actual"]) == Decimal("1")

    solo = cliente.get("/api/v1/inventario/stock?solo_alertas=true", headers=cajero)
    assert solo.status_code == 200 and solo.json()["total"] == 1


def test_sin_token_es_401(app_con_base):
    cliente, _, _ = app_con_base
    assert cliente.get("/api/v1/inventario/stock").status_code == 401
    assert cliente.post("/api/v1/compras", json={}).status_code == 401
