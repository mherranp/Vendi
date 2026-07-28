"""La anulación por el sync contra la sesión de caja (I-1/I-2 de la revisión
final de caja).

`_anular_venta` resuelve la sesión de caja (FOR UPDATE) antes de estampar
`anulada_en`, igual que `_registrar_venta`: sin sesión abierta abre la
implícita y la marca siempre cae dentro de su ventana (`abierta_en <=
anulada_en`), y la carrera con el cierre se serializa sobre la fila — quien
llega segundo ve la sesión `cerrada` y la devolución cae en la sesión nueva.

Misma regla que `test_caja_servicio.py`: la base no se dobla. Estos tests son
integration y corren contra el PostgreSQL real con el rol `vendi_app`.
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

from app.modules.caja.schemas import SesionAbrir, SesionCerrar
from app.modules.caja.service import CajaService, calcular_desglose
from app.modules.ventas.models import CajaSesion
from app.modules.ventas.schemas import LoteSync
from app.modules.ventas.service import VentasService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM caja_movimientos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.caja.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)

_CONSECUTIVO = itertools.count(1)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Un dispositivo en T1 y limpieza total antes y después: la suite es
    re-entrante."""
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


async def _venta(pg_platform_url: str, semilla: dict, sesion_id: uuid.UUID, total: int) -> uuid.UUID:
    """Una venta en efectivo `completada` por SQL, atada a la sesión dada."""
    venta_id = uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                    "medio_pago, total_centavos, creada_en_cliente, recibida_en, secuencia_dispositivo, estado) "
                    f"VALUES (:v, :t, :d, :s, {next(_CONSECUTIVO)}, 'efectivo', :total, now(), now(), 1, "
                    "'completada')"
                ),
                {"v": venta_id, "t": T1, "d": semilla["dispositivo"], "s": sesion_id, "total": total},
            )
    finally:
        await engine.dispose()
    return venta_id


def _lote_anulacion(dispositivo_id: uuid.UUID, venta_id: uuid.UUID) -> LoteSync:
    return LoteSync.model_validate(
        {
            "dispositivo_id": str(dispositivo_id),
            "operaciones": [
                {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 1, "datos": {"venta_id": str(venta_id)}}
            ],
        }
    )


async def test_anular_sin_sesion_abierta_abre_la_implicita_y_la_devolucion_cae_en_ella(
    servicio, semilla, pg_platform_url
):
    """I-1: la anulación llega por el sync en el hueco — la sesión A cerró a
    las 9pm y la de mañana no se ha abierto. Antes del fix, `anulada_en` se
    estampaba a ciegas y quedaba fuera de TODA ventana: la devolución no
    aparecía en ningún arqueo. Ahora el resolvedor abre la implícita y el
    esperado vivo de ESA sesión la resta (ADR-021, decisión 7)."""
    sesion_a = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    venta_vieja = await _venta(pg_platform_url, semilla, sesion_a.id, 10000)
    await servicio.cerrar_sesion(sesion_a.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()

    # El hueco: ninguna sesión abierta. La anulación llega por el sync.
    ventas = VentasService(session=servicio._session, tenant_id=T1, actor_id="dueno-prueba", puede_anular=True)
    [resultado] = await ventas.procesar_lote(_lote_anulacion(semilla["dispositivo"], venta_vieja))
    await servicio._session.commit()
    assert resultado.resultado == "aceptada"

    fila = await _uno(
        pg_platform_url,
        "SELECT v.estado, v.anulada_en, v.sesion_caja_id, s.id AS implicita_id, s.abierta_en, s.base_inicial "
        "FROM ventas v, caja_sesiones s "
        "WHERE v.id = :v AND s.tenant_id = :t AND s.estado = 'abierta'",
        v=venta_vieja,
        t=T1,
    )
    assert fila.estado == "anulada" and fila.anulada_en is not None
    # La venta CONSERVA su sesión original: la devolución la ubica la ventana
    # que contiene `anulada_en`, no la sesión de la venta.
    assert fila.sesion_caja_id == sesion_a.id
    # La implícita se abrió (base 0, como manda ADR-018) y la marca cae
    # DENTRO de su ventana: `abierta_en <= anulada_en`, siempre.
    assert fila.base_inicial == 0
    assert fila.abierta_en <= fila.anulada_en

    sesion_implicita = await servicio._session.get(CajaSesion, fila.implicita_id)
    desglose = await calcular_desglose(servicio._session, sesion_implicita)
    assert desglose.devoluciones == 10000
    assert desglose.esperado == -10000  # base 0 menos la devolución
    # Y el arqueo firmado de A sigue intacto: el cierre de ayer cuadra mañana.
    congelado = await _uno(
        pg_platform_url,
        "SELECT efectivo_esperado, diferencia FROM caja_sesiones WHERE id = :s",
        s=sesion_a.id,
    )
    assert (congelado.efectivo_esperado, congelado.diferencia) == (10000, 0)


async def test_anulacion_concurrente_con_el_cierre_cae_en_sesion_viva_y_la_cerrada_queda_intacta(
    servicio, semilla, pg_app_url, pg_platform_url
):
    """I-2: la anulación confirma mientras la sesión B cierra. El FOR UPDATE
    del resolvedor serializa ambos sobre la fila de B (patrón asyncio.gather
    de los tests de carrera existentes). En el orden dominante —el cierre,
    que arranca antes, gana— B queda CONGELADA sin la devolución y la
    anulación abre la implícita C, que sí la resta. En el orden inverso la
    anulación entra al `calcular_desglose` de B y queda dentro del SUM
    congelado: las dos ramas se afirman, porque las dos son correctas — lo
    que jamás puede pasar es `anulada_en < cerrada_en` sin haber entrado al
    congelado ni a la siguiente."""
    sesion_a = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    venta_vieja = await _venta(pg_platform_url, semilla, sesion_a.id, 10000)
    await servicio.cerrar_sesion(sesion_a.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()
    sesion_b = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()

    async def cierre_con_sesion_propia():
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                caja = CajaService(session=s, tenant_id=T1, actor_id="dueno-prueba", puede_cerrar=True)
                arqueo = await caja.cerrar_sesion(sesion_b.id, SesionCerrar.model_validate({"contado": 50000}))
                await s.commit()
                return arqueo
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    async def anulacion_con_sesion_propia():
        # El cierre toma la fila de B en su primera consulta; la anulación la
        # toca solo al final (tras la venta y los ítems). El pequeño retardo
        # hace dominante el orden «gana el cierre»; la rama inversa también
        # está afirmada abajo, así que el test no depende del orden.
        await asyncio.sleep(0.05)
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                ventas = VentasService(session=s, tenant_id=T1, actor_id="dueno-prueba", puede_anular=True)
                [resultado] = await ventas.procesar_lote(_lote_anulacion(semilla["dispositivo"], venta_vieja))
                await s.commit()
                return resultado
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    resultados = await asyncio.gather(cierre_con_sesion_propia(), anulacion_con_sesion_propia(), return_exceptions=True)
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            raise resultado
    _, resultado_anulacion = resultados
    assert resultado_anulacion.resultado == "aceptada"

    venta = await _uno(
        pg_platform_url,
        "SELECT estado, anulada_en, sesion_caja_id FROM ventas WHERE id = :v",
        v=venta_vieja,
    )
    assert venta.estado == "anulada" and venta.anulada_en is not None
    assert venta.sesion_caja_id == sesion_a.id  # conserva la suya

    # A, la sesión de la venta, sigue congelada e intacta en ambos órdenes.
    congelado_a = await _uno(
        pg_platform_url,
        "SELECT efectivo_esperado, diferencia FROM caja_sesiones WHERE id = :s",
        s=sesion_a.id,
    )
    assert (congelado_a.efectivo_esperado, congelado_a.diferencia) == (10000, 0)

    sesion_c = await _uno(
        pg_platform_url,
        "SELECT id, abierta_en, base_inicial FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta'",
        t=T1,
    )
    congelado_b = await _uno(
        pg_platform_url,
        "SELECT estado, efectivo_esperado, efectivo_contado, diferencia FROM caja_sesiones WHERE id = :s",
        s=sesion_b.id,
    )
    assert congelado_b.estado == "cerrada"
    if sesion_c is not None:
        # Ganó el cierre: B se congeló SIN la devolución y la anulación abrió
        # la implícita C, cuya ventana contiene la marca y cuyo esperado vivo
        # la resta. La devolución NO desaparece: cae en la sesión nueva.
        assert (congelado_b.efectivo_esperado, congelado_b.diferencia) == (50000, 0)
        assert sesion_c.base_inicial == 0 and sesion_c.abierta_en <= venta.anulada_en
        desglose_c = await calcular_desglose(servicio._session, await servicio._session.get(CajaSesion, sesion_c.id))
        assert desglose_c.devoluciones == 10000
        assert desglose_c.esperado == -10000
    else:
        # Ganó la anulación: el `calcular_desglose` del cierre ya la vio
        # `anulada` y la devolución entró al SUM congelado de B (el sobrante
        # es el contado menos ese esperado). Tampoco desaparece.
        assert congelado_b.efectivo_esperado == 40000
        assert congelado_b.diferencia == 50000 - 40000

    # Un solo evento de cada tipo: ni doble anulación ni doble cierre.
    eventos = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM outbox_messages WHERE routing_key = :k1) AS anuladas, "
        "(SELECT count(*) FROM outbox_messages WHERE routing_key = :k2) AS cierres",
        k1=f"{T1}.venta.anulada",
        k2=f"{T1}.caja.sesion_cerrada",
    )
    assert (eventos.anuladas, eventos.cierres) == (1, 2)  # el cierre de A y el de B
