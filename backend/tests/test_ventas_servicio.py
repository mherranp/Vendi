"""`VentasService` contra el PostgreSQL real, con el rol `vendi_app`.

Misma regla que `test_catalogo_servicio.py`: la base no se dobla. Aquí se
fijan los comportamientos firmados del sync que no son la idempotencia (esa
tiene su propio archivo): orden de recepción como verdad, reloj del cliente
como dato, sesión implícita, divergencia de payload, fiado y anulación.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta, timezone
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
from vendi_core.errors.domain import ValidationError
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
    ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4(), "producto2": uuid.uuid4()}
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
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                "VALUES (:p, :t, 'Huevo und', 600, 3)"
            ),
            {"p": ids["producto2"], "t": T1},
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
            yield VentasService(session=s, tenant_id=T1, actor_id="cajero-prueba", puede_anular=True)
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


def _lote(semilla: dict, *operaciones: dict) -> LoteSync:
    return LoteSync.model_validate({"dispositivo_id": str(semilla["dispositivo"]), "operaciones": list(operaciones)})


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


# --- Dispositivos ---------------------------------------------------------------


async def test_registrar_dispositivo_es_idempotente_por_el_id_del_cliente(servicio):
    el_id = uuid.uuid4()
    primero = await servicio.registrar_dispositivo(DispositivoRegistrar(id=el_id, nombre="Caja 1"))
    segundo = await servicio.registrar_dispositivo(DispositivoRegistrar(id=el_id, nombre="Caja 1"))
    assert primero.id == segundo.id == el_id


async def test_lote_de_un_dispositivo_desconocido_es_422_de_lote_entero(servicio, semilla):
    """El dispositivo se valida ANTES de la primera operación: sin él no hay
    lote y el 422 es del lote entero, no un rechazo por operación (no hay a
    quién anclar secuencias ni sync). Un id de OTRO negocio da el mismo
    veredicto, porque la RLS lo hace invisible."""
    fantasma = LoteSync.model_validate(
        {"dispositivo_id": str(uuid.uuid4()), "operaciones": [_op_venta(semilla, uuid.uuid4())]}
    )
    with pytest.raises(ValidationError) as exc:
        await servicio.procesar_lote(fantasma)
    assert exc.value.code == "dispositivo_no_encontrado"


# --- Aplicación de ventas -------------------------------------------------------


async def test_aplicar_una_venta_descuenta_stock_abre_sesion_implicita_y_emite_evento(
    servicio, semilla, pg_platform_url
):
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4())))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()

    fila = await _uno(pg_platform_url, "SELECT estado, medio_pago FROM ventas WHERE tenant_id = :t", t=T1)
    assert fila.estado == "completada"
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == Decimal("9")
    sesiones = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta'",
        t=T1,
    )
    assert sesiones.n == 1, "ADR-018: sin sesión abierta, el servidor abre UNA implícita"
    eventos = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k", k=f"{T1}.venta.creada"
    )
    assert eventos.n == 1


async def test_la_segunda_venta_reusa_la_sesion_implicita(servicio, semilla, pg_platform_url):
    await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), secuencia=1)))
    await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2)))
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM caja_sesiones WHERE tenant_id = :t", t=T1)
    assert fila.n == 1


async def test_el_stock_puede_quedar_negativo_y_la_venta_se_acepta(servicio, semilla, pg_platform_url):
    """ADR-020: la tienda ya vendió físicamente esa unidad; bloquear la venta
    por el stock del servidor rompería justo el escenario del offline."""
    datos = {
        "items": [{"producto_id": str(semilla["producto2"]), "cantidad": "5", "precio_unitario_centavos": 600}],
        "total_centavos": 3000,
    }
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), **datos)))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto2"])
    assert stock.stock_actual == Decimal("-2")


async def test_el_reloj_del_cliente_es_dato_y_la_verdad_es_recibida_en(servicio, semilla, pg_platform_url):
    """El escenario de QA «reloj adelantado/atrasado»: se acepta y se guarda
    para el ticket, pero el orden lo da el servidor."""
    datos = {"creada_en_cliente": "1999-12-31T23:00:00-05:00"}
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), **datos)))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT creada_en_cliente, recibida_en FROM ventas WHERE tenant_id = :t", t=T1)
    # `timestamptz` guarda el INSTANTE: la lectura llega en UTC (2000-01-01
    # 04:00Z), así que se compara el instante, no la hora de pared del cliente.
    esperado = datetime(1999, 12, 31, 23, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert fila.creada_en_cliente == esperado, "el dato del ticket se conserva tal cual"
    assert fila.recibida_en.year >= 2026, "la verdad temporal es del servidor"


async def test_las_operaciones_se_aplican_en_el_orden_del_lote_no_del_reloj(servicio, semilla, pg_platform_url):
    """Fuera de orden: la secuencia 2 llega en el mismo lote ANTES que la 1
    (la cola del dispositivo se reordenó). Las dos se aceptan y el orden de
    recepción es la verdad (ADR-017)."""
    v2, v1 = uuid.uuid4(), uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(
            semilla,
            _op_venta(semilla, v2, secuencia=2, consecutivo_local=2),
            _op_venta(semilla, v1, secuencia=1, consecutivo_local=1),
        )
    )
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada"]
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas WHERE tenant_id = :t", t=T1)
    assert fila.n == 2
    dispositivo = await _uno(
        pg_platform_url, "SELECT ultima_secuencia FROM dispositivos WHERE id = :d", d=semilla["dispositivo"]
    )
    assert dispositivo.ultima_secuencia == 2


# --- Rechazos de dominio (por operación, sin abortar el lote) --------------------


async def test_payload_divergente_con_el_mismo_id_es_rechazada_con_detalles(servicio, semilla, pg_platform_url):
    """Decisión 4 del plan: la trampa del QA del catálogo aquí es rechazo
    explícito. O es el mismo hecho, o es otro que el tendero resuelve a cara
    vista — nunca un no-op silencioso con dinero de por medio."""
    venta_id = uuid.uuid4()
    await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, venta_id)))
    await servicio._session.commit()

    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, venta_id, total_centavos=9999)))
    assert [r.resultado for r in resultados] == ["rechazada"]
    assert resultados[0].motivo == "venta_id_divergente"
    assert "total_centavos" in resultados[0].detalles["campos"]
    fila = await _uno(pg_platform_url, "SELECT total_centavos FROM ventas WHERE id = :v", v=venta_id)
    assert fila.total_centavos == 2500, "la divergencia NO pisa la venta aceptada"


async def test_un_producto_que_no_existe_rechaza_solo_esa_operacion(servicio, semilla, pg_platform_url):
    fantasma = _op_venta(
        semilla,
        uuid.uuid4(),
        secuencia=1,
        items=[{"producto_id": str(uuid.uuid4()), "cantidad": "1", "precio_unitario_centavos": 100}],
        total_centavos=100,
    )
    buena = _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2)
    resultados = await servicio.procesar_lote(_lote(semilla, fantasma, buena))
    assert [r.resultado for r in resultados] == ["rechazada", "aceptada"]
    assert resultados[0].motivo == "producto_no_encontrado"
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas WHERE tenant_id = :t", t=T1)
    assert fila.n == 1, "la buena se aplicó: una operación mala no arrastra el lote"


async def test_el_fiado_exige_cliente_y_el_efectivo_lo_prohibe(servicio, semilla):
    sin_cliente = _op_venta(semilla, uuid.uuid4(), medio_pago="fiado")
    con_cliente = _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2, cliente_id=str(uuid.uuid4()))
    resultados = await servicio.procesar_lote(_lote(semilla, sin_cliente, con_cliente))
    assert [(r.resultado, r.motivo) for r in resultados] == [
        ("rechazada", "fiado_requiere_cliente"),
        ("rechazada", "cliente_solo_en_fiado"),
    ]


async def test_el_total_debe_cuadrar_con_los_items(servicio, semilla):
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), total_centavos=9999)))
    assert [r.resultado for r in resultados] == ["rechazada"]
    assert resultados[0].motivo == "total_incoherente"


async def test_datos_mal_formados_rechazan_la_operacion_no_el_lote(servicio, semilla):
    """Decisión 6: `datos` se valida por operación dentro del servicio."""
    mala = {"id": str(uuid.uuid4()), "tipo": "venta.crear", "secuencia": 1, "datos": {"consecutivo_local": "x"}}
    buena = _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2)
    resultados = await servicio.procesar_lote(_lote(semilla, mala, buena))
    assert [r.resultado for r in resultados] == ["rechazada", "aceptada"]
    assert resultados[0].motivo == "datos_invalidos"


async def test_un_tipo_desconocido_es_rechazada_no_422(servicio, semilla):
    futura = {"id": str(uuid.uuid4()), "tipo": "compra.registrar", "secuencia": 1, "datos": {}}
    resultados = await servicio.procesar_lote(_lote(semilla, futura))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "tipo_desconocido")]


async def test_el_consecutivo_repetido_en_el_mismo_dispositivo_se_rechaza(servicio, semilla):
    await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4())))
    await servicio._session.commit()
    # Otro id de venta, mismo consecutivo: es OTRA venta con el número ya dado.
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), secuencia=2)))
    assert [r.resultado for r in resultados] == ["rechazada"]
    assert resultados[0].motivo == "consecutivo_duplicado"


# --- Carreras cross-request sobre la PK de la venta -------------------------------


async def _carrera_de_la_misma_venta(pg_app_url: str, semilla, op_ganadora: dict, op_perdedora: dict) -> list:
    """Dos requests insertan la MISMA venta a la vez. El ganador queda sin
    confirmar reteniendo la fila; el perdedor espera en el índice único, recibe
    el `IntegrityError` de `ventas_pkey` cuando el ganador confirma y pasa por
    la traducción de `_traducir_integridad`."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s1, factory() as s2:
            servicio1 = VentasService(session=s1, tenant_id=T1, actor_id="cajero-prueba", puede_anular=True)
            servicio2 = VentasService(session=s2, tenant_id=T1, actor_id="cajero-prueba", puede_anular=True)
            assert [r.resultado for r in await servicio1.procesar_lote(_lote(semilla, op_ganadora))] == ["aceptada"]
            perdedor = asyncio.create_task(servicio2.procesar_lote(_lote(semilla, op_perdedora)))
            await asyncio.sleep(0.1)  # que el perdedor llegue al bloqueo antes del commit
            await s1.commit()
            resultados = await perdedor
            await s2.commit()
            return resultados
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def test_la_carrera_de_la_misma_venta_identica_es_duplicada(pg_app_url, pg_platform_url, semilla):
    """Mismo id, MISMO payload: el perdedor revienta contra `ventas_pkey`, pero
    la venta quedó aplicada por el ganador — es `duplicada`, no
    `venta_id_divergente`, y en la base queda exactamente una de cada cosa."""
    venta_id = uuid.uuid4()
    op = _op_venta(semilla, venta_id)
    resultados = await _carrera_de_la_misma_venta(pg_app_url, semilla, op, op)
    assert [r.resultado for r in resultados] == ["duplicada"]
    filas = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas WHERE tenant_id = :t", t=T1)
    assert filas.n == 1
    eventos = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k", k=f"{T1}.venta.creada"
    )
    assert eventos.n == 1


async def test_la_carrera_con_payload_divergente_sigue_siendo_rechazada(pg_app_url, pg_platform_url, semilla):
    """Mismo id, payload DISTINTO: el choque de `ventas_pkey` se traduce en
    `rechazada venta_id_divergente` con los campos que difieren (decisión 4),
    y la versión del ganador no se toca."""
    venta_id = uuid.uuid4()
    ganadora = _op_venta(semilla, venta_id, secuencia=1, consecutivo_local=1)
    perdedora = _op_venta(semilla, venta_id, secuencia=2, consecutivo_local=2)
    resultados = await _carrera_de_la_misma_venta(pg_app_url, semilla, ganadora, perdedora)
    assert [r.resultado for r in resultados] == ["rechazada"]
    assert resultados[0].motivo == "venta_id_divergente"
    assert "consecutivo_local" in resultados[0].detalles["campos"]
    fila = await _uno(pg_platform_url, "SELECT consecutivo_local FROM ventas WHERE id = :v", v=venta_id)
    assert fila.consecutivo_local == 1, "la divergencia NO pisa la venta del ganador"


# --- Anulación como operación nueva ----------------------------------------------


async def _vender(servicio, semilla, venta_id: uuid.UUID, secuencia: int = 1) -> None:
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, venta_id, secuencia=secuencia)))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()


async def test_anular_repone_stock_emite_evento_y_no_toca_la_venta_original(servicio, semilla, pg_platform_url):
    venta_id = uuid.uuid4()
    await _vender(servicio, semilla, venta_id)

    anulacion_id = uuid.uuid4()
    op = {"id": str(anulacion_id), "tipo": "venta.anular", "secuencia": 2, "datos": {"venta_id": str(venta_id)}}
    resultados = await servicio.procesar_lote(_lote(semilla, op))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()

    fila = await _uno(pg_platform_url, "SELECT estado, total_centavos FROM ventas WHERE id = :v", v=venta_id)
    assert fila.estado == "anulada"
    assert fila.total_centavos == 2500, "append-only: la anulación NO modifica la venta original"
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == Decimal("10"), "el delta inverso repuso el stock"
    movimientos = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM movimientos_inventario WHERE tenant_id = :t AND producto_id = :p",
        t=T1,
        p=semilla["producto"],
    )
    assert movimientos.n == 2, "salida y reposición: el libro cuenta las dos (ADR-020)"
    for clave, cuantos in ((f"{T1}.venta.creada", 1), (f"{T1}.venta.anulada", 1)):
        fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k", k=clave)
        assert fila.n == cuantos, f"{clave}: {cuantos}"


async def test_anular_dos_veces_es_duplicada_y_no_repone_dos_veces(servicio, semilla, pg_platform_url):
    venta_id = uuid.uuid4()
    await _vender(servicio, semilla, venta_id)
    op = {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 2, "datos": {"venta_id": str(venta_id)}}
    assert [r.resultado for r in await servicio.procesar_lote(_lote(semilla, op))] == ["aceptada"]
    await servicio._session.commit()

    # Reintento del MISMO lote de anulación (mismo id de operación):
    assert [r.resultado for r in await servicio.procesar_lote(_lote(semilla, op))] == ["duplicada"]
    # Y una anulación NUEVA sobre la venta ya anulada también es duplicada:
    op2 = {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 3, "datos": {"venta_id": str(venta_id)}}
    assert [r.resultado for r in await servicio.procesar_lote(_lote(semilla, op2))] == ["duplicada"]
    await servicio._session.commit()
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == Decimal("10")
    fila = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k", k=f"{T1}.venta.anulada"
    )
    assert fila.n == 1


async def test_dos_anulaciones_concurrentes_reponen_el_stock_una_sola_vez(pg_app_url, pg_platform_url, semilla):
    """La carrera cross-request de la anulación: dos requests anulan la MISMA
    venta con ids de operación DISTINTOS. Sin bloqueo de fila ambos leen
    `completada` (READ COMMITTED) y `ux_movimientos_origen` NO los deduplica,
    porque cada uno repone con el referencia_id de SU operación: stock repuesto
    dos veces y dos `venta.anulada`. Con el `SELECT ... FOR UPDATE` sobre la
    venta, el perdedor espera al commit del ganador, re-lee `anulada` y sale
    como `duplicada`: un solo juego de reposición y un solo evento."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    venta_id = uuid.uuid4()
    try:
        async with factory() as s0:
            servicio = VentasService(session=s0, tenant_id=T1, actor_id="dueno", puede_anular=True)
            await _vender(servicio, semilla, venta_id)

        async with factory() as s1, factory() as s2:
            servicio1 = VentasService(session=s1, tenant_id=T1, actor_id="dueno", puede_anular=True)
            servicio2 = VentasService(session=s2, tenant_id=T1, actor_id="dueno", puede_anular=True)
            op1 = {
                "id": str(uuid.uuid4()),
                "tipo": "venta.anular",
                "secuencia": 2,
                "datos": {"venta_id": str(venta_id)},
            }
            op2 = {
                "id": str(uuid.uuid4()),
                "tipo": "venta.anular",
                "secuencia": 3,
                "datos": {"venta_id": str(venta_id)},
            }
            assert [r.resultado for r in await servicio1.procesar_lote(_lote(semilla, op1))] == ["aceptada"]
            # s1 retiene el bloqueo de la venta hasta su commit: s2 espera y re-lee.
            perdedor = asyncio.create_task(servicio2.procesar_lote(_lote(semilla, op2)))
            await asyncio.sleep(0.1)
            await s1.commit()
            assert [r.resultado for r in await perdedor] == ["duplicada"]
            await s2.commit()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()

    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == Decimal("10"), "la reposición se aplicó UNA vez, no dos"
    reposiciones = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM movimientos_inventario WHERE tenant_id = :t AND cantidad > 0",
        t=T1,
    )
    assert reposiciones.n == 1, "un solo juego de movimientos de reposición"
    eventos = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k", k=f"{T1}.venta.anulada"
    )
    assert eventos.n == 1, "un solo evento venta.anulada"


async def test_el_cajero_no_puede_anular(servicio, semilla, pg_platform_url):
    """ADR-023: anular es del dueño. El servicio lo sabe por `puede_anular`
    (el router lo deriva del token); la operación se rechaza y la cola del
    cajero sigue drenando."""
    venta_id = uuid.uuid4()
    await _vender(servicio, semilla, venta_id)
    servicio_cajero = VentasService(
        session=servicio._session, tenant_id=T1, actor_id="cajero-prueba", puede_anular=False
    )
    op = {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 2, "datos": {"venta_id": str(venta_id)}}
    resultados = await servicio_cajero.procesar_lote(_lote(semilla, op))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "permiso_ausente")]
    fila = await _uno(pg_platform_url, "SELECT estado FROM ventas WHERE id = :v", v=venta_id)
    assert fila.estado == "completada"


async def test_anular_una_venta_que_no_existe_es_rechazada(servicio, semilla):
    op = {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 1, "datos": {"venta_id": str(uuid.uuid4())}}
    resultados = await servicio.procesar_lote(_lote(semilla, op))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "venta_no_encontrada")]


async def test_una_venta_que_sube_ya_anulada_no_mueve_stock(servicio, semilla, pg_platform_url):
    """ADR-018: anulada localmente antes de sincronizar, sube ya anulada.
    Decisión 9: efecto neto cero — sin movimientos, sin venta.anulada, y el
    evento venta.creada lleva el estado en el payload."""
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), estado="anulada")))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == Decimal("10")
    movimientos = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM movimientos_inventario WHERE tenant_id = :t", t=T1
    )
    assert movimientos.n == 0
    fila = await _uno(pg_platform_url, "SELECT estado FROM ventas WHERE tenant_id = :t", t=T1)
    assert fila.estado == "anulada", "la trazabilidad vale más que una fila de menos (ADR-018)"


# --- Delta -----------------------------------------------------------------------


async def test_el_delta_devuelve_los_cambios_desde_el_watermark(servicio, semilla, pg_platform_url):
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        viejo = (
            await conn.execute(text("SELECT created_at FROM productos WHERE id = :p"), {"p": semilla["producto"]})
        ).scalar_one()
    await engine.dispose()

    desde = viejo  # justo en la creación: el producto NO debe salir (>)
    delta = await servicio.delta_productos(desde)
    assert semilla["producto"] not in [p.id for p in delta.productos]

    # Una venta toca el stock del producto → updated_at → aparece en el delta:
    await _vender(servicio, semilla, uuid.uuid4())
    delta = await servicio.delta_productos(desde)
    assert semilla["producto"] in [p.id for p in delta.productos]
    assert delta.hasta > desde, "el watermark lo pone el servidor (ADR-017)"

    # Y una baja lógica llega como tumba:
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE productos SET deleted_at = now(), codigo_barras = NULL WHERE id = :p"),
            {"p": semilla["producto2"]},
        )
    await engine.dispose()
    delta = await servicio.delta_productos(desde)
    assert semilla["producto2"] in delta.eliminados
    assert semilla["producto2"] not in [p.id for p in delta.productos]
