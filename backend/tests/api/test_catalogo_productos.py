"""El router `/api/v1/productos` contra el PostgreSQL real.

Misma regla que `test_tenants_crud.py`: la base no se dobla. Cada test crea
su negocio por el camino real (alta de plataforma) y opera con tokens de
roles distintos, porque lo que se mide aquí es quién puede hacer qué — y un
403 que aparece cuando NO debe es tan grave como un 200 que aparece cuando
no debe.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_con_rol, usuario_de_plataforma
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.auth.policies import ROL_ALMACENISTA, ROL_CAJERO, ROL_DUENO

pytestmark = pytest.mark.integration


def _dec(valor) -> Decimal:
    return Decimal(str(valor))


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


def _alta(cliente, cabeceras, **campos) -> dict:
    cuerpo = {"nombre": "Arroz 500g", "precio_venta": 2500, **campos}
    respuesta = cliente.post("/api/v1/productos", json=cuerpo, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# --- Alta y permisos ----------------------------------------------------------


def test_crear_producto_devuelve_201_con_sus_campos(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 1")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d1")

    cuerpo = _alta(cliente, dueno, codigo_barras="770100000001", iva_pct=5, categoria="Granos")

    assert uuid.UUID(cuerpo["id"])
    assert cuerpo["nombre"] == "Arroz 500g"
    assert cuerpo["precio_venta"] == 2500
    assert _dec(cuerpo["iva_pct"]) == Decimal("5")
    assert _dec(cuerpo["stock_actual"]) == Decimal("0")


def test_crear_requiere_producto_editar_y_el_cajero_no_lo_tiene(app_con_base):
    """El cajero vende con el catálogo pero no lo mantiene (ADR-023). El 403
    es la respuesta correcta y esperada, con sobre estándar y código."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 2")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c2")

    respuesta = cliente.post("/api/v1/productos", json={"nombre": "X", "precio_venta": 100}, headers=cajero)

    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "permiso_ausente"
    assert respuesta.json()["success"] is False


def test_el_cajero_si_puede_leer(app_con_base):
    """La pareja del anterior: distingue «deniega porque no lo tiene» de
    «deniega siempre» (el patrón de `test_un_rol_ausente_deniega_de_verdad`)."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 3")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d3")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c3")
    creado = _alta(cliente, dueno)

    assert cliente.get("/api/v1/productos", headers=cajero).status_code == 200
    assert cliente.get(f"/api/v1/productos/{creado['id']}", headers=cajero).status_code == 200


def test_el_almacenista_crea_edita_y_tambien_borra(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 4")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a4")

    creado = _alta(cliente, almacenista)
    respuesta = cliente.patch(f"/api/v1/productos/{creado['id']}", json={"precio_venta": 3000}, headers=almacenista)
    assert respuesta.status_code == 200
    assert respuesta.json()["precio_venta"] == 3000
    # ADR-023 reparte producto:editar al almacenista, y el borrado lógico es
    # una edición (un UPDATE de deleted_at), así que también puede:
    assert cliente.delete(f"/api/v1/productos/{creado['id']}", headers=almacenista).status_code == 204


def test_sin_token_da_401(app_sin_base):
    cliente, _, _ = app_sin_base
    assert cliente.get("/api/v1/productos").status_code == 401


# --- Lectura, búsqueda y listado ----------------------------------------------


def test_get_por_id_y_404_tipado(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 5")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d5")
    creado = _alta(cliente, dueno)

    assert cliente.get(f"/api/v1/productos/{creado['id']}", headers=dueno).json()["id"] == creado["id"]
    respuesta = cliente.get(f"/api/v1/productos/{uuid.uuid4()}", headers=dueno)
    assert respuesta.status_code == 404
    assert respuesta.json()["code"] == "producto_no_encontrado"


def test_un_producto_de_otro_negocio_es_un_404_no_una_fuga(app_con_base):
    """El id es válido y existe — pero en otro tenant. La RLS lo hace
    invisible y el 404 no revela ni que existe."""
    cliente, validador, _ = app_con_base
    negocio_a = _crear_negocio(cliente, validador, "Catálogo 6A")
    negocio_b = _crear_negocio(cliente, validador, "Catálogo 6B")
    dueno_a = _cabeceras_de(validador, ROL_DUENO, negocio_a, "tok-d6a")
    dueno_b = _cabeceras_de(validador, ROL_DUENO, negocio_b, "tok-d6b")
    creado = _alta(cliente, dueno_a)

    assert cliente.get(f"/api/v1/productos/{creado['id']}", headers=dueno_b).status_code == 404
    assert cliente.get("/api/v1/productos", headers=dueno_b).json()["total"] == 0


def test_buscar_por_codigo_de_barras(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 7")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d7")
    _alta(cliente, dueno, codigo_barras="770400000004")

    respuesta = cliente.get("/api/v1/productos/por-codigo/770400000004", headers=dueno)
    assert respuesta.status_code == 200
    assert respuesta.json()["nombre"] == "Arroz 500g"
    assert cliente.get("/api/v1/productos/por-codigo/000", headers=dueno).status_code == 404


def test_listado_paginado_con_filtro_de_nombre(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 8")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d8")
    for nombre in ("Arroz 500g", "Arroz integral", "Detergente"):
        _alta(cliente, dueno, nombre=nombre)

    respuesta = cliente.get("/api/v1/productos?q=arroz&skip=0&limit=1", headers=dueno)
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 2
    assert len(cuerpo["items"]) == 1
    assert cliente.get("/api/v1/productos?limit=0", headers=dueno).status_code == 422


# --- Integridad, idempotencia y borrado ---------------------------------------


def test_el_ean_duplicado_da_409_y_en_otro_tenant_no(app_con_base):
    cliente, validador, _ = app_con_base
    negocio_a = _crear_negocio(cliente, validador, "Catálogo 9A")
    negocio_b = _crear_negocio(cliente, validador, "Catálogo 9B")
    dueno_a = _cabeceras_de(validador, ROL_DUENO, negocio_a, "tok-d9a")
    dueno_b = _cabeceras_de(validador, ROL_DUENO, negocio_b, "tok-d9b")
    _alta(cliente, dueno_a, codigo_barras="770900000009")

    duplicado = cliente.post(
        "/api/v1/productos",
        json={"nombre": "Otro", "precio_venta": 100, "codigo_barras": "770900000009"},
        headers=dueno_a,
    )
    assert duplicado.status_code == 409
    assert duplicado.json()["code"] == "codigo_barras_duplicado"

    # El mismo EAN en OTRO negocio es válido (índice único por tenant):
    respuesta = cliente.post(
        "/api/v1/productos",
        json={"nombre": "Suyo", "precio_venta": 100, "codigo_barras": "770900000009"},
        headers=dueno_b,
    )
    assert respuesta.status_code == 201


def test_post_con_uuid_de_cliente_es_idempotente(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 10")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d10")
    el_id = str(uuid.uuid4())
    cuerpo = {"id": el_id, "nombre": "Huevo und", "precio_venta": 600}

    assert cliente.post("/api/v1/productos", json=cuerpo, headers=dueno).status_code == 201
    reintento = cliente.post("/api/v1/productos", json=cuerpo, headers=dueno)

    assert reintento.status_code == 201
    assert reintento.json()["id"] == el_id
    assert cliente.get("/api/v1/productos", headers=dueno).json()["total"] == 1


def test_eliminar_es_borrado_logico_y_libera_el_ean(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 11")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d11")
    creado = _alta(cliente, dueno, codigo_barras="771100000011")

    assert cliente.delete(f"/api/v1/productos/{creado['id']}", headers=dueno).status_code == 204
    assert cliente.get(f"/api/v1/productos/{creado['id']}", headers=dueno).status_code == 404
    assert cliente.get("/api/v1/productos", headers=dueno).json()["total"] == 0
    # El EAN queda libre para un alta nueva:
    assert (
        cliente.post(
            "/api/v1/productos",
            json={"nombre": "Re alta", "precio_venta": 100, "codigo_barras": "771100000011"},
            headers=dueno,
        ).status_code
        == 201
    )


def test_la_validacion_da_422(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 12")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d12")

    assert cliente.post("/api/v1/productos", json={"nombre": "X", "precio_venta": -5}, headers=dueno).status_code == 422
    assert (
        cliente.post(
            "/api/v1/productos", json={"nombre": "X", "precio_venta": 5, "iva_pct": 8}, headers=dueno
        ).status_code
        == 422
    )


def test_el_limite_del_tier_da_403(app_con_base, pg_platform_url):
    """El límite se fuerza sembrando 100 filas en SQL (100 altas por HTTP
    harían el test lento sin probar nada nuevo) y anulando el tier con
    `dependency_overrides`: el camino del check es el real."""
    from app.modules.catalogo.dependencies import tier_del_negocio

    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 13")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d13")

    valores = ", ".join(f"('{negocio}', 'Producto {i:03d}', 100)" for i in range(100))
    engine = create_async_engine(pg_platform_url)

    async def _sembrar():
        async with engine.begin() as conn:
            await conn.execute(text(f"INSERT INTO productos (tenant_id, nombre, precio_venta) VALUES {valores}"))
        await engine.dispose()

    import asyncio

    asyncio.run(_sembrar())

    cliente.app.dependency_overrides[tier_del_negocio] = lambda: "gratis"
    try:
        respuesta = cliente.post("/api/v1/productos", json={"nombre": "El 101", "precio_venta": 100}, headers=dueno)
        assert respuesta.status_code == 403
        assert respuesta.json()["code"] == "limite_de_productos_alcanzado"
        # Y con el tier del piloto (pro, sin límite) el mismo alta entra:
        cliente.app.dependency_overrides[tier_del_negocio] = lambda: "pro"
        assert (
            cliente.post("/api/v1/productos", json={"nombre": "El 101", "precio_venta": 100}, headers=dueno).status_code
            == 201
        )
    finally:
        cliente.app.dependency_overrides.clear()


# --- El costo no es para el cajero ------------------------------------------


def _compra(cliente, cabeceras, producto_id: str, costo: int = 2000) -> None:
    """Una compra real por el camino real: es la que puebla `ultimo_costo`
    (ADR-020). Sembrar la columna a mano no probaría el camino que la llena."""
    respuesta = cliente.post(
        "/api/v1/compras",
        json={
            "proveedor_nombre": "Distribuidora La 33",
            "items": [{"producto_id": producto_id, "cantidad": "10", "costo_unitario_centavos": costo}],
        },
        headers=cabeceras,
    )
    assert respuesta.status_code == 201, respuesta.text


def test_el_cajero_no_ve_el_ultimo_costo_en_ninguna_lectura(app_con_base):
    """Decisión firmada: los costos son el margen del negocio y viven tras
    `compra:crear`. El cajero lee el catálogo con `producto:leer`, así que el
    servidor le anula `ultimo_costo` en listado, detalle y búsqueda por
    código — el dato existe en base, pero no viaja en SU respuesta."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 15")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d15")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c15")
    creado = _alta(cliente, dueno, codigo_barras="771500000015")
    _compra(cliente, dueno, creado["id"])

    listado = cliente.get("/api/v1/productos", headers=cajero)
    assert listado.status_code == 200 and listado.json()["items"][0]["ultimo_costo"] is None
    detalle = cliente.get(f"/api/v1/productos/{creado['id']}", headers=cajero)
    assert detalle.status_code == 200 and detalle.json()["ultimo_costo"] is None
    escaner = cliente.get("/api/v1/productos/por-codigo/771500000015", headers=cajero)
    assert escaner.status_code == 200 and escaner.json()["ultimo_costo"] is None


def test_dueno_y_almacenista_si_ven_el_ultimo_costo(app_con_base):
    """La pareja del anterior: quien tiene `compra:crear` (dueño y
    almacenista) ve el costo que su compra acaba de fijar. Sin esta lectura,
    el null del cajero sería indistinguible de un costo que nunca se sirve."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 16")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d16")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a16")
    creado = _alta(cliente, dueno)
    _compra(cliente, dueno, creado["id"], costo=2000)

    for cabeceras in (dueno, almacenista):
        detalle = cliente.get(f"/api/v1/productos/{creado['id']}", headers=cabeceras)
        assert detalle.status_code == 200, detalle.text
        assert detalle.json()["ultimo_costo"] == 2000


def test_un_negocio_suspendido_no_opera_su_catalogo(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 14")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d14")
    cliente.patch(
        f"/api/v1/platform/tenants/{negocio}", json={"estado": "suspendido"}, headers=_admin(cliente, validador)
    )

    respuesta = cliente.get("/api/v1/productos", headers=dueno)
    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "tenant_suspendido"
