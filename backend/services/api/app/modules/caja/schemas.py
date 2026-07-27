"""Schemas del módulo caja y de los reportes (ADR-021/ADR-006).

El contrato que consume el frontend sale de aquí vía `openapi.json`: cada
cambio es un cambio de contrato (se regenera el congelado y el cliente TS).

Dinero SIEMPRE en centavos enteros, con cota `le=TOPE_PRECIO` contra la
columna `Integer` (un overflow saldría como `DataError` → 500, no como 422:
BUG-2 del QA del catálogo). El `motivo` se limpia ANTES de las cotas de
largo y ningún validador `mode="before"` asume `str` (BUG-1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.caja.models import CATEGORIAS_DE_MOVIMIENTO, TIPOS_DE_MOVIMIENTO_CAJA
from app.modules.catalogo.schemas import TOPE_PRECIO, _limpiar_texto

# --- Entradas ---------------------------------------------------------------


class SesionAbrir(BaseModel):
    """Apertura explícita de la caja del día. `id` es el UUID del cliente
    (ADR-017): reenviar la misma apertura devuelve la sesión existente."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    #: La base con la que arranca la gaveta. 0 es legítimo (es la base de la
    #: sesión implícita del sync, ADR-018).
    base_inicial: int = Field(default=0, ge=0, le=TOPE_PRECIO)


class SesionCerrar(BaseModel):
    """El arqueo: el conteo físico de la gaveta. El servidor calcula el
    esperado y la diferencia y los CONGELA en la sesión (ADR-021)."""

    model_config = ConfigDict(extra="forbid")

    contado: int = Field(ge=0, le=TOPE_PRECIO)


class MovimientoCrear(BaseModel):
    """Un ingreso o egreso manual de la gaveta.

    `id` es REQUERIDO (decisión 6): es dinero, y solo la ancla hace seguro
    el reintento tras un timeout. El `motivo` es obligatorio: un movimiento
    de caja sin justificación es un desfalco con buenos modales."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    tipo: Literal[*TIPOS_DE_MOVIMIENTO_CAJA]
    categoria: Literal[*CATEGORIAS_DE_MOVIMIENTO]
    monto: int = Field(gt=0, le=TOPE_PRECIO)
    motivo: str = Field(min_length=3, max_length=300)

    # La limpieza va ANTES de min_length: un motivo de puros espacios choca
    # con la cota, no se cuela como "".
    _motivo_limpio = field_validator("motivo", mode="before")(_limpiar_texto)


# --- Salidas de caja ---------------------------------------------------------


class SesionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    abierta_por: str
    abierta_en: datetime
    base_inicial: int
    estado: str


class SesionActualSalida(SesionSalida):
    """La sesión abierta con su esperado VIVO — solo para quien cierra caja.

    `efectivo_esperado` viaja en `null` sin `caja:cerrar` (decisión 4, mismo
    patrón que `ultimo_costo` sin `compra:crear`): el esperado en vivo es la
    cifra con la que se cuadra un faltante antes de que el dueño arquee, y
    ADR-023 firma que el cajero no cierra ni ve reportes. El campo sigue en
    el esquema; lo que cambia con el permiso es su valor, no la forma."""

    efectivo_esperado: int | None = None


class DesgloseSalida(BaseModel):
    """La cuenta del arqueo (ADR-021: «una cuenta, no una pantalla mágica»).

    `esperado = base + ventas_efectivo + abonos_efectivo + ingresos
    − egresos − devoluciones`. `abonos_efectivo` es 0 hasta el módulo 5
    (fiado, ADR-022) — declarado en `docs/api/README.md`."""

    base_inicial: int
    ventas_efectivo: int
    abonos_efectivo: int
    ingresos: int
    egresos: int
    devoluciones: int
    esperado: int


class ArqueoSalida(BaseModel):
    """Una sesión con su arqueo congelado (o abierta, con los campos del
    cierre en null). Las columnas congeladas son la única fuente para una
    sesión cerrada: jamás se recalculan."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    abierta_por: str
    abierta_en: datetime
    base_inicial: int
    estado: str
    cerrada_por: str | None = None
    cerrada_en: datetime | None = None
    efectivo_esperado: int | None = None
    efectivo_contado: int | None = None
    diferencia: int | None = None


class ArqueoConDesglose(ArqueoSalida):
    """La respuesta del cierre: el arqueo congelado más la cuenta que lo
    produjo. En el REINTENTO del cierre (mismo conteo) el desglose es null:
    no se recalcula — el arqueo está congelado (Global Constraints)."""

    desglose: DesgloseSalida | None = None


class MovimientoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sesion_caja_id: uuid.UUID
    tipo: str
    categoria: str
    monto: int
    motivo: str
    registrado_por: str
    created_at: datetime | None = None


# --- Salidas de reportes (ADR-006) -------------------------------------------


class PyLSalida(BaseModel):
    """El P&L simple del período. Cada número declara su fuente en `fuentes`
    (ADR-006: la pantalla dice de qué datos sale — condición firmada)."""

    periodo: str
    desde: datetime
    hasta: datetime
    ventas_netas_centavos: int
    ventas_efectivo_centavos: int
    ventas_fiado_centavos: int
    #: Informativo: lo anulado en el período NO entra a las ventas netas.
    ventas_anuladas_centavos: int
    costo_de_lo_vendido_centavos: int
    margen_bruto_centavos: int
    ingresos_caja_centavos: int
    egresos_caja_centavos: int
    #: Flujo informativo: NO se resta del resultado (decisión 8).
    compras_proveedores_centavos: int
    resultado_operativo_centavos: int
    fuentes: dict[str, str]


class ForecastSalida(BaseModel):
    """El forecast a 30 días: una proyección explicada, no una promesa
    (ADR-006). Cada número declara su fuente; lo que no tiene fuente todavía
    (cobros de fiado) viaja en 0 y lo dice."""

    dias: int
    saldo_actual_centavos: int
    ventas_proyectadas_centavos: int
    cobros_fiado_proyectados_centavos: int
    egresos_proyectados_centavos: int
    saldo_proyectado_centavos: int
    dias_con_datos: int
    fuentes: dict[str, str]


__all__ = [
    "ArqueoConDesglose",
    "ArqueoSalida",
    "DesgloseSalida",
    "ForecastSalida",
    "MovimientoCrear",
    "MovimientoSalida",
    "PyLSalida",
    "SesionAbrir",
    "SesionActualSalida",
    "SesionCerrar",
    "SesionSalida",
]
