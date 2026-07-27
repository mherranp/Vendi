"""Catálogo: `/api/v1/productos/*`.

Primer router de dominio de Fase 1. Todo lo que hay aquí trabaja con la
sesión de TENANT (rol `vendi_app`, RLS activo): ningún handler recibe un
`tenant_id` por URL, cuerpo o cabecera — el único que interviene es el que
`TenantMiddleware` sacó del claim `organization`, y la policy hace el resto.

Los permisos (ADR-023): lectura con `producto:leer` (los tres roles),
escritura con `producto:editar` (dueño y almacenista; el cajero recibe 403
`permiso_ausente`, que es la respuesta correcta y esperada).

`ultimo_costo` es la excepción de la lectura compartida: los costos son el
margen del negocio y la decisión firmada es que viven tras `compra:crear`.
El cajero lee el catálogo con `producto:leer`, así que las respuestas le
llegan con `ultimo_costo` en null — el dato existe en base (lo pueblan las
compras, ADR-020) pero no viaja en SU JSON.
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
from vendi_core.auth.policies import PERM_COMPRA_CREAR, has_permission
from vendi_core.models.pagination import PagedList
from vendi_core.models.responses import ErrorResponse

router = APIRouter(prefix="/productos", tags=["catalogo"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    404: {"model": ErrorResponse, "description": "El producto no existe"},
}


def ocultar_costo_a_quien_no_compra(salida: ProductoSalida, actor: UserContext) -> ProductoSalida:
    """Anula `ultimo_costo` cuando el actor no tiene `compra:crear`.

    Mismo criterio que el flag `puede_anular` de ventas (decisión 12 del
    plan): el veredicto se deriva del token en el borde y la autorización lee
    solo el JWT — el servicio no conoce claims. Se aplica en TODA respuesta
    de producto, no solo en las de lectura: la regla es del dato, no del
    endpoint. Es pública porque el delta del sync (`ventas/router.py`) sirve
    los mismos `ProductoSalida` y cumple la misma regla con ella.
    """
    if not has_permission(actor, PERM_COMPRA_CREAR):
        salida.ultimo_costo = None
    return salida


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
    actor: UserContext = Depends(exigir_producto_editar),
) -> ProductoSalida:
    """Acepta el `id` que traiga el cliente (ADR-017): reenviar la misma
    creación devuelve el producto ya creado, sin duplicar fila ni evento."""
    return ocultar_costo_a_quien_no_compra(ProductoSalida.model_validate(await servicio.crear(datos)), actor)


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
    actor: UserContext = Depends(exigir_producto_leer),
) -> PagedList[ProductoSalida]:
    filas, total = await servicio.listar(skip=skip, limit=limit, q=q, categoria=categoria)
    return PagedList[ProductoSalida](
        items=[ocultar_costo_a_quien_no_compra(ProductoSalida.model_validate(f), actor) for f in filas],
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
    actor: UserContext = Depends(exigir_producto_leer),
) -> ProductoSalida:
    """El camino del escáner (ADR-024): un EAN resuelve a exactamente un
    producto, gracias al índice único parcial."""
    return ocultar_costo_a_quien_no_compra(
        ProductoSalida.model_validate(await servicio.buscar_por_codigo(codigo)), actor
    )


@router.get(
    "/{producto_id}",
    response_model=ProductoSalida,
    summary="Ver un producto",
    responses=_RESPUESTAS_COMUNES,
)
async def ver_producto(
    producto_id: uuid.UUID,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    actor: UserContext = Depends(exigir_producto_leer),
) -> ProductoSalida:
    return ocultar_costo_a_quien_no_compra(ProductoSalida.model_validate(await servicio.obtener(producto_id)), actor)


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
    actor: UserContext = Depends(exigir_producto_editar),
) -> ProductoSalida:
    """No acepta `stock_actual` ni `ultimo_costo`: el stock lo mueven los
    movimientos de inventario y el costo las compras (ADR-020)."""
    return ocultar_costo_a_quien_no_compra(
        ProductoSalida.model_validate(await servicio.actualizar(producto_id, datos)), actor
    )


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
