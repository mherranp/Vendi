"""QA adversarial del fiado y los clientes: ataques sobre el saldo al peso,
las carreras del abono, la anulación creativa, la conversión del sync, los
vencimientos en el calendario de Bogotá, el arqueo y el forecast.

Compañero de `test_fiado_servicio.py`, `test_fiado_sync.py`,
`test_fiado_vencimientos.py` y `test_aislamiento_fiado.py`, no sustituto:
aquello fija el camino feliz, la idempotencia firmada y el aislamiento por
RLS; esto empuja las esquinas que el plan deja en penumbra — dos abonos
concurrentes que juntos exceden, el abono que salda contra otro en vuelo, la
anulación de la fiada SALDADA con el dinero ya en la gaveta, el placeholder
mejorado tras una edición REST intermedia, la venta fiada con el `cliente_id`
de OTRO tenant, el que vence exactamente hoy, el segundo recordatorio, la
pasada del trabajo en paralelo, el abono contra el cierre, y el borde de 30
días del forecast — y deja cada comportamiento FIJO en un test.

Dos de estos tests DOCUMENTAN comportamientos discutibles a propósito (el
assert es el comportamiento actual; la discusión vive en
`.superpowers/sdd/qa-adversarial-fiado-report.md`):

- El upgrade del placeholder `(sin nombre)` PISA la edición REST intermedia:
  si el tendero le puso nota y teléfono por la API antes de que suba el
  `cliente.crear` del lote, el upgrade adopta el payload (con `None` y todo)
  y la edición humana se pierde.
- La venta fiada cuyo `cliente_id` existe en OTRO tenant sale `rechazada`
  (el INSERT del placeholder revienta contra la PK invisible): es la única
  venta que el sistema rechaza por un id ajeno, contra el espíritu de
  «la venta no se rechaza jamás» de ADR-018.

Si alguno cambia a un comportamiento distinto, el test se reescribe, no se
borra.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from pydantic import ValidationError as ErrorDeEsquema
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.caja.reportes import ZONA_LOCAL, ReportesService
from app.modules.caja.schemas import SesionCerrar
from app.modules.caja.service import CajaService, calcular_desglose
from app.modules.fiado.models import Cliente, FiadoCredito
from app.modules.fiado.schemas import AbonoCrear, ClienteCrear, ClienteEditar, CreditoReprogramar
from app.modules.fiado.service import FiadoService, construir_whatsapp_url
from app.modules.ventas.models import CajaSesion
from app.modules.ventas.schemas import LoteSync
from app.modules.ventas.service import VentasService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_platform_session_factory, create_session_factory
from vendi_core.errors.domain import ConflictError, NotFoundError, ValidationError
from vendi_core.jobs.types import JobContext
from vendi_core.tenant.context import current_tenant_id
from worker.jobs import marcar_vencimientos_fiado

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM fiado_abonos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM fiado_creditos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM clientes WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_movimientos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.fiado.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)

#: «Hoy» en el calendario que juzga los vencimientos (ADR-022), calculado por
#: el propio Postgres: su `CURRENT_DATE` corre en UTC y se adelanta a Bogotá.
HOY_BOGOTA = "(now() AT TIME ZONE 'America/Bogota')::date"


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """En T1: un cliente con límite, un dispositivo, un producto y una sesión
    de caja abierta con base 0. En T2: un cliente (id conocido, para los
    choques de PK), un dispositivo y una sesión — la infraestructura del
    vecino para sembrarle un crédito. Limpieza total antes y después."""
    engine = create_async_engine(pg_platform_url)
    ids = {
        "cliente": uuid.uuid4(),
        "cliente_t2": uuid.uuid4(),
        "dispositivo": uuid.uuid4(),
        "dispositivo_t2": uuid.uuid4(),
        "producto": uuid.uuid4(),
        "sesion": uuid.uuid4(),
        "sesion_t2": uuid.uuid4(),
    }
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text(
                "INSERT INTO clientes (id, tenant_id, nombre, telefono, limite_credito) "
                "VALUES (:c, :t, 'Don Carlos', '3001234567', 100000)"
            ),
            {"c": ids["cliente"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO clientes (id, tenant_id, nombre) VALUES (:c, :t, 'La vecina')"),
            {"c": ids["cliente_t2"], "t": T2},
        )
        for clave, tenant in (("dispositivo", T1), ("dispositivo_t2", T2)):
            await conn.execute(
                text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
                {"d": ids[clave], "t": tenant},
            )
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                "VALUES (:p, :t, 'Arroz 500g', 2500, 100)"
            ),
            {"p": ids["producto"], "t": T1},
        )
        for clave, tenant in (("sesion", T1), ("sesion_t2", T2)):
            await conn.execute(
                text(
                    "INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) VALUES (:s, :t, 'dueno', 0)"
                ),
                {"s": ids[clave], "t": tenant},
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
            yield FiadoService(session=s, tenant_id=T1, actor_id="qa-adversarial")
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


@pytest_asyncio.fixture
async def ventas(pg_app_url: str, semilla):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield VentasService(
                session=s,
                tenant_id=T1,
                actor_id="qa-adversarial",
                puede_anular=True,
                puede_fiar=True,
                puede_gestionar_clientes=True,
            )
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def _credito(
    pg_platform_url: str,
    semilla: dict,
    monto: int,
    saldo: int,
    estado: str = "vigente",
    vencimiento: str = f"{HOY_BOGOTA} + 10",
    cliente_id: uuid.UUID | None = None,
    tenant: uuid.UUID = T1,
) -> uuid.UUID:
    """Un crédito por SQL con su venta fiada (mismo criterio que
    `test_fiado_servicio._credito`): aquí se siembra el estado ya aplicado."""
    sufijo = "" if tenant == T1 else "_t2"
    venta_id, credito_id = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            consecutivo = (
                await conn.execute(text("SELECT count(*) FROM ventas WHERE tenant_id = :t"), {"t": tenant})
            ).scalar_one() + 1
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                    "medio_pago, total_centavos, cliente_id, creada_en_cliente, secuencia_dispositivo) "
                    f"VALUES (:v, :t, :d, :s, {consecutivo}, 'fiado', :m, :c, now(), 1)"
                ),
                {
                    "v": venta_id,
                    "t": tenant,
                    "d": semilla[f"dispositivo{sufijo}"],
                    "s": semilla[f"sesion{sufijo}"],
                    "m": monto,
                    "c": cliente_id or semilla[f"cliente{sufijo}"],
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO fiado_creditos (id, tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, "
                    f"fecha_vencimiento, estado) VALUES (:cr, :t, :c, :v, :m, :s, {vencimiento}, :e)"
                ),
                {
                    "cr": credito_id,
                    "t": tenant,
                    "c": cliente_id or semilla[f"cliente{sufijo}"],
                    "v": venta_id,
                    "m": monto,
                    "s": saldo,
                    "e": estado,
                },
            )
    finally:
        await engine.dispose()
    return credito_id


async def _venta_de(pg_platform_url: str, credito_id: uuid.UUID) -> uuid.UUID:
    fila = await _uno(pg_platform_url, "SELECT venta_id FROM fiado_creditos WHERE id = :c", c=credito_id)
    return fila.venta_id


def _abono(monto: int, metodo: str = "efectivo", **cambios) -> AbonoCrear:
    return AbonoCrear.model_validate({"id": str(uuid.uuid4()), "monto": monto, "metodo_pago": metodo, **cambios})


def _lote(semilla: dict, operaciones: list[dict]) -> LoteSync:
    return LoteSync.model_validate({"dispositivo_id": str(semilla["dispositivo"]), "operaciones": operaciones})


def _op_cliente(cliente_id: uuid.UUID, secuencia: int, **datos) -> dict:
    base: dict = {"nombre": "Don Carlos", "telefono": "3001234567"}
    base.update(datos)
    return {"id": str(cliente_id), "tipo": "cliente.crear", "secuencia": secuencia, "datos": base}


def _op_venta_fiada(
    venta_id: uuid.UUID, semilla: dict, cliente_id: uuid.UUID, total: int, secuencia: int, consecutivo: int = 1
) -> dict:
    return {
        "id": str(venta_id),
        "tipo": "venta.crear",
        "secuencia": secuencia,
        "datos": {
            "consecutivo_local": consecutivo,
            "estado": "completada",
            "medio_pago": "fiado",
            "total_centavos": total,
            "cliente_id": str(cliente_id),
            "creada_en_cliente": "2026-07-28T10:00:00+00:00",
            "items": [{"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": total}],
        },
    }


def _op_anular(operacion_id: uuid.UUID, venta_id: uuid.UUID, secuencia: int) -> dict:
    return {
        "id": str(operacion_id),
        "tipo": "venta.anular",
        "secuencia": secuencia,
        "datos": {"venta_id": str(venta_id)},
    }


def _ctx(pg_platform_url: str, tenant_id: uuid.UUID) -> JobContext:
    engine = create_engine(pg_platform_url)
    return JobContext(session_factory=create_platform_session_factory(engine), engine=engine, tenant_id=tenant_id)


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


async def _conteo_eventos(pg_platform_url: str, evento: str) -> int:
    fila = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key LIKE :k", k=f"%.{evento}"
    )
    return fila.n


async def _estado_credito(pg_platform_url: str, credito_id: uuid.UUID) -> tuple:
    fila = await _uno(pg_platform_url, "SELECT estado, saldo_pendiente FROM fiado_creditos WHERE id = :c", c=credito_id)
    return fila.estado, fila.saldo_pendiente


async def _abono_con_sesion_propia(pg_app_url: str, credito_id: uuid.UUID, datos: AbonoCrear) -> str:
    """Un abono desde su propia conexión (la carrera de verdad: dos requests
    no comparten sesión). Traduce el desenlace a una etiqueta comparable."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            servicio_propio = FiadoService(session=s, tenant_id=T1, actor_id="qa-adversarial")
            try:
                await servicio_propio.registrar_abono(credito_id, datos)
                await s.commit()
                return "registrado"
            except ConflictError as exc:
                await s.rollback()
                assert exc.code in ("abono_id_divergente", "credito_no_abonable", "caja_sin_sesion_abierta")
                return exc.code
            except ValidationError as exc:
                await s.rollback()
                assert exc.code == "abono_excede_saldo"
                return "excede"
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


# --- El saldo al peso: carreras y aritmética exacta ------------------------------


@pytest.mark.asyncio
async def test_dos_abonos_concurrentes_que_juntos_exceden_deja_uno_y_el_otro_es_422(
    pg_app_url, semilla, pg_platform_url
):
    """Crédito de 100, dos abonos de 70 en vuelo: el FOR UPDATE los serializa
    (no el CHECK — el perdedor ni siquiera llega a insertar: re-lee el saldo
    ya descontado y el pre-chequeo da el 422). Uno registra, el otro sale
    `abono_excede_saldo`, el saldo queda en 30 y hay UN abono y UN evento."""
    credito_id = await _credito(pg_platform_url, semilla, 100000, 100000)
    resultados = await asyncio.gather(
        _abono_con_sesion_propia(pg_app_url, credito_id, _abono(70000, "otro")),
        _abono_con_sesion_propia(pg_app_url, credito_id, _abono(70000, "otro")),
        return_exceptions=True,
    )
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            raise resultado
    assert sorted(resultados) == ["excede", "registrado"]
    assert await _estado_credito(pg_platform_url, credito_id) == ("vigente", 30000)
    fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM fiado_abonos WHERE credito_id = :c", c=credito_id)
    assert fila.n == 1
    assert await _conteo_eventos(pg_platform_url, "fiado.abono_registrado") == 1


@pytest.mark.asyncio
async def test_el_abono_que_salda_y_otro_abono_concurrente_deja_uno_solo(pg_app_url, semilla, pg_platform_url):
    """Abono de 50 (salda) contra abono de 10, en vuelo. Los dos intercalados
    posibles son correctos: si gana el de 50, el de 10 re-lee `saldado` y sale
    409 `credito_no_abonable` (NO se cuela); si gana el de 10, el de 50 re-lee
    saldo 40 y sale 422. Jamás los dos: UN abono y un saldo coherente."""
    credito_id = await _credito(pg_platform_url, semilla, 50000, 50000)
    resultados = await asyncio.gather(
        _abono_con_sesion_propia(pg_app_url, credito_id, _abono(50000, "otro")),
        _abono_con_sesion_propia(pg_app_url, credito_id, _abono(10000, "otro")),
        return_exceptions=True,
    )
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            raise resultado
    assert sorted(resultados) in (["credito_no_abonable", "registrado"], ["excede", "registrado"])
    estado, saldo = await _estado_credito(pg_platform_url, credito_id)
    assert (estado, saldo) in (("saldado", 0), ("vigente", 40000))
    fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM fiado_abonos WHERE credito_id = :c", c=credito_id)
    assert fila.n == 1


@pytest.mark.asyncio
async def test_dos_primeros_envios_concurrentes_con_la_misma_ancla_dejan_un_abono(pg_app_url, semilla, pg_platform_url):
    """La carrera de dos PRIMEROS envíos con el mismo `id`: los dos leen
    `get() → None`; el perdedor revienta contra la PK al insertar y sale 409
    `abono_id_divergente`, nunca un 500 (mismo patrón que caja). Una fila, un
    evento, el saldo descontado UNA vez."""
    credito_id = await _credito(pg_platform_url, semilla, 80000, 80000)
    ancla = _abono(30000, "otro")
    resultados = await asyncio.gather(
        _abono_con_sesion_propia(pg_app_url, credito_id, ancla),
        _abono_con_sesion_propia(pg_app_url, credito_id, ancla),
        return_exceptions=True,
    )
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            raise resultado
    assert sorted(resultados) == ["abono_id_divergente", "registrado"]
    assert await _estado_credito(pg_platform_url, credito_id) == ("vigente", 50000)
    fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM fiado_abonos WHERE credito_id = :c", c=credito_id)
    assert fila.n == 1
    assert await _conteo_eventos(pg_platform_url, "fiado.abono_registrado") == 1


@pytest.mark.asyncio
async def test_el_abono_de_un_centavo_sobre_saldo_de_uno_salda_exacto(servicio, semilla, pg_platform_url):
    """Aritmética entera (centavos, ADR-018): no hay fracción que acumular —
    1 sobre 1 salda al peso y cierra el crédito. Un monto fraccionado ni
    siquiera pasa el schema."""
    credito_id = await _credito(pg_platform_url, semilla, 1, 1)
    await servicio.registrar_abono(credito_id, _abono(1, "otro"))
    await servicio._session.commit()
    assert await _estado_credito(pg_platform_url, credito_id) == ("saldado", 0)
    with pytest.raises(ErrorDeEsquema):
        AbonoCrear.model_validate({"id": str(uuid.uuid4()), "monto": 1.5, "metodo_pago": "otro"})


@pytest.mark.asyncio
async def test_el_reintento_del_abono_que_salda_no_choca_con_el_saldado(servicio, semilla, pg_platform_url):
    """La trampa del orden de los chequeos: el abono de 50 salda y confirma;
    el cliente reintenta por timeout con la MISMA ancla. La idempotencia va
    ANTES del candado de estado — si fuera al revés, el reintento legítimo
    recibiría 409 `credito_no_abonable` y el POS creería que el pago falló."""
    credito_id = await _credito(pg_platform_url, semilla, 50000, 50000)
    datos = _abono(50000, "transferencia")
    primero = await servicio.registrar_abono(credito_id, datos)
    await servicio._session.commit()
    segundo = await servicio.registrar_abono(credito_id, datos)
    assert segundo.id == primero.id
    assert await _estado_credito(pg_platform_url, credito_id) == ("saldado", 0)
    fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM fiado_abonos WHERE credito_id = :c", c=credito_id)
    assert fila.n == 1


# --- Anulación creativa ------------------------------------------------------------


@pytest.mark.asyncio
async def test_anular_la_fiada_saldada_deja_el_abono_y_el_arqueo_intactos(ventas, servicio, semilla, pg_platform_url):
    """El caso firmado, verificado en la gaveta: fiado de 50 cobrado EN
    EFECTIVO (saldado, plata dentro de la sesión abierta) y la venta se anula
    después. El crédito pasa a `anulado`, el abono es historia intocable
    (ADR-022) y el arqueo NO se descuadra: el esperado vivo sigue contando
    los 50 — la devolución es un gesto manual de caja (decisión 3)."""
    venta_id = uuid.uuid4()
    await ventas.procesar_lote(_lote(semilla, [_op_venta_fiada(venta_id, semilla, semilla["cliente"], 50000, 1)]))
    await ventas._session.commit()
    credito_id = (await _uno(pg_platform_url, "SELECT id FROM fiado_creditos WHERE venta_id = :v", v=venta_id)).id
    await servicio.registrar_abono(credito_id, _abono(50000))
    await servicio._session.commit()
    sesion = await servicio._session.get(CajaSesion, semilla["sesion"])
    antes = await calcular_desglose(servicio._session, sesion)
    assert antes.abonos_efectivo == 50000 and antes.esperado == 50000

    anulacion = await ventas.procesar_lote(_lote(semilla, [_op_anular(uuid.uuid4(), venta_id, 2)]))
    assert anulacion[0].resultado == "aceptada"
    await ventas._session.commit()

    assert await _estado_credito(pg_platform_url, credito_id) == ("anulado", 0)
    despues = await calcular_desglose(servicio._session, sesion)
    assert despues.abonos_efectivo == 50000 and despues.esperado == antes.esperado
    abono = await _uno(
        pg_platform_url,
        "SELECT monto, sesion_caja_id FROM fiado_abonos WHERE credito_id = :c",
        c=credito_id,
    )
    assert abono.monto == 50000 and abono.sesion_caja_id == semilla["sesion"]  # intacto, con su sesión
    evento = await _uno(
        pg_platform_url,
        "SELECT payload FROM outbox_messages WHERE routing_key LIKE :k",
        k="%.fiado.credito_anulado",
    )
    assert evento.payload["data"]["total_abonado"] == 50000


@pytest.mark.asyncio
async def test_la_anulacion_reintentada_de_la_fiada_es_duplicada_y_no_reemite(ventas, semilla, pg_platform_url):
    """Dos operaciones de anulación DISTINTAS sobre la misma venta fiada: la
    segunda sale `duplicada`, el crédito se anuló una vez y hay UN solo
    `fiado.credito_anulado` en el outbox."""
    venta_id = uuid.uuid4()
    await ventas.procesar_lote(_lote(semilla, [_op_venta_fiada(venta_id, semilla, semilla["cliente"], 43000, 1)]))
    await ventas._session.commit()
    primera = await ventas.procesar_lote(_lote(semilla, [_op_anular(uuid.uuid4(), venta_id, 2)]))
    await ventas._session.commit()
    segunda = await ventas.procesar_lote(_lote(semilla, [_op_anular(uuid.uuid4(), venta_id, 3)]))
    assert primera[0].resultado == "aceptada" and segunda[0].resultado == "duplicada"
    credito = await _uno(
        pg_platform_url, "SELECT estado, saldo_pendiente FROM fiado_creditos WHERE venta_id = :v", v=venta_id
    )
    assert (credito.estado, credito.saldo_pendiente) == ("anulado", 0)
    assert await _conteo_eventos(pg_platform_url, "fiado.credito_anulado") == 1


@pytest.mark.asyncio
async def test_anular_la_venta_fiada_del_vecino_es_rechazada_y_no_toca_el_credito(pg_app_url, semilla, pg_platform_url):
    """El lote de T2 pide anular la venta fiada de T1: la RLS la hace
    invisible → `venta_no_encontrada`, y el crédito del vecino sigue vigente
    con su saldo intacto."""
    credito_id = await _credito(pg_platform_url, semilla, 60000, 60000)
    venta_id = await _venta_de(pg_platform_url, credito_id)
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T2)
    try:
        async with factory() as s2:
            ventas_t2 = VentasService(session=s2, tenant_id=T2, actor_id="vecino", puede_anular=True, puede_fiar=True)
            lote = LoteSync.model_validate(
                {
                    "dispositivo_id": str(semilla["dispositivo_t2"]),
                    "operaciones": [_op_anular(uuid.uuid4(), venta_id, 1)],
                }
            )
            resultados = await ventas_t2.procesar_lote(lote)
            await s2.commit()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "venta_no_encontrada"
    assert await _estado_credito(pg_platform_url, credito_id) == ("vigente", 60000)


# --- Conversión sync ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_upgrade_del_placeholder_pisa_la_edicion_rest_intermedia(ventas, servicio, semilla, pg_platform_url):
    """DOCUMENTA UN COMPORTAMIENTO DISCUTIBLE (ver reporte QA): la venta fiada
    sube primero y deja el placeholder; el tendero le pone nota y teléfono
    por la API; el `cliente.crear` del lote llega tarde SIN esos datos y el
    upgrade adopta el payload entero — la edición humana se pierde (`None`
    incluido). El assert fija el comportamiento actual, no el deseado."""
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    await ventas.procesar_lote(_lote(semilla, [_op_venta_fiada(venta_id, semilla, cliente_id, 12000, 1)]))
    await ventas._session.commit()
    await servicio.editar_cliente(
        cliente_id, ClienteEditar.model_validate({"nota": "El de la bicicleta", "telefono": "3119876543"})
    )
    await servicio._session.commit()

    resultados = await ventas.procesar_lote(
        _lote(semilla, [_op_cliente(cliente_id, 2, nombre="Don Carlos real", telefono=None, nota=None)])
    )
    assert resultados[0].resultado == "aceptada" and resultados[0].detalles == {"placeholder_mejorado": True}
    await ventas._session.commit()
    fila = await _uno(pg_platform_url, "SELECT nombre, telefono, nota FROM clientes WHERE id = :c", c=cliente_id)
    assert fila == ("Don Carlos real", None, None)  # la nota y el teléfono de la API: borrados


@pytest.mark.asyncio
async def test_la_venta_fiada_con_cliente_id_de_otro_tenant_es_rechazada(ventas, semilla, pg_platform_url):
    """DOCUMENTA UN COMPORTAMIENTO DISCUTIBLE (ver reporte QA): el `cliente_id`
    existe en T2 (invisible por RLS) → el alta mínima del placeholder revienta
    contra `clientes_pkey` y la VENTA sale `rechazada` — la única venta que el
    sistema rechaza por un id ajeno, contra el «no se rechaza jamás» de
    ADR-018. El motivo (`cliente_id_divergente`) además describe mal el caso.
    No queda venta, ni crédito, ni placeholder: el fiado se pierde."""
    venta_id = uuid.uuid4()
    resultados = await ventas.procesar_lote(
        _lote(semilla, [_op_venta_fiada(venta_id, semilla, semilla["cliente_t2"], 25000, 1)])
    )
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "cliente_id_divergente"
    await ventas._session.commit()
    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM ventas WHERE id = :v) AS ventas, "
        "(SELECT count(*) FROM fiado_creditos WHERE venta_id = :v) AS creditos, "
        "(SELECT count(*) FROM clientes WHERE id = :c) AS clientes",
        v=venta_id,
        c=semilla["cliente_t2"],
    )
    assert (fila.ventas, fila.creditos, fila.clientes) == (0, 0, 1)  # la única fila es la del vecino


@pytest.mark.asyncio
async def test_dos_ventas_fiadas_del_mismo_cliente_en_un_lote_dejan_dos_creditos(
    ventas, servicio, semilla, pg_platform_url
):
    """Un cliente, dos fiadas en el mismo lote: dos créditos (UNO por venta,
    `ux_fiado_creditos_venta`), un solo cliente, y el cupo de la segunda se
    evalúa contra el saldo ACUMULADO — 40 + 40 con límite 50: la primera no
    marca, la segunda viaja con `cupo_excedido` (sin rechazar, ADR-018)."""
    cliente_id = uuid.uuid4()
    resultados = await ventas.procesar_lote(
        _lote(
            semilla,
            [
                _op_cliente(cliente_id, 1, limite_credito=50000),
                _op_venta_fiada(uuid.uuid4(), semilla, cliente_id, 40000, 2),
                _op_venta_fiada(uuid.uuid4(), semilla, cliente_id, 40000, 3, consecutivo=2),
            ],
        )
    )
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada", "aceptada"]
    assert resultados[1].detalles is None and resultados[2].detalles == {"cupo_excedido": True}
    await ventas._session.commit()
    fila = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n, sum(saldo_pendiente) AS saldo FROM fiado_creditos WHERE cliente_id = :c",
        c=cliente_id,
    )
    assert (fila.n, fila.saldo) == (2, 80000)
    detalle = await servicio.obtener_cliente(cliente_id)
    assert detalle.saldo_pendiente_total == 80000 and detalle.cupo_excedido is True


# --- Vencimientos en el calendario de Bogotá ----------------------------------------


@pytest.mark.asyncio
async def test_el_que_vence_hoy_aun_no_vence_y_el_anulado_lo_ignora_el_trabajo(pg_platform_url, semilla):
    """El `fecha_vencimiento < hoy` del UPDATE, en sus dos bordes: el que
    vence EXACTAMENTE hoy en Bogotá tiene todo el día para pagar (no se marca,
    no hay evento), y un `anulado` con fecha ya pasada no existe para el
    trabajo aunque su fecha grite."""
    vence_hoy = await _credito(pg_platform_url, semilla, 43000, 43000, vencimiento=HOY_BOGOTA)
    anulado = await _credito(pg_platform_url, semilla, 30000, 0, estado="anulado", vencimiento=f"{HOY_BOGOTA} - 3")
    cambios = await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    assert cambios == {"creditos_vencidos": 0}
    assert await _estado_credito(pg_platform_url, vence_hoy) == ("vigente", 43000)
    assert await _estado_credito(pg_platform_url, anulado) == ("anulado", 0)
    assert await _conteo_eventos(pg_platform_url, "fiado.credito_vencido") == 0


@pytest.mark.asyncio
async def test_reprogramar_a_ayer_lo_deja_vencido_y_el_trabajo_no_reemite(servicio, semilla, pg_platform_url):
    """«Déjelo para ayer»: un `vencido` reprogramado a una fecha YA pasada no
    vuelve a `vigente` — sigue vencido sin re-emitir, y la siguiente pasada
    del trabajo lo encuentra `vencido` (0 marcados, 0 eventos nuevos)."""
    credito_id = await _credito(
        pg_platform_url, semilla, 50000, 50000, estado="vencido", vencimiento=f"{HOY_BOGOTA} - 2"
    )
    ayer = datetime.now(ZONA_LOCAL).date() - timedelta(days=1)
    reprogramado = await servicio.reprogramar_vencimiento(
        credito_id, CreditoReprogramar.model_validate({"fecha_vencimiento": ayer})
    )
    assert reprogramado.estado == "vencido" and reprogramado.fecha_vencimiento == ayer
    await servicio._session.commit()
    cambios = await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    assert cambios == {"creditos_vencidos": 0}
    assert await _conteo_eventos(pg_platform_url, "fiado.credito_vencido") == 0


@pytest.mark.asyncio
async def test_reprogramar_a_futuro_y_dejarlo_vencer_emite_un_segundo_recordatorio(servicio, semilla, pg_platform_url):
    """El ciclo completo firmado (decisión 7): vence → 1 recordatorio; «deme
    hasta el otro viernes» → `vigente`; la nueva fecha pasa → el trabajo lo
    vuelve a marcar y emite el SEGUNDO `fiado.credito_vencido`. La transición
    es el anti-duplicado y también el re-armado."""
    credito_id = await _credito(pg_platform_url, semilla, 50000, 50000, vencimiento=f"{HOY_BOGOTA} - 1")
    await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    assert await _estado_credito(pg_platform_url, credito_id) == ("vencido", 50000)
    assert await _conteo_eventos(pg_platform_url, "fiado.credito_vencido") == 1
    reprogramado = await servicio.reprogramar_vencimiento(
        credito_id, CreditoReprogramar.model_validate({"fecha_vencimiento": "2099-01-15"})
    )
    assert reprogramado.estado == "vigente"
    await servicio._session.commit()
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE fiado_creditos SET fecha_vencimiento = {HOY_BOGOTA} - 1 WHERE id = :c"), {"c": credito_id}
        )
    await engine.dispose()
    cambios = await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    assert cambios == {"creditos_vencidos": 1}
    assert await _conteo_eventos(pg_platform_url, "fiado.credito_vencido") == 2


@pytest.mark.asyncio
async def test_el_trabajo_en_paralelo_marca_una_sola_vez(pg_platform_url, semilla):
    """Dos pasadas EN PARALELO (reintento del scheduler contra sí mismo): el
    UPDATE bloquea las filas que devuelve hasta el commit — el perdedor
    espera, re-lee `vencido` y marca 0. Un solo evento entre los dos."""
    credito_id = await _credito(pg_platform_url, semilla, 43000, 43000, vencimiento=f"{HOY_BOGOTA} - 1")
    resultados = await asyncio.gather(
        marcar_vencimientos_fiado(_ctx(pg_platform_url, T1)),
        marcar_vencimientos_fiado(_ctx(pg_platform_url, T1)),
    )
    assert sorted(r["creditos_vencidos"] for r in resultados) == [0, 1]
    assert await _estado_credito(pg_platform_url, credito_id) == ("vencido", 43000)
    assert await _conteo_eventos(pg_platform_url, "fiado.credito_vencido") == 1


# --- Arqueo y forecast con fiado ------------------------------------------------------


@pytest.mark.asyncio
async def test_el_arqueo_cuadra_al_peso_con_venta_abono_y_movimientos(servicio, semilla, pg_platform_url):
    """La cuenta completa de la sesión, al peso: base 0 + venta en efectivo
    25.000 + abono de fiado en efectivo 30.000 + ingreso 5.000 − egreso 2.000
    = 58.000. El abono entra desde `fiado_abonos` por su `sesion_caja_id`,
    sin duplicarse como movimiento (ADR-021)."""
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                "medio_pago, total_centavos, creada_en_cliente, secuencia_dispositivo) "
                "VALUES (:v, :t, :d, :s, 900, 'efectivo', 25000, now(), 900)"
            ),
            {"v": uuid.uuid4(), "t": T1, "d": semilla["dispositivo"], "s": semilla["sesion"]},
        )
        for tipo, monto in (("ingreso", 5000), ("egreso", 2000)):
            await conn.execute(
                text(
                    "INSERT INTO caja_movimientos (id, tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, "
                    "registrado_por) VALUES (:m, :t, :s, :tipo, 'otro', :monto, 'QA', 'qa')"
                ),
                {"m": uuid.uuid4(), "t": T1, "s": semilla["sesion"], "tipo": tipo, "monto": monto},
            )
    await engine.dispose()
    credito_id = await _credito(pg_platform_url, semilla, 30000, 30000)
    await servicio.registrar_abono(credito_id, _abono(30000))
    await servicio._session.commit()
    sesion = await servicio._session.get(CajaSesion, semilla["sesion"])
    desglose = await calcular_desglose(servicio._session, sesion)
    assert (desglose.ventas_efectivo, desglose.abonos_efectivo, desglose.ingresos, desglose.egresos) == (
        25000,
        30000,
        5000,
        2000,
    )
    assert desglose.esperado == 58000


@pytest.mark.asyncio
async def test_el_abono_por_transferencia_no_toca_el_arqueo_ni_las_ventas(servicio, semilla, pg_platform_url):
    """Decisión 9: la transferencia no pasa por la gaveta — `sesion_caja_id`
    NULL, `abonos_efectivo` en 0 y el esperado vivo sin moverse. Tampoco es
    una venta: el P&L la conoce como cobro del fiado, no como venta nueva."""
    credito_id = await _credito(pg_platform_url, semilla, 40000, 40000)
    abono = await servicio.registrar_abono(credito_id, _abono(40000, "transferencia"))
    assert abono.sesion_caja_id is None
    await servicio._session.commit()
    sesion = await servicio._session.get(CajaSesion, semilla["sesion"])
    desglose = await calcular_desglose(servicio._session, sesion)
    assert desglose.abonos_efectivo == 0 and desglose.esperado == 0


@pytest.mark.asyncio
async def test_el_abono_en_efectivo_y_el_cierre_concurrentes_no_se_pisan(pg_app_url, semilla, pg_platform_url):
    """La carrera de la gaveta: abono en efectivo contra el arqueo. Los dos
    bloquean la fila de la sesión y se serializan — si gana el abono, su
    plata entra al esperado que el cierre CONGELA; si gana el cierre, el
    abono ya no ve sesión abierta y sale 409 `caja_sin_sesion_abierta`. Nunca
    un abono cobrado por fuera del arqueo que lo debía contar."""
    credito_id = await _credito(pg_platform_url, semilla, 20000, 20000)

    async def cierre_con_sesion_propia() -> int:
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                caja = CajaService(session=s, tenant_id=T1, actor_id="qa-adversarial", puede_cerrar=True)
                arqueo = await caja.cerrar_sesion(semilla["sesion"], SesionCerrar.model_validate({"contado": 999999}))
                await s.commit()
                return arqueo.efectivo_esperado
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    abono, esperado_congelado = await asyncio.gather(
        _abono_con_sesion_propia(pg_app_url, credito_id, _abono(20000)), cierre_con_sesion_propia()
    )
    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM fiado_abonos WHERE credito_id = :c) AS abonos, "
        "(SELECT estado FROM caja_sesiones WHERE id = :s) AS estado",
        c=credito_id,
        s=semilla["sesion"],
    )
    assert fila.estado == "cerrada"
    if abono == "registrado":
        assert esperado_congelado == 20000 and fila.abonos == 1  # el abono ganó: está DENTRO del arqueo
    else:
        assert abono == "caja_sin_sesion_abierta"
        assert esperado_congelado == 0 and fila.abonos == 0  # el cierre ganó: no hay plata invisible


@pytest.mark.asyncio
async def test_el_forecast_cuenta_el_vencido_y_respeta_la_ventana_de_30_dias(pg_app_url, semilla, pg_platform_url):
    """Los cobros proyectados (decisión 11): suman el saldo de los créditos
    con deuda que vencen dentro de 30 días — los YA vencidos cuentan (el
    cuaderno espera cobrarlos) y el borde mismo (+30) entra. Fuera: el que
    vence más allá de la ventana, el sin fecha (sin promesa de pago, ADR-022)
    y el saldado."""
    await _credito(pg_platform_url, semilla, 10000, 10000, estado="vencido", vencimiento=f"{HOY_BOGOTA} - 5")
    await _credito(pg_platform_url, semilla, 20000, 20000, vencimiento=f"{HOY_BOGOTA} + 30")
    await _credito(pg_platform_url, semilla, 40000, 40000, vencimiento=f"{HOY_BOGOTA} + 45")
    await _credito(pg_platform_url, semilla, 80000, 80000, vencimiento="NULL")
    await _credito(pg_platform_url, semilla, 90000, 0, estado="saldado")
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            reportes = ReportesService(session=s, tenant_id=T1)
            forecast = await reportes.forecast()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()
    assert forecast.cobros_fiado_proyectados_centavos == 30000


# --- Vecinos y oráculos -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_crear_cliente_con_el_id_de_otro_tenant_es_409_tipado(servicio, semilla):
    """El alta online con la PK del cliente del vecino: la RLS la oculta, el
    INSERT revienta y sale 409 `cliente_id_en_conflicto` — el criterio de la
    PK inadivinable (UUIDv4), nunca un 500 ni una adopción silenciosa."""
    with pytest.raises(ConflictError) as exc:
        await servicio.crear_cliente(
            ClienteCrear.model_validate({"id": str(semilla["cliente_t2"]), "nombre": "La vecina"})
        )
    assert exc.value.code == "cliente_id_en_conflicto"


@pytest.mark.asyncio
async def test_el_credito_del_vecino_no_se_ve_ni_se_reprograma(servicio, semilla, pg_platform_url):
    """El crédito de T2 por id desde T1: 404 en la lectura y 404 en la
    reprogramación — el `FOR UPDATE` de ésta no lo hace más visible."""
    credito_t2 = await _credito(pg_platform_url, semilla, 33000, 33000, tenant=T2)
    with pytest.raises(NotFoundError) as exc1:
        await servicio.obtener_credito(credito_t2)
    assert exc1.value.code == "credito_no_encontrado"
    with pytest.raises(NotFoundError) as exc2:
        await servicio.reprogramar_vencimiento(
            credito_t2, CreditoReprogramar.model_validate({"fecha_vencimiento": "2099-01-15"})
        )
    assert exc2.value.code == "credito_no_encontrado"
    assert await _estado_credito(pg_platform_url, credito_t2) == ("vigente", 33000)


# --- El wa.me y la limpieza del teléfono ----------------------------------------------


def test_el_telefono_se_limpia_en_el_schema_y_el_prefijo_es_solo_para_el_local():
    """La limpieza es del schema (espacios, guiones, paréntesis, `+`); el
    prefijo 57 es SOLO para el número local de 10 dígitos: el que ya trae
    indicativo —propio o de otro país— viaja tal cual al `wa.me`."""
    limpio = ClienteCrear.model_validate({"nombre": "Ok", "telefono": "+57 (300) 123-4567"})
    assert limpio.telefono == "573001234567"
    cliente = Cliente(nombre="Don Carlos", telefono="573001234567")
    credito = FiadoCredito(saldo_pendiente=43000)
    assert construir_whatsapp_url(cliente, credito).startswith("https://wa.me/573001234567?text=")
    cliente.telefono = "3001234567"  # 10 dígitos = celular local sin indicativo
    assert construir_whatsapp_url(cliente, credito).startswith("https://wa.me/573001234567?text=")
    cliente.telefono = "13055551234"  # otro país: el indicativo ya viene puesto
    assert construir_whatsapp_url(cliente, credito).startswith("https://wa.me/13055551234?text=")
    with pytest.raises(ErrorDeEsquema):
        ClienteCrear.model_validate({"nombre": "Ok", "telefono": "+57 300 123"})  # 7 dígitos: 422


def test_el_saldo_del_wa_me_va_formateado_con_miles():
    """«$12.345,67» al estilo de acá (punto de miles, coma decimal), dentro
    del mensaje codificado: `$` → `%24`, `,` → `%2C`, los puntos quedan
    literales. El saldo se guarda en centavos y el mensaje va en PESOS
    (dividido por 100): mostrar los centavos crudos como si fueran pesos
    inflaba la deuda 100x (revisión final del módulo)."""
    cliente = Cliente(nombre="Don Carlos", telefono="3001234567")
    credito = FiadoCredito(saldo_pendiente=1234567)
    url = construir_whatsapp_url(cliente, credito)
    assert "%2412.345%2C67" in url
    credito.saldo_pendiente = 99900  # $999 redondos: sin decimales
    assert "%24999" in construir_whatsapp_url(cliente, credito)
