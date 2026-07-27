"""Inventario y compras: `/api/v1/compras*` y `/api/v1/inventario/*`.

Endpoints REST ONLINE clásicos (decisión 3 del plan): NADA de este módulo
viaja por el lote del sync. El ajuste es la única operación de inventario que
exige conexión (ADR-020: su delta se calcula contra el stock del servidor en
el momento del conteo) y la compra es un gesto síncrono del dueño o el
almacenista; un lote con `tipo: "inventario.ajustar"` sale `rechazada` con
`tipo_desconocido` — el contrato del sync queda cerrado.

Todo trabaja con la sesión de TENANT (rol `vendi_app`, RLS activo): ningún
handler recibe `tenant_id` por URL, cuerpo o cabecera. Los permisos
(ADR-023, decisión 10 del plan): escribir Y leer compras exige `compra:crear`;
escribir Y leer ajustes exige `inventario:ajustar`; el estado de stock, con
su nivel derivado, exige `producto:leer`. El 403 del cajero es la respuesta
correcta y esperada.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.modules.inventario.dependencies import (
    exigir_compra_crear,
    exigir_inventario_ajustar,
    exigir_producto_leer,
    servicio_de_inventario,
)
from app.modules.inventario.schemas import (
    AjusteCreado,
    AjusteCrear,
    AjusteSalida,
    CompraCrear,
    CompraDetalleSalida,
    CompraItemSalida,
    CompraSalida,
    StockSalida,
)
from app.modules.inventario.service import InventarioService
from vendi_core.auth.context import UserContext
from vendi_core.models.pagination import PagedList
from vendi_core.models.responses import ErrorResponse

router = APIRouter(tags=["inventario"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    422: {"model": ErrorResponse, "description": "Request malformado (validación de estructura o de dominio)"},
}


@router.post(
    "/compras",
    response_model=CompraDetalleSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una compra a proveedor",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "El id de la compra ya existe (en este u otro negocio)"},
    },
)
async def registrar_compra(
    datos: CompraCrear,
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_compra_crear),
) -> CompraDetalleSalida:
    """En la MISMA transacción: la compra, sus ítems, un movimiento `compra`
    por línea, `stock_actual` y `ultimo_costo` de cada producto, y el evento
    `compra.registrada` (ADR-020). Acepta el `id` que traiga el cliente
    (ADR-017): reenviar la misma compra devuelve la existente, sin duplicar
    fila, stock ni evento. El total lo calcula el servidor por línea; el
    `proveedor_nombre` es texto libre (la factura es un papel: no hay tabla
    de proveedores)."""
    compra, items = await servicio.obtener_compra((await servicio.registrar_compra(datos)).id)
    return _detalle(compra, items)


@router.get(
    "/compras",
    response_model=PagedList[CompraSalida],
    summary="Listar compras",
    responses=_RESPUESTAS_COMUNES,
)
async def listar_compras(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_compra_crear),
) -> PagedList[CompraSalida]:
    filas, total = await servicio.listar_compras(skip=skip, limit=limit)
    return PagedList[CompraSalida](
        items=[CompraSalida.model_validate(f) for f in filas], total=total, skip=skip, limit=limit
    )


@router.get(
    "/compras/{compra_id}",
    response_model=CompraDetalleSalida,
    summary="Ver una compra con sus ítems",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "La compra no existe"}},
)
async def ver_compra(
    compra_id: uuid.UUID,
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_compra_crear),
) -> CompraDetalleSalida:
    compra, items = await servicio.obtener_compra(compra_id)
    return _detalle(compra, items)


@router.post(
    "/inventario/ajustes",
    response_model=AjusteCreado,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un ajuste por conteo o una merma (ONLINE)",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "El id del ajuste ya existe con datos distintos"},
    },
)
async def registrar_ajuste(
    datos: AjusteCrear,
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_inventario_ajustar),
) -> AjusteCreado:
    """La única operación de inventario que EXIGE conexión (ADR-020): el
    delta se calcula contra el stock del servidor en el momento del conteo —
    un ajuste offline corrompería el contador de forma no conmutativa. El
    `motivo` es obligatorio. El `id` del cliente es requerido y ancla la
    idempotencia: el reintento idéntico devuelve lo ya respondido sin mover
    stock; el divergente es 409 `ajuste_id_divergente`. Un conteo que cuadra
    (delta 0) graba la fila pero no escribe movimiento en el libro."""
    return await servicio.registrar_ajuste(datos)


@router.get(
    "/inventario/ajustes",
    response_model=PagedList[AjusteSalida],
    summary="Listar ajustes y mermas",
    responses=_RESPUESTAS_COMUNES,
)
async def listar_ajustes(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_inventario_ajustar),
) -> PagedList[AjusteSalida]:
    """La auditoría del «¿quién movió el arroz?»: cada fila lleva su motivo
    y quién la aplicó."""
    filas, total = await servicio.listar_ajustes(skip=skip, limit=limit)
    return PagedList[AjusteSalida](
        items=[AjusteSalida.model_validate(f) for f in filas], total=total, skip=skip, limit=limit
    )


@router.get(
    "/inventario/stock",
    response_model=PagedList[StockSalida],
    summary="Estado de stock con su nivel (agotado/crítico/bajo/ok)",
    responses=_RESPUESTAS_COMUNES,
)
async def estado_de_stock(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    solo_alertas: bool = Query(default=False, description="Solo productos agotados o por debajo del mínimo"),
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_producto_leer),
) -> PagedList[StockSalida]:
    """El nivel lo deriva el servidor con la misma función que dispara
    `inventario.alerta_stock`: una sola definición del umbral. El stock
    negativo es un dato legítimo (ADR-020) y viaja como `agotado`."""
    items, total = await servicio.estado_stock(skip=skip, limit=limit, solo_alertas=solo_alertas)
    return PagedList[StockSalida](items=items, total=total, skip=skip, limit=limit)


def _detalle(compra, items) -> CompraDetalleSalida:
    salida = CompraSalida.model_validate(compra)
    return CompraDetalleSalida(
        **salida.model_dump(),
        items=[CompraItemSalida.model_validate(i) for i in items],
    )
