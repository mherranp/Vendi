"""Esquemas de entrada y salida del catálogo.

El contrato que consume el frontend sale de aquí vía `openapi.json`, así que
cada cambio en estos modelos es un cambio de contrato: se regenera
`docs/api/openapi-fase0.json` y con él el cliente de Angular.

Dinero en centavos enteros (`precio_venta`, `ultimo_costo`); cantidades en
`Decimal` (`stock_minimo`, `stock_actual`), nunca flotante (ADR-019/ADR-018).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.catalogo.models import TARIFAS_DE_IVA, UNIDADES_DE_MEDIDA

LARGO_MAX_NOMBRE = 160


def _limpiar_texto(valor: str) -> str:
    return " ".join(valor.split())


def _validar_unidad(valor: str) -> str:
    if valor not in UNIDADES_DE_MEDIDA:
        raise ValueError(f"La unidad de medida debe ser una de: {', '.join(UNIDADES_DE_MEDIDA)}.")
    return valor


def _validar_iva(valor: Decimal) -> Decimal:
    if valor not in TARIFAS_DE_IVA:
        raise ValueError("El IVA debe ser 0, 5 o 19: son las tarifas vigentes en Colombia.")
    return valor


def _normalizar_ean(valor: str | None) -> str | None:
    """Un EAN en blanco es NULL, no cadena vacía: el índice único parcial
    trata los NULL como ausencia, y una cadena vacía chocaría con la
    siguiente."""
    if valor is None:
        return None
    limpio = valor.strip()
    return limpio or None


class ProductoCrear(BaseModel):
    #: UUID generado por el cliente (ADR-017). El servidor lo acepta como PK:
    #: reenviar la misma creación es un no-op porque la fila ya existe.
    id: uuid.UUID | None = None
    nombre: str = Field(min_length=1, max_length=LARGO_MAX_NOMBRE)
    codigo_barras: str | None = Field(default=None, max_length=64)
    categoria: str | None = Field(default=None, max_length=120)
    unidad_medida: str = "unidad"
    precio_venta: int = Field(ge=0)
    iva_pct: Decimal = Decimal("0")
    stock_minimo: Decimal = Field(default=Decimal("0"), ge=0)
    padre_id: uuid.UUID | None = None

    _nombre_limpio = field_validator("nombre")(lambda v: _limpiar_texto(v))
    _ean_normalizado = field_validator("codigo_barras")(_normalizar_ean)
    _unidad_valida = field_validator("unidad_medida")(_validar_unidad)
    _iva_valido = field_validator("iva_pct")(_validar_iva)


class ProductoActualizar(BaseModel):
    """Todo opcional: es un PATCH. `None` significa "no lo toques" (misma
    convención que `TenantActualizar`).

    No lleva `stock_actual` ni `ultimo_costo`: el stock lo mueven los
    movimientos de inventario y el costo las compras (ADR-020). Un endpoint
    que dejara editar el contador a mano rompería la invariante del libro.
    """

    nombre: str | None = Field(default=None, min_length=1, max_length=LARGO_MAX_NOMBRE)
    codigo_barras: str | None = Field(default=None, max_length=64)
    categoria: str | None = Field(default=None, max_length=120)
    unidad_medida: str | None = None
    precio_venta: int | None = Field(default=None, ge=0)
    iva_pct: Decimal | None = None
    stock_minimo: Decimal | None = Field(default=None, ge=0)
    padre_id: uuid.UUID | None = None

    _nombre_limpio = field_validator("nombre")(lambda v: None if v is None else _limpiar_texto(v))
    _ean_normalizado = field_validator("codigo_barras")(_normalizar_ean)
    _unidad_valida = field_validator("unidad_medida")(lambda v: None if v is None else _validar_unidad(v))
    _iva_valido = field_validator("iva_pct")(lambda v: None if v is None else _validar_iva(v))


class ProductoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    padre_id: uuid.UUID | None = None
    nombre: str
    codigo_barras: str | None = None
    categoria: str | None = None
    unidad_medida: str
    precio_venta: int
    ultimo_costo: int
    iva_pct: Decimal
    stock_actual: Decimal
    stock_minimo: Decimal
    created_at: datetime | None = None
