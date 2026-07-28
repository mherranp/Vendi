"""Clientes y el cuaderno: `/api/v1/clientes/*` y `/api/v1/fiado/creditos/*`.

Los endpoints de ABONOS son REST ONLINE puros (decisión 6 del plan): el
abono offline por el lote llega con su propia decisión (D-27), y el `id`
requerido ya deja puesta su ancla. Los créditos NACEN en el sync (Tarea 7):
aquí se consultan, se reprograman y se cobran. Todo trabaja con la sesión
de TENANT (rol `vendi_app`, RLS activo): ningún handler recibe `tenant_id`.
El 403 por rol es la respuesta correcta y esperada (ADR-023).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.modules.fiado.dependencies import (
    exigir_cliente_gestionar,
    exigir_fiado_abonar,
    exigir_fiado_crear,
    servicio_de_fiado,
)
from app.modules.fiado.schemas import (
    AbonoCrear,
    AbonoSalida,
    ClienteConSaldo,
    ClienteCrear,
    ClienteDetalleSalida,
    ClienteEditar,
    ClienteSalida,
    CreditoDetalleSalida,
    CreditoReprogramar,
    CreditoResumenSalida,
)
from app.modules.fiado.service import FiadoService
from vendi_core.auth.context import UserContext
from vendi_core.models.pagination import PagedList
from vendi_core.models.responses import ErrorResponse

router = APIRouter(tags=["fiado"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    422: {"model": ErrorResponse, "description": "Request malformado (validación de estructura o de dominio)"},
}


@router.post(
    "/clientes",
    response_model=ClienteSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un cliente",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "El id ya existe con datos distintos (o está en uso)"},
    },
)
async def crear_cliente(
    datos: ClienteCrear,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_cliente_gestionar),
) -> ClienteSalida:
    """Idempotente por el `id` del cliente (ADR-017): reenviar el mismo alta
    devuelve el existente; con otro contenido, 409 `cliente_id_divergente`."""
    return await servicio.crear_cliente(datos)


@router.get(
    "/clientes",
    response_model=PagedList[ClienteConSaldo],
    summary="La libreta de clientes con su deuda viva",
    responses=_RESPUESTAS_COMUNES,
)
async def listar_clientes(
    q: str | None = Query(default=None, max_length=160),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_cliente_gestionar),
) -> PagedList[ClienteConSaldo]:
    """El saldo es `SUM(saldo_pendiente)` de vigente/vencido, calculado en
    cada lectura (ADR-022): nunca una columna que se desactualice. `q`
    busca por nombre."""
    filas, total = await servicio.listar_clientes(q, skip=skip, limit=limit)
    return PagedList[ClienteConSaldo](items=filas, total=total, skip=skip, limit=limit)


@router.get(
    "/clientes/{cliente_id}",
    response_model=ClienteDetalleSalida,
    summary="La ficha del cliente: saldo, cupo y sus fiados con deuda",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "El cliente no existe"}},
)
async def obtener_cliente(
    cliente_id: uuid.UUID,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_cliente_gestionar),
) -> ClienteDetalleSalida:
    """Con `saldo_pendiente_total` y `cupo_excedido` calculados (decisión 8):
    es lo que el POS muestra antes de fiarle más."""
    return await servicio.obtener_cliente(cliente_id)


@router.patch(
    "/clientes/{cliente_id}",
    response_model=ClienteSalida,
    summary="Editar un cliente",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "El cliente no existe"}},
)
async def editar_cliente(
    cliente_id: uuid.UUID,
    datos: ClienteEditar,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_cliente_gestionar),
) -> ClienteSalida:
    """`null` explícito borra el valor (quitar el cupo vuelve a «sin tope»).
    El cliente no se borra (decisión 13): el cuaderno lo referencia."""
    return await servicio.editar_cliente(cliente_id, datos)


@router.get(
    "/fiado/creditos",
    response_model=PagedList[CreditoResumenSalida],
    summary="El cuaderno: los fiados, lo que vence primero arriba",
    responses=_RESPUESTAS_COMUNES,
)
async def listar_creditos(
    estado: str | None = Query(default=None, pattern="^(vigente|vencido|saldado|anulado|todos)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_fiado_crear),
) -> PagedList[CreditoResumenSalida]:
    """Por defecto solo lo que se debe (`vigente` + `vencido`); `estado=todos`
    incluye la historia. La lista de estados es CERRADA: uno arbitrario es
    422, no una lista vacía. El fiado ES el cuaderno (ADR-009)."""
    filas, total = await servicio.listar_creditos(estado, skip=skip, limit=limit)
    return PagedList[CreditoResumenSalida](items=filas, total=total, skip=skip, limit=limit)


@router.get(
    "/fiado/creditos/{credito_id}",
    response_model=CreditoDetalleSalida,
    summary="El fiado: historial de pagos y enlace de WhatsApp prearmado",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "El crédito no existe"}},
)
async def obtener_credito(
    credito_id: uuid.UUID,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_fiado_crear),
) -> CreditoDetalleSalida:
    """El historial de abonos es la verdad y no se reescribe (ADR-022). El
    `wa.me` va prearmado con el saldo; `null` si el cliente no tiene teléfono."""
    return await servicio.obtener_credito(credito_id)


@router.patch(
    "/fiado/creditos/{credito_id}",
    response_model=CreditoResumenSalida,
    summary="Reprogramar la fecha de vencimiento",
    responses={
        **_RESPUESTAS_COMUNES,
        404: {"model": ErrorResponse, "description": "El crédito no existe"},
        409: {"model": ErrorResponse, "description": "El crédito está saldado o anulado"},
    },
)
async def reprogramar_credito(
    credito_id: uuid.UUID,
    datos: CreditoReprogramar,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_fiado_crear),
) -> CreditoResumenSalida:
    """«Deme hasta el otro viernes»: un `vencido` reprogramado a futuro (o
    dejado sin fecha) vuelve a `vigente` (decisión 7)."""
    return await servicio.reprogramar_vencimiento(credito_id, datos)


@router.post(
    "/fiado/creditos/{credito_id}/abonos",
    response_model=AbonoSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un abono",
    responses={
        **_RESPUESTAS_COMUNES,
        404: {"model": ErrorResponse, "description": "El crédito no existe"},
        409: {
            "model": ErrorResponse,
            "description": "El crédito no admite abonos, no hay caja abierta, o el id diverge",
        },
    },
)
async def registrar_abono(
    credito_id: uuid.UUID,
    datos: AbonoCrear,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_fiado_abonar),
) -> AbonoSalida:
    """El saldo se descuenta en la misma transacción con el CHECK como red
    (ADR-022). `efectivo` entra al arqueo de la sesión abierta (decisión 9);
    un abono mayor que el saldo es 422 `abono_excede_saldo`."""
    return await servicio.registrar_abono(credito_id, datos)
