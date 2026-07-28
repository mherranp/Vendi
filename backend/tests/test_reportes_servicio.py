"""`ReportesService` contra el PostgreSQL real: el P&L simple y el forecast
de ADR-006, con el día en America/Bogota (ADR-021) y cada número declarando
su fuente.

Las marcas se siembran por SQL con `recibida_en` controlada: el P&L suma por
la verdad del servidor (ADR-018), no por el reloj del test.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import date

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.caja.reportes import ReportesService, ventana_del_periodo
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM caja_movimientos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compra_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compras WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
)

_CONSECUTIVO = itertools.count(1)

# Un instante fijo: martes 2026-07-28 10:00 en Bogotá (15:00 UTC).
DIA = date(2026, 7, 28)
EN_PUNTO = "'2026-07-28T15:00:00+00:00'"


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Dispositivo, producto (ultimo_costo 1500) y sesión con movimientos en
    T1; una venta en T2 para probar el aislamiento de los reportes."""
    engine = create_async_engine(pg_platform_url)
    ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4(), "sesion": uuid.uuid4()}
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
                "INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) VALUES (:s, :t, 'dueno', 50000)"
            ),
            {"s": ids["sesion"], "t": T1},
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
            yield ReportesService(session=s, tenant_id=T1)
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def _venta(
    pg_platform_url,
    semilla,
    total,
    medio_pago="efectivo",
    estado="completada",
    recibida_en=EN_PUNTO,
    con_item=False,
    cantidad="2",
) -> uuid.UUID:
    venta_id = uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                    f"medio_pago, total_centavos, creada_en_cliente, recibida_en, secuencia_dispositivo, estado) "
                    f"VALUES (:v, :t, :d, :s, {next(_CONSECUTIVO)}, :mp, :total, now(), {recibida_en}, 1, :estado)"
                ),
                {
                    "v": venta_id,
                    "t": T1,
                    "d": semilla["dispositivo"],
                    "s": semilla["sesion"],
                    "mp": medio_pago,
                    "total": total,
                    "estado": estado,
                },
            )
            if con_item:
                await conn.execute(
                    text(
                        "INSERT INTO ventas_items (tenant_id, venta_id, producto_id, cantidad, precio_unitario_centavos) "
                        f"VALUES (:t, :v, :p, {cantidad}, :precio)"
                    ),
                    {"t": T1, "v": venta_id, "p": semilla["producto"], "precio": total},
                )
    finally:
        await engine.dispose()
    return venta_id


async def _compra(pg_platform_url, total: int, fecha: str = "'2026-07-28'") -> None:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"INSERT INTO compras (tenant_id, proveedor_nombre, fecha, total_centavos) "
                    f"VALUES (:t, 'Distribuidora La 33', {fecha}, :total)"
                ),
                {"t": T1, "total": total},
            )
    finally:
        await engine.dispose()


async def _movimiento(pg_platform_url, semilla, monto: int, tipo: str = "egreso", creado: str = EN_PUNTO) -> None:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO caja_movimientos (tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, "
                    f"registrado_por, created_at) VALUES (:t, :s, :tipo, 'otro', :monto, 'Prueba', 'dueno', {creado})"
                ),
                {"t": T1, "s": semilla["sesion"], "tipo": tipo, "monto": monto},
            )
    finally:
        await engine.dispose()


# --- El P&L ---------------------------------------------------------------------


async def test_el_pyl_del_dia_suma_lo_firmado_y_declara_sus_fuentes(servicio, semilla, pg_platform_url):
    await _venta(pg_platform_url, semilla, 10000, con_item=True)  # efectivo, 2 und × costo 1500
    await _venta(pg_platform_url, semilla, 4000, medio_pago="fiado")  # fiado: cuenta en netas, no en caja
    await _venta(pg_platform_url, semilla, 7000, estado="anulada")  # anulada: NO cuenta
    await _compra(pg_platform_url, 50000)
    await _movimiento(pg_platform_url, semilla, 8000)
    await _movimiento(pg_platform_url, semilla, 5000, tipo="ingreso")

    pyl = await servicio.pyl("dia", DIA)

    assert pyl.ventas_netas_centavos == 14000
    assert (pyl.ventas_efectivo_centavos, pyl.ventas_fiado_centavos) == (10000, 4000)
    assert pyl.ventas_anuladas_centavos == 7000  # informativo: fuera de las netas
    assert pyl.costo_de_lo_vendido_centavos == 3000  # 2 × 1500, ultimo_costo ACTUAL
    assert pyl.margen_bruto_centavos == 11000
    assert pyl.compras_proveedores_centavos == 50000  # flujo informativo: NO se resta
    assert (pyl.ingresos_caja_centavos, pyl.egresos_caja_centavos) == (5000, 8000)
    assert pyl.resultado_operativo_centavos == 11000 + 5000 - 8000
    assert "ultimo_costo" in pyl.fuentes["costo_de_lo_vendido"]
    assert "NO se resta" in pyl.fuentes["compras_proveedores"]


async def test_el_dia_es_el_de_bogota_no_el_de_utc(servicio, semilla, pg_platform_url):
    """Las 8:30pm del 28 en Colombia ya son el 29 en UTC: la venta cuenta en
    el día Bogotá que le corresponde (ADR-021)."""
    await _venta(pg_platform_url, semilla, 10000, recibida_en="'2026-07-29T01:30:00+00:00'")
    dia_28 = await servicio.pyl("dia", date(2026, 7, 28))
    dia_29 = await servicio.pyl("dia", date(2026, 7, 29))
    assert dia_28.ventas_netas_centavos == 10000
    assert dia_29.ventas_netas_centavos == 0


async def test_la_semana_arranca_en_lunes_y_el_mes_en_dia_uno(servicio, semilla, pg_platform_url):
    # Domingo 26 de julio, mediodía Bogotá: semana del lunes 20, no del 27.
    await _venta(pg_platform_url, semilla, 3000, recibida_en="'2026-07-26T17:00:00+00:00'")
    # 30 de junio: fuera del mes de julio.
    await _venta(pg_platform_url, semilla, 9000, recibida_en="'2026-06-30T17:00:00+00:00'")
    semana_del_28 = await servicio.pyl("semana", DIA)
    semana_del_26 = await servicio.pyl("semana", date(2026, 7, 26))
    mes_julio = await servicio.pyl("mes", DIA)
    assert semana_del_28.ventas_netas_centavos == 0
    assert semana_del_26.ventas_netas_centavos == 3000
    assert mes_julio.ventas_netas_centavos == 3000
    # Los límites viajan en UTC y cuadran con medianoche Bogotá.
    desde, hasta = ventana_del_periodo("dia", DIA)
    assert desde.isoformat() == "2026-07-28T05:00:00+00:00"
    assert hasta.isoformat() == "2026-07-29T05:00:00+00:00"


async def test_el_costo_es_el_ultimo_costo_actual_aunque_cambie_tras_la_venta(servicio, semilla, pg_platform_url):
    """La fuente honesta (decisión 8): si el costo cambió después de la venta,
    el P&L usa el de HOY y lo declara — no inventa un costo histórico que el
    modelo no guarda."""
    await _venta(pg_platform_url, semilla, 5000, con_item=True, cantidad="2")
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE productos SET ultimo_costo = 2000 WHERE id = :p"), {"p": semilla["producto"]})
    await engine.dispose()
    pyl = await servicio.pyl("dia", DIA)
    assert pyl.costo_de_lo_vendido_centavos == 4000  # 2 × 2000, el costo actual


async def test_el_pyl_no_ve_el_negocio_de_al_lado(servicio, pg_platform_url):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            dispositivo, sesion = uuid.uuid4(), uuid.uuid4()
            await conn.execute(
                text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja T2')"),
                {"d": dispositivo, "t": T2},
            )
            await conn.execute(
                text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por) VALUES (:s, :t, 'dueno')"),
                {"s": sesion, "t": T2},
            )
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                    f"medio_pago, total_centavos, creada_en_cliente, recibida_en, secuencia_dispositivo) "
                    f"VALUES (:v, :t, :d, :s, 1, 'efectivo', 999000, now(), {EN_PUNTO}, 1)"
                ),
                {"v": uuid.uuid4(), "t": T2, "d": dispositivo, "s": sesion},
            )
    finally:
        await engine.dispose()
    pyl = await servicio.pyl("dia", DIA)
    assert pyl.ventas_netas_centavos == 0  # la RLS hace invisible la venta de T2


# --- El forecast --------------------------------------------------------------------


async def test_el_forecast_suma_saldo_mas_promedios_menos_egresos(servicio, semilla, pg_platform_url):
    """La fórmula honesta (decisión 9): saldo vivo de la sesión abierta +
    ventas en efectivo de los últimos 30d + cobros de fiado (0, declarado) −
    egresos de caja de los últimos 30d."""
    # `now()` en ambas: la ventana del forecast son los últimos 30d desde la
    # corrida, y una fecha fija quedaría fuera de ella con el tiempo.
    await _venta(pg_platform_url, semilla, 10000, recibida_en="now()")  # efectivo: sesión abierta y ventana 30d
    await _venta(pg_platform_url, semilla, 4000, medio_pago="fiado", recibida_en="now()")  # fiado: no es caja
    await _movimiento(pg_platform_url, semilla, 8000, creado="now()")

    forecast = await servicio.forecast()

    # El saldo es el esperado VIVO (decisión 3): base + ventas en efectivo
    # + movimientos − devoluciones. El egreso de 8000 es de ESTA sesión, así
    # que también entra en la cuenta: 50000 + 10000 − 8000.
    assert forecast.saldo_actual_centavos == 50000 + 10000 - 8000
    assert forecast.ventas_proyectadas_centavos == 10000  # promedio diario × 30 con días en 0
    assert forecast.cobros_fiado_proyectados_centavos == 0  # sin fuente hasta el módulo 5: declarado
    assert forecast.egresos_proyectados_centavos == 8000
    assert forecast.saldo_proyectado_centavos == 52000 + 10000 + 0 - 8000
    assert forecast.dias_con_datos == 1
    assert "módulo 5" in forecast.fuentes["cobros_fiado"]
    assert "egresos de caja de los últimos 30" in forecast.fuentes["egresos_proyectados"]


async def test_el_forecast_sin_sesion_abierta_parte_de_cero_y_lo_declara(pg_app_url, semilla, pg_platform_url):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            # Cierra la sesión sembrada: sin abierta, el saldo parte de 0.
            await s.execute(
                text(
                    "UPDATE caja_sesiones SET estado = 'cerrada', cerrada_por = 'dueno', cerrada_en = now(), "
                    "efectivo_esperado = 50000, efectivo_contado = 50000, diferencia = 0"
                )
            )
            servicio = ReportesService(session=s, tenant_id=T1)
            forecast = await servicio.forecast()
            assert forecast.saldo_actual_centavos == 0
            assert "sin sesión abierta" in forecast.fuentes["saldo_actual"]
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()
