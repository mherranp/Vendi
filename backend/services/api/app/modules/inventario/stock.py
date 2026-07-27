"""El punto ÚNICO por el que se aplica un movimiento de stock (decisión 1).

Todo cambio de inventario —venta, anulación, compra, ajuste, merma— pasa por
`aplicar_movimiento`: inserta la fila del libro, actualiza la proyección
`stock_actual` y evalúa el cruce de umbral. Si la evaluación viviera en cada
punto de aplicación serían cinco copias del mismo `if` esperando a que
alguien olvide una; aquí es estructuralmente imposible mover stock sin
evaluar la alerta.

## El nivel se DERIVA, no se persiste (decisión 2)

Quien llama tiene la fila del producto bloqueada `FOR UPDATE`, así que
`stock_actual` antes del delta ES el estado exacto post-commit del movimiento
anterior: comparar `nivel(antes)` con `nivel(después)` con la función pura
basta. Una columna `nivel_anterior` sería estado redundante capaz de derivar
(quedaría stale al editar `stock_minimo`, que cambia el nivel sin movimiento).

## El evento solo al cruzar hacia abajo (ADR-020)

`inventario.alerta_stock` se emite cuando el nivel EMPEORA. Nunca por
movimiento (una cola de 40 ventas del mismo producto mandaría 40 push
idénticas), nunca al recuperarse (la compra que repone no alerta: re-arma el
umbral), nunca dos veces por el mismo cruce (el siguiente movimiento lee el
nivel ya empeorado como su «antes»). Payload mínimo, sin PII (decisión 13).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalogo.models import Producto
from app.modules.ventas.models import MovimientoInventario
from vendi_core.events.service import DomainEventService

logger = structlog.get_logger()

#: Los cuatro niveles derivados de `stock_minimo` (ADR-020). El ORDEN de la
#: tupla es el criterio de «empeora»: agotado > crítico > bajo > ok.
NIVELES_DE_STOCK: tuple[str, ...] = ("ok", "bajo", "critico", "agotado")

#: La severidad de cada nivel ES su posición en `NIVELES_DE_STOCK`: una sola
#: fuente — añadir un nivel a la tupla lo hace comparable sin tocar nada más.
_SEVERIDAD: dict[str, int] = {nivel: i for i, nivel in enumerate(NIVELES_DE_STOCK)}


def nivel_de_stock(stock: Decimal, stock_minimo: Decimal) -> str:
    """El nivel de un stock dado su mínimo. Función pura: la misma que usa el
    endpoint de estado de stock, para que lo que la app muestra y lo que
    dispara la alerta sea una sola definición.

    ADR-020 literal: agotado (`<= 0`), crítico (`< stock_minimo / 2`), bajo
    (`< stock_minimo`). Los bordes son estrictos: el mínimo exacto es `ok` y
    la mitad exacta es `bajo`. Con `stock_minimo = 0` no hay bajo ni crítico:
    el primer nivel alcanzable es el agotado del cero."""
    if stock <= 0:
        return "agotado"
    if stock < stock_minimo / 2:
        return "critico"
    if stock < stock_minimo:
        return "bajo"
    return "ok"


async def aplicar_movimiento(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    producto: Producto,
    delta: Decimal,
    tipo: str,
    referencia_id: uuid.UUID,
) -> None:
    """Un movimiento en el libro + la proyección + la alerta si cruza, todo
    en la transacción del llamante (ADR-020).

    El signo lo pone quien llama (la venta descuenta, la compra suma). El
    stock puede quedar negativo y es legítimo. Quien llama cargó el producto
    con `with_for_update=True`: el read-modify-write de `stock_actual` —y la
    comparación antes/después del nivel— solo son seguros con la fila
    bloqueada hasta el commit. El evento viaja en la misma transacción: un
    rollback se lleva el movimiento Y la alerta (decisión 14).
    """
    antes = nivel_de_stock(producto.stock_actual, producto.stock_minimo)
    session.add(
        MovimientoInventario(
            tenant_id=tenant_id,
            tipo=tipo,
            cantidad=delta,
            referencia_id=referencia_id,
            producto_id=producto.id,
        )
    )
    producto.stock_actual += delta
    despues = nivel_de_stock(producto.stock_actual, producto.stock_minimo)
    if _SEVERIDAD[despues] > _SEVERIDAD[antes]:
        await DomainEventService.emit(
            session,
            tenant_id=tenant_id,
            event_name="inventario.alerta_stock",
            resource_type="producto",
            resource_id=str(producto.id),
            data={
                "producto_id": str(producto.id),
                "nivel": despues,
                "stock_actual": str(producto.stock_actual),
                "stock_minimo": str(producto.stock_minimo),
            },
        )
        logger.info(
            "alerta_stock_emitida",
            producto_id=str(producto.id),
            nivel_antes=antes,
            nivel_despues=despues,
        )
