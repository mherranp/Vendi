"""QA adversarial de ventas y del sync offline: ataques sobre el camino del dinero.

Compañero de `test_ventas_servicio.py` y de `test_sync_idempotente.py`, no
sustituto: aquello fija el camino feliz, la idempotencia y las carreras
firmadas; esto empuja las esquinas que el plan deja en penumbra — dos ventas
del mismo producto en un lote, ítems y anulaciones cross-tenant, inyección en
`tipo`, la carrera de la sesión implícita, la venta que llega tras el cierre
y el reintento de una venta ya anulada— y deja cada comportamiento FIJO en un
test.

Dos de estos tests DOCUMENTAN comportamientos discutibles a propósito (la
venta que cae en una sesión implícita nueva tras el cierre, y el reintento de
una venta ya anulada que sale `venta_id_divergente` por el campo `estado`):
el assert es el comportamiento actual y la discusión vive en
`.superpowers/sdd/qa-adversarial-ventas-report.md`. Si alguno cambia a un
comportamiento distinto, el test se reescribe, no se borra.

Los BUGS encontrados (ítem duplicado del mismo producto, cantidad que
redondea a cero en NUMERIC(14,3), anulación con id de operación igual al de
la venta, dispositivo con id de otro tenant) NO tienen test aquí: están en el
reporte con su reproducción exacta, porque un test que los fijara sería un
test que documenta dinero perdido.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.ventas.schemas import LoteSync
from app.modules.ventas.service import VentasService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
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
    """El escenario base del ataque: T1 con un dispositivo y dos productos."""
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
            yield VentasService(session=s, tenant_id=T1, actor_id="qa-adversarial", puede_anular=True)
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


# --- Stock: el libro por deltas bajo fuego --------------------------------------


async def test_dos_ventas_del_mismo_producto_en_un_lote_descuentan_las_dos(servicio, semilla, pg_platform_url):
    """La sospecha «¿stock descontado dos veces?» al revés: son DOS ventas
    distintas y el libro debe contar las dos — dos movimientos con su propio
    `referencia_id` (el índice único los admite) y stock 10 → 8."""
    resultados = await servicio.procesar_lote(
        _lote(
            semilla,
            _op_venta(semilla, uuid.uuid4(), secuencia=1, consecutivo_local=1),
            _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2),
        )
    )
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada"]
    await servicio._session.commit()

    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("8")
    movimientos = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM movimientos_inventario WHERE tenant_id = :t AND cantidad < 0",
        t=T1,
    )
    assert movimientos.n == 2, "un movimiento por venta: la clave es (tipo, referencia_id, producto_id)"
    eventos = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k", k=f"{T1}.venta.creada"
    )
    assert eventos.n == 2


async def test_la_misma_venta_dos_veces_en_el_mismo_lote_aplica_una_sola(servicio, semilla, pg_platform_url):
    """Reintento INTRA-lote (la cola del dispositivo duplicó la operación antes
    de subir): la primera aplica y la segunda es `duplicada` por la PK del
    cliente — una fila, un movimiento, un evento."""
    operacion = _op_venta(semilla, uuid.uuid4())
    resultados = await servicio.procesar_lote(_lote(semilla, operacion, dict(operacion)))
    assert [r.resultado for r in resultados] == ["aceptada", "duplicada"]
    await servicio._session.commit()

    filas = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas WHERE tenant_id = :t", t=T1)
    assert filas.n == 1
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("9")
    eventos = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k", k=f"{T1}.venta.creada"
    )
    assert eventos.n == 1


async def test_el_lote_sobrevive_a_un_integrity_error_en_mitad(servicio, semilla, pg_platform_url):
    """La operación del medio revienta contra `ux_ventas_consecutivo` DENTRO de
    su savepoint (dos ventas con el mismo consecutivo en el mismo lote). El
    savepoint revierte solo lo suyo y la sesión sigue sana: la tercera venta
    del lote se aplica como si nada."""
    resultados = await servicio.procesar_lote(
        _lote(
            semilla,
            _op_venta(semilla, uuid.uuid4(), secuencia=1, consecutivo_local=1),
            _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=1),
            _op_venta(semilla, uuid.uuid4(), secuencia=3, consecutivo_local=2),
        )
    )
    assert [r.resultado for r in resultados] == ["aceptada", "rechazada", "aceptada"]
    assert resultados[1].motivo == "consecutivo_duplicado"
    await servicio._session.commit()

    filas = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas WHERE tenant_id = :t", t=T1)
    assert filas.n == 2, "las dos buenas quedaron: el IntegrityError no envenenó la transacción"
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("8")


async def test_anular_una_venta_que_dejo_el_stock_negativo_lo_repone(servicio, semilla, pg_platform_url):
    """El stock negativo es legítimo (ADR-020) y su anulación también: vende 5
    habiendo 3 (−2) y la anulación devuelve el stock a 3, no a cero ni a un
    tope inventado."""
    venta_id = uuid.uuid4()
    await _vender(
        servicio,
        semilla,
        venta_id,
        items=[{"producto_id": str(semilla["producto2"]), "cantidad": "5", "precio_unitario_centavos": 600}],
        total_centavos=3000,
    )
    assert await _stock(pg_platform_url, semilla["producto2"]) == Decimal("-2")

    resultados = await servicio.procesar_lote(_lote(semilla, _op_anulacion(venta_id, secuencia=2)))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    assert await _stock(pg_platform_url, semilla["producto2"]) == Decimal("3")


# --- Cross-tenant: el dinero del vecino -------------------------------------------


async def test_un_item_con_producto_de_otro_tenant_es_rechazado_sin_fuga(servicio, semilla, pg_platform_url):
    """El ítem apunta a un producto que EXISTE — pero en otro negocio. La RLS
    lo hace invisible y la respuesta es la misma que para un id inventado:
    `producto_no_encontrado`, sin venta y sin asomo de que el producto existe."""
    producto_ajeno = uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                "VALUES (:p, :t, 'Del vecino', 100, 5)"
            ),
            {"p": producto_ajeno, "t": T2},
        )
    await engine.dispose()

    resultados = await servicio.procesar_lote(
        _lote(
            semilla,
            _op_venta(
                semilla,
                uuid.uuid4(),
                items=[{"producto_id": str(producto_ajeno), "cantidad": "1", "precio_unitario_centavos": 100}],
                total_centavos=100,
            ),
        )
    )
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "producto_no_encontrado")]
    filas = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas WHERE tenant_id = :t", t=T1)
    assert filas.n == 0
    assert await _stock(pg_platform_url, producto_ajeno) == Decimal("5"), "ni el stock del vecino se movió"


async def test_anular_una_venta_de_otro_tenant_es_rechazada_y_no_la_toca(servicio, semilla, pg_platform_url):
    """El `venta_id` de la anulación existe — en otro negocio. El FOR UPDATE no
    lo ve (RLS) y la respuesta no revela nada; la venta ajena sigue completada."""
    venta_ajena, dispositivo_ajeno, sesion_ajena = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja ajena')"),
            {"d": dispositivo_ajeno, "t": T2},
        )
        await conn.execute(
            text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por) VALUES (:s, :t, 'vecino')"),
            {"s": sesion_ajena, "t": T2},
        )
        await conn.execute(
            text(
                "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local,"
                " medio_pago, total_centavos, creada_en_cliente, secuencia_dispositivo)"
                " VALUES (:v, :t, :d, :s, 1, 'efectivo', 2500, now(), 1)"
            ),
            {"v": venta_ajena, "t": T2, "d": dispositivo_ajeno, "s": sesion_ajena},
        )
    await engine.dispose()

    resultados = await servicio.procesar_lote(_lote(semilla, _op_anulacion(venta_ajena, secuencia=1)))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "venta_no_encontrada")]
    fila = await _uno(pg_platform_url, "SELECT estado FROM ventas WHERE id = :v", v=venta_ajena)
    assert fila.estado == "completada", "la venta del vecino, intacta"


# --- Abuso del formato -------------------------------------------------------------


async def test_un_tipo_con_inyeccion_sql_es_tipo_desconocido_y_no_pasa_nada(servicio, semilla, pg_platform_url):
    """`tipo` viaja como texto pero jamás toca SQL: se compara por igualdad en
    Python. Una «inyección» es solo un tipo desconocido — `rechazada` por
    operación, y la base sigue ahí (la venta buena del mismo lote se aplica)."""
    maliciosa = {
        "id": str(uuid.uuid4()),
        "tipo": "venta.crear'; DROP TABLE ventas;--",
        "secuencia": 1,
        "datos": {},
    }
    buena = _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2)
    resultados = await servicio.procesar_lote(_lote(semilla, maliciosa, buena))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "tipo_desconocido"), ("aceptada", None)]
    await servicio._session.commit()
    filas = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas WHERE tenant_id = :t", t=T1)
    assert filas.n == 1, "la tabla ventas sigue existiendo y la buena se aplicó"


def test_una_operacion_sin_datos_ni_siquiera_entra_al_lote():
    """D-14 CERRADA: `datos` es requerido en el contrato. La operación sin
    `datos` ya no cae en el default `{}` para salir `rechazada` con
    `datos_invalidos`: pydantic la corta en la frontera del lote — en la API
    es un 422 del request entero y nada se aplicó. (El contenido inválido CON
    campo sigue siendo `rechazada` por operación: eso no cambia, lo fija
    `test_datos_mal_formados_rechazan_la_operacion_no_el_lote`.)"""
    sin_datos = {"id": str(uuid.uuid4()), "tipo": "venta.crear", "secuencia": 1}
    with pytest.raises(ValidationError):
        LoteSync.model_validate({"dispositivo_id": str(uuid.uuid4()), "operaciones": [sin_datos]})


async def test_una_venta_de_cero_items_no_llega_al_servicio_como_venta(servicio, semilla):
    """El ticket vacío: el schema exige `min_length=1` en `items`, así que la
    operación se rechaza como `datos_invalidos` — nunca una venta de 0 ítems
    con total 0 colada en el libro."""
    vacia = _op_venta(semilla, uuid.uuid4(), items=[], total_centavos=0)
    resultados = await servicio.procesar_lote(_lote(semilla, vacia))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "datos_invalidos")]


async def test_un_producto_dado_de_baja_logica_se_puede_vender(servicio, semilla, pg_platform_url):
    """ADR-018 bajo fuego: la baja lógica llegó al servidor pero el dispositivo
    offline vendió la última unidad física. La venta SE ACEPTA (el precio va
    congelado en el ítem) y el stock baja — el borrado es del catálogo, no de
    la historia."""
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE productos SET deleted_at = now(), codigo_barras = NULL WHERE id = :p"),
            {"p": semilla["producto2"]},
        )
    await engine.dispose()

    resultados = await servicio.procesar_lote(
        _lote(
            semilla,
            _op_venta(
                semilla,
                uuid.uuid4(),
                items=[{"producto_id": str(semilla["producto2"]), "cantidad": "1", "precio_unitario_centavos": 600}],
                total_centavos=600,
            ),
        )
    )
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    assert await _stock(pg_platform_url, semilla["producto2"]) == Decimal("2")


# --- Sesión de caja: la carrera implícita y la venta tardía -------------------------


async def test_la_carrera_de_aperturas_implicitas_abre_una_sola_sesion(pg_app_url, pg_platform_url, semilla):
    """Dos requests suben su primera venta a la vez y no hay sesión abierta:
    los dos intentan abrir la implícita. El índice parcial
    `ux_caja_sesion_abierta` decide — el perdedor espera al commit del ganador,
    revienta contra el índice y re-lee la ganadora. Una sola sesión y las dos
    ventas cuelgan de ella. Las ventas son de productos DISTINTOS a propósito:
    con el FOR UPDATE del camino del stock, dos ventas del mismo producto se
    serializan en la fila del producto ANTES de llegar a la sesión, y la
    carrera del índice parcial nunca ocurriría."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s1, factory() as s2:
            servicio1 = VentasService(session=s1, tenant_id=T1, actor_id="caja-1", puede_anular=True)
            servicio2 = VentasService(session=s2, tenant_id=T1, actor_id="caja-2", puede_anular=True)
            op1 = _op_venta(semilla, uuid.uuid4(), secuencia=1, consecutivo_local=1)
            op2 = _op_venta(
                semilla,
                uuid.uuid4(),
                secuencia=2,
                consecutivo_local=2,
                items=[{"producto_id": str(semilla["producto2"]), "cantidad": "1", "precio_unitario_centavos": 600}],
                total_centavos=600,
            )
            assert [r.resultado for r in await servicio1.procesar_lote(_lote(semilla, op1))] == ["aceptada"]
            # s1 retiene la sesión implícita sin confirmar: s2 espera en el índice.
            perdedor = asyncio.create_task(servicio2.procesar_lote(_lote(semilla, op2)))
            await asyncio.sleep(0.1)
            await s1.commit()
            assert [r.resultado for r in await perdedor] == ["aceptada"]
            await s2.commit()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()

    sesiones = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta'",
        t=T1,
    )
    assert sesiones.n == 1, "ADR-021: una sola sesión abierta por tienda, incluso en carrera"
    distintas = await _uno(
        pg_platform_url, "SELECT count(DISTINCT sesion_caja_id) AS n FROM ventas WHERE tenant_id = :t", t=T1
    )
    assert distintas.n == 1, "las dos ventas colgaron de la MISMA sesión"


async def test_la_venta_que_llega_tras_el_cierre_cae_en_una_sesion_implicita_nueva(servicio, semilla, pg_platform_url):
    """DOCUMENTA el borde firmado de ADR-018: el dispositivo vendió AYER
    offline, el tendero cerró caja, y hoy sube el lote. La venta no revienta
    ni se pierde: se acepta y el servidor abre OTRA sesión implícita para
    cobijarla. El arqueo de ayer nunca la verá — la discusión vive en el
    reporte (cuestionable-firmado)."""
    await _vender(servicio, semilla, uuid.uuid4())
    sesion_dia_1 = await _uno(pg_platform_url, "SELECT id FROM caja_sesiones WHERE tenant_id = :t", t=T1)
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            # Cierre completo: `ck_caja_sesiones_cierre_completo` (0008) exige
            # las cinco columnas del arqueo junto al estado.
            text(
                "UPDATE caja_sesiones SET estado = 'cerrada', cerrada_por = 'dueno', cerrada_en = now(), "
                "efectivo_esperado = 0, efectivo_contado = 0, diferencia = 0 WHERE tenant_id = :t"
            ),
            {"t": T1},
        )
    await engine.dispose()

    ayer = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    venta_tardia = uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(semilla, _op_venta(semilla, venta_tardia, secuencia=2, consecutivo_local=2, creada_en_cliente=ayer))
    )
    assert [r.resultado for r in resultados] == ["aceptada"], (
        "la venta tardía no se rechaza: el dinero ya cambió de manos"
    )
    await servicio._session.commit()

    fila = await _uno(pg_platform_url, "SELECT sesion_caja_id FROM ventas WHERE id = :v", v=venta_tardia)
    assert fila.sesion_caja_id != sesion_dia_1.id, "cae en una sesión NUEVA, no en la cerrada"
    abiertas = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta'",
        t=T1,
    )
    assert abiertas.n == 1, "la implícita de cobijo queda abierta esperando su arqueo"


# --- Doble verdad temporal y delta ---------------------------------------------------


async def test_el_reloj_del_cliente_en_2099_es_dato_y_no_arbitro(servicio, semilla, pg_platform_url):
    """El gemelo futurista del test de 1999: un reloj adelantado una vida se
    acepta y se guarda para el ticket, pero `recibida_en` —la única verdad— la
    pone el servidor."""
    resultados = await servicio.procesar_lote(
        _lote(semilla, _op_venta(semilla, uuid.uuid4(), creada_en_cliente="2099-01-01T00:00:00+00:00"))
    )
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT creada_en_cliente, recibida_en FROM ventas WHERE tenant_id = :t", t=T1)
    assert fila.creada_en_cliente == datetime(2099, 1, 1, tzinfo=UTC), "el dato del ticket se conserva tal cual"
    assert fila.recibida_en.year < 2099, "la verdad temporal es del servidor, no del cliente"


async def test_el_delta_con_watermark_del_futuro_no_explota_ni_miente(servicio, semilla):
    """Un dispositivo con el watermark corrupto (del futuro) recibe un delta
    vacío y un `hasta` del SERVIDOR: no hay 500, no hay catálogo regalado y el
    próximo drenado se reancla a la verdad del servidor."""
    futuro = datetime(2099, 1, 1, tzinfo=timezone(timedelta(hours=-5)))
    delta = await servicio.delta_productos(futuro)
    assert delta.productos == [] and delta.eliminados == []
    assert delta.hasta < datetime(2099, 1, 1, tzinfo=UTC), "el watermark de salida lo pone el servidor (ADR-017)"


async def test_el_reintento_de_una_venta_ya_anulada_es_divergente_por_el_estado(servicio, semilla, pg_platform_url):
    """DOCUMENTA el borde de la decisión 4: `estado` es campo del hecho, pero
    la anulación lo MUTA en el servidor. El reintento legítimo del `venta.crear`
    original (mismo id, mismo payload) ya no es `duplicada`: es `rechazada`
    `venta_id_divergente` con `campos == ["estado"]`. El dato queda bien —la
    venta sigue anulada y el stock no se mueve—; lo discutible es el motivo,
    que sugiere fraude donde solo hubo un reintento tardío."""
    venta_id = uuid.uuid4()
    operacion = _op_venta(semilla, venta_id)
    assert [r.resultado for r in await servicio.procesar_lote(_lote(semilla, operacion))] == ["aceptada"]
    await servicio._session.commit()
    assert [r.resultado for r in await servicio.procesar_lote(_lote(semilla, _op_anulacion(venta_id, 2)))] == [
        "aceptada"
    ]
    await servicio._session.commit()

    resultados = await servicio.procesar_lote(_lote(semilla, operacion))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "venta_id_divergente")]
    assert resultados[0].detalles["campos"] == ["estado"]

    fila = await _uno(pg_platform_url, "SELECT estado FROM ventas WHERE id = :v", v=venta_id)
    assert fila.estado == "anulada", "el reintento NO resucita la venta"
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("10"), "y el stock no se movió de más"


# --- Concurrencia: el orden de bloqueo de los productos (cierre de D-21) ----------


async def test_lotes_con_el_mismo_surtido_en_orden_inverso_no_se_interbloquean(pg_app_url, pg_platform_url, semilla):
    """FIJA el cierre de D-21: dos cajas suben a la vez tickets con los mismos
    productos en orden INVERSO ([arroz, huevo] y [huevo, arroz]).

    Antes del arreglo, cada lote tomaba el FOR UPDATE en el orden del ticket:
    el intercalado A bloquea arroz → B bloquea huevo → A pide huevo → B pide
    arroz era un `DeadlockDetected` de Postgres y un 500. Con los bloqueos
    ordenados por `producto_id` (la receta de la compra, decisión 9) los dos
    lotes piden primero la MISMA fila: el perdedor espera al commit del
    ganador y aplica después, sin deadlock y con el stock exacto.

    El `gather` es a propósito (no `create_task` + commit como la carrera de
    la sesión implícita): el deadlock solo existe si los dos lotes están
    DENTRO de su bucle de bloqueos a la vez. La caja 1 confirma tras una
    pausa para dejar al perdedor esperando el bloqueo en medio del gather.
    """
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)

    def _op_invertida(venta_id: uuid.UUID, secuencia: int, consecutivo: int) -> dict:
        return _op_venta(
            semilla,
            venta_id,
            secuencia=secuencia,
            consecutivo_local=consecutivo,
            items=[
                {"producto_id": str(semilla["producto2"]), "cantidad": "1", "precio_unitario_centavos": 600},
                {"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": 2500},
            ],
            total_centavos=3100,
        )

    try:
        async with factory() as s1, factory() as s2:
            servicio1 = VentasService(session=s1, tenant_id=T1, actor_id="caja-1", puede_anular=True)
            servicio2 = VentasService(session=s2, tenant_id=T1, actor_id="caja-2", puede_anular=True)
            lote1 = _lote(
                semilla,
                _op_venta(
                    semilla,
                    uuid.uuid4(),
                    secuencia=1,
                    consecutivo_local=1,
                    items=[
                        {"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": 2500},
                        {"producto_id": str(semilla["producto2"]), "cantidad": "1", "precio_unitario_centavos": 600},
                    ],
                    total_centavos=3100,
                ),
            )
            lote2 = _lote(semilla, _op_invertida(uuid.uuid4(), secuencia=2, consecutivo=2))

            async def caja1():
                resultados = await servicio1.procesar_lote(lote1)
                # Mantiene los bloqueos un instante: la caja 2 pide la MISMA
                # primera fila (ordenadas por producto_id) y espera aquí.
                await asyncio.sleep(0.2)
                await s1.commit()
                return resultados

            async def caja2():
                resultados = await servicio2.procesar_lote(lote2)
                await s2.commit()
                return resultados

            # Sin el orden de bloqueo, este gather reventaba con
            # DeadlockDetected: A retenía arroz y pedía huevo, B al revés.
            r1, r2 = await asyncio.gather(caja1(), caja2())
            assert [r.resultado for r in r1] == ["aceptada"]
            assert [r.resultado for r in r2] == ["aceptada"]
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()

    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("8"), "10 − 1 − 1, sin deadlock ni reintento"
    assert await _stock(pg_platform_url, semilla["producto2"]) == Decimal("1"), "3 − 1 − 1"
    movimientos = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM movimientos_inventario WHERE tenant_id = :t AND tipo = 'venta'",
        t=T1,
    )
    assert movimientos.n == 4, "dos ventas × dos productos consolidados, los dos lotes aplicaron una sola vez"
