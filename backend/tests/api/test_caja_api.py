"""Los endpoints de caja y reportes contra el PostgreSQL real.

Misma regla que `test_inventario_api.py`: la base no se dobla, y cada test
crea su negocio por el camino real y opera con tokens de roles distintos,
porque lo que se mide aquí es quién puede hacer qué (ADR-023): el cajero
abre y mueve caja pero NO cierra, NO ve el esperado, NO ve el historial y
NO ve reportes; el almacenista no toca caja.
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


def _abrir(cliente, cabeceras, base: int = 50000) -> dict:
    respuesta = cliente.post("/api/v1/caja/sesiones", json={"base_inicial": base}, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _movimiento(**cambios) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "tipo": "egreso",
        "categoria": "servicios",
        "monto": 12000,
        "motivo": "Recibo de la luz",
        **cambios,
    }


# --- Apertura, movimientos y cierre -------------------------------------------------


def test_abrir_caja_devuelve_201_y_la_segunda_apertura_es_409(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 1")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d1")

    sesion = _abrir(cliente, cabeceras)
    assert sesion["estado"] == "abierta" and sesion["base_inicial"] == 50000

    segunda = cliente.post("/api/v1/caja/sesiones", json={"base_inicial": 30000}, headers=cabeceras)
    assert segunda.status_code == 409
    assert segunda.json()["code"] == "caja_ya_abierta"


def test_el_cajero_abre_y_mueve_caja_pero_no_cierra(app_con_base):
    """El reparto firmado de ADR-023: abrir y registrar movimientos es del
    cajero; cerrar/arquear es el gesto con dinero que queda en el dueño."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 2")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c2")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d2")

    sesion = _abrir(cliente, cajero, base=40000)
    alta = cliente.post("/api/v1/caja/movimientos", json=_movimiento(), headers=cajero)
    assert alta.status_code == 201, alta.text
    assert alta.json()["sesion_caja_id"] == sesion["id"]

    cierre_cajero = cliente.post(
        f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 40000}, headers=cajero
    )
    assert cierre_cajero.status_code == 403 and cierre_cajero.json()["code"] == "permiso_ausente"
    # Y el dueño sí cierra (distingue «deniega porque no lo tiene» de «deniega siempre»).
    cierre_dueno = cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 28000}, headers=dueno)
    assert cierre_dueno.status_code == 200, cierre_dueno.text
    cuerpo = cierre_dueno.json()
    assert cuerpo["efectivo_esperado"] == 28000  # base 40.000 − egreso 12.000
    assert cuerpo["diferencia"] == 0
    assert cuerpo["desglose"]["egresos"] == 12000


def test_el_almacenista_no_toca_caja(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 3")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a3")

    assert cliente.post("/api/v1/caja/sesiones", json={"base_inicial": 0}, headers=almacenista).status_code == 403
    assert cliente.get("/api/v1/caja/sesiones/actual", headers=almacenista).status_code == 403
    assert cliente.post("/api/v1/caja/movimientos", json=_movimiento(), headers=almacenista).status_code == 403
    assert cliente.get("/api/v1/caja/sesiones", headers=almacenista).status_code == 403


def test_el_cajero_no_ve_el_esperado_ni_el_historial(app_con_base):
    """Decisión 4: el esperado vivo viaja en null sin `caja:cerrar` (misma
    forma, mismo patrón que `ultimo_costo`), y el historial de arqueos es
    del dueño."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 4")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d4")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c4")
    _abrir(cliente, dueno, base=50000)

    vista_dueno = cliente.get("/api/v1/caja/sesiones/actual", headers=dueno)
    assert vista_dueno.status_code == 200 and vista_dueno.json()["efectivo_esperado"] == 50000
    vista_cajero = cliente.get("/api/v1/caja/sesiones/actual", headers=cajero)
    assert vista_cajero.status_code == 200
    assert "efectivo_esperado" in vista_cajero.json() and vista_cajero.json()["efectivo_esperado"] is None
    assert cliente.get("/api/v1/caja/sesiones", headers=cajero).status_code == 403
    assert cliente.get("/api/v1/caja/sesiones", headers=dueno).json()["total"] == 1


def test_el_movimiento_valida_cotas_motivo_y_forma(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 5")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d5")
    _abrir(cliente, cabeceras)

    # Monto que desborda Integer → 422, nunca 500 (lección BUG-2).
    assert cliente.post("/api/v1/caja/movimientos", json=_movimiento(monto=2**31), headers=cabeceras).status_code == 422
    assert cliente.post("/api/v1/caja/movimientos", json=_movimiento(monto=0), headers=cabeceras).status_code == 422
    assert cliente.post("/api/v1/caja/movimientos", json=_movimiento(motivo="  "), headers=cabeceras).status_code == 422
    assert (
        cliente.post("/api/v1/caja/movimientos", json=_movimiento(categoria="ropa"), headers=cabeceras).status_code
        == 422
    )
    # Un tenant_id inyectado → 422 por extra="forbid".
    assert (
        cliente.post(
            "/api/v1/caja/movimientos", json=_movimiento(tenant_id=str(uuid.uuid4())), headers=cabeceras
        ).status_code
        == 422
    )


def test_el_movimiento_sin_sesion_abierta_es_409(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 6")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d6")

    respuesta = cliente.post("/api/v1/caja/movimientos", json=_movimiento(), headers=cabeceras)
    assert respuesta.status_code == 409
    assert respuesta.json()["code"] == "caja_sin_sesion_abierta"


def test_el_reintento_del_movimiento_no_duplica_y_el_divergente_es_409(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 7")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d7")
    _abrir(cliente, cabeceras)

    datos = _movimiento()
    primero = cliente.post("/api/v1/caja/movimientos", json=datos, headers=cabeceras)
    segundo = cliente.post("/api/v1/caja/movimientos", json=datos, headers=cabeceras)
    assert primero.status_code == 201 and segundo.status_code == 201
    assert segundo.json()["id"] == datos["id"]
    lista = cliente.get("/api/v1/caja/movimientos", headers=cabeceras)
    assert lista.json()["total"] == 1
    divergente = cliente.post("/api/v1/caja/movimientos", json={**datos, "monto": 9999}, headers=cabeceras)
    assert divergente.status_code == 409 and divergente.json()["code"] == "movimiento_id_divergente"


def test_cerrar_desconocida_es_404_y_el_reintento_del_cierre_no_reabre(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 8")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d8")

    assert (
        cliente.post(f"/api/v1/caja/sesiones/{uuid.uuid4()}/cerrar", json={"contado": 0}, headers=cabeceras).status_code
        == 404
    )

    sesion = _abrir(cliente, cabeceras, base=0)
    primero = cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 0}, headers=cabeceras)
    reintento = cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 0}, headers=cabeceras)
    assert primero.status_code == 200 and reintento.status_code == 200
    assert reintento.json()["efectivo_esperado"] == 0 and reintento.json()["desglose"] is None
    otro_conteo = cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 100}, headers=cabeceras)
    assert otro_conteo.status_code == 409 and otro_conteo.json()["code"] == "caja_ya_cerrada"


def test_la_caja_de_otro_negocio_es_invisible(app_con_base):
    cliente, validador, _ = app_con_base
    negocio_a = _crear_negocio(cliente, validador, "Caja 9A")
    negocio_b = _crear_negocio(cliente, validador, "Caja 9B")
    cab_a = _cabeceras_de(validador, ROL_DUENO, negocio_a, "tok-d9a")
    cab_b = _cabeceras_de(validador, ROL_DUENO, negocio_b, "tok-d9b")
    sesion = _abrir(cliente, cab_a)

    # Cerrar la sesión del vecino: 404 (la RLS la hace invisible), no 200 ni 500.
    assert (
        cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 0}, headers=cab_b).status_code
        == 404
    )
    assert cliente.get("/api/v1/caja/sesiones", headers=cab_b).json()["total"] == 0
    assert cliente.get(f"/api/v1/caja/movimientos?sesion_id={sesion['id']}", headers=cab_b).status_code == 404


# --- Reportes ---------------------------------------------------------------------


def test_el_pyl_y_el_forecast_son_del_dueno(app_con_base):
    """ADR-023: el cajero no ve reportes; el almacenista tampoco."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 10")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d10")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c10")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a10")

    for cabeceras in (cajero, almacenista):
        assert cliente.get("/api/v1/reportes/pyl", headers=cabeceras).status_code == 403
        assert cliente.get("/api/v1/reportes/forecast", headers=cabeceras).status_code == 403

    pyl = cliente.get("/api/v1/reportes/pyl?periodo=dia", headers=dueno)
    assert pyl.status_code == 200, pyl.text
    cuerpo = pyl.json()
    assert cuerpo["ventas_netas_centavos"] == 0
    assert "ultimo_costo" in cuerpo["fuentes"]["costo_de_lo_vendido"]
    forecast = cliente.get("/api/v1/reportes/forecast", headers=dueno)
    assert forecast.status_code == 200
    assert forecast.json()["cobros_fiado_proyectados_centavos"] == 0
    assert forecast.json()["dias"] == 30


def test_el_periodo_invalido_es_422(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 11")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d11")

    assert cliente.get("/api/v1/reportes/pyl?periodo=trimestre", headers=cabeceras).status_code == 422
    assert cliente.get("/api/v1/reportes/pyl?fecha=28-07-2026", headers=cabeceras).status_code == 422
    assert cliente.get("/api/v1/reportes/pyl?periodo=semana&fecha=2026-07-28", headers=cabeceras).status_code == 200


def test_sin_sesion_abierta_la_actual_es_404(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 12")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d12")

    respuesta = cliente.get("/api/v1/caja/sesiones/actual", headers=cabeceras)
    assert respuesta.status_code == 404 and respuesta.json()["code"] == "caja_sin_sesion_abierta"


def test_sin_token_es_401(app_con_base):
    cliente, _, _ = app_con_base
    assert cliente.get("/api/v1/caja/sesiones/actual").status_code == 401
    assert cliente.post("/api/v1/caja/movimientos", json={}).status_code == 401
    assert cliente.get("/api/v1/reportes/pyl").status_code == 401
