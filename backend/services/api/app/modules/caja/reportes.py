"""Servicio de reportes: el P&L simple y el forecast a 30 días (ADR-006).

## Todo se calcula de lo que ya se registra — nada pide dato nuevo al usuario

Ventas (`recibida_en`, la verdad del servidor — ADR-018), ítems ×
`ultimo_costo` ACTUAL (ADR-020: «lo que el P&L costea»), compras por su
fecha de factura, y `caja_movimientos` (ADR-021). Cada número de la
respuesta declara su fuente en `fuentes`: la pantalla dice de qué datos
sale, que es la condición firmada de ADR-006.

## El día es el de America/Bogota; las marcas se guardan en UTC (ADR-021)

La ventana del período se construye como medianoches en `America/Bogota` y
se convierte a UTC para consultar. Anclarla al UTC crudo del servidor
movería al «día siguiente» todo lo vendido después de las 7pm en Colombia.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.caja.models import CajaMovimiento
from app.modules.caja.schemas import ForecastSalida, PyLSalida
from app.modules.caja.service import calcular_desglose
from app.modules.catalogo.models import Producto
from app.modules.fiado.models import FiadoCredito
from app.modules.inventario.models import Compra
from app.modules.ventas.models import CajaSesion, Venta, VentaItem

logger = structlog.get_logger()

#: El «día» del P&L y del cierre (ADR-021). Única zona del MVP (moneda y
#: operación únicas: Colombia); multi-zona no existe en el roadmap.
ZONA_LOCAL = ZoneInfo("America/Bogota")

#: La ventana del forecast (ADR-006) y del promedio que lo alimenta.
DIAS_DE_FORECAST = 30

PERIODOS: tuple[str, ...] = ("dia", "semana", "mes")


def ventana_del_periodo(periodo: str, fecha: date | None) -> tuple[datetime, datetime]:
    """`[desde, hasta)` en UTC del período anclado a America/Bogota.

    `dia` es la fecha Bogotá; `semana` arranca el LUNES de esa fecha; `mes`,
    su día 1. La ancla por defecto es HOY en Bogotá — nunca la fecha UTC del
    servidor, que a las 7pm de Colombia ya es «mañana»."""
    ancla = fecha or datetime.now(ZONA_LOCAL).date()
    if periodo == "semana":
        inicio = ancla - timedelta(days=ancla.weekday())
        fin = inicio + timedelta(days=7)
    elif periodo == "mes":
        inicio = ancla.replace(day=1)
        fin = (inicio.replace(day=28) + timedelta(days=7)).replace(day=1)
    else:  # dia
        inicio, fin = ancla, ancla + timedelta(days=1)
    desde = datetime(inicio.year, inicio.month, inicio.day, tzinfo=ZONA_LOCAL).astimezone(UTC)
    hasta = datetime(fin.year, fin.month, fin.day, tzinfo=ZONA_LOCAL).astimezone(UTC)
    return desde, hasta


class ReportesService:
    """P&L y forecast de UN negocio: el del GUC de la sesión (la RLS acota
    cada SUM; ningún reporte filtra por `tenant_id` a mano)."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self._session = session
        self._tenant_id = tenant_id

    # --- P&L ---------------------------------------------------------------------

    async def pyl(self, periodo: str, fecha: date | None) -> PyLSalida:
        """El P&L simple del período: ventas netas, costo de lo vendido,
        movimientos de caja y compras (flujo informativo, decisión 8)."""
        desde, hasta = ventana_del_periodo(periodo, fecha)
        # Las fechas Bogotá de la ventana, para las compras (su `fecha` es la
        # de la factura: un DATE sin zona).
        desde_fecha = desde.astimezone(ZONA_LOCAL).date()
        hasta_fecha = hasta.astimezone(ZONA_LOCAL).date()

        por_medio = dict(
            (
                await self._session.execute(
                    select(Venta.medio_pago, func.coalesce(func.sum(Venta.total_centavos), 0))
                    .where(Venta.estado == "completada", Venta.recibida_en >= desde, Venta.recibida_en < hasta)
                    .group_by(Venta.medio_pago)
                )
            ).all()
        )
        ventas_netas = sum(int(v) for v in por_medio.values())
        anuladas = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(Venta.total_centavos), 0)).where(
                    Venta.estado == "anulada", Venta.recibida_en >= desde, Venta.recibida_en < hasta
                )
            )
        )
        costo = await self._session.scalar(
            select(func.coalesce(func.sum(VentaItem.cantidad * func.coalesce(Producto.ultimo_costo, 0)), 0))
            .join(Venta, VentaItem.venta_id == Venta.id)
            .join(Producto, VentaItem.producto_id == Producto.id)
            .where(Venta.estado == "completada", Venta.recibida_en >= desde, Venta.recibida_en < hasta)
        )
        # Redondeo al TOTAL, declarado (decisión 8): granel × costo da
        # fracciones de centavo; una sola cuantización, no una por línea.
        costo_centavos = int(Decimal(costo).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        compras = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(Compra.total_centavos), 0)).where(
                    Compra.fecha >= desde_fecha, Compra.fecha < hasta_fecha
                )
            )
        )
        movimientos = dict(
            (
                await self._session.execute(
                    select(CajaMovimiento.tipo, func.coalesce(func.sum(CajaMovimiento.monto), 0))
                    .where(CajaMovimiento.created_at >= desde, CajaMovimiento.created_at < hasta)
                    .group_by(CajaMovimiento.tipo)
                )
            ).all()
        )
        ingresos = int(movimientos.get("ingreso", 0))
        egresos = int(movimientos.get("egreso", 0))
        margen = ventas_netas - costo_centavos
        resultado = margen + ingresos - egresos
        logger.info("pyl_calculado", periodo=periodo, ventas_netas=ventas_netas, resultado=resultado)
        return PyLSalida(
            periodo=periodo,
            desde=desde,
            hasta=hasta,
            ventas_netas_centavos=ventas_netas,
            ventas_efectivo_centavos=int(por_medio.get("efectivo", 0)),
            ventas_fiado_centavos=int(por_medio.get("fiado", 0)),
            ventas_anuladas_centavos=anuladas,
            costo_de_lo_vendido_centavos=costo_centavos,
            margen_bruto_centavos=margen,
            ingresos_caja_centavos=ingresos,
            egresos_caja_centavos=egresos,
            compras_proveedores_centavos=compras,
            resultado_operativo_centavos=resultado,
            fuentes={
                "ventas_netas": (
                    "Suma de ventas completadas (efectivo + fiado) recibidas por el servidor en el período; "
                    "las anuladas no cuentan."
                ),
                "costo_de_lo_vendido": (
                    "Suma de cantidad × ultimo_costo ACTUAL de cada producto: el costo de la última compra "
                    "de hoy, no necesariamente el del día de la venta (ADR-020). Redondeo al total."
                ),
                "compras_proveedores": (
                    "Suma de compras con fecha de factura en el período. Flujo informativo: NO se resta "
                    "del resultado porque repone inventario."
                ),
                "ingresos_caja": "Suma de movimientos manuales de ingreso de caja del período.",
                "egresos_caja": "Suma de movimientos manuales de egreso de caja del período.",
                "resultado_operativo": "ventas_netas − costo_de_lo_vendido + ingresos_caja − egresos_caja.",
            },
        )

    # --- Forecast --------------------------------------------------------------------

    async def forecast(self) -> ForecastSalida:
        """La proyección a 30 días con el alcance honesto de los datos de hoy
        (decisión 9): saldo vivo + promedio de ventas en efectivo + cobros de
        fiado (saldo de los créditos que vencen en la ventana, decisión 11 del
        plan de fiado) − promedio de egresos de caja.

        «Promedio diario × 30» con los días sin datos contando 0 equivale al
        total de los últimos 30 días — y es conservador con la tienda nueva,
        que es donde una proyección optimista haría daño. Los «egresos
        recurrentes» de ADR-021 no tienen fuente en el MVP (no hay tabla de
        gastos recurrentes): el proxy declarado es el total de egresos de
        caja del mismo período. Es una proyección explicada, no una promesa
        (ADR-006)."""
        desde = datetime.now(UTC) - timedelta(days=DIAS_DE_FORECAST)
        ventas_30d = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(Venta.total_centavos), 0)).where(
                    Venta.estado == "completada", Venta.medio_pago == "efectivo", Venta.recibida_en >= desde
                )
            )
        )
        egresos_30d = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(CajaMovimiento.monto), 0)).where(
                    CajaMovimiento.tipo == "egreso", CajaMovimiento.created_at >= desde
                )
            )
        )
        dias_con_datos = int(
            await self._session.scalar(
                select(func.count(func.distinct(func.date(func.timezone("America/Bogota", Venta.recibida_en))))).where(
                    Venta.estado == "completada", Venta.recibida_en >= desde
                )
            )
        )
        sesion = (
            await self._session.execute(select(CajaSesion).where(CajaSesion.estado == "abierta"))
        ).scalar_one_or_none()
        saldo = 0
        if sesion is not None:
            # El saldo actual ES el esperado vivo de la sesión abierta: la
            # misma función del arqueo (decisión 3), jamás una copia.
            saldo = (await calcular_desglose(self._session, sesion)).esperado
        hoy = datetime.now(ZONA_LOCAL).date()
        # Los cobros que deberían entrar si cada fiado se paga a tiempo
        # (módulo 5, decisión 11 del plan de fiado): saldo vivo de créditos
        # vigente/vencido con vencimiento a 30 días o menos. Los ya vencidos
        # cuentan — el cuaderno espera cobrarlos —; los sin fecha, no: sin
        # fecha no hay promesa de pago (ADR-022).
        cobros = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(FiadoCredito.saldo_pendiente), 0)).where(
                    FiadoCredito.estado.in_(("vigente", "vencido")),
                    FiadoCredito.fecha_vencimiento.is_not(None),
                    FiadoCredito.fecha_vencimiento <= hoy + timedelta(days=DIAS_DE_FORECAST),
                )
            )
        )
        proyectado = saldo + ventas_30d + cobros - egresos_30d
        logger.info("forecast_calculado", saldo=saldo, proyectado=proyectado)
        return ForecastSalida(
            dias=DIAS_DE_FORECAST,
            saldo_actual_centavos=saldo,
            ventas_proyectadas_centavos=ventas_30d,
            cobros_fiado_proyectados_centavos=cobros,
            egresos_proyectados_centavos=egresos_30d,
            saldo_proyectado_centavos=proyectado,
            dias_con_datos=dias_con_datos,
            fuentes={
                "saldo_actual": (
                    "Esperado vivo de la sesión de caja abierta (base + ventas en efectivo + abonos de fiado "
                    "en efectivo + movimientos − devoluciones). Con 0 y «sin sesión abierta» cuando no hay "
                    "caja abierta."
                ),
                "ventas_proyectadas": (
                    "Promedio diario de ventas en efectivo completadas de los últimos 30 días × 30 "
                    "(los días sin datos cuentan 0 — conservador con la tienda nueva)."
                ),
                "cobros_fiado": (
                    "Suma del saldo pendiente de los fiados vigentes o vencidos que vencen en los próximos 30 "
                    "días (los ya vencidos cuentan). Los fiados sin fecha de vencimiento no entran: sin fecha "
                    "no hay promesa de pago (ADR-022)."
                ),
                "egresos_proyectados": (
                    "Total de egresos de caja de los últimos 30 días. No hay gastos recurrentes "
                    "registrables en el MVP: es el proxy honesto, declarado."
                ),
                "saldo_proyectado": "saldo_actual + ventas_proyectadas + cobros_fiado − egresos_proyectados.",
            },
        )
