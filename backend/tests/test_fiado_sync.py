"""El fiado dentro del lote del sync (decisiones 1-3 del plan del módulo).

Mismo criterio que `test_ventas_servicio.py`: el lote se procesa con la
sesión de tenant real y las filas se verifican por SQL con el rol de
plataforma. Aquí se fija lo firmado: la venta fiada se convierte en crédito
en la misma transacción (incluida la que llega tarde por el sync), el
servidor NO rechaza por cupo (registra y lo muestra), y la anulación anula
el crédito sin tocar el historial de abonos.
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
    engine = create_async_engine(pg_platform_url)
    ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4()}
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


def _op_venta_fiada(
    venta_id: uuid.UUID,
    semilla: dict,
    cliente_id: uuid.UUID,
    total: int,
    secuencia: int,
    consecutivo: int = 1,
    vencimiento: str | None = "2026-08-15",
    estado: str = "completada",
) -> dict:
    datos: dict = {
        "consecutivo_local": consecutivo,
        "estado": estado,
        "medio_pago": "fiado",
        "total_centavos": total,
        "cliente_id": str(cliente_id),
        "creada_en_cliente": "2026-07-28T10:00:00+00:00",
        "items": [{"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": total}],
    }
    if vencimiento is not None:
        datos["fecha_vencimiento"] = vencimiento
    return {"id": str(venta_id), "tipo": "venta.crear", "secuencia": secuencia, "datos": datos}


def _op_anular(operacion_id: uuid.UUID, venta_id: uuid.UUID, secuencia: int) -> dict:
    return {
        "id": str(operacion_id),
        "tipo": "venta.anular",
        "secuencia": secuencia,
        "datos": {"venta_id": str(venta_id)},
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


@pytest.mark.asyncio
async def test_cliente_crear_del_lote_crea_la_fila(servicio, semilla, pg_platform_url):
    cliente_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(_lote(semilla, [_op_cliente(cliente_id, 1)]))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT nombre, telefono FROM clientes WHERE id = :c", c=cliente_id)
    assert fila == ("Don Carlos", "3001234567")


@pytest.mark.asyncio
async def test_cliente_crear_es_idempotente_y_la_divergencia_es_rechazo(servicio, semilla):
    cliente_id = uuid.uuid4()
    await servicio.procesar_lote(_lote(semilla, [_op_cliente(cliente_id, 1)]))
    de_nuevo = await servicio.procesar_lote(_lote(semilla, [_op_cliente(cliente_id, 2)]))
    assert de_nuevo[0].resultado == "duplicada"
    divergente = await servicio.procesar_lote(_lote(semilla, [_op_cliente(cliente_id, 3, nombre="Otro nombre")]))
    assert divergente[0].resultado == "rechazada" and divergente[0].motivo == "cliente_id_divergente"


@pytest.mark.asyncio
async def test_cliente_crear_sin_permiso_es_rechazada(servicio, semilla):
    """El veredicto viaja del token como flag (patrón `puede_anular`): sin
    `cliente:gestionar` la operación es `rechazada`, no un 403 del lote."""
    servicio._puede_gestionar_clientes = False
    resultados = await servicio.procesar_lote(_lote(semilla, [_op_cliente(uuid.uuid4(), 1)]))
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "permiso_ausente"


@pytest.mark.asyncio
async def test_la_venta_fiada_se_convierte_en_credito_en_la_misma_transaccion(servicio, semilla, pg_platform_url):
    """Decisión 1: cliente y venta en el MISMO lote (el orden FIFO del
    dispositivo garantiza la dependencia); al confirmar, el crédito ya
    existe con su saldo igual al total — no hay consumidor que esperar."""
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(semilla, [_op_cliente(cliente_id, 1), _op_venta_fiada(venta_id, semilla, cliente_id, 43000, 2)])
    )
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada"]
    await servicio._session.commit()
    fila = await _uno(
        pg_platform_url,
        "SELECT cliente_id, monto_total, saldo_pendiente, estado, fecha_vencimiento FROM fiado_creditos WHERE venta_id = :v",
        v=venta_id,
    )
    assert fila is not None
    assert fila[0] == cliente_id and fila[1] == 43000 and fila[2] == 43000 and fila[3] == "vigente"
    assert str(fila[4]) == "2026-08-15"
    creados = await _eventos(pg_platform_url, "fiado.credito_creado")
    assert len(creados) == 1 and creados[0]["data"]["monto_total"] == 43000


@pytest.mark.asyncio
async def test_la_venta_fiada_sin_cliente_conocido_no_se_rechaza(servicio, semilla, pg_platform_url):
    """La red de seguridad de la decisión 2: la venta se acepta SIEMPRE
    (ADR-018); el cliente queda con placeholder editable y el fiado existe."""
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(semilla, [_op_venta_fiada(venta_id, semilla, cliente_id, 12000, 1)])
    )
    assert resultados[0].resultado == "aceptada"
    await servicio._session.commit()
    cliente = await _uno(pg_platform_url, "SELECT nombre FROM clientes WHERE id = :c", c=cliente_id)
    assert cliente == ("(sin nombre)",)
    credito = await _uno(pg_platform_url, "SELECT saldo_pendiente FROM fiado_creditos WHERE venta_id = :v", v=venta_id)
    assert credito == (12000,)


@pytest.mark.asyncio
async def test_la_venta_fiada_sin_permiso_es_rechazada_y_no_deja_credito(servicio, semilla, pg_platform_url):
    servicio._puede_fiar = False
    venta_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(semilla, [_op_venta_fiada(venta_id, semilla, uuid.uuid4(), 5000, 1)])
    )
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "permiso_ausente"
    assert await _uno(pg_platform_url, "SELECT id FROM ventas WHERE id = :v", v=venta_id) is None
    assert await _uno(pg_platform_url, "SELECT id FROM fiado_creditos WHERE venta_id = :v", v=venta_id) is None


@pytest.mark.asyncio
async def test_el_cupo_no_rechaza_pero_el_exceso_viaja_en_el_resultado(servicio, semilla, pg_platform_url):
    """ADR-018: la mercancía ya salió; el servidor registra el exceso y lo
    muestra (decisión 8): `detalles.cupo_excedido` en la aceptada."""
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(
            semilla,
            [
                _op_cliente(cliente_id, 1, limite_credito=50000),
                _op_venta_fiada(venta_id, semilla, cliente_id, 80000, 2),
            ],
        )
    )
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada"]
    assert resultados[1].detalles == {"cupo_excedido": True}
    # Y una venta dentro del cupo viaja sin la señal.
    dentro = await servicio.procesar_lote(
        _lote(semilla, [_op_venta_fiada(uuid.uuid4(), semilla, cliente_id, 1000, 3, consecutivo=2)])
    )
    assert dentro[0].detalles == {"cupo_excedido": True}  # 81.000 > 50.000: sigue excedido


@pytest.mark.asyncio
async def test_la_anulacion_anula_el_credito_sin_tocar_los_abonos(servicio, semilla, pg_platform_url):
    """Decisión 3 (el caso duro): fiado de 100 con 30 abonados; la anulación
    pone el crédito `anulado` con saldo 0, el abono queda como historia y el
    evento lleva `total_abonado` para que el tendero decida la devolución."""
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    await servicio.procesar_lote(
        _lote(semilla, [_op_cliente(cliente_id, 1), _op_venta_fiada(venta_id, semilla, cliente_id, 100000, 2)])
    )
    await servicio._session.commit()
    credito = await _uno(pg_platform_url, "SELECT id FROM fiado_creditos WHERE venta_id = :v", v=venta_id)
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO fiado_abonos (id, tenant_id, credito_id, monto, metodo_pago, registrado_por) "
                "VALUES (:a, :t, :cr, 30000, 'efectivo', 'dueno')"
            ),
            {"a": uuid.uuid4(), "t": T1, "cr": credito[0]},
        )
        await conn.execute(text("UPDATE fiado_creditos SET saldo_pendiente = 70000 WHERE id = :cr"), {"cr": credito[0]})
    await engine.dispose()

    anulacion = await servicio.procesar_lote(_lote(semilla, [_op_anular(uuid.uuid4(), venta_id, 3)]))
    assert anulacion[0].resultado == "aceptada"
    await servicio._session.commit()
    estado = await _uno(
        pg_platform_url, "SELECT estado, saldo_pendiente FROM fiado_creditos WHERE id = :c", c=credito[0]
    )
    assert estado == ("anulado", 0)
    abono = await _uno(pg_platform_url, "SELECT monto FROM fiado_abonos WHERE credito_id = :c", c=credito[0])
    assert abono == (30000,)  # el historial es la verdad y no se reescribe (ADR-022)
    anulados = await _eventos(pg_platform_url, "fiado.credito_anulado")
    assert len(anulados) == 1 and anulados[0]["data"]["total_abonado"] == 30000


@pytest.mark.asyncio
async def test_la_venta_que_sube_ya_anulada_no_genera_credito(servicio, semilla, pg_platform_url):
    """Como no mueve stock (decisión 9 del plan de ventas), tampoco genera
    deuda: su efecto neto es cero."""
    venta_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(semilla, [_op_venta_fiada(venta_id, semilla, uuid.uuid4(), 8000, 1, estado="anulada")])
    )
    assert resultados[0].resultado == "aceptada"
    assert await _uno(pg_platform_url, "SELECT id FROM fiado_creditos WHERE venta_id = :v", v=venta_id) is None


@pytest.mark.asyncio
async def test_la_fecha_de_vencimiento_es_solo_del_fiado(servicio, semilla):
    datos = _op_venta_fiada(uuid.uuid4(), semilla, uuid.uuid4(), 5000, 1)
    datos["datos"]["medio_pago"] = "efectivo"
    datos["datos"]["cliente_id"] = None
    resultados = await servicio.procesar_lote(_lote(semilla, [datos]))
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "fecha_vencimiento_solo_en_fiado"


@pytest.mark.asyncio
async def test_el_lote_reenviado_no_duplica_cliente_credito_ni_eventos(servicio, semilla, pg_platform_url):
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    lote = _lote(semilla, [_op_cliente(cliente_id, 1), _op_venta_fiada(venta_id, semilla, cliente_id, 9000, 2)])
    await servicio.procesar_lote(lote)
    de_nuevo = await servicio.procesar_lote(lote)
    assert [r.resultado for r in de_nuevo] == ["duplicada", "duplicada"]
    await servicio._session.commit()
    filas = await _uno(pg_platform_url, "SELECT count(*) FROM fiado_creditos WHERE venta_id = :v", v=venta_id)
    assert filas == (1,)
    assert len(await _eventos(pg_platform_url, "fiado.credito_creado")) == 1
