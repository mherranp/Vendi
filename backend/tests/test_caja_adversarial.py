"""QA adversarial de caja y finanzas: ataques sobre el arqueo al peso, el
congelamiento, las carreras, la visibilidad por rol y los reportes.

Compañero de `test_caja_servicio.py`, `test_reportes_servicio.py` y
`test_aislamiento_caja.py`, no sustituto: aquello fija el camino feliz, la
idempotencia firmada y el aislamiento por RLS; esto empuja las esquinas que
el plan deja en penumbra — la devolución que cae UNA sola vez aunque la
sesión que la absorbió ya cerró, la base en el tope del `Integer`, el
esperado negativo, dos movimientos concurrentes con la misma ancla, la
apertura explícita contra el sync, el id del vecino en apertura y movimiento,
la frontera de medianoche Bogotá al minuto y el forecast sin un solo dato— y
deja cada comportamiento FIJO en un test.

Tres de estos tests DOCUMENTAN comportamientos discutibles a propósito (el
del `retiro_dueno` se discutía aquí y quedó RESUELTO con el arreglo del C-3:
hoy fija la visibilidad por permiso, no la fuga):

- La anulación que cae en el HUECO entre sesiones (venta anulada cuando no
  hay ninguna caja abierta) no entra en NINGÚN arqueo: ni reabre el congelado
  de su sesión (firmado) ni resta en la siguiente, porque su `anulada_en` es
  anterior a la apertura. El assert es el comportamiento actual y la discusión
  —es dinero devuelto al cliente que la caja nunca ve— vive en
  `.superpowers/sdd/qa-adversarial-caja-report.md`.
- El egreso mayor que el efectivo disponible deja el esperado en NEGATIVO y
  la sesión cierra así: el sistema no exige que la gaveta dé para el retiro.
- El cajero (sin `caja:cerrar`) no ve el historial de ARQUEOS, y aunque sí
  puede listar los MOVIMIENTOS de una sesión cerrada cuyo id conoce (su POS
  lo guarda), los `retiro_dueno` quedan fuera de su vista — de la lista y
  del total — desde el arreglo del C-3 (misma lección que `ultimo_costo`).
- El movimiento con el `id` de OTRO tenant sale 409 `movimiento_id_divergente`
  (la RLS oculta la fila; espejo de D-24, ya comentado en el servicio).

Si alguno cambia a un comportamiento distinto, el test se reescribe, no se
borra.
"""

from __future__ import annotations

import asyncio
import itertools
import uuid
from datetime import date

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from pydantic import ValidationError as ErrorDeEsquema
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.caja.reportes import ReportesService
from app.modules.caja.schemas import MovimientoCrear, SesionAbrir, SesionCerrar
from app.modules.caja.service import CajaService, calcular_desglose
from app.modules.catalogo.schemas import TOPE_PRECIO
from app.modules.ventas.schemas import LoteSync
from app.modules.ventas.service import VentasService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import ConflictError, ValidationError
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM caja_movimientos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compra_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compras WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.inventario.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.caja.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)

_CONSECUTIVO = itertools.count(1)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """El escenario base del ataque: en T1, un dispositivo y un producto con
    stock y costo (para ventas por sync y por SQL); en T2, una sesión abierta
    con un movimiento — las filas del vecino para las pruebas de aislamiento
    por id. Limpieza total antes y después: la suite es re-entrante."""
    ids = {
        "dispositivo": uuid.uuid4(),
        "producto": uuid.uuid4(),
        "sesion_t2": uuid.uuid4(),
        "movimiento_t2": uuid.uuid4(),
    }
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
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual, ultimo_costo) "
                "VALUES (:p, :t, 'Arroz 500g', 2500, 100, 1500)"
            ),
            {"p": ids["producto"], "t": T1},
        )
        await conn.execute(
            text(
                "INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) "
                "VALUES (:s, :t, 'dueno-vecino', 30000)"
            ),
            {"s": ids["sesion_t2"], "t": T2},
        )
        await conn.execute(
            text(
                "INSERT INTO caja_movimientos (id, tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, "
                "registrado_por) VALUES (:m, :t, :s, 'egreso', 'arriendo', 900000, 'Arriendo del vecino', 'vecino')"
            ),
            {"m": ids["movimiento_t2"], "t": T2, "s": ids["sesion_t2"]},
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
            yield CajaService(session=s, tenant_id=T1, actor_id="qa-adversarial", puede_cerrar=True)
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


def _reportes(servicio: CajaService) -> ReportesService:
    """El servicio de reportes sobre la MISMA sesión de base del fixture."""
    return ReportesService(session=servicio._session, tenant_id=T1)


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


async def _venta(
    pg_platform_url: str,
    semilla: dict,
    sesion_id: uuid.UUID,
    total: int,
    medio_pago: str = "efectivo",
    estado: str = "completada",
    recibida_en: str = "now()",
    anulada_en: str | None = None,
) -> uuid.UUID:
    """Una venta por SQL con la marca del servidor controlada (el arqueo y el
    P&L suman por `recibida_en`, no por el reloj del cliente)."""
    venta_id = uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                    "medio_pago, total_centavos, creada_en_cliente, recibida_en, secuencia_dispositivo, "
                    f"estado, anulada_en) VALUES (:v, :t, :d, :s, {next(_CONSECUTIVO)}, :mp, :total, "
                    f"now(), {recibida_en}, 1, :estado, {anulada_en or 'NULL'})"
                ),
                {
                    "v": venta_id,
                    "t": T1,
                    "d": semilla["dispositivo"],
                    "s": sesion_id,
                    "mp": medio_pago,
                    "total": total,
                    "estado": estado,
                },
            )
    finally:
        await engine.dispose()
    return venta_id


async def _anular(pg_platform_url: str, venta_id: uuid.UUID) -> None:
    """La anulación por SQL, como la estampa `_anular_venta` (decisión 7)."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE ventas SET estado = 'anulada', anulada_en = now() WHERE id = :v"), {"v": venta_id}
            )
    finally:
        await engine.dispose()


def _movimiento(
    monto: int,
    /,
    tipo: str = "ingreso",
    categoria: str = "otro",
    motivo: str = "Consignación del dueño",
    **cambios,
) -> MovimientoCrear:
    # `monto` es POSICIONAL-PURO a propósito: los ataques lo pisan por
    # `**cambios` (`_movimiento(7000, monto=-1)`) y un parámetro nominal
    # reventaría con "multiple values" antes de llegar al schema.
    datos = {"id": str(uuid.uuid4()), "tipo": tipo, "categoria": categoria, "monto": monto, "motivo": motivo}
    datos.update(cambios)
    return MovimientoCrear.model_validate(datos)


def _lote_venta(dispositivo_id: uuid.UUID, producto_id: uuid.UUID, total: int) -> LoteSync:
    return LoteSync.model_validate(
        {
            "dispositivo_id": str(dispositivo_id),
            "operaciones": [
                {
                    "id": str(uuid.uuid4()),
                    "tipo": "venta.crear",
                    "secuencia": 1,
                    "datos": {
                        "consecutivo_local": 1,
                        "medio_pago": "efectivo",
                        "total_centavos": total,
                        "creada_en_cliente": "2026-07-28T10:00:00+00:00",
                        "items": [
                            {"producto_id": str(producto_id), "cantidad": "1", "precio_unitario_centavos": total}
                        ],
                    },
                }
            ],
        }
    )


# --- El arqueo al peso: la devolución cae UNA vez, y el hueco entre sesiones --------


async def test_la_devolucion_cae_en_una_sola_sesion_aunque_esa_ya_cerro(servicio, semilla, pg_platform_url):
    """La venta se cobra en A, A cierra cuadrada, se anula durante B y B la
    absorbe (firmado, decisión 7). El ataque es el día después: B ya cerró con
    la devolución congelada y C abre — si C la volviera a restar, la misma
    devolución se contaría DOS veces y el esperado de C nacería cuadrado en
    contra del cajero. `anulada_en < abierta_en de C` la deja fuera: UNA vez."""
    sesion_a = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    venta = await _venta(pg_platform_url, semilla, sesion_a.id, 10000)
    await servicio.cerrar_sesion(sesion_a.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()

    sesion_b = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    await _anular(pg_platform_url, venta)
    arqueo_b = await servicio.cerrar_sesion(sesion_b.id, SesionCerrar.model_validate({"contado": 40000}))
    await servicio._session.commit()
    assert arqueo_b.efectivo_esperado == 40000  # 50000 − 10000: la absorbió B

    sesion_c = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    desglose_c = await calcular_desglose(servicio._session, sesion_c)
    assert desglose_c.devoluciones == 0, "la misma devolución NO se resta dos veces"
    assert desglose_c.esperado == 0
    congelado_b = await _uno(
        pg_platform_url,
        "SELECT efectivo_esperado, diferencia FROM caja_sesiones WHERE id = :s",
        s=sesion_b.id,
    )
    assert (congelado_b.efectivo_esperado, congelado_b.diferencia) == (40000, 0)


async def test_la_anulacion_en_el_hueco_entre_sesiones_no_cae_en_ningun_arqueo(servicio, semilla, pg_platform_url):
    """DOCUMENTA el agujero: la venta se cobra en A, A cierra cuadrada y la
    anulación llega de NOCHE, sin ninguna caja abierta (el dispositivo sincroniza
    tarde; `_anular_venta` no exige sesión). Al abrir B a la mañana siguiente,
    la devolución —plata que salió físicamente de la gaveta— no resta en B
    (`anulada_en < abierta_en`) y el congelado de A jamás se reabre (firmado):
    no cae en NINGÚN arqueo. El assert es el comportamiento actual; la discusión
    y la propuesta viven en `.superpowers/sdd/qa-adversarial-caja-report.md`."""
    sesion_a = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    venta = await _venta(pg_platform_url, semilla, sesion_a.id, 10000)
    await servicio.cerrar_sesion(sesion_a.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()

    # Sin sesión abierta: la anulación se estampa en el hueco de la noche.
    await _anular(pg_platform_url, venta)

    sesion_b = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    desglose_b = await calcular_desglose(servicio._session, sesion_b)
    assert desglose_b.devoluciones == 0, "huérfana: no cayó en la sesión siguiente"
    assert desglose_b.esperado == 50000, "y el esperado de B nace como si la plata no hubiera salido"
    congelado_a = await _uno(
        pg_platform_url,
        "SELECT efectivo_esperado, diferencia FROM caja_sesiones WHERE id = :s",
        s=sesion_a.id,
    )
    assert (congelado_a.efectivo_esperado, congelado_a.diferencia) == (10000, 0)


async def test_el_esperado_negativo_cierra_sin_error(servicio, pg_platform_url):
    """DOCUMENTA el borde: un egreso mayor que todo el efectivo de la sesión
    (la gaveta no da para el retiro, pero el sistema no lo impide) deja el
    esperado en NEGATIVO y el cierre cuadra contra él: contado 0, diferencia
    positiva. Ningún CHECK prohíbe `efectivo_esperado < 0` — discutido en el
    reporte."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    await servicio.registrar_movimiento(
        _movimiento(5000, tipo="egreso", categoria="retiro_dueno", motivo="Retiro del dueño")
    )
    await servicio._session.commit()

    arqueo = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 0}))
    await servicio._session.commit()
    assert arqueo.efectivo_esperado == -5000
    assert arqueo.diferencia == 5000 and arqueo.estado == "cerrada"


async def test_la_base_en_el_tope_y_una_venta_mas_corta_el_cierre_con_422_tipado(servicio, semilla, pg_platform_url):
    """La base cabe en el schema (`le=TOPE_PRECIO`) pero base + UNA venta de un
    centavo desborda el `Integer` de `efectivo_esperado`: sin la cota del
    servicio, el UPDATE reventaría con `DataError` → 500. Sale 422
    `total_fuera_de_rango` y la sesión NO queda cerrada a medias."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": TOPE_PRECIO}))
    await servicio._session.commit()
    await _venta(pg_platform_url, semilla, sesion.id, 1)

    with pytest.raises(ValidationError) as exc:
        await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": TOPE_PRECIO}))
    assert exc.value.code == "total_fuera_de_rango"
    await servicio._session.rollback()

    vista = await servicio.sesion_actual()
    assert vista.estado == "abierta", "el 422 no cierra la sesión a medias"


async def test_la_base_en_el_tope_exacto_cierra_en_el_borde(servicio):
    """El borde por dentro: esperado == TOPE (sin pasarse) cabe justo en el
    `Integer` y la diferencia cero también — el cierre cuadra en el límite."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": TOPE_PRECIO}))
    await servicio._session.commit()
    arqueo = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": TOPE_PRECIO}))
    await servicio._session.commit()
    assert arqueo.efectivo_esperado == TOPE_PRECIO and arqueo.diferencia == 0


# --- El congelamiento: el historial no se recalcula aunque el origen mute --------------


async def test_el_historial_devuelve_el_congelado_aunque_el_origen_mute_por_sql(servicio, semilla, pg_platform_url):
    """Tras el cierre, alguien con acceso a la base inserta contra la sesión
    cerrada una venta tardía y un movimiento (la FK los deja pasar: la sesión
    existe). El historial de arqueos —la pantalla del dueño— sigue mostrando
    las columnas CONGELADAS: jamás recalcula desde el origen mutado."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    await _venta(pg_platform_url, semilla, sesion.id, 10000)
    await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()

    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO caja_movimientos (id, tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, "
                "registrado_por) VALUES (:m, :t, :s, 'ingreso', 'otro', 3333, 'Inyección directa', 'intruso')"
            ),
            {"m": uuid.uuid4(), "t": T1, "s": sesion.id},
        )
    await engine.dispose()
    await _venta(pg_platform_url, semilla, sesion.id, 7777)  # tardía, contra la cerrada

    filas, total = await servicio.listar_sesiones()
    assert total == 1
    arqueo = filas[0]
    assert (arqueo.efectivo_esperado, arqueo.efectivo_contado, arqueo.diferencia) == (10000, 10000, 0)


# --- Carreras: nuevos intercalados sobre las ya cubiertas ------------------------------


async def test_dos_movimientos_concurrentes_con_el_mismo_id_dejan_uno_y_el_otro_es_409(
    pg_app_url, servicio, semilla, pg_platform_url
):
    """La carrera de dos PRIMEROS envíos con la misma ancla: los dos leen
    `get() → None` antes de bloquear; el FOR UPDATE de la sesión los serializa
    y el perdedor revienta contra la PK al insertar — traducido a 409
    `movimiento_id_divergente`, nunca un 500. Una fila, un evento."""
    await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    el_id = str(uuid.uuid4())

    async def movimiento_con_sesion_propia() -> str:
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                servicio_propio = CajaService(session=s, tenant_id=T1, actor_id="qa-adversarial", puede_cerrar=True)
                try:
                    await servicio_propio.registrar_movimiento(
                        _movimiento(7000, id=el_id, motivo="Consignación del dueño")
                    )
                    await s.commit()
                    return "registrado"
                except ConflictError as exc:
                    await s.rollback()
                    assert exc.code == "movimiento_id_divergente"
                    return "conflicto"
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    resultados = await asyncio.gather(
        movimiento_con_sesion_propia(), movimiento_con_sesion_propia(), return_exceptions=True
    )
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            raise resultado
    assert sorted(resultados) == ["conflicto", "registrado"]

    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM caja_movimientos WHERE tenant_id = :t) AS movimientos, "
        "(SELECT count(*) FROM outbox_messages WHERE routing_key = :k) AS eventos",
        t=T1,
        k=f"{T1}.caja.movimiento_registrado",
    )
    assert (fila.movimientos, fila.eventos) == (1, 1)


async def test_la_apertura_explicita_y_el_sync_concurrentes_dejan_una_sola_sesion(pg_app_url, semilla, pg_platform_url):
    """Apertura vs sync: el dueño abre con base 50.000 mientras un dispositivo
    sincroniza una venta (que abriría una implícita con base 0). No hay fila
    abierta que bloquear: los dos INSERT compiten y `ux_caja_sesion_abierta`
    decide. Si gana la explícita, el sync la re-lee y la venta cae ahí; si gana
    la implícita, la explícita recibe el 409 tipado. SIEMPRE una sola abierta
    y la venta dentro de ella — nunca dos gavetas ni una venta huérfana."""

    async def apertura_con_sesion_propia() -> str:
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                servicio_propio = CajaService(session=s, tenant_id=T1, actor_id="dueno-prueba", puede_cerrar=True)
                try:
                    await servicio_propio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
                    await s.commit()
                    return "abierta"
                except ConflictError as exc:
                    await s.rollback()
                    assert exc.code == "caja_ya_abierta"
                    return "conflicto"
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    async def sync_con_sesion_propia() -> str:
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                ventas = VentasService(session=s, tenant_id=T1, actor_id="cajero-prueba", puede_anular=False)
                [resultado] = await ventas.procesar_lote(_lote_venta(semilla["dispositivo"], semilla["producto"], 4000))
                await s.commit()
                assert resultado.resultado == "aceptada"
                return "vendida"
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    resultados = await asyncio.gather(apertura_con_sesion_propia(), sync_con_sesion_propia(), return_exceptions=True)
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            raise resultado
    assert sorted(resultados) == ["abierta", "vendida"] or sorted(resultados) == ["conflicto", "vendida"]

    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta') AS abiertas, "
        "(SELECT count(*) FROM ventas WHERE tenant_id = :t AND sesion_caja_id IN "
        "(SELECT id FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta')) AS ventas_en_la_abierta, "
        "(SELECT count(*) FROM ventas WHERE tenant_id = :t) AS ventas",
        t=T1,
    )
    assert fila.abiertas == 1
    assert (fila.ventas, fila.ventas_en_la_abierta) == (1, 1)


async def test_abrir_tras_cerrar_en_rafaga_arranca_con_la_base_dada(servicio, pg_platform_url):
    """Cerrar y reabrir en ráfaga (el dueño que se equivocó de conteo y abre el
    turno siguiente): la sesión nueva nace con SU base — nada arrastra saldo de
    la cerrada — y la anterior queda congelada e intacta."""
    sesion_a = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 1000}))
    await servicio._session.commit()
    await servicio.cerrar_sesion(sesion_a.id, SesionCerrar.model_validate({"contado": 1000}))
    await servicio._session.commit()

    sesion_b = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 2000}))
    await servicio._session.commit()
    assert sesion_b.estado == "abierta" and sesion_b.base_inicial == 2000 and sesion_b.id != sesion_a.id

    filas, total = await servicio.listar_sesiones()
    assert total == 2
    cerrada = next(f for f in filas if f.id == sesion_a.id)
    assert (cerrada.efectivo_esperado, cerrada.diferencia) == (1000, 0)
    fila = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta'",
        t=T1,
    )
    assert fila.n == 1


# --- Permisos y visibilidad: los ids del vecino y lo que el cajero sí alcanza ---------


async def test_el_movimiento_con_id_de_otro_tenant_es_409_sin_tocar_la_fila_ajena(servicio, semilla, pg_platform_url):
    """DOCUMENTA el espejo de D-24 (ya comentado en el servicio): el `id` del
    movimiento choca con uno que EXISTE — en T2. La RLS lo hace invisible al
    `get`, el INSERT revienta contra la PK y sale 409 `movimiento_id_divergente`
    tipado, nunca el 500 del IntegrityError. La fila del vecino queda intacta y
    aquí no se mueve nada: ni movimiento, ni evento. Hace falta una sesión
    abierta en T1: sin ella el servicio se detiene antes, en el 409
    `caja_sin_sesion_abierta`, y el choque de PK nunca ocurre."""
    await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()

    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_movimiento(
            _movimiento(7000, id=str(semilla["movimiento_t2"]), motivo="Consignación del dueño")
        )
    assert exc.value.code == "movimiento_id_divergente"
    await servicio._session.rollback()

    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT motivo FROM caja_movimientos WHERE id = :m) AS motivo_ajeno, "
        "(SELECT count(*) FROM caja_movimientos WHERE tenant_id = :t) AS propios, "
        "(SELECT count(*) FROM outbox_messages WHERE routing_key = :k) AS eventos",
        m=semilla["movimiento_t2"],
        t=T1,
        k=f"{T1}.caja.movimiento_registrado",
    )
    assert fila.motivo_ajeno == "Arriendo del vecino"
    assert (fila.propios, fila.eventos) == (0, 0)


async def test_la_apertura_con_id_de_otro_tenant_es_409_sin_fuga(servicio, semilla, pg_platform_url):
    """El `id` de la apertura choca con la sesión del vecino: la RLS la oculta,
    la PK revienta y sale 409 `sesion_id_duplicado` — el mismo sobre que un id
    repetido propio, sin asomo de que la sesión existe en otro negocio. La fila
    ajena queda intacta y aquí no se abre nada."""
    with pytest.raises(ConflictError) as exc:
        await servicio.abrir_sesion(
            SesionAbrir.model_validate({"id": str(semilla["sesion_t2"]), "base_inicial": 50000})
        )
    assert exc.value.code == "sesion_id_duplicado"
    await servicio._session.rollback()

    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT estado FROM caja_sesiones WHERE id = :s) AS estado_ajeno, "
        "(SELECT count(*) FROM caja_sesiones WHERE tenant_id = :t) AS propias",
        s=semilla["sesion_t2"],
        t=T1,
    )
    assert fila.estado_ajeno == "abierta"
    assert fila.propias == 0


async def test_el_cajero_lista_movimientos_de_una_sesion_cerrada_cuyo_id_conoce(pg_app_url, servicio, pg_platform_url):
    """El historial de ARQUEOS exige `caja:cerrar` (decisión 4) y el de
    MOVIMIENTOS solo `caja:leer`: el POS del cajero conoce los ids de las
    sesiones que operó y puede listar sus movimientos aunque nunca verá el
    arqueo. Pero el `retiro_dueno` es tan sensible como el costo (C-3 del
    QA, la lección de `ultimo_costo`): sin `caja:cerrar` NO aparece — ni en
    la lista ni en el total — aunque el cajero conozca la sesión. El dueño
    lo ve todo."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    await servicio.registrar_movimiento(
        _movimiento(900000, tipo="egreso", categoria="retiro_dueno", motivo="Retiro del dueño")
    )
    await servicio.registrar_movimiento(_movimiento(300000, tipo="egreso", categoria="arriendo", motivo="Arriendo"))
    await servicio._session.commit()
    await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 0}))
    await servicio._session.commit()

    # El dueño (el fixture tiene puede_cerrar=True) ve los dos movimientos.
    filas_dueno, total_dueno = await servicio.listar_movimientos(sesion.id)
    assert total_dueno == 2
    assert {f.categoria for f in filas_dueno} == {"retiro_dueno", "arriendo"}

    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            cajero = CajaService(session=s, tenant_id=T1, actor_id="cajero-prueba", puede_cerrar=False)
            filas, total = await cajero.listar_movimientos(sesion.id)
            # Ni en la lista ni en el total: para el cajero el retiro no existe.
            assert total == 1
            assert filas[0].categoria == "arriendo" and filas[0].monto == 300000
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


# --- P&L y forecast: medianoche Bogotá, el retroactivo firmado y el vacío -------------


async def test_la_frontera_de_medianoche_bogota_al_minuto(servicio, semilla, pg_platform_url):
    """El día cambia a medianoche BOGOTÁ, no UTC: 04:59:59 UTC todavía es ayer
    en Colombia (23:59:59) y 05:00:00 UTC ya es hoy. Un minuto separa dos días
    del P&L — y los dos caen del lado correcto."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    await _venta(pg_platform_url, semilla, sesion.id, 1111, recibida_en="'2026-07-29T04:59:59+00:00'")
    await _venta(pg_platform_url, semilla, sesion.id, 2222, recibida_en="'2026-07-29T05:00:00+00:00'")

    reportes = _reportes(servicio)
    dia_28 = await reportes.pyl("dia", date(2026, 7, 28))
    dia_29 = await reportes.pyl("dia", date(2026, 7, 29))
    assert dia_28.ventas_netas_centavos == 1111
    assert dia_29.ventas_netas_centavos == 2222


async def test_la_anulacion_tardia_reescribe_el_pyl_del_dia_original(servicio, semilla, pg_platform_url):
    """Lo firmado en ADR-021 («esas ventas reabren la cuenta solo en reportes,
    nunca en el arqueo»), fijado: la venta del 28 cuenta en el P&L del 28
    mientras está completada; anulada después, el P&L DEL 28 la saca de las
    netas y la muestra como anulada — el arqueo congelado no se entera."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    venta = await _venta(pg_platform_url, semilla, sesion.id, 10000, recibida_en="'2026-07-28T15:00:00+00:00'")

    reportes = _reportes(servicio)
    antes = await reportes.pyl("dia", date(2026, 7, 28))
    assert antes.ventas_netas_centavos == 10000 and antes.ventas_anuladas_centavos == 0

    await _anular(pg_platform_url, venta)
    despues = await reportes.pyl("dia", date(2026, 7, 28))
    assert despues.ventas_netas_centavos == 0
    assert despues.ventas_anuladas_centavos == 10000


async def test_el_forecast_sin_un_solo_dato_no_se_rompe_y_lo_declara(servicio):
    """La tienda que nunca ha vendido: sin ventas ni egresos en 30 días, el
    forecast es saldo + 0 + 0 − 0, `dias_con_datos = 0` y ninguna división por
    cero disfrazada — la cuenta es un total, no un promedio sobre cero."""
    await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()

    forecast = await _reportes(servicio).forecast()
    assert forecast.saldo_actual_centavos == 50000
    assert forecast.ventas_proyectadas_centavos == 0
    assert forecast.egresos_proyectados_centavos == 0
    assert forecast.cobros_fiado_proyectados_centavos == 0
    assert forecast.dias_con_datos == 0
    assert forecast.saldo_proyectado_centavos == 50000


# --- Movimientos: la frontera del schema y la divergencia campo a campo ---------------


@pytest.mark.parametrize(
    "cambios",
    [
        {"motivo": "ab"},  # dos caracteres: no es una justificación
        {"motivo": "   "},  # puros espacios: la limpieza lo deja en nada
        {"monto": 0},  # un movimiento de cero no es movimiento
        {"monto": -5000},  # el signo lo da el tipo, nunca el monto
        {"monto": TOPE_PRECIO + 1},  # desborda el Integer → 422, nunca 500
        {"tipo": "traspaso"},  # fuera de la lista cerrada
        {"categoria": "ropa"},  # fuera de la lista cerrada
    ],
)
def test_el_movimiento_invalido_no_pasa_del_schema(cambios):
    with pytest.raises(ErrorDeEsquema):
        _movimiento(7000, **cambios)


@pytest.mark.parametrize(
    "schema,datos",
    [
        (SesionAbrir, {"base_inicial": -1}),
        (SesionAbrir, {"base_inicial": TOPE_PRECIO + 1}),
        (SesionCerrar, {"contado": -1}),
        (SesionCerrar, {"contado": TOPE_PRECIO + 1}),
    ],
)
def test_la_apertura_y_el_cierre_respetan_las_cotas_del_integer(schema, datos):
    with pytest.raises(ErrorDeEsquema):
        schema.model_validate(datos)


def test_el_borde_exacto_del_schema_si_pasa():
    """Y el borde por dentro: monto y base en el TOPE exacto caben, igual que
    el motivo de tres caracteres."""
    assert _movimiento(TOPE_PRECIO, motivo="abc").monto == TOPE_PRECIO
    assert SesionAbrir.model_validate({"base_inicial": TOPE_PRECIO}).base_inicial == TOPE_PRECIO
    assert SesionCerrar.model_validate({"contado": TOPE_PRECIO}).contado == TOPE_PRECIO


@pytest.mark.parametrize(
    "cambios,campo",
    [
        ({"motivo": "Otro motivo válido"}, "motivo"),
        ({"tipo": "egreso"}, "tipo"),
        ({"categoria": "arriendo"}, "categoria"),
        ({"monto": 7001}, "monto"),
    ],
)
async def test_el_reintento_divergente_se_detecta_campo_a_campo(servicio, cambios, campo):
    """La ancla compara los cuatro campos firmados: mismo id con CUALQUIERA de
    ellos distinto no es un reintento — es otro movimiento, y sale 409 nombrando
    exactamente el campo que difiere. El servidor conserva la primera versión."""
    await servicio.abrir_sesion(SesionAbrir.model_validate({}))
    await servicio._session.commit()
    original = _movimiento(7000)
    await servicio.registrar_movimiento(original)
    await servicio._session.commit()

    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_movimiento(_movimiento(7000, id=str(original.id), **cambios))
    assert exc.value.code == "movimiento_id_divergente"
    assert exc.value.details["campos"] == [campo]
