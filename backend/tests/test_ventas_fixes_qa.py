"""Fixes de los cuatro bugs del QA adversarial de ventas (BUG-1..4).

Cada test reproduce el bug EXACTAMENTE como lo documenta
`.superpowers/sdd/qa-adversarial-ventas-report.md` y fija el comportamiento
correcto — los bugs ya no están «documentados en el reporte sin test», están
arreglados y candados aquí:

- BUG-1: un ticket con el mismo producto en dos líneas se reportaba
  `duplicada` y no persistía NADA (choque contra `ux_movimientos_origen`).
  Ahora se acepta y el libro consolida un movimiento por (venta, producto).
- BUG-2: `cantidad="0.0004"` redondeaba a 0 en NUMERIC(14,3) y reventaba el
  lote con 500, envenenando la cola del dispositivo. Ahora el schema cuantiza
  a 3 decimales (ROUND_HALF_UP, el mismo redondeo de la columna) y lo que
  cuantiza a cero es `datos_invalidos` por operación.
- BUG-3: una anulación con id de operación == id de la venta se reportaba
  `duplicada` sin anular. Los movimientos de reposición ahora son
  `tipo='anulacion'` y ya no chocan con los de la venta.
- BUG-4: registrar un dispositivo con el id de OTRO tenant era un 500 crudo.
  Ahora es un 409 tipado (`dispositivo_id_en_conflicto`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.ventas.schemas import DispositivoRegistrar, LoteSync
from app.modules.ventas.service import VentasService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import ConflictError
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """El mismo escenario del QA: T1 con un dispositivo y un producto."""
    ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4()}
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
        )
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                "VALUES (:p, :t, 'Arroz 500g', 2500, 10)"
            ),
            {"p": ids["producto"], "t": T1},
        )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def servicio(pg_app_url: str, semilla):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield VentasService(session=s, tenant_id=T1, actor_id="qa-fixes", puede_anular=True)
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


def _op_venta(semilla: dict, venta_id: uuid.UUID, secuencia: int = 1, **datos) -> dict:
    cuerpo = {
        "consecutivo_local": 1,
        "medio_pago": "efectivo",
        "total_centavos": 2500,
        "creada_en_cliente": datetime.now(UTC).isoformat(),
        "items": [{"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": 2500}],
        **datos,
    }
    return {"id": str(venta_id), "tipo": "venta.crear", "secuencia": secuencia, "datos": cuerpo}


def _op_anulacion(venta_id: uuid.UUID, secuencia: int, operacion_id: uuid.UUID | None = None) -> dict:
    return {
        "id": str(operacion_id or uuid.uuid4()),
        "tipo": "venta.anular",
        "secuencia": secuencia,
        "datos": {"venta_id": str(venta_id)},
    }


def _lote(semilla: dict, *operaciones: dict) -> LoteSync:
    return LoteSync.model_validate({"dispositivo_id": str(semilla["dispositivo"]), "operaciones": list(operaciones)})


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


async def _vender(servicio, semilla, venta_id: uuid.UUID, secuencia: int = 1, **datos) -> None:
    resultados = await servicio.procesar_lote(
        _lote(semilla, _op_venta(semilla, venta_id, secuencia=secuencia, **datos))
    )
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()


async def _stock(pg_platform_url: str, producto_id: uuid.UUID) -> Decimal:
    fila = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=producto_id)
    return fila.stock_actual


# --- BUG-1: el mismo producto en dos líneas del ticket --------------------------


async def test_el_ticket_con_el_mismo_producto_en_dos_lineas_se_acepta_y_consolida(servicio, semilla, pg_platform_url):
    """Repro exacta del reporte: dos líneas del mismo producto. Antes:
    `duplicada` sin persistir nada (la segunda línea chocaba contra la primera
    en `ux_movimientos_origen` y la venta cobrada se perdía en silencio).
    Ahora: `aceptada`, el ticket conserva sus dos líneas y el libro consolida
    UN movimiento por (venta, producto) con la cantidad sumada."""
    venta_id = uuid.uuid4()
    operacion = _op_venta(
        semilla,
        venta_id,
        items=[
            {"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": 2500},
            {"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": 2500},
        ],
        total_centavos=5000,
    )
    resultados = await servicio.procesar_lote(_lote(semilla, operacion))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()

    items = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas_items WHERE venta_id = :v", v=venta_id)
    assert items.n == 2, "las líneas del ticket quedan tal cual: la consolidación es del libro, no del ticket"
    movimiento = await _uno(
        pg_platform_url,
        "SELECT cantidad FROM movimientos_inventario WHERE referencia_id = :v AND tipo = 'venta'",
        v=venta_id,
    )
    assert movimiento.cantidad == Decimal("-2"), "un movimiento por (venta, producto) con la cantidad sumada"
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("8"), "stock descontado una vez, por la suma"

    # La idempotencia no cambia: el reintento byte-idéntico es `duplicada`.
    resultados = await servicio.procesar_lote(_lote(semilla, operacion))
    assert [r.resultado for r in resultados] == ["duplicada"]


# --- BUG-2: la cantidad que la columna redondea -----------------------------------


async def test_la_cantidad_que_cuantiza_a_cero_es_datos_invalidos_y_no_envenena_el_lote(
    servicio, semilla, pg_platform_url
):
    """Repro exacta del reporte: `0.0004` cuantiza a 0 en NUMERIC(14,3). Antes:
    IntegrityError sin traducir → 500 del lote entero y la cola del dispositivo
    envenenada para siempre. Ahora: `datos_invalidos` por operación y la venta
    buena que viene detrás en el lote se aplica."""
    veneno = _op_venta(
        semilla,
        uuid.uuid4(),
        secuencia=1,
        items=[{"producto_id": str(semilla["producto"]), "cantidad": "0.0004", "precio_unitario_centavos": 2500}],
        total_centavos=1,
    )
    buena = _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2)
    resultados = await servicio.procesar_lote(_lote(semilla, veneno, buena))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "datos_invalidos"), ("aceptada", None)]
    await servicio._session.commit()

    filas = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas WHERE tenant_id = :t", t=T1)
    assert filas.n == 1, "solo la buena: el veneno es rechazo de dominio, no 500 del lote"
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("9")


async def test_la_cantidad_de_cuatro_decimales_se_cuantiza_y_el_reintento_es_duplicada(
    servicio, semilla, pg_platform_url
):
    """El cuestionable-firmado 4 del reporte, curado de raíz: `0.0005` se
    cuantiza a `0.001` EN EL SCHEMA — el mismo redondeo que haría la columna—
    así que el reintento byte-idéntico compara lo mismo que se guardó y es
    `duplicada`, no `venta_id_divergente`."""
    venta_id = uuid.uuid4()
    operacion = _op_venta(
        semilla,
        venta_id,
        # El total cuadra con la cantidad CUANTIZADA (0.001 × 2000 = 2): es lo
        # que el dispositivo cobró por esa fracción de granel.
        items=[{"producto_id": str(semilla["producto"]), "cantidad": "0.0005", "precio_unitario_centavos": 2000}],
        total_centavos=2,
    )
    resultados = await servicio.procesar_lote(_lote(semilla, operacion))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()

    item = await _uno(pg_platform_url, "SELECT cantidad FROM ventas_items WHERE venta_id = :v", v=venta_id)
    assert item.cantidad == Decimal("0.001")

    resultados = await servicio.procesar_lote(_lote(semilla, operacion))
    assert [r.resultado for r in resultados] == ["duplicada"], "cliente y servidor comparan la MISMA cantidad"


# --- BUG-3: anulación con id de operación == id de la venta -----------------------


async def test_anular_con_el_id_de_la_venta_como_id_de_operacion_anula(servicio, semilla, pg_platform_url):
    """Repro exacta del reporte: el cliente deriva el id de la anulación del id
    de la venta («la anulación DE la venta V»). Antes: los movimientos de
    reposición chocaban con los de la venta en `ux_movimientos_origen` (mismo
    tipo `venta` y mismo referencia_id) y salía `duplicada` sin anular nada.
    Ahora la reposición usa `tipo='anulacion'`: comparte referencia sin chocar
    y la anulación se aplica."""
    venta_id = uuid.uuid4()
    await _vender(servicio, semilla, venta_id)
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("9")

    resultados = await servicio.procesar_lote(
        _lote(semilla, _op_anulacion(venta_id, secuencia=2, operacion_id=venta_id))
    )
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()

    fila = await _uno(pg_platform_url, "SELECT estado FROM ventas WHERE id = :v", v=venta_id)
    assert fila.estado == "anulada"
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("10"), "stock repuesto exactamente una vez"
    tipos = await _uno(
        pg_platform_url,
        "SELECT count(DISTINCT tipo) AS n FROM movimientos_inventario WHERE referencia_id = :v",
        v=venta_id,
    )
    assert tipos.n == 2, "el descuento ('venta') y la reposición ('anulacion') comparten referencia sin chocar"

    # El reintento de la misma anulación sigue deduplicado: `duplicada`, sin
    # reponer dos veces (lo decide el estado con FOR UPDATE, y el índice único
    # cubre (tipo, referencia_id=operacion.id, producto_id) como red).
    resultados = await servicio.procesar_lote(
        _lote(semilla, _op_anulacion(venta_id, secuencia=3, operacion_id=venta_id))
    )
    assert [r.resultado for r in resultados] == ["duplicada"]
    await servicio._session.commit()
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("10")


async def test_anular_un_ticket_con_lineas_consolidadas_repone_la_suma(servicio, semilla, pg_platform_url):
    """La pareja del fix de BUG-1: si la venta consolidó dos líneas del mismo
    producto en UN movimiento, su anulación también repone con UN movimiento
    (misma clave del índice: dos movimientos `anulacion` del mismo producto y
    la misma operación chocarían igual)."""
    venta_id = uuid.uuid4()
    await _vender(
        servicio,
        semilla,
        venta_id,
        items=[
            {"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": 2500},
            {"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": 2500},
        ],
        total_centavos=5000,
    )
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("8")

    resultados = await servicio.procesar_lote(_lote(semilla, _op_anulacion(venta_id, secuencia=2)))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("10")
    movimiento = await _uno(
        pg_platform_url,
        "SELECT cantidad FROM movimientos_inventario WHERE referencia_id != :v AND tipo = 'anulacion'",
        v=venta_id,
    )
    assert movimiento.cantidad == Decimal("2"), "la reposición también se consolida por producto"


# --- BUG-4: registrar dispositivo con id de otro tenant ---------------------------


async def test_registrar_un_dispositivo_con_el_id_de_otro_tenant_da_409_tipado(servicio, semilla, pg_platform_url):
    """Repro exacta del reporte: el id existe — en OTRO negocio. La RLS lo hace
    invisible, el INSERT revienta contra `dispositivos_pkey` y no hay existente
    que devolver. Antes: el IntegrityError original subía como 500. Ahora: 409
    `dispositivo_id_en_conflicto`, un error de dominio tipado."""
    ajeno = uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja ajena')"),
            {"d": ajeno, "t": T2},
        )
    await engine.dispose()

    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_dispositivo(DispositivoRegistrar(id=ajeno, nombre="Caja infiltrada"))
    assert exc.value.code == "dispositivo_id_en_conflicto"
    assert exc.value.status_code == 409
    await servicio._session.rollback()

    filas = await _uno(pg_platform_url, "SELECT count(*) AS n FROM dispositivos WHERE tenant_id = :t", t=T1)
    assert filas.n == 1, "el 409 no escribió nada: solo queda el dispositivo de la semilla"
    nombre = await _uno(pg_platform_url, "SELECT nombre FROM dispositivos WHERE id = :d", d=ajeno)
    assert nombre.nombre == "Caja ajena", "y el dispositivo del vecino, intacto"
