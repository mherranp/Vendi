"""Caja y reportes: `/api/v1/caja/*` y `/api/v1/reportes/*`.

Endpoints REST ONLINE puros (patrón inventario): NADA de este módulo viaja
por el lote del sync — la apertura implícita del sync sigue igual (ADR-018,
decisión 10 del plan). Todo trabaja con la sesión de TENANT (rol
`vendi_app`, RLS activo): ningún handler recibe `tenant_id` por URL, cuerpo
o cabecera. Los permisos (ADR-023): abrir `caja:abrir`, leer `caja:leer`,
movimientos `caja:movimiento`, cerrar e historial `caja:cerrar`, reportes
`reporte:leer`. El 403 por rol es la respuesta correcta y esperada.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from app.modules.caja.dependencies import (
    exigir_caja_abrir,
    exigir_caja_cerrar,
    exigir_caja_leer,
    exigir_caja_movimiento,
    exigir_reporte_leer,
    servicio_de_caja,
    servicio_de_reportes,
)
from app.modules.caja.reportes import ReportesService
from app.modules.caja.schemas import (
    ArqueoConDesglose,
    ArqueoSalida,
    ForecastSalida,
    MovimientoCrear,
    MovimientoSalida,
    PyLSalida,
    SesionAbrir,
    SesionActualSalida,
    SesionCerrar,
    SesionSalida,
)
from app.modules.caja.service import CajaService
from vendi_core.auth.context import UserContext
from vendi_core.models.pagination import PagedList
from vendi_core.models.responses import ErrorResponse

router = APIRouter(tags=["caja"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    422: {"model": ErrorResponse, "description": "Request malformado (validación de estructura o de dominio)"},
}


@router.post(
    "/caja/sesiones",
    response_model=SesionSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Abrir la caja del día",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "Ya hay una caja abierta (o el id de sesión está en uso)"},
    },
)
async def abrir_caja(
    datos: SesionAbrir,
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_abrir),
) -> SesionSalida:
    """UNA sesión abierta por tienda (ADR-021): la regla la hace cumplir el
    índice único parcial, no el código. Acepta el `id` del cliente
    (ADR-017): reenviar la misma apertura devuelve la sesión existente."""
    return SesionSalida.model_validate(await servicio.abrir_sesion(datos))


@router.get(
    "/caja/sesiones/actual",
    response_model=SesionActualSalida,
    summary="La sesión abierta, con el esperado vivo solo para quien cierra",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "No hay caja abierta"}},
)
async def sesion_actual(
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_leer),
) -> SesionActualSalida:
    """`efectivo_esperado` viaja en `null` sin `caja:cerrar` (decisión 4):
    el esperado vivo es la cifra con la que se cuadra un faltante, y el
    cajero no cierra ni ve reportes (ADR-023)."""
    return await servicio.sesion_actual()


@router.get(
    "/caja/sesiones",
    response_model=PagedList[ArqueoSalida],
    summary="Historial de sesiones con su arqueo congelado",
    responses=_RESPUESTAS_COMUNES,
)
async def listar_sesiones(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_cerrar),
) -> PagedList[ArqueoSalida]:
    """Faltantes y sobrantes históricos son un reporte: exige `caja:cerrar`
    (decisión 4). Las columnas congeladas son la única fuente: jamás se
    recalculan."""
    filas, total = await servicio.listar_sesiones(skip=skip, limit=limit)
    return PagedList[ArqueoSalida](
        items=[ArqueoSalida.model_validate(f) for f in filas], total=total, skip=skip, limit=limit
    )


@router.post(
    "/caja/sesiones/{sesion_id}/cerrar",
    response_model=ArqueoConDesglose,
    summary="Cerrar la caja con arqueo (conteo físico)",
    responses={
        **_RESPUESTAS_COMUNES,
        404: {"model": ErrorResponse, "description": "La sesión no existe"},
        409: {"model": ErrorResponse, "description": "La sesión ya fue cerrada con otro conteo"},
    },
)
async def cerrar_caja(
    sesion_id: uuid.UUID,
    datos: SesionCerrar,
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_cerrar),
) -> ArqueoConDesglose:
    """El arqueo (ADR-021): el servidor calcula `esperado = base + ventas en
    efectivo + abonos de fiado en efectivo + ingresos − egresos −
    devoluciones` sumando desde las tablas de origen, y lo CONGELA con el
    `contado` y la `diferencia` en la sesión. Desde entonces nada lo reabre:
    ni una venta que sincroniza tarde, ni una anulación posterior. El
    reintento con el mismo conteo devuelve el arqueo firmado."""
    return await servicio.cerrar_sesion(sesion_id, datos)


@router.post(
    "/caja/movimientos",
    response_model=MovimientoSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un ingreso o egreso manual de caja",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {
            "model": ErrorResponse,
            "description": "No hay caja abierta, o el id del movimiento ya existe con datos distintos",
        },
    },
)
async def registrar_movimiento(
    datos: MovimientoCrear,
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_movimiento),
) -> MovimientoSalida:
    """Con `motivo` obligatorio e `id` del cliente requerido (es dinero: la
    ancla hace seguro el reintento). Las ventas en efectivo y los abonos NO
    son movimientos: el arqueo los suma desde su tabla de origen (ADR-021)."""
    return MovimientoSalida.model_validate(await servicio.registrar_movimiento(datos))


@router.get(
    "/caja/movimientos",
    response_model=PagedList[MovimientoSalida],
    summary="Movimientos de una sesión (la abierta, por defecto)",
    responses={
        **_RESPUESTAS_COMUNES,
        404: {"model": ErrorResponse, "description": "La sesión no existe (o no hay abierta)"},
    },
)
async def listar_movimientos(
    sesion_id: uuid.UUID | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_leer),
) -> PagedList[MovimientoSalida]:
    """El listado es del cajero (`caja:leer`) salvo los `retiro_dueno`: el
    retiro del dueño es tan sensible como el costo y solo aparece — en la
    lista y en el total — con `caja:cerrar` (C-3 del QA, misma lección que
    `ultimo_costo`)."""
    filas, total = await servicio.listar_movimientos(sesion_id, skip=skip, limit=limit)
    return PagedList[MovimientoSalida](
        items=[MovimientoSalida.model_validate(f) for f in filas], total=total, skip=skip, limit=limit
    )


@router.get(
    "/reportes/pyl",
    response_model=PyLSalida,
    summary="P&L simple del período (día/semana/mes en America/Bogota)",
    responses=_RESPUESTAS_COMUNES,
)
async def pyl(
    periodo: Literal["dia", "semana", "mes"] = Query(default="dia"),
    fecha: date | None = Query(default=None, description="Ancla Bogotá (YYYY-MM-DD); por defecto, hoy"),
    servicio: ReportesService = Depends(servicio_de_reportes),
    _actor: UserContext = Depends(exigir_reporte_leer),
) -> PyLSalida:
    """Se calcula de lo que ya se registra (ADR-006): ventas por
    `recibida_en`, costo con el `ultimo_costo` actual (declarado), compras
    por fecha de factura y movimientos de caja. Cada número declara su
    fuente en `fuentes`."""
    return await servicio.pyl(periodo, fecha)


@router.get(
    "/reportes/forecast",
    response_model=ForecastSalida,
    summary="Forecast de flujo de caja a 30 días",
    responses=_RESPUESTAS_COMUNES,
)
async def forecast(
    servicio: ReportesService = Depends(servicio_de_reportes),
    _actor: UserContext = Depends(exigir_reporte_leer),
) -> ForecastSalida:
    """Proyección explicada, no promesa (ADR-006): saldo vivo + promedio de
    ventas en efectivo 30d + cobros de fiado (saldo de los créditos que
    vencen en la ventana) − promedio de egresos de caja 30d. Cada número
    declara su fuente."""
    return await servicio.forecast()
