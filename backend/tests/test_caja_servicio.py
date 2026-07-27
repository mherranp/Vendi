"""`CajaService` contra el PostgreSQL real, con el rol `vendi_app`.

Misma regla que `test_ventas_servicio.py`: la base no se dobla. Aquí se fijan
los comportamientos firmados del módulo: una sesión abierta por tienda (la
hace cumplir el índice, no el código); el arqueo que suma desde las tablas
de origen y se CONGELA al cerrar; la venta que sincroniza tras el cierre y
cae en la sesión nueva; la devolución de una anulación tardía que cae en la
sesión abierta (ADR-021).
"""

from __future__ import annotations

import asyncio
import itertools
import uuid

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.caja.schemas import MovimientoCrear, SesionAbrir, SesionCerrar
from app.modules.caja.service import CajaService, calcular_desglose
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import ConflictError, NotFoundError
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM caja_movimientos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.caja.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)

_CONSECUTIVO = itertools.count(1)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Un dispositivo en T1 (para insertar ventas por SQL con `recibida_en`
    controlada) y limpieza total antes y después: la suite es re-entrante."""
    engine = create_async_engine(pg_platform_url)
    ids = {"dispositivo": uuid.uuid4()}
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
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
            yield CajaService(session=s, tenant_id=T1, actor_id="dueno-prueba", puede_cerrar=True)
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


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


def _movimiento(
    monto: int, tipo: str = "ingreso", categoria: str = "otro", motivo: str = "Prueba de movimiento", **cambios
) -> MovimientoCrear:
    return MovimientoCrear.model_validate(
        {"id": str(uuid.uuid4()), "tipo": tipo, "categoria": categoria, "monto": monto, "motivo": motivo, **cambios}
    )


# --- Apertura -----------------------------------------------------------------


async def test_abrir_caja_crea_la_sesion_y_emite_el_evento(servicio, pg_platform_url):
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()

    assert sesion.estado == "abierta" and sesion.base_inicial == 50000 and sesion.abierta_por == "dueno-prueba"
    evento = await _uno(
        pg_platform_url,
        "SELECT payload->'data'->>'base_inicial' AS base FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.caja.sesion_abierta",
    )
    assert evento.base == "50000"


async def test_la_segunda_apertura_es_409_con_la_sesion_vigente(servicio):
    primera = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    with pytest.raises(ConflictError) as exc:
        await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 30000}))
    assert exc.value.code == "caja_ya_abierta"
    assert exc.value.details["sesion_id"] == str(primera.id)


async def test_la_apertura_es_idempotente_por_el_id_del_cliente(servicio, pg_platform_url):
    el_id = uuid.uuid4()
    primera = await servicio.abrir_sesion(SesionAbrir.model_validate({"id": str(el_id), "base_inicial": 50000}))
    await servicio._session.commit()
    segunda = await servicio.abrir_sesion(SesionAbrir.model_validate({"id": str(el_id), "base_inicial": 50000}))
    await servicio._session.commit()
    assert segunda.id == primera.id == el_id
    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM caja_sesiones WHERE tenant_id = :t) AS sesiones, "
        "(SELECT count(*) FROM outbox_messages WHERE routing_key = :k) AS eventos",
        t=T1,
        k=f"{T1}.caja.sesion_abierta",
    )
    assert (fila.sesiones, fila.eventos) == (1, 1)


async def test_dos_aperturas_concurrentes_dejan_una_sola_sesion(pg_app_url, semilla, pg_platform_url):
    """La regla «una caja por tienda» la hace cumplir `ux_caja_sesion_abierta`
    bajo carrera: una gana, la otra recibe un 409 tipado — nunca un 500."""

    async def apertura_con_sesion_propia(base: int) -> str:
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                servicio = CajaService(session=s, tenant_id=T1, actor_id="cajero-prueba", puede_cerrar=False)
                try:
                    await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": base}))
                    await s.commit()
                    return "abierta"
                except ConflictError as exc:
                    await s.rollback()
                    assert exc.value.code == "caja_ya_abierta"
                    return "conflicto"
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    resultados = await asyncio.gather(apertura_con_sesion_propia(50000), apertura_con_sesion_propia(30000))
    assert sorted(resultados) == ["abierta", "conflicto"]
    fila = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta'",
        t=T1,
    )
    assert fila.n == 1


# --- Movimientos ------------------------------------------------------------------


async def test_registrar_movimiento_lo_ata_a_la_sesion_abierta_y_emite_evento(servicio, pg_platform_url):
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    movimiento = await servicio.registrar_movimiento(
        _movimiento(12000, tipo="egreso", categoria="servicios", motivo="Recibo de la luz")
    )
    await servicio._session.commit()

    assert movimiento.sesion_caja_id == sesion.id and movimiento.registrado_por == "dueno-prueba"
    evento = await _uno(
        pg_platform_url,
        "SELECT payload->'data'->>'monto' AS monto, payload->'data'->>'tipo' AS tipo "
        "FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.caja.movimiento_registrado",
    )
    assert (evento.monto, evento.tipo) == ("12000", "egreso")


async def test_el_movimiento_sin_sesion_abierta_es_409(servicio):
    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_movimiento(_movimiento(5000, motivo="Retiro para el banco"))
    assert exc.value.code == "caja_sin_sesion_abierta"


async def test_el_movimiento_es_idempotente_y_el_divergente_es_409(servicio, pg_platform_url):
    await servicio.abrir_sesion(SesionAbrir.model_validate({}))
    await servicio._session.commit()
    datos = _movimiento(7000, motivo="Retiro para el banco", tipo="egreso", categoria="retiro_dueno")
    primero = await servicio.registrar_movimiento(datos)
    await servicio._session.commit()
    segundo = await servicio.registrar_movimiento(datos)  # reintento byte-idéntico
    await servicio._session.commit()
    assert segundo.id == primero.id
    fila = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM caja_movimientos WHERE tenant_id = :t",
        t=T1,
    )
    assert fila.n == 1  # ni doble movimiento ni doble evento
    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_movimiento(
            _movimiento(9999, id=str(datos.id), motivo="Retiro para el banco", tipo="egreso", categoria="retiro_dueno")
        )
    assert exc.value.code == "movimiento_id_divergente"
    assert "monto" in exc.value.details["campos"]


# --- El arqueo --------------------------------------------------------------------


async def test_el_arqueo_suma_desde_las_tablas_de_origen_y_cuadra_al_peso(servicio, semilla, pg_platform_url):
    """El candado de ADR-021: `esperado = base + ventas efectivo completadas
    + abonos (0, módulo 5) + ingresos − egresos − devoluciones`; la venta
    fiada NO suma y la anulada de la propia sesión tampoco."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    await _venta(pg_platform_url, semilla, sesion.id, 10000)  # efectivo: +10.000
    await _venta(pg_platform_url, semilla, sesion.id, 4000, medio_pago="fiado")  # fiado: NO suma
    await _venta(
        pg_platform_url, semilla, sesion.id, 2500, estado="anulada", anulada_en="now()"
    )  # anulada propia: NO suma
    await servicio.registrar_movimiento(_movimiento(20000, motivo="Consignación del dueño"))
    await servicio.registrar_movimiento(
        _movimiento(8000, tipo="egreso", categoria="servicios", motivo="Recibo del agua")
    )
    await servicio._session.commit()

    arqueo = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 72500}))
    await servicio._session.commit()

    assert arqueo.efectivo_esperado == 50000 + 10000 + 0 + 20000 - 8000 - 0
    assert arqueo.diferencia == 72500 - 72000  # sobrante de 500 centavos
    assert arqueo.estado == "cerrada" and arqueo.cerrada_por == "dueno-prueba"
    assert arqueo.desglose is not None
    assert (arqueo.desglose.ventas_efectivo, arqueo.desglose.ingresos, arqueo.desglose.egresos) == (10000, 20000, 8000)
    assert arqueo.desglose.abonos_efectivo == 0  # declarado: los abonos son del módulo 5
    evento = await _uno(
        pg_platform_url,
        "SELECT payload->'data'->>'efectivo_esperado' AS esperado, payload->'data'->>'diferencia' AS diferencia "
        "FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.caja.sesion_cerrada",
    )
    assert (evento.esperado, evento.diferencia) == ("72000", "500")


async def test_el_arqueo_con_faltante_da_diferencia_negativa(servicio, semilla, pg_platform_url):
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    await _venta(pg_platform_url, semilla, sesion.id, 10000)
    arqueo = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 55000}))
    await servicio._session.commit()
    assert arqueo.efectivo_esperado == 60000
    assert arqueo.diferencia == -5000  # faltante


async def test_el_arqueo_se_congela_y_nada_lo_reabre(servicio, semilla, pg_platform_url):
    """El cierre de ayer sigue cuadrando mañana (ADR-021): una venta insertada
    DESPUÉS contra la sesión cerrada (carrera perdida, SQL directo) NO cambia
    las columnas congeladas, y la anulación posterior tampoco."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    await _venta(pg_platform_url, semilla, sesion.id, 10000)
    await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()
    # Tardía y anulada: dos mutaciones posteriores contra la sesión cerrada.
    await _venta(pg_platform_url, semilla, sesion.id, 999999)
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE ventas SET estado = 'anulada', anulada_en = now() WHERE tenant_id = :t"), {"t": T1}
        )
    await engine.dispose()

    fila = await _uno(
        pg_platform_url,
        "SELECT efectivo_esperado, efectivo_contado, diferencia FROM caja_sesiones WHERE id = :s",
        s=sesion.id,
    )
    assert (fila.efectivo_esperado, fila.efectivo_contado, fila.diferencia) == (10000, 10000, 0)


async def test_el_reintento_del_cierre_devuelve_lo_congelado_y_el_otro_conteo_es_409(servicio):
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    primero = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 0}))
    await servicio._session.commit()
    # Timeout del cliente y reintento con el MISMO conteo: el arqueo congelado,
    # sin recalcular el desglose (no hay segunda emisión del evento).
    reintento = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 0}))
    assert reintento.efectivo_esperado == primero.efectivo_esperado == 0
    assert reintento.desglose is None
    with pytest.raises(ConflictError) as exc:
        await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 100}))
    assert exc.value.code == "caja_ya_cerrada"


async def test_cerrar_una_sesion_desconocida_es_404_sin_fuga(servicio):
    """La sesión de otro negocio es invisible por RLS: mismo 404 que una
    inexistente (mismo criterio que `compra_no_encontrada`)."""
    with pytest.raises(NotFoundError) as exc:
        await servicio.cerrar_sesion(uuid.uuid4(), SesionCerrar.model_validate({"contado": 0}))
    assert exc.value.code == "caja_sesion_no_encontrada"


async def test_la_devolucion_de_una_venta_de_sesion_cerrada_cae_en_la_sesion_abierta(
    servicio, semilla, pg_platform_url
):
    """ADR-021: «la anulación cae en la sesión abierta en ese momento». La
    sesión A cierra cuadrada; al día siguiente se anula una venta en efectivo
    de A y la plata sale de la gaveta de B: el esperado VIVO de B la resta.
    (La anulación por el camino real del sync es Tarea 6; aquí se fija el
    cálculo del desglose.)"""
    sesion_a = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    venta_vieja = await _venta(pg_platform_url, semilla, sesion_a.id, 10000)
    await servicio.cerrar_sesion(sesion_a.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()

    sesion_b = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE ventas SET estado = 'anulada', anulada_en = now() WHERE id = :v"),
            {"v": venta_vieja},
        )
    await engine.dispose()

    desglose = await calcular_desglose(servicio._session, sesion_b)
    assert desglose.devoluciones == 10000
    assert desglose.esperado == 50000 - 10000  # base de B menos la devolución


async def test_la_sesion_actual_muestra_el_esperado_vivo_solo_a_quien_cierra(pg_app_url, semilla, pg_platform_url):
    """Decisión 4 (la lección de la fuga de `ultimo_costo`): el esperado vivo
    es del dueño; el cajero recibe el campo en null con la MISMA forma."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            dueno = CajaService(session=s, tenant_id=T1, actor_id="dueno-prueba", puede_cerrar=True)
            sesion = await dueno.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
            await s.commit()
            await _venta(pg_platform_url, semilla, sesion.id, 10000)
            vista_dueno = await dueno.sesion_actual()
            assert vista_dueno.efectivo_esperado == 60000
            cajero = CajaService(session=s, tenant_id=T1, actor_id="cajero-prueba", puede_cerrar=False)
            vista_cajero = await cajero.sesion_actual()
            assert vista_cajero.id == sesion.id and vista_cajero.base_inicial == 50000
            assert vista_cajero.efectivo_esperado is None
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def test_sin_sesion_abierta_la_actual_es_404(servicio):
    with pytest.raises(NotFoundError) as exc:
        await servicio.sesion_actual()
    assert exc.value.code == "caja_sin_sesion_abierta"
