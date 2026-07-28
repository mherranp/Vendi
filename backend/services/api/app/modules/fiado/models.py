"""Modelos del módulo fiado y clientes: el cuaderno (ADR-009/ADR-022).

Una fila de `fiado_creditos` por venta fiada (UN crédito por venta:
`ux_fiado_creditos_venta`). El `saldo_pendiente` SÍ se materializa y se
descuenta en la misma transacción de cada abono; el `CHECK (>= 0)` convierte
el desfase en error, no en dato malo. El saldo por CLIENTE no se guarda: es
`SUM(saldo_pendiente)` de sus créditos `vigente`/`vencido`, calculado en
cada lectura (ADR-022).

`ventas.cliente_id` se queda SIN FK (decisión 4 del plan): la venta no se
rechaza jamás y Postgres no aplica RLS al verificar llaves. Aquí la FK SÍ
existe: el crédito lo crea el servidor, que garantiza la fila del cliente.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import UUID, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, TenantModel

#: Las tres firmadas en ADR-022 más `anulado` (decisión 3: la anulación de
#: la venta fiada anula el crédito; append-only, nunca se borra).
ESTADOS_DE_CREDITO: tuple[str, ...] = ("vigente", "vencido", "saldado", "anulado")

#: Cómo pagó el cliente. El arqueo solo suma `efectivo` (decisión 9);
#: ampliar la lista exige migración, a propósito.
METODOS_DE_PAGO_ABONO: tuple[str, ...] = ("efectivo", "transferencia", "otro")

#: Estados con deuda viva: el saldo por cliente suma solo estos (ADR-022).
ESTADOS_CON_DEUDA: tuple[str, ...] = ("vigente", "vencido")


class Cliente(Base, TenantModel):
    """El vecino del cuaderno (ADR-009): nombre, teléfono para el `wa.me`,
    nota y límite de crédito opcional. Sin más: el CRM avanzado es Fase 3.

    La PK la pone el cliente cuando nace offline (patrón ADR-017, cierre de
    D-10 por adopción). No se borra (decisión 13): el cuaderno lo referencia
    y la historia no se reescribe."""

    __tablename__ = "clientes"
    __table_args__ = (
        Index("ix_clientes_tenant_nombre", "tenant_id", "nombre"),
        CheckConstraint("limite_credito IS NULL OR limite_credito >= 0", name="ck_clientes_limite_no_negativo"),
    )

    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    #: Formato WhatsApp colombiano, solo dígitos (la limpieza es del schema).
    telefono: Mapped[str | None] = mapped_column(String(15), nullable=True)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: NULL = sin cupo declarado: se fía sin tope (el cuaderno nunca dijo que no).
    limite_credito: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FiadoCredito(Base, TenantModel):
    """Un fiado: «Don Carlos me debe 43.000 del martes». Una fila por venta
    fiada; el crédito no duplica las líneas de la venta (ADR-022).

    `saldo_pendiente` se materializa y se descuenta en la misma transacción
    del abono, con el CHECK como red. `fecha_vencimiento` NULL = sin
    recordatorio (ADR-022). `anulado` es el cuarto estado (decisión 3): la
    anulación de la venta fiada lo pone en 0 y lo cierra; un `saldado` o
    `anulado` nunca vuelve a `vigente`."""

    __tablename__ = "fiado_creditos"
    __table_args__ = (
        Index("ix_fiado_creditos_tenant_cliente", "tenant_id", "cliente_id"),
        Index("ix_fiado_creditos_tenant_estado", "tenant_id", "estado", "fecha_vencimiento"),
        UniqueConstraint("venta_id", name="ux_fiado_creditos_venta"),
        CheckConstraint("monto_total > 0", name="ck_fiado_creditos_monto_positivo"),
        CheckConstraint("saldo_pendiente >= 0", name="ck_fiado_creditos_saldo_no_negativo"),
        CheckConstraint("saldo_pendiente <= monto_total", name="ck_fiado_creditos_saldo_acotado"),
        CheckConstraint(
            "estado IN (" + ", ".join(f"'{e}'" for e in ESTADOS_DE_CREDITO) + ")",
            name="ck_fiado_creditos_estado",
        ),
    )

    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False
    )
    venta_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ventas.id", ondelete="RESTRICT"), nullable=False
    )
    #: Centavos enteros (criterio unificado ADR-018).
    monto_total: Mapped[int] = mapped_column(Integer, nullable=False)
    saldo_pendiente: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_vencimiento: Mapped[date | None] = mapped_column(nullable=True)
    estado: Mapped[str] = mapped_column(String(12), nullable=False, default="vigente")


class FiadoAbono(Base, TenantModel):
    """Un pago parcial o total contra el crédito que el usuario tocó
    (ADR-022: nada de aplicarlo al más antiguo automáticamente).

    Append-only: el historial de pagos de ADR-009 es la verdad y no se
    reescribe. La PK es el UUID del cliente (REQUERIDO en el schema: es
    dinero — solo la ancla hace seguro el reintento tras un timeout, y deja
    lista la vía del abono offline, decisión 6). `sesion_caja_id` es la
    sesión que cobró el efectivo (NULL en los demás métodos, decisión 9):
    el arqueo la suma desde aquí, sin duplicar movimientos (ADR-021)."""

    __tablename__ = "fiado_abonos"
    __table_args__ = (
        Index("ix_fiado_abonos_tenant_credito", "tenant_id", "credito_id"),
        Index("ix_fiado_abonos_tenant_sesion", "tenant_id", "sesion_caja_id"),
        CheckConstraint("monto > 0", name="ck_fiado_abonos_monto_positivo"),
        CheckConstraint(
            "metodo_pago IN (" + ", ".join(f"'{m}'" for m in METODOS_DE_PAGO_ABONO) + ")",
            name="ck_fiado_abonos_metodo",
        ),
    )

    credito_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fiado_creditos.id", ondelete="RESTRICT"), nullable=False
    )
    sesion_caja_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caja_sesiones.id", ondelete="RESTRICT"), nullable=True
    )
    monto: Mapped[int] = mapped_column(Integer, nullable=False)
    metodo_pago: Mapped[str] = mapped_column(String(16), nullable=False)
    registrado_por: Mapped[str] = mapped_column(String(120), nullable=False)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
