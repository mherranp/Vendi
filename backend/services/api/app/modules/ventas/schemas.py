"""Esquemas de entrada y salida del módulo ventas y del sync offline.

El contrato que consume el frontend (y la app del POS) sale de aquí vía
`openapi.json`: cada cambio es un cambio de contrato y se regenera
`docs/api/openapi-fase0.json` con su cliente TypeScript.

Reglas duras heredadas del QA del catálogo:

- Cotas `le=` contra el tipo de columna en TODO número de entrada: un
  overflow de `Integer` o `Numeric(14,3)` es un `DataError` → 500, no un 422.
- Dinero en centavos enteros; cantidades en `Decimal`; jamás flotante.
- `extra="forbid"` en los payloads de dominio: un campo inyectado (p. ej.
  `tenant_id`) se rechaza, no se ignora silenciosamente.
- `creada_en_cliente` exige zona horaria pero NO se acota en rango: el reloj
  del cliente es dato del ticket, no árbitro (ADR-017/018).

La validación de NEGOCIO por operación (fiado⇔cliente, total coherente con
los ítems, duplicados, divergencia) NO está aquí: la hace el servicio dentro
del procesamiento del lote para que una operación mala no arrastre a las
demás al 422 (decisión 6 del plan).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.catalogo.schemas import TOPE_PRECIO, TOPE_STOCK, ProductoSalida
from app.modules.ventas.models import ESTADOS_DE_VENTA, MEDIOS_DE_PAGO

#: Tope de la columna `BigInteger` (2^63 - 1) de `secuencia_dispositivo`.
TOPE_SECUENCIA = 9_223_372_036_854_775_807

#: Tope de operaciones por lote (decisión 7 del plan): acota la transacción
#: que retiene los bloqueos de fila del stock.
TOPE_OPERACIONES_POR_LOTE = 200

#: Tope de líneas por ticket: suficiente para cualquier venta de barrio.
TOPE_ITEMS_POR_VENTA = 500


def _exigir_con_zona(valor: datetime) -> datetime:
    if valor.tzinfo is None or valor.tzinfo.utcoffset(valor) is None:
        raise ValueError("La fecha debe traer zona horaria (offset): un timestamp sin zona no dice nada.")
    return valor


class DispositivoRegistrar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: UUID generado por el cliente (ADR-017): re-registrar es un no-op.
    id: uuid.UUID | None = None
    nombre: str = Field(min_length=1, max_length=120)

    _nombre_limpio = field_validator("nombre", mode="before")(
        # BUG-1 del QA: lo que no sea str pasa intacto y pydantic da 422.
        lambda v: " ".join(v.split()) if isinstance(v, str) else v
    )


class DispositivoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    ultima_secuencia: int
    ultima_sync: datetime | None = None


class VentaItemSync(BaseModel):
    """Una línea de ticket. El precio viene CONGELADO del dispositivo: el
    servidor no recalcula desde el catálogo (ADR-018, decisión 14)."""

    model_config = ConfigDict(extra="forbid")

    producto_id: uuid.UUID
    cantidad: Decimal = Field(gt=0, le=TOPE_STOCK)
    precio_unitario_centavos: int = Field(ge=0, le=TOPE_PRECIO)


class VentaCrearSync(BaseModel):
    """Los datos de una operación `venta.crear`. El id de la venta es el id
    de la OPERACIÓN (va en `OperacionSync.id`): es la PK que puso el cliente.

    Fiado⇔cliente y la coherencia total/ítems las verifica el servicio por
    operación (rechazada con motivo), no el schema — ver la cabecera.
    """

    model_config = ConfigDict(extra="forbid")

    consecutivo_local: int = Field(ge=1, le=TOPE_PRECIO)
    estado: Literal["completada", "anulada"] = "completada"
    medio_pago: Literal["efectivo", "fiado"]
    total_centavos: int = Field(ge=0, le=TOPE_PRECIO)
    cliente_id: uuid.UUID | None = None
    creada_en_cliente: datetime
    items: list[VentaItemSync] = Field(min_length=1, max_length=TOPE_ITEMS_POR_VENTA)

    _con_zona = field_validator("creada_en_cliente")(_exigir_con_zona)


class VentaAnularSync(BaseModel):
    """Los datos de una operación `venta.anular`: anular una venta YA
    ACEPTADA por el servidor. El id de la operación (`OperacionSync.id`) es
    el que referencian los movimientos de reposición de stock."""

    model_config = ConfigDict(extra="forbid")

    venta_id: uuid.UUID


class OperacionSync(BaseModel):
    """Una operación de la cola del dispositivo.

    `tipo` es texto libre acotado, no Literal: un tipo desconocido (cliente y
    servidor de versiones distintas) es `rechazada` por operación, no un 422
    del lote entero (decisión 6). `datos` viaja como dict y lo valida el
    servicio contra `VentaCrearSync`/`VentaAnularSync` por la misma razón.
    """

    model_config = ConfigDict(extra="forbid")

    #: El UUID del cliente. En `venta.crear` ES la PK de la venta; en
    #: `venta.anular` es el id de la operación de anulación.
    id: uuid.UUID
    tipo: str = Field(min_length=1, max_length=40)
    #: Posición FIFO en la cola local del dispositivo (ADR-017).
    secuencia: int = Field(ge=1, le=TOPE_SECUENCIA)
    datos: dict[str, Any] = Field(default_factory=dict)


class LoteSync(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispositivo_id: uuid.UUID
    operaciones: list[OperacionSync] = Field(min_length=1, max_length=TOPE_OPERACIONES_POR_LOTE)


class ResultadoOperacion(BaseModel):
    """El desenlace de UNA operación del lote (ADR-017):

    - `aceptada`: se aplicó (venta registrada/anulada, stock movido, evento
      encolado — todo en la transacción del lote).
    - `duplicada`: ya estaba aplicada exactamente igual; no-op sin evento.
    - `rechazada`: bien formada pero negada por el dominio; `motivo` es el
      `code` estable y `detalles` el contexto (campos divergentes, etc.).
    """

    id: uuid.UUID
    tipo: str
    resultado: Literal["aceptada", "duplicada", "rechazada"]
    motivo: str | None = None
    detalles: dict[str, Any] | None = None


class RespuestaLote(BaseModel):
    """Un resultado por operación, en el MISMO orden del lote."""

    resultados: list[ResultadoOperacion]


class DeltaSalida(BaseModel):
    """El drenado de datos de referencia hacia el dispositivo (ADR-017).

    `hasta` es la marca del SERVIDOR que el dispositivo guarda y devuelve
    como próximo `desde`: el watermark nunca lo pone el reloj del cliente.
    `eliminados` son tumbas: el dispositivo los quita de su IndexedDB.
    """

    hasta: datetime
    productos: list[ProductoSalida]
    eliminados: list[uuid.UUID]


__all__ = [
    "DeltaSalida",
    "DispositivoRegistrar",
    "DispositivoSalida",
    "ESTADOS_DE_VENTA",
    "LoteSync",
    "MEDIOS_DE_PAGO",
    "OperacionSync",
    "RespuestaLote",
    "ResultadoOperacion",
    "TOPE_OPERACIONES_POR_LOTE",
    "VentaAnularSync",
    "VentaCrearSync",
    "VentaItemSync",
]
