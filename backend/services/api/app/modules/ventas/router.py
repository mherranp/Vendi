"""Ventas y sync offline: `/api/v1/dispositivos` y `/api/v1/sync/*`.

El endpoint que hace al POS offline-first (ADR-017). Todo trabaja con la
sesión de TENANT (rol `vendi_app`, RLS activo): ningún handler recibe un
`tenant_id` por URL, cuerpo o cabecera — el lote entero corre con el GUC del
negocio del token y cada fila pasa la policy (el `WITH CHECK` rechaza un
`tenant_id` inyectado, y los schemas llevan `extra="forbid"` para rechazarlo
antes).

Los permisos (ADR-023): registrar dispositivo y sincronizar el lote exigen
`venta:crear` (el cajero drena su cola); el delta exige `producto:leer`. La
anulación NO se guarda en el router: es por operación dentro del lote
(decisión 12 del plan), porque un 403 del lote entero detendría la cola del
cajero por una sola operación prohibida.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status

from app.modules.ventas.dependencies import (
    exigir_producto_leer,
    exigir_venta_crear,
    servicio_de_ventas,
)
from app.modules.ventas.schemas import (
    DeltaSalida,
    DispositivoRegistrar,
    DispositivoSalida,
    LoteSync,
    RespuestaLote,
)
from app.modules.ventas.service import VentasService
from vendi_core.auth.context import UserContext
from vendi_core.errors.domain import ValidationError
from vendi_core.models.responses import ErrorResponse

router = APIRouter(tags=["ventas"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    422: {"model": ErrorResponse, "description": "Request malformado (validación de estructura)"},
}


@router.post(
    "/dispositivos",
    response_model=DispositivoSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un dispositivo del negocio",
    responses=_RESPUESTAS_COMUNES,
)
async def registrar_dispositivo(
    datos: DispositivoRegistrar,
    servicio: VentasService = Depends(servicio_de_ventas),
    _actor: UserContext = Depends(exigir_venta_crear),
) -> DispositivoSalida:
    """Acepta el `id` que traiga el cliente (ADR-017): re-registrar con el
    mismo id devuelve el existente, sin duplicar fila."""
    return DispositivoSalida.model_validate(await servicio.registrar_dispositivo(datos))


@router.post(
    "/sync/lotes",
    response_model=RespuestaLote,
    summary="Aplicar un lote de operaciones de la cola del dispositivo",
    responses=_RESPUESTAS_COMUNES,
)
async def sincronizar_lote(
    lote: LoteSync,
    servicio: VentasService = Depends(servicio_de_ventas),
    _actor: UserContext = Depends(exigir_venta_crear),
) -> RespuestaLote:
    """Una transacción por lote, un resultado por operación
    (`aceptada`/`duplicada`/`rechazada`), en el orden del lote.

    HTTP 200 aunque haya operaciones rechazadas: el lote SE PROCESÓ; el
    desenlace de cada operación viaja en su resultado. Los 4xx de este
    endpoint significan «el request entero es inválido», no «una operación
    falló».

    Idempotencia y divergencia (decisión 4 del plan): reenviar una operación
    con el mismo `id` y un payload IDÉNTICO responde `duplicada` (no-op, sin
    evento); el mismo `id` con cualquier campo del hecho distinto (ítems,
    total, medio de pago, cliente, consecutivo, `creada_en_cliente` o
    estado) responde `rechazada` con motivo `venta_id_divergente` y los
    campos que difieren en `detalles.campos` — jamás un no-op silencioso.
    El dispositivo NO se compara: viaja en el lote, no en `datos`, así que
    un reintento del mismo id de venta desde OTRO dispositivo se reporta
    `duplicada` si el resto del payload coincide.

    Doble verdad temporal (ADR-017/018): `creada_en_cliente` es el dato del
    ticket y se guarda tal cual; al comparar un reintento contra la venta ya
    aceptada se ignoran los microsegundos (la columna `timestamptz` no los
    conserva en el viaje de ida y vuelta), así que una diferencia sub-segundo
    NO convierte un reintento legítimo en `venta_id_divergente`. El orden de
    aplicación es el de recepción y el watermark del delta lo pone el reloj
    del servidor, nunca el del cliente."""
    return RespuestaLote(resultados=await servicio.procesar_lote(lote))


@router.get(
    "/sync/delta",
    response_model=DeltaSalida,
    summary="Descargar los cambios del catálogo desde un watermark",
    responses=_RESPUESTAS_COMUNES,
)
async def delta_de_sync(
    desde: datetime = Query(description="Watermark devuelto como `hasta` por el delta anterior (o una fecha inicial)"),
    servicio: VentasService = Depends(servicio_de_ventas),
    _actor: UserContext = Depends(exigir_producto_leer),
) -> DeltaSalida:
    """El drenado hacia los dispositivos (ADR-017): productos modificados
    desde `desde` y tumbas de los dados de baja. El próximo watermark es el
    `hasta` de la respuesta — lo pone el reloj del servidor, nunca el del
    cliente."""
    if desde.tzinfo is None or desde.tzinfo.utcoffset(desde) is None:
        # FastAPI parsea "2020-01-01" como datetime naive sin error; un
        # watermark sin zona no dice nada (mismo criterio que
        # `creada_en_cliente` en los schemas).
        raise ValidationError("El parámetro `desde` debe traer zona horaria (offset).", code="fecha_sin_zona")
    return await servicio.delta_productos(desde)
