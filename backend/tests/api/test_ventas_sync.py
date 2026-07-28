"""Los endpoints del sync (`/api/v1/dispositivos`, `/api/v1/sync/*`) contra el
PostgreSQL real.

Misma regla que `test_catalogo_productos.py`: la base no se dobla. Cada test
crea su negocio por el camino real y opera con tokens de roles distintos,
porque lo que se mide aquí es quién puede hacer qué — el cajero sincroniza y
vende, pero NO anula (ADR-023).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_con_rol, usuario_de_plataforma

from vendi_core.auth.policies import ROL_ALMACENISTA, ROL_CAJERO, ROL_DUENO

pytestmark = pytest.mark.integration


def _admin(cliente, validador, token: str = "tok-admin") -> dict:
    validador.registrar(token, usuario_de_plataforma())
    return {"Authorization": f"Bearer {token}"}


def _crear_negocio(cliente, validador, nombre: str) -> str:
    respuesta = cliente.post(
        "/api/v1/platform/tenants", json={"nombre": PREFIJO_PRUEBA + nombre}, headers=_admin(cliente, validador)
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _cabeceras_de(validador, rol: str, tenant_id: str, token: str) -> dict:
    validador.registrar(token, usuario_con_rol(rol, uuid.UUID(tenant_id)))
    return {"Authorization": f"Bearer {token}"}


def _alta_producto(cliente, cabeceras, precio: int = 2500, stock=None) -> str:
    cuerpo = {"nombre": "Arroz 500g", "precio_venta": precio}
    respuesta = cliente.post("/api/v1/productos", json=cuerpo, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _registrar_dispositivo(cliente, cabeceras) -> str:
    respuesta = cliente.post("/api/v1/dispositivos", json={"nombre": "Caja 1"}, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _operacion_venta(producto_id: str, secuencia: int = 1) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "tipo": "venta.crear",
        "secuencia": secuencia,
        "datos": {
            "consecutivo_local": secuencia,
            "medio_pago": "efectivo",
            "total_centavos": 2500,
            "creada_en_cliente": datetime.now(UTC).isoformat(),
            "items": [{"producto_id": producto_id, "cantidad": "1", "precio_unitario_centavos": 2500}],
        },
    }


def _lote(dispositivo_id: str, producto_id: str, *operaciones: dict) -> dict:
    if not operaciones:
        operaciones = (_operacion_venta(producto_id),)
    return {"dispositivo_id": dispositivo_id, "operaciones": list(operaciones)}


def _montar(cliente, validador, nombre: str, rol: str = ROL_DUENO, token: str = "tok-d"):
    negocio = _crear_negocio(cliente, validador, nombre)
    cabeceras = _cabeceras_de(validador, rol, negocio, token)
    producto = _alta_producto(cliente, cabeceras)
    dispositivo = _registrar_dispositivo(cliente, cabeceras)
    return cabeceras, producto, dispositivo


# --- Dispositivos -----------------------------------------------------------------


def test_registrar_dispositivo_devuelve_201_y_es_idempotente(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras, _, _ = _montar(cliente, validador, "Sync 1")
    el_id = str(uuid.uuid4())

    primero = cliente.post("/api/v1/dispositivos", json={"id": el_id, "nombre": "Caja 1"}, headers=cabeceras)
    segundo = cliente.post("/api/v1/dispositivos", json={"id": el_id, "nombre": "Caja 1"}, headers=cabeceras)

    assert primero.status_code == 201
    assert segundo.status_code == 201
    assert segundo.json()["id"] == el_id


def test_registrar_dispositivo_exige_venta_crear(app_con_base):
    """El almacenista no vende (ADR-023): tampoco registra cajas."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Sync 2")
    almacenista = _cabeceras_de(validador, "almacenista", negocio, "tok-a2")

    respuesta = cliente.post("/api/v1/dispositivos", json={"nombre": "X"}, headers=almacenista)
    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "permiso_ausente"


# --- El lote ------------------------------------------------------------------------


def test_el_lote_se_aplica_y_responde_por_operacion(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 3")

    respuesta = cliente.post("/api/v1/sync/lotes", json=_lote(dispositivo, producto), headers=cabeceras)

    assert respuesta.status_code == 200, respuesta.text
    resultados = respuesta.json()["resultados"]
    assert [r["resultado"] for r in resultados] == ["aceptada"]


def test_el_mismo_lote_dos_veces_por_http_es_duplicada_la_segunda(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 4")
    lote = _lote(dispositivo, producto)

    assert cliente.post("/api/v1/sync/lotes", json=lote, headers=cabeceras).status_code == 200
    reintento = cliente.post("/api/v1/sync/lotes", json=lote, headers=cabeceras)

    assert reintento.status_code == 200
    assert [r["resultado"] for r in reintento.json()["resultados"]] == ["duplicada"]


def test_un_dispositivo_de_otro_negocio_es_un_422_no_una_fuga(app_con_base):
    """El dispositivo existe — pero en otro tenant. La RLS lo hace invisible
    y la respuesta no revela ni que existe (mismo criterio que el 404 del
    catálogo, aquí 422 por venir en el cuerpo)."""
    cliente, validador, _ = app_con_base
    _, producto, dispositivo_ajeno = _montar(cliente, validador, "Sync 5A", token="tok-d5a")
    cabeceras_b, _, _ = _montar(cliente, validador, "Sync 5B", token="tok-d5b")

    respuesta = cliente.post("/api/v1/sync/lotes", json=_lote(dispositivo_ajeno, producto), headers=cabeceras_b)
    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "dispositivo_no_encontrado"


def test_un_tenant_inyectado_en_el_payload_da_422(app_con_base):
    """`extra="forbid"` como defensa en profundidad del WITH CHECK (ADR-017)."""
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 6")
    lote = _lote(dispositivo, producto)
    lote["operaciones"][0]["datos"]["tenant_id"] = str(uuid.uuid4())

    respuesta = cliente.post("/api/v1/sync/lotes", json=lote, headers=cabeceras)
    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "campos_desconocidos"


def test_el_422_por_campo_desconocido_no_aplica_nada_del_lote(app_con_base):
    """La garantía firmada del 422: el lote entero hace rollback. La venta
    válida que compartía lote con la operación contaminada NO quedó a
    medias — al reenviarla sola debe salir `aceptada`; si saliera
    `duplicada`, habría commit parcial (un bug, no un test roto)."""
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 13")

    venta_valida = _operacion_venta(producto, secuencia=1)
    venta_contaminada = _operacion_venta(producto, secuencia=2)
    venta_contaminada["datos"]["tenant_id"] = str(uuid.uuid4())

    respuesta = cliente.post(
        "/api/v1/sync/lotes", json=_lote(dispositivo, producto, venta_valida, venta_contaminada), headers=cabeceras
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "campos_desconocidos"

    reenvio = cliente.post("/api/v1/sync/lotes", json=_lote(dispositivo, producto, venta_valida), headers=cabeceras)
    assert reenvio.status_code == 200, reenvio.text
    assert [r["resultado"] for r in reenvio.json()["resultados"]] == ["aceptada"]


def test_una_operacion_sin_datos_es_422_del_lote(app_con_base):
    """El 422 es del request entero (estructura malformada), no un rechazo por
    operación: el cliente que omite `datos` tiene un bug y nada se aplicó."""
    cliente, validador, _ = app_con_base
    cabeceras, _, dispositivo = _montar(cliente, validador, "Sync datos")
    lote = {
        "dispositivo_id": dispositivo,
        "operaciones": [{"id": str(uuid.uuid4()), "tipo": "venta.crear", "secuencia": 1}],
    }
    respuesta = cliente.post("/api/v1/sync/lotes", json=lote, headers=cabeceras)
    assert respuesta.status_code == 422


def test_el_lote_se_corta_en_200_operaciones(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 7")
    lote = _lote(dispositivo, producto)
    lote["operaciones"] = lote["operaciones"] * 201

    assert cliente.post("/api/v1/sync/lotes", json=lote, headers=cabeceras).status_code == 422


def test_el_cajero_sincroniza_y_vende_pero_su_anulacion_se_rechaza(app_con_base):
    """ADR-023 en el sync: el guard del endpoint es `venta:crear` (el cajero
    drena su cola), y la anulación se rechaza POR OPERACIÓN con
    `permiso_ausente` — la cola del cajero no se detiene por ella."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Sync 8")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d8")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c8")
    producto = _alta_producto(cliente, dueno)
    dispositivo = _registrar_dispositivo(cliente, cajero)

    # El cajero vende:
    venta_id = str(uuid.uuid4())
    lote_venta = _lote(dispositivo, producto)
    lote_venta["operaciones"][0]["id"] = venta_id
    respuesta = cliente.post("/api/v1/sync/lotes", json=lote_venta, headers=cajero)
    assert [r["resultado"] for r in respuesta.json()["resultados"]] == ["aceptada"]

    # ...pero NO anula:
    lote_anula = _lote(
        dispositivo,
        producto,
        {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 2, "datos": {"venta_id": venta_id}},
    )
    respuesta = cliente.post("/api/v1/sync/lotes", json=lote_anula, headers=cajero)
    resultado = respuesta.json()["resultados"][0]
    assert resultado["resultado"] == "rechazada"
    assert resultado["motivo"] == "permiso_ausente"

    # Y el dueño sí:
    respuesta = cliente.post("/api/v1/sync/lotes", json=lote_anula, headers=dueno)
    assert [r["resultado"] for r in respuesta.json()["resultados"]] == ["aceptada"]


def test_el_lote_mixto_del_cajero_acepta_la_venta_y_rechaza_la_anulacion(app_con_base):
    """ADR-023 dentro del mismo lote: la creación del cajero sale `aceptada`
    y su anulación `rechazada` con `permiso_ausente`, ambas en la misma
    respuesta 200 — la cola del cajero no se detiene por la anulación."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Sync 14")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d14")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c14")
    producto = _alta_producto(cliente, dueno)
    dispositivo = _registrar_dispositivo(cliente, cajero)

    venta = _operacion_venta(producto, secuencia=1)
    anulacion = {
        "id": str(uuid.uuid4()),
        "tipo": "venta.anular",
        "secuencia": 2,
        "datos": {"venta_id": venta["id"]},
    }

    respuesta = cliente.post("/api/v1/sync/lotes", json=_lote(dispositivo, producto, venta, anulacion), headers=cajero)

    assert respuesta.status_code == 200, respuesta.text
    resultados = respuesta.json()["resultados"]
    assert [r["resultado"] for r in resultados] == ["aceptada", "rechazada"]
    assert resultados[1]["motivo"] == "permiso_ausente"


def test_un_negocio_suspendido_no_sincroniza(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Sync 9")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d9")
    producto = _alta_producto(cliente, cabeceras)
    dispositivo = _registrar_dispositivo(cliente, cabeceras)
    cliente.patch(
        f"/api/v1/platform/tenants/{negocio}", json={"estado": "suspendido"}, headers=_admin(cliente, validador)
    )

    respuesta = cliente.post("/api/v1/sync/lotes", json=_lote(dispositivo, producto), headers=cabeceras)
    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "tenant_suspendido"


# --- El delta -----------------------------------------------------------------------


def test_el_delta_baja_el_catalogo_y_las_tumbas(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 10")

    desde = "2020-01-01T00:00:00+00:00"
    respuesta = cliente.get("/api/v1/sync/delta", params={"desde": desde}, headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert producto in [p["id"] for p in cuerpo["productos"]]
    assert cuerpo["eliminados"] == []
    hasta = cuerpo["hasta"]

    # El watermark lleva el margen de solape de D-18 (`now() - 5s`): lo
    # confirmado dentro del margen —como este producto, creado hace un
    # instante— se re-entrega en el siguiente delta, y el cliente lo absorbe
    # con su upsert por id. Nada MÁS nuevo puede llegar:
    respuesta = cliente.get("/api/v1/sync/delta", params={"desde": hasta}, headers=cabeceras)
    assert [p["id"] for p in respuesta.json()["productos"]] == [producto]

    # Una baja lógica llega como tumba:
    assert cliente.delete(f"/api/v1/productos/{producto}", headers=cabeceras).status_code == 204
    respuesta = cliente.get("/api/v1/sync/delta", params={"desde": desde}, headers=cabeceras)
    assert producto in respuesta.json()["eliminados"]


def test_el_delta_no_muestra_el_catalogo_del_vecino(app_con_base):
    cliente, validador, _ = app_con_base
    _montar(cliente, validador, "Sync 11A", token="tok-d11a")
    cabeceras_b, _, _ = _montar(cliente, validador, "Sync 11B", token="tok-d11b")

    respuesta = cliente.get("/api/v1/sync/delta", params={"desde": "2020-01-01T00:00:00+00:00"}, headers=cabeceras_b)
    assert len(respuesta.json()["productos"]) == 1, "solo el producto del negocio B, no el del A"


def test_el_delta_valida_el_watermark(app_con_base):
    """Sin `desde` es 422 de FastAPI (query param requerido); con fecha naive
    es 422 tipado del handler — un watermark sin zona no dice nada."""
    cliente, validador, _ = app_con_base
    cabeceras, _, _ = _montar(cliente, validador, "Sync 12")

    assert cliente.get("/api/v1/sync/delta", headers=cabeceras).status_code == 422
    respuesta = cliente.get("/api/v1/sync/delta?desde=2020-01-01", headers=cabeceras)
    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "fecha_sin_zona"


def test_el_delta_sirve_el_costo_solo_a_quien_tiene_compra_crear(app_con_base):
    """La fuga residual del fix C1: el cajero sincroniza el catálogo al
    IndexedDB del POS por este endpoint, así que la misma regla de los
    endpoints de productos aplica aquí — `ultimo_costo` viaja solo para
    quien tiene `compra:crear` y el campo SIGUE presente (null) en el
    contrato que el POS consume. Dueño y almacenista reciben el costo real
    que su compra fijó."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Sync 13")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d13")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c13")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a13")
    producto = _alta_producto(cliente, dueno)
    compra = cliente.post(
        "/api/v1/compras",
        json={
            "proveedor_nombre": "Distribuidora La 33",
            "items": [{"producto_id": producto, "cantidad": "10", "costo_unitario_centavos": 2000}],
        },
        headers=dueno,
    )
    assert compra.status_code == 201, compra.text

    desde = {"desde": "2020-01-01T00:00:00+00:00"}

    respuesta = cliente.get("/api/v1/sync/delta", params=desde, headers=cajero)
    assert respuesta.status_code == 200, respuesta.text
    (unico,) = respuesta.json()["productos"]
    assert unico["id"] == producto
    assert "ultimo_costo" in unico, "el campo sigue en el contrato que el POS consume"
    assert unico["ultimo_costo"] is None

    for cabeceras in (dueno, almacenista):
        respuesta = cliente.get("/api/v1/sync/delta", params=desde, headers=cabeceras)
        assert respuesta.status_code == 200, respuesta.text
        (unico,) = respuesta.json()["productos"]
        assert unico["ultimo_costo"] == 2000
