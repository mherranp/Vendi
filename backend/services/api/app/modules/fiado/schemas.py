"""Schemas del módulo fiado y clientes (ADR-022).

El contrato que consume el frontend sale de aquí vía `openapi.json`: cada
cambio es un cambio de contrato (se regenera el congelado y el cliente TS).

Dinero SIEMPRE en centavos enteros, con cota `le=TOPE_PRECIO` contra la
columna `Integer` (un overflow saldría como `DataError` → 500, no como 422:
BUG-2 del QA del catálogo). La limpieza de texto va ANTES de las cotas de
largo y ningún validador `mode="before"` asume `str` (BUG-1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.catalogo.schemas import TOPE_PRECIO, _limpiar_texto
from app.modules.fiado.models import METODOS_DE_PAGO_ABONO


def _telefono_limpio(valor: object) -> object:
    """Formato WhatsApp colombiano, sin validación internacional (ADR-022):
    solo dígitos, 10 a 15 (10 = celular local sin indicativo). Corre ANTES
    de la validación de tipo (mode="before"): lo que no sea str pasa intacto
    para que pydantic lo rechace como 422 (BUG-1)."""
    if valor is None or not isinstance(valor, str):
        return valor
    limpio = valor.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if limpio.startswith("+"):
        limpio = limpio[1:]
    if not limpio.isdigit() or not 10 <= len(limpio) <= 15:
        raise ValueError("El teléfono debe ser de WhatsApp: solo dígitos, entre 10 y 15 (con indicativo).")
    return limpio


# --- Entradas ------------------------------------------------------------


class ClienteCrear(BaseModel):
    """Alta online de un cliente. `id` es el UUID del cliente (ADR-017):
    reenviar el mismo alta devuelve el existente; con otro contenido, 409."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    nombre: str = Field(min_length=2, max_length=160)
    telefono: str | None = None
    nota: str | None = Field(default=None, max_length=300)
    #: NULL = sin cupo: se fía sin tope (el cuaderno nunca le dijo que no a
    #: nadie). 0 = no fiarle más. El servidor nunca rechaza por cupo
    #: (ADR-018): lo registra y lo muestra (decisión 8).
    limite_credito: int | None = Field(default=None, ge=0, le=TOPE_PRECIO)

    _nombre_limpio = field_validator("nombre", mode="before")(_limpiar_texto)
    _nota_limpia = field_validator("nota", mode="before")(_limpiar_texto)
    _telefono_valido = field_validator("telefono", mode="before")(_telefono_limpio)


class ClienteEditar(BaseModel):
    """Edición parcial. `null` explícito en `limite_credito`/`telefono`/`nota`
    BORRA el valor (vuelve a «sin cupo»/«sin teléfono»)."""

    model_config = ConfigDict(extra="forbid")

    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    telefono: str | None = None
    nota: str | None = Field(default=None, max_length=300)
    limite_credito: int | None = Field(default=None, ge=0, le=TOPE_PRECIO)

    _nombre_limpio = field_validator("nombre", mode="before")(_limpiar_texto)
    _nota_limpia = field_validator("nota", mode="before")(_limpiar_texto)
    _telefono_valido = field_validator("telefono", mode="before")(_telefono_limpio)


class ClienteCrearSync(BaseModel):
    """Los datos de una operación `cliente.crear` del lote (decisión 2). El
    id del cliente ES el id de la operación (`OperacionSync.id`): la PK que
    puso el dispositivo, adoptada como PK (cierre de D-10)."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=2, max_length=160)
    telefono: str | None = None
    nota: str | None = Field(default=None, max_length=300)
    limite_credito: int | None = Field(default=None, ge=0, le=TOPE_PRECIO)

    _nombre_limpio = field_validator("nombre", mode="before")(_limpiar_texto)
    _nota_limpia = field_validator("nota", mode="before")(_limpiar_texto)
    _telefono_valido = field_validator("telefono", mode="before")(_telefono_limpio)


class AbonoCrear(BaseModel):
    """Un pago contra el crédito que el usuario tocó (ADR-022).

    `id` es REQUERIDO (es dinero: solo la ancla hace seguro el reintento
    tras un timeout — y deja lista la vía del abono offline por el lote,
    decisión 6). El servidor descuenta el saldo en la misma transacción; un
    abono mayor que el saldo es 422 `abono_excede_saldo` (el CHECK es la
    red, no la regla)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    monto: int = Field(gt=0, le=TOPE_PRECIO)
    metodo_pago: Literal[*METODOS_DE_PAGO_ABONO]
    nota: str | None = Field(default=None, max_length=300)

    _nota_limpia = field_validator("nota", mode="before")(_limpiar_texto)


class AbonoSync(BaseModel):
    """Los datos de una operación `fiado.abonar` del lote (cierre de D-27).

    El id del abono ES el id de la operación (`OperacionSync.id`): la ancla
    de ADR-022 («un abono registrado sin señal tiene que sincronizar sin
    duplicarse, y la idempotencia la da el id») ya estaba puesta en el POST
    online y aquí se reutiliza intacta.

    `cliente_id` es REQUERIDO como ancla de coherencia: el dispositivo cobró
    contra el crédito que veía en el cuaderno de ESE cliente; si el crédito
    resulta ser de otro, la operación es `rechazada` y no un descuento a
    ciegas. `sesion_caja_id` NO viaja: la sesión la resuelve el servidor al
    aplicar el abono (patrón del abono online, decisión 9 del plan)."""

    model_config = ConfigDict(extra="forbid")

    cliente_id: uuid.UUID
    credito_id: uuid.UUID
    monto: int = Field(gt=0, le=TOPE_PRECIO)
    metodo_pago: Literal[*METODOS_DE_PAGO_ABONO]
    nota: str | None = Field(default=None, max_length=300)

    _nota_limpia = field_validator("nota", mode="before")(_limpiar_texto)


class CreditoReprogramar(BaseModel):
    """«Deme hasta el otro viernes»: nueva fecha de vencimiento. El campo es
    REQUERIDO: `null` explícito deja el fiado sin recordatorio, pero ese
    gesto tiene que ser deliberado — un body `{}` es 422, nunca un borrado
    tácito por el default del schema. Un `vencido` reprogramado a futuro
    vuelve a `vigente` (decisión 7)."""

    model_config = ConfigDict(extra="forbid")

    fecha_vencimiento: date | None


# --- Salidas -------------------------------------------------------------


class ClienteSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    telefono: str | None = None
    nota: str | None = None
    limite_credito: int | None = None
    created_at: datetime | None = None


class CreditoResumenSalida(BaseModel):
    """Un fiado del cuaderno. `monto_total` y `saldo_pendiente` en centavos."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cliente_id: uuid.UUID
    venta_id: uuid.UUID
    monto_total: int
    saldo_pendiente: int
    fecha_vencimiento: date | None = None
    estado: str
    created_at: datetime | None = None
    #: El nombre viaja para que el cuaderno diga «Don Carlos me debe...» sin
    #: un segundo viaje por crédito.
    cliente_nombre: str | None = None


class ClienteConSaldo(ClienteSalida):
    """El cliente con su deuda viva: `SUM(saldo_pendiente)` de sus créditos
    `vigente`/`vencido` — calculado en cada lectura, nunca guardado
    (ADR-022) — y el cupo evaluado (decisión 8)."""

    saldo_pendiente_total: int
    cupo_excedido: bool


class ClienteDetalleSalida(ClienteConSaldo):
    """La ficha del cliente: sus datos, su saldo y sus fiados con deuda."""

    creditos: list[CreditoResumenSalida] = []


class AbonoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    credito_id: uuid.UUID
    sesion_caja_id: uuid.UUID | None = None
    monto: int
    metodo_pago: str
    registrado_por: str
    nota: str | None = None
    created_at: datetime | None = None


class CreditoDetalleSalida(CreditoResumenSalida):
    """La pantalla del fiado: su historial de pagos (ADR-009) y el enlace
    `wa.me` prearmado para cobrarle (ADR-022: WhatsApp manual). `null` si el
    cliente no tiene teléfono."""

    abonos: list[AbonoSalida] = []
    whatsapp_url: str | None = None


__all__ = [
    "AbonoCrear",
    "AbonoSalida",
    "AbonoSync",
    "ClienteConSaldo",
    "ClienteCrear",
    "ClienteCrearSync",
    "ClienteDetalleSalida",
    "ClienteEditar",
    "ClienteSalida",
    "CreditoDetalleSalida",
    "CreditoReprogramar",
    "CreditoResumenSalida",
]
