"""Catálogo: `/api/v1/productos/*`.

Primer router de dominio de Fase 1. Todo lo que hay aquí trabaja con la
sesión de TENANT (rol `vendi_app`, RLS activo): ningún handler recibe un
`tenant_id` por URL, cuerpo o cabecera — el único que interviene es el que
`TenantMiddleware` sacó del claim `organization`, y la policy hace el resto.

Los permisos (ADR-023): lectura con `producto:leer` (los tres roles),
escritura con `producto:editar` (dueño y almacenista; el cajero recibe 403
`permiso_ausente`, que es la respuesta correcta y esperada).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.modules.catalogo.dependencies import (
    exigir_producto_editar,
    exigir_producto_leer,
    servicio_de_catalogo,
)
from app.modules.catalogo.schemas import ProductoActualizar, ProductoCrear, ProductoSalida
from app.modules.catalogo.service import CatalogoService
from vendi_core.auth.context import UserContext
from vendi_core.models.pagination import PagedList
from vendi_core.models.responses import ErrorResponse

router = APIRouter(prefix="/productos", tags=["catalogo"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    404: {"model": ErrorResponse, "description": "El producto no existe"},
}


@router.post(
    "",
    response_model=ProductoSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un producto",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "EAN duplicado o id ya usado"},
    },
)
async def crear_producto(
    datos: ProductoCrear,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_editar),
) -> ProductoSalida:
    """Acepta el `id` que traiga el cliente (ADR-017): reenviar la misma
    creación devuelve el producto ya creado, sin duplicar fila ni evento."""
    return ProductoSalida.model_validate(await servicio.crear(datos))


@router.get(
    "",
    response_model=PagedList[ProductoSalida],
    summary="Listar productos",
    responses={k: v for k, v in _RESPUESTAS_COMUNES.items() if k != 404},
)
async def listar_productos(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    q: str | None = Query(default=None, description="Texto a buscar en el nombre"),
    categoria: str | None = Query(default=None),
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_leer),
) -> PagedList[ProductoSalida]:
    filas, total = await servicio.listar(skip=skip, limit=limit, q=q, categoria=categoria)
    return PagedList[ProductoSalida](
        items=[ProductoSalida.model_validate(f) for f in filas],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/por-codigo/{codigo}",
    response_model=ProductoSalida,
    summary="Buscar un producto por código de barras",
    responses=_RESPUESTAS_COMUNES,
)
async def buscar_por_codigo(
    codigo: str,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_leer),
) -> ProductoSalida:
    """El camino del escáner (ADR-024): un EAN resuelve a exactamente un
    producto, gracias al índice único parcial."""
    return ProductoSalida.model_validate(await servicio.buscar_por_codigo(codigo))


@router.get(
    "/{producto_id}",
    response_model=ProductoSalida,
    summary="Ver un producto",
    responses=_RESPUESTAS_COMUNES,
)
async def ver_producto(
    producto_id: uuid.UUID,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_leer),
) -> ProductoSalida:
    return ProductoSalida.model_validate(await servicio.obtener(producto_id))


@router.patch(
    "/{producto_id}",
    response_model=ProductoSalida,
    summary="Actualizar un producto",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "EAN duplicado"},
    },
)
async def actualizar_producto(
    producto_id: uuid.UUID,
    datos: ProductoActualizar,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_editar),
) -> ProductoSalida:
    """No acepta `stock_actual` ni `ultimo_costo`: el stock lo mueven los
    movimientos de inventario y el costo las compras (ADR-020)."""
    return ProductoSalida.model_validate(await servicio.actualizar(producto_id, datos))


@router.delete(
    "/{producto_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dar de baja un producto (borrado lógico)",
    responses=_RESPUESTAS_COMUNES,
)
async def eliminar_producto(
    producto_id: uuid.UUID,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_editar),
) -> Response:
    """Marca `deleted_at` y libera el EAN. La fila sobrevive: el historial de
    ventas la referencia (ADR-019)."""
    await servicio.eliminar(producto_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
