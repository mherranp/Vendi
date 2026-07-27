"""Modelos del módulo inventario: compras y ajustes (ADR-020, decisiones 5-7 del plan).

Tres tablas, todas de negocio (policy `tenant_isolation` puesta por la
migración 0007):

- `Compra`: el registro simple de una compra a proveedor. `proveedor_nombre`
  es texto libre (la factura es un papel; NO hay tabla de proveedores —
  YAGNI firmado en ADR-020). `total_centavos` lo calcula el servidor por
  línea: nunca viene del cliente. Sin `SoftDeleteMixin`: una compra
  equivocada no se borra ni se edita, se corrige con un ajuste — el libro
  es inmutable.
- `CompraItem`: las líneas con el costo de ESTA compra. El índice por
  producto es el insumo de las futuras sugerencias de reabastecimiento.
- `AjusteInventario`: el ajuste de conteo o la merma como hecho, con su
  `motivo` obligatorio. Su PK es el UUID del cliente (la fila es la prueba
  de idempotencia incluso con delta cero, decisión 5); el movimiento del
  libro —cuando lo hay— la referencia.

El libro `movimientos_inventario` NO se mueve a este módulo: nació en
`ventas/models.py` (módulo 2) y allí se queda; `inventario/stock.py` lo
importa. Moverlo sería churn sin beneficio.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import UUID, CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, TenantModel

#: Las dos operaciones online del inventario (ADR-020). El ajuste es un
#: conteo absoluto; la merma, una cantidad que se dañó. La forma de cada una
#: la hace cumplir `ck_ajustes_forma`.
TIPOS_DE_AJUSTE: tuple[str, ...] = ("ajuste", "merma")


class Compra(Base, TenantModel):
    """Una compra a proveedor. Append-only como el resto del inventario: la
    corrección es un ajuste, nunca un UPDATE."""

    __tablename__ = "compras"
    __table_args__ = (
        Index("ix_compras_tenant_fecha", "tenant_id", "fecha"),
        CheckConstraint("total_centavos >= 0", name="ck_compras_total_no_negativo"),
    )

    #: Texto libre (ADR-020): «Distribuidora La 33», «el de las gaseosas».
    proveedor_nombre: Mapped[str] = mapped_column(Text, nullable=False)
    #: El dato de la factura de papel; el defecto es la fecha del servidor.
    fecha: Mapped[date] = mapped_column(Date, server_default=func.current_date(), nullable=False)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Σ por línea, calculado en el servidor (decisión 7). Centavos enteros.
    total_centavos: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Compra {self.id} {self.proveedor_nombre!r} {self.total_centavos}>"


class CompraItem(Base, TenantModel):
    """Una línea de compra. El costo se congela aquí: es lo que ESTA compra
    costó, y al confirmarse actualiza `ultimo_costo` del producto (ADR-020)."""

    __tablename__ = "compra_items"
    __table_args__ = (
        Index("ix_compra_items_tenant_compra", "tenant_id", "compra_id"),
        Index("ix_compra_items_tenant_producto", "tenant_id", "producto_id"),
        CheckConstraint("cantidad > 0", name="ck_compra_items_cantidad_positiva"),
        CheckConstraint("costo_unitario_centavos >= 0", name="ck_compra_items_costo_no_negativo"),
    )

    compra_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compras.id", ondelete="RESTRICT"), nullable=False
    )
    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False
    )
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    costo_unitario_centavos: Mapped[int] = mapped_column(Integer, nullable=False)


class AjusteInventario(Base, TenantModel):
    """Un ajuste por conteo («conté 14, el sistema dice 16») o una merma
    («se dañaron 3 kg»). ONLINE obligatorio (ADR-020): su delta se calcula
    contra el stock del servidor en el momento, con la fila bloqueada.

    La PK es el UUID del cliente (decisión 4: REQUERIDO, porque la merma es
    un delta relativo y solo la ancla la hace segura ante reintentos). La
    fila se crea SIEMPRE, incluso cuando `delta` es 0 y no hay movimiento
    que escribir: es la prueba de idempotencia (decisión 5)."""

    __tablename__ = "ajustes_inventario"
    __table_args__ = (
        Index("ix_ajustes_tenant_producto", "tenant_id", "producto_id"),
        CheckConstraint("tipo IN ('ajuste', 'merma')", name="ck_ajustes_tipo"),
        CheckConstraint(
            "(tipo = 'ajuste' AND stock_contado IS NOT NULL AND cantidad IS NULL) OR "
            "(tipo = 'merma' AND cantidad IS NOT NULL AND stock_contado IS NULL)",
            name="ck_ajustes_forma",
        ),
        CheckConstraint("cantidad IS NULL OR cantidad > 0", name="ck_ajustes_cantidad_positiva"),
        CheckConstraint("stock_contado IS NULL OR stock_contado >= 0", name="ck_ajustes_conteo_no_negativo"),
    )

    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(8), nullable=False)
    #: El conteo físico (solo ajustes). NULL en mermas.
    stock_contado: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    #: Lo que se dañó (solo mermas). NULL en ajustes.
    cantidad: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    #: Lo aplicado contra el stock del servidor: `stock_contado - stock_actual`
    #: en el ajuste; `-cantidad` en la merma. Admite 0 (conteo que cuadra).
    delta: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    #: La justificación obligatoria: un ajuste sin motivo es un desfalco con
    #: buenos modales.
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    aplicado_por: Mapped[str] = mapped_column(String(120), nullable=False)
    #: El stock tras aplicar: lo que se responde también al reintento.
    stock_resultante: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
