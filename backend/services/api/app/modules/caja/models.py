"""Modelos del módulo caja: los movimientos manuales (ADR-021).

`caja_sesiones` NO se mueve a este módulo: nació en `ventas/models.py`
(módulo 2, decisión 3 de su plan) y allí se queda — este módulo la importa.
Moverla sería churn sin beneficio, mismo criterio que `movimientos_inventario`
en el plan de inventario.

Las ventas en efectivo y los abonos de fiado NO son filas de esta tabla: el
arqueo los suma desde su tabla de origen (ADR-021). Duplicarlos sería dos
fuentes de verdad para el mismo peso.
"""

from __future__ import annotations

import uuid

from sqlalchemy import UUID, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, TenantModel

#: Ingreso o egreso manual de la gaveta (ADR-021). El signo lo da el tipo;
#: `monto` es estrictamente positivo.
TIPOS_DE_MOVIMIENTO_CAJA: tuple[str, ...] = ("ingreso", "egreso")

#: La lista cerrada corta de ADR-021. Ampliarla exige migración, a propósito:
#: el P&L agrupa los egresos por categoría y una categoría libre sería una
#: categoría por tendero.
CATEGORIAS_DE_MOVIMIENTO: tuple[str, ...] = ("arriendo", "servicios", "retiro_dueno", "otro")


class CajaMovimiento(Base, TenantModel):
    """Un ingreso o egreso manual de la gaveta (ADR-021). Append-only por
    modelo: un error se corrige con otro movimiento, nunca editando éste.

    La PK es el UUID del cliente (REQUERIDO en el schema, decisión 6: es
    dinero — solo la ancla hace seguro el reintento tras un timeout)."""

    __tablename__ = "caja_movimientos"
    __table_args__ = (
        Index("ix_caja_movimientos_tenant_sesion", "tenant_id", "sesion_caja_id"),
        Index("ix_caja_movimientos_tenant_created", "tenant_id", "created_at"),
        CheckConstraint("tipo IN ('ingreso', 'egreso')", name="ck_caja_movimientos_tipo"),
        CheckConstraint(
            "categoria IN ('arriendo', 'servicios', 'retiro_dueno', 'otro')",
            name="ck_caja_movimientos_categoria",
        ),
        CheckConstraint("monto > 0", name="ck_caja_movimientos_monto_positivo"),
    )

    sesion_caja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caja_sesiones.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(8), nullable=False)
    categoria: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Dinero en centavos enteros, estrictamente positivo (el signo es el tipo).
    monto: Mapped[int] = mapped_column(Integer, nullable=False)
    #: La justificación obligatoria (decisión 2): un movimiento sin motivo es
    #: un desfalco con buenos modales.
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    registrado_por: Mapped[str] = mapped_column(String(120), nullable=False)
