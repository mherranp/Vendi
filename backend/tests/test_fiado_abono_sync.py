"""El abono del fiado dentro del lote del sync (cierre de D-27).

Cobrar un fiado sin señal es tan normal como vender sin señal: la operación
`fiado.abonar` encola como cualquier otra y se aplica por el MISMO camino
del abono online (`FiadoService.registrar_abono`). Aquí se fija lo firmado:

- el abono en efectivo descuenta el saldo y cae en la sesión de caja abierta
  AL APLICARSE en el servidor (el `sesion_caja_id` no lo manda el cliente),
  abriendo la implícita si no hay ninguna (ADR-018);
- el reintento del lote es `duplicada` sin doble descuento ni doble evento
  (la ancla es el id de la operación, ADR-022);
- el abono que excede el saldo es `rechazada` `abono_excede_saldo` y NO
  arrastra el lote;
- el permiso `fiado:abonar` se exige por operación (el cobro de un
  almacenista es `rechazada`, no un 403 del lote);
- el abono a un crédito de otro tenant es `rechazada`
  `credito_no_encontrado` — el mismo motivo que un crédito inexistente, sin
  fuga.

Mismo criterio que `test_fiado_sync.py`: el lote se procesa con la sesión de
tenant real y las filas se verifican por SQL con el rol de plataforma.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.ventas.schemas import LoteSync
from app.modules.ventas.service import VentasService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM fiado_abonos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM fiado_creditos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM clientes WHERE tenant_id = ANY(:ids)",
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.fiado.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """En T1: dispositivo y producto para fiar por el lote. En T2: cliente,
    dispositivo y sesión — la infraestructura del vecino para sembrarle un
    crédito. Limpieza total antes y después."""
    engine = create_async_engine(pg_platform_url)
    ids = {
        "dispositivo": uuid.uuid4(),
        "producto": uuid.uuid4(),
        "cliente_t2": uuid.uuid4(),
        "dispositivo_t2": uuid.uuid4(),
        "sesion_t2": uuid.uuid4(),
    }
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
                "VALUES (:p, :t, 'Arroz 500g', 2500, 100)"
            ),
            {"p": ids["producto"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO clientes (id, tenant_id, nombre) VALUES (:c, :t, 'La vecina')"),
            {"c": ids["cliente_t2"], "t": T2},
        )
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo_t2"], "t": T2},
        )
        await conn.execute(
            text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) VALUES (:s, :t, 'dueno', 0)"),
            {"s": ids["sesion_t2"], "t": T2},
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
            yield VentasService(
                session=s,
                tenant_id=T1,
                actor_id="cajero-prueba",
                puede_anular=True,
                puede_fiar=True,
                puede_gestionar_clientes=True,
                puede_abonar=True,
            )
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


def _lote(semilla: dict, operaciones: list[dict]) -> LoteSync:
    return LoteSync.model_validate({"dispositivo_id": str(semilla["dispositivo"]), "operaciones": operaciones})


def _op_cliente(cliente_id: uuid.UUID, secuencia: int, **datos) -> dict:
    base: dict = {"nombre": "Don Carlos", "telefono": "3001234567"}
    base.update(datos)
    return {"id": str(cliente_id), "tipo": "cliente.crear", "secuencia": secuencia, "datos": base}


def _op_venta_fiada(venta_id: uuid.UUID, semilla: dict, cliente_id: uuid.UUID, total: int, secuencia: int) -> dict:
    return {
        "id": str(venta_id),
        "tipo": "venta.crear",
        "secuencia": secuencia,
        "datos": {
            "consecutivo_local": 1,
            "estado": "completada",
            "medio_pago": "fiado",
            "total_centavos": total,
            "cliente_id": str(cliente_id),
            "creada_en_cliente": "2026-07-28T10:00:00+00:00",
            "items": [{"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": total}],
        },
    }


def _op_abono(
    abono_id: uuid.UUID,
    credito_id: uuid.UUID,
    cliente_id: uuid.UUID,
    secuencia: int,
    monto: int,
    metodo: str = "efectivo",
) -> dict:
    return {
        "id": str(abono_id),
        "tipo": "fiado.abonar",
        "secuencia": secuencia,
        "datos": {
            "cliente_id": str(cliente_id),
            "credito_id": str(credito_id),
            "monto": monto,
            "metodo_pago": metodo,
        },
    }


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


async def _eventos(pg_platform_url: str, evento: str) -> list:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            filas = (
                await conn.execute(
                    text("SELECT payload FROM outbox_messages WHERE routing_key LIKE :k ORDER BY created_at"),
                    {"k": f"%.{evento}"},
                )
            ).all()
            return [f[0] for f in filas]
    finally:
        await engine.dispose()


async def _credito_por_lote(servicio, semilla, pg_platform_url, total: int = 43000) -> tuple[uuid.UUID, uuid.UUID]:
    """Un crédito como llega de verdad: `cliente.crear` + la venta fiada en
    el mismo lote. Devuelve (cliente_id, credito_id), ya confirmados."""
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(semilla, [_op_cliente(cliente_id, 1), _op_venta_fiada(venta_id, semilla, cliente_id, total, 2)])
    )
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada"]
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT id FROM fiado_creditos WHERE venta_id = :v", v=venta_id)
    return cliente_id, fila[0]


@pytest.mark.asyncio
async def test_el_abono_offline_descuenta_el_saldo_y_cae_en_la_sesion(servicio, semilla, pg_platform_url):
    """El camino feliz: abono en efectivo registrado sin señal. Al aplicarse,
    el saldo baja, la fila guarda la sesión abierta DEL SERVIDOR (no la manda
    el cliente) y el evento `fiado.abono_registrado` viaja en la misma
    transacción."""
    cliente_id, credito_id = await _credito_por_lote(servicio, semilla, pg_platform_url)
    sesion = await _uno(
        pg_platform_url, "SELECT id FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta'", t=T1
    )
    assert sesion is not None  # la abrió la venta fiada (implícita, ADR-018)

    abono_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(_lote(semilla, [_op_abono(abono_id, credito_id, cliente_id, 3, 13000)]))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()

    abono = await _uno(
        pg_platform_url,
        "SELECT credito_id, monto, metodo_pago, sesion_caja_id, registrado_por FROM fiado_abonos WHERE id = :a",
        a=abono_id,
    )
    assert abono == (credito_id, 13000, "efectivo", sesion[0], "cajero-prueba")
    saldo = await _uno(
        pg_platform_url, "SELECT saldo_pendiente, estado FROM fiado_creditos WHERE id = :c", c=credito_id
    )
    assert saldo == (30000, "vigente")
    eventos = await _eventos(pg_platform_url, "fiado.abono_registrado")
    assert len(eventos) == 1
    assert eventos[0]["data"]["abono_id"] == str(abono_id) and eventos[0]["data"]["saldo_restante"] == 30000


@pytest.mark.asyncio
async def test_el_abono_en_efectivo_sin_sesion_abierta_abre_la_implicita(servicio, semilla, pg_platform_url):
    """El cobro ocurrió físicamente: si al aplicarse NO hay sesión abierta
    (la del turno ya cerró), el abono no se rechaza — cae en la implícita
    que se abre en ese momento (ADR-018), como la venta y la anulación."""
    cliente_id, credito_id = await _credito_por_lote(servicio, semilla, pg_platform_url)
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE caja_sesiones SET estado = 'cerrada', cerrada_por = 'dueno', cerrada_en = now(), "
                "efectivo_esperado = 0, efectivo_contado = 0, diferencia = 0 "
                "WHERE tenant_id = :t AND estado = 'abierta'"
            ),
            {"t": T1},
        )
    await engine.dispose()

    abono_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(_lote(semilla, [_op_abono(abono_id, credito_id, cliente_id, 3, 5000)]))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()

    abono = await _uno(pg_platform_url, "SELECT sesion_caja_id FROM fiado_abonos WHERE id = :a", a=abono_id)
    sesion = await _uno(pg_platform_url, "SELECT estado, abierta_por FROM caja_sesiones WHERE id = :s", s=abono[0])
    assert sesion == ("abierta", "cajero-prueba")  # la implícita del momento de aplicarse
    saldo = await _uno(pg_platform_url, "SELECT saldo_pendiente FROM fiado_creditos WHERE id = :c", c=credito_id)
    assert saldo == (38000,)


@pytest.mark.asyncio
async def test_el_reintento_del_abono_es_duplicada_sin_doble_descuento(servicio, semilla, pg_platform_url):
    """La ancla de ADR-022 aplicada al lote: el reenvío del MISMO abono es
    `duplicada` — sin segundo descuento ni segundo evento — y el reenvío con
    otro monto es `rechazada` `abono_id_divergente`, nunca un no-op mudo."""
    cliente_id, credito_id = await _credito_por_lote(servicio, semilla, pg_platform_url)
    abono_id = uuid.uuid4()
    lote = _lote(semilla, [_op_abono(abono_id, credito_id, cliente_id, 3, 13000)])

    primera = await servicio.procesar_lote(lote)
    assert [r.resultado for r in primera] == ["aceptada"]
    de_nuevo = await servicio.procesar_lote(lote)
    assert [r.resultado for r in de_nuevo] == ["duplicada"]
    divergente = await servicio.procesar_lote(_lote(semilla, [_op_abono(abono_id, credito_id, cliente_id, 4, 14000)]))
    assert divergente[0].resultado == "rechazada" and divergente[0].motivo == "abono_id_divergente"
    await servicio._session.commit()

    assert await _uno(pg_platform_url, "SELECT count(*) FROM fiado_abonos WHERE id = :a", a=abono_id) == (1,)
    saldo = await _uno(pg_platform_url, "SELECT saldo_pendiente FROM fiado_creditos WHERE id = :c", c=credito_id)
    assert saldo == (30000,)  # un solo descuento
    assert len(await _eventos(pg_platform_url, "fiado.abono_registrado")) == 1


@pytest.mark.asyncio
async def test_el_abono_que_excede_el_saldo_es_rechazada_y_no_arrastra_el_lote(servicio, semilla, pg_platform_url):
    """El 422 `abono_excede_saldo` del servicio es una `rechazada` tipada por
    operación dentro de su SAVEPOINT: el abono bueno que viaja detrás en el
    mismo lote se aplica igual."""
    cliente_id, credito_id = await _credito_por_lote(servicio, semilla, pg_platform_url)
    resultados = await servicio.procesar_lote(
        _lote(
            semilla,
            [
                _op_abono(uuid.uuid4(), credito_id, cliente_id, 3, 99999),
                _op_abono(uuid.uuid4(), credito_id, cliente_id, 4, 20000),
            ],
        )
    )
    assert [r.resultado for r in resultados] == ["rechazada", "aceptada"]
    assert resultados[0].motivo == "abono_excede_saldo"
    assert resultados[0].detalles["saldo_pendiente"] == 43000
    await servicio._session.commit()

    abonos = await _uno(
        pg_platform_url,
        "SELECT count(*), coalesce(sum(monto), 0) FROM fiado_abonos WHERE credito_id = :c",
        c=credito_id,
    )
    assert abonos == (1, 20000)
    saldo = await _uno(pg_platform_url, "SELECT saldo_pendiente FROM fiado_creditos WHERE id = :c", c=credito_id)
    assert saldo == (23000,)


@pytest.mark.asyncio
async def test_el_abono_sin_permiso_es_rechazada(servicio, semilla, pg_platform_url):
    """El veredicto viaja del token como flag (patrón `puede_anular`): el
    lote de un almacenista —sin `fiado:abonar`— ve su abono `rechazada`
    `permiso_ausente`, no un 403 del lote entero."""
    cliente_id, credito_id = await _credito_por_lote(servicio, semilla, pg_platform_url)
    servicio._puede_abonar = False
    abono_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(_lote(semilla, [_op_abono(abono_id, credito_id, cliente_id, 3, 13000)]))
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "permiso_ausente"
    assert resultados[0].detalles["permiso"] == "fiado:abonar"
    await servicio._session.commit()
    assert await _uno(pg_platform_url, "SELECT count(*) FROM fiado_abonos WHERE id = :a", a=abono_id) == (0,)
    saldo = await _uno(pg_platform_url, "SELECT saldo_pendiente FROM fiado_creditos WHERE id = :c", c=credito_id)
    assert saldo == (43000,)


@pytest.mark.asyncio
async def test_el_abono_a_un_credito_de_otro_tenant_es_rechazada_sin_fuga(servicio, semilla, pg_platform_url):
    """El crédito del vecino es invisible por RLS: el abono sale `rechazada`
    `credito_no_encontrado` — el MISMO motivo que un crédito inexistente, sin
    confirmar que el id exista en otro negocio — y no descuenta nada."""
    venta_t2, credito_t2 = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                "medio_pago, total_centavos, cliente_id, creada_en_cliente, secuencia_dispositivo) "
                "VALUES (:v, :t, :d, :s, 1, 'fiado', 50000, :c, now(), 1)"
            ),
            {
                "v": venta_t2,
                "t": T2,
                "d": semilla["dispositivo_t2"],
                "s": semilla["sesion_t2"],
                "c": semilla["cliente_t2"],
            },
        )
        await conn.execute(
            text(
                "INSERT INTO fiado_creditos (id, tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, "
                "estado) VALUES (:cr, :t, :c, :v, 50000, 50000, 'vigente')"
            ),
            {"cr": credito_t2, "t": T2, "c": semilla["cliente_t2"], "v": venta_t2},
        )
    await engine.dispose()

    abono_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(semilla, [_op_abono(abono_id, credito_t2, semilla["cliente_t2"], 1, 10000)])
    )
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "credito_no_encontrado"
    await servicio._session.commit()
    assert await _uno(pg_platform_url, "SELECT count(*) FROM fiado_abonos WHERE credito_id = :c", c=credito_t2) == (0,)
    saldo = await _uno(pg_platform_url, "SELECT saldo_pendiente FROM fiado_creditos WHERE id = :c", c=credito_t2)
    assert saldo == (50000,)


@pytest.mark.asyncio
async def test_el_abono_con_cliente_que_no_es_el_del_credito_es_rechazada(servicio, semilla, pg_platform_url):
    """El ancla de coherencia: el `cliente_id` REQUERIDO del payload es el
    cliente cuyo cuaderno tocó el tendero. Un abono que apunta al crédito de
    otro cliente es `rechazada` `abono_cliente_divergente` antes de tocar
    nada — nunca un descuento a ciegas."""
    cliente_id, credito_id = await _credito_por_lote(servicio, semilla, pg_platform_url)
    otro_cliente = uuid.uuid4()
    await servicio.procesar_lote(_lote(semilla, [_op_cliente(otro_cliente, 3, nombre="Otro vecino")]))

    abono_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(_lote(semilla, [_op_abono(abono_id, credito_id, otro_cliente, 4, 13000)]))
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "abono_cliente_divergente"
    await servicio._session.commit()
    assert await _uno(pg_platform_url, "SELECT count(*) FROM fiado_abonos WHERE credito_id = :c", c=credito_id) == (0,)
    saldo = await _uno(pg_platform_url, "SELECT saldo_pendiente FROM fiado_creditos WHERE id = :c", c=credito_id)
    assert saldo == (43000,)
