"""Esquemas de entrada y salida del módulo inventario.

El contrato que consume el frontend sale de aquí vía `openapi.json`: cada
cambio es un cambio de contrato y se regenera `docs/api/openapi-fase0.json`
con su cliente TypeScript.

Reglas duras heredadas de los QA adversariales de catálogo y ventas:

- Cotas `le=` contra el tipo de columna en TODO número de entrada: un
  overflow de `Integer` o `Numeric(14,3)` es un `DataError` → 500, no un 422.
- Las cantidades se CUANTIZAN a los 3 decimales de la columna con
  `ROUND_HALF_UP` al validar (BUG-2 del QA de ventas: Postgres redondea en
  silencio; cliente y servidor deben comparar siempre la misma cantidad).
- Dinero en centavos enteros (`costo_unitario_centavos`), jamás flotante.
- `extra="forbid"` en las entradas: un `tenant_id` inyectado se rechaza.
- Los validadores `mode="before"` no asumen `str` (BUG-1 del QA de catálogo).

El `total_centavos` de la compra NO está aquí a propósito: lo calcula el
servidor por línea (decisión 7 del plan) — el cliente no puede declararlo.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.catalogo.schemas import TOPE_PRECIO, TOPE_STOCK

#: Tope de líneas por compra: acota la transacción que retiene los bloqueos
#: de fila de los productos (mismo criterio que el tope del lote del sync).
TOPE_ITEMS_POR_COMPRA = 200


def _limpiar_texto(valor: object) -> object:
    # Corre ANTES de la validación de tipo (mode="before"): lo que no sea str
    # pasa intacto para que pydantic lo rechace como 422. Intentar limpiarlo
    # reventaría con AttributeError dentro del validador y saldría como 500.
    if not isinstance(valor, str):
        return valor
    return " ".join(valor.split())


def _cuantizar_cantidad(valor: Decimal) -> Decimal:
    """La columna es NUMERIC(14,3): Postgres REDONDEA lo que no cabe
    (BUG-2 del QA de ventas). El schema aplica el MISMO redondeo al validar
    y rechaza lo que cuantiza a cero, que reventaría `ck_..._cantidad_positiva`
    como 500. Misma regla que `ventas/schemas.py`; se duplica a propósito:
    el mensaje de error nombra el contexto (una línea de compra)."""
    cuantizada = valor.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if cuantizada == 0:
        raise ValueError("La cantidad es menor que 0.001: no cabe en una línea de compra.")
    return cuantizada


def _cuantizar_conteo(valor: Decimal) -> Decimal:
    """El conteo físico también se guarda en NUMERIC(14,3), pero el cero es
    un conteo VÁLIDO («no queda ninguna»): se cuantiza sin rechazarlo."""
    return valor.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# --- Compra ---------------------------------------------------------------------


class CompraItemEntrada(BaseModel):
    """Una línea de factura. El costo es el de ESTA compra: al confirmarse
    actualiza `ultimo_costo` del producto (ADR-020)."""

    model_config = ConfigDict(extra="forbid")

    producto_id: uuid.UUID
    cantidad: Decimal = Field(gt=0, le=TOPE_STOCK)
    costo_unitario_centavos: int = Field(ge=0, le=TOPE_PRECIO)

    _cantidad_cuantizada = field_validator("cantidad")(_cuantizar_cantidad)


class CompraCrear(BaseModel):
    """Una compra a proveedor. `proveedor_nombre` es texto libre (ADR-020:
    la factura es un papel; no hay tabla de proveedores). El `id` del
    cliente se acepta como PK (ADR-017): reenviar la misma compra es un
    no-op. El total NO viaja: lo calcula el servidor (decisión 7)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    proveedor_nombre: str = Field(min_length=1, max_length=160)
    #: El dato de la factura de papel; sin cota de rango (una factura de
    #: ayer se registra hoy). Si falta, el servidor pone su fecha.
    fecha: date | None = None
    observaciones: str | None = Field(default=None, max_length=500)
    items: list[CompraItemEntrada] = Field(min_length=1, max_length=TOPE_ITEMS_POR_COMPRA)

    _proveedor_limpio = field_validator("proveedor_nombre", mode="before")(_limpiar_texto)
    _observaciones_limpias = field_validator("observaciones", mode="before")(
        lambda v: None if v is None else _limpiar_texto(v)
    )

    @model_validator(mode="after")
    def _un_producto_por_linea(self) -> CompraCrear:
        """Decisión 8: dos líneas del mismo producto chocarían en
        `ux_movimientos_origen` (referencia = compra.id) y habría que elegir
        en silencio qué costo gana para `ultimo_costo`. La compra es un
        formulario síncrono: la UI suma las líneas, y si no, 422."""
        ids = [item.producto_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("La compra tiene el mismo producto en dos líneas: súmalas en una sola.")
        return self


class CompraItemSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    producto_id: uuid.UUID
    cantidad: Decimal
    costo_unitario_centavos: int


class CompraSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    proveedor_nombre: str
    fecha: date
    observaciones: str | None = None
    total_centavos: int
    created_at: datetime | None = None


class CompraDetalleSalida(CompraSalida):
    items: list[CompraItemSalida]


# --- Ajuste y merma ---------------------------------------------------------------


class AjusteCrear(BaseModel):
    """Un ajuste por conteo o una merma. ONLINE obligatorio (ADR-020): el
    delta se calcula contra el stock del servidor en el momento.

    `id` es REQUERIDO (decisión 4): es la PK de `ajustes_inventario` y la
    única ancla que hace seguro el reintento de una merma, que es un delta
    relativo. El `motivo` es obligatorio: un ajuste sin justificación es un
    desfalco con buenos modales.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    tipo: Literal["ajuste", "merma"]
    producto_id: uuid.UUID
    #: El conteo físico (solo `tipo="ajuste"`).
    stock_contado: Decimal | None = Field(default=None, ge=0, le=TOPE_STOCK)
    #: Lo que se dañó (solo `tipo="merma"`).
    cantidad: Decimal | None = Field(default=None, gt=0, le=TOPE_STOCK)
    motivo: str = Field(min_length=3, max_length=300)

    _conteo_cuantizado = field_validator("stock_contado")(lambda v: None if v is None else _cuantizar_conteo(v))
    _cantidad_cuantizada = field_validator("cantidad")(lambda v: None if v is None else _cuantizar_cantidad(v))
    # La limpieza va ANTES de min_length: un motivo de puros espacios choca
    # con la cota, no se cuela como "".
    _motivo_limpio = field_validator("motivo", mode="before")(_limpiar_texto)

    @model_validator(mode="after")
    def _la_forma_es_la_del_tipo(self) -> AjusteCrear:
        """Espejo en la aplicación de `ck_ajustes_forma`: el 422 lo da
        pydantic, no la constraint (que saldría como 500)."""
        if self.tipo == "ajuste":
            if self.stock_contado is None:
                raise ValueError("Un ajuste por conteo necesita `stock_contado` (lo que contaste).")
            if self.cantidad is not None:
                raise ValueError("`cantidad` es solo para mermas; el ajuste lleva `stock_contado`.")
        else:
            if self.cantidad is None:
                raise ValueError("Una merma necesita `cantidad` (lo que se dañó).")
            if self.stock_contado is not None:
                raise ValueError("`stock_contado` es solo para ajustes por conteo; la merma lleva `cantidad`.")
        return self


class AjusteSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tipo: str
    producto_id: uuid.UUID
    stock_contado: Decimal | None = None
    cantidad: Decimal | None = None
    #: Lo aplicado contra el stock del servidor (0 = el conteo cuadraba y no
    #: hubo movimiento en el libro).
    delta: Decimal
    motivo: str
    aplicado_por: str
    stock_resultante: Decimal
    created_at: datetime | None = None


class AjusteCreado(AjusteSalida):
    """La respuesta del alta: lo mismo que la fila, más el nivel de alerta en
    que quedó el producto (lo deriva el servidor, que es la única autoridad
    del umbral — decisión 2)."""

    nivel: str


# --- Estado de stock ---------------------------------------------------------------


class StockSalida(BaseModel):
    """El stock de un producto con su nivel derivado (agotado/crítico/bajo/ok).

    El nivel lo calcula el servidor con la misma función que dispara las
    alertas: una sola definición del umbral, ninguna reimplementación en el
    frontend. El stock negativo es un dato legítimo (ADR-020) y viaja tal
    cual con nivel `agotado`."""

    producto_id: uuid.UUID
    nombre: str
    stock_actual: Decimal
    stock_minimo: Decimal
    nivel: str


__all__ = [
    "TOPE_ITEMS_POR_COMPRA",
    "AjusteCreado",
    "AjusteCrear",
    "AjusteSalida",
    "CompraCrear",
    "CompraDetalleSalida",
    "CompraItemEntrada",
    "CompraItemSalida",
    "CompraSalida",
    "StockSalida",
]
