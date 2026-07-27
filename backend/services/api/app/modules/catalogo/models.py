"""Modelo del catálogo: una fila = un ítem vendible (ADR-019).

`Producto` hereda `TenantModel` (PK UUID + `tenant_id` + timestamps) y
`SoftDeleteMixin` (`deleted_at`): es tabla DE NEGOCIO, con policy
`tenant_isolation` puesta por la migración 0004, y borrado lógico porque el
historial de ventas referencia productos que ya no se venden.

Dos cosas que este archivo NO hace, a propósito:

- No mueve stock. `stock_actual` es una proyección del libro de movimientos
  de inventario (ADR-020) y `ultimo_costo` lo actualizan las compras. Aquí
  solo se declaran; el único campo de stock editable por el catálogo es
  `stock_minimo` (el umbral de las alertas).
- No declara el `id` como autogenerado por el cliente ni por el servidor de
  forma exclusiva: `TenantModel` ya deja ambos caminos (`default` de Python y
  `server_default`), y el servicio acepta el UUID que traiga el cliente
  (ADR-017: es lo que hace al sync idempotente de raíz).

El índice único del EAN se declara aquí (para que el metadata sea fiel a la
base) y se crea en la migración (para que exista de verdad); las dos
definiciones deben coincidir y `test_catalogo_modelo.py` vigila ésta.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import UUID, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, SoftDeleteMixin, TenantModel

#: Las cinco unidades del ADR-019. Se guardan como texto con CHECK, no como
#: ENUM de Postgres: el conjunto es corto y estable, y cambiar un enum es DDL
#: con sus propias reglas (mismo criterio que `estado` en `tenants`).
UNIDADES_DE_MEDIDA: tuple[str, ...] = ("unidad", "kg", "g", "lt", "ml")

#: Las tres tarifas de IVA vigentes en Colombia. Cuando llegue la DIAN (Fase
#: 2) esto se amplía, no se reescribe: `iva_pct` ya está en el sitio correcto.
TARIFAS_DE_IVA: tuple[Decimal, ...] = (Decimal("0"), Decimal("5"), Decimal("19"))


class Producto(Base, TenantModel, SoftDeleteMixin):
    """Un ítem vendible de un negocio. La variante es una fila más (`padre_id`)."""

    __tablename__ = "productos"
    __table_args__ = (
        # Sustituye al `ix_productos_tenant_id` que `TenantModel` declara por
        # defecto: éste también empieza por `tenant_id` (cumple la regla del
        # predicado RLS) y además ordena el listado del POS por nombre.
        Index("ix_productos_tenant_nombre", "tenant_id", "nombre"),
        # El EAN es único POR NEGOCIO y solo cuando existe. Sin el WHERE,
        # todos los NULL chocarían entre sí y un negocio solo podría tener UN
        # producto sin código de barras.
        Index(
            "ux_productos_ean",
            "tenant_id",
            "codigo_barras",
            unique=True,
            postgresql_where=text("codigo_barras IS NOT NULL"),
        ),
        CheckConstraint(
            "unidad_medida IN (" + ", ".join(f"'{u}'" for u in UNIDADES_DE_MEDIDA) + ")",
            name="ck_productos_unidad_medida",
        ),
        CheckConstraint("iva_pct IN (0, 5, 19)", name="ck_productos_iva_pct"),
        CheckConstraint("precio_venta >= 0", name="ck_productos_precio_no_negativo"),
        CheckConstraint("ultimo_costo >= 0", name="ck_productos_costo_no_negativo"),
    )

    #: La variante apunta al producto base. Postgres NO aplica RLS al
    #: verificar llaves foráneas, así que la pertenencia del padre al mismo
    #: negocio la valida el servicio, no la base.
    padre_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("productos.id", ondelete="RESTRICT"),
        nullable=True,
    )
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    #: Opcional: gran parte del surtido de barrio no tiene EAN (granel, huevo
    #: por unidad). Único por negocio cuando existe (ver `ux_productos_ean`).
    codigo_barras: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Texto libre, no tabla: la clasificación ABC es un cálculo sobre ventas,
    #: no una taxonomía que mantener (ADR-019).
    categoria: Mapped[str | None] = mapped_column(Text, nullable=True)
    unidad_medida: Mapped[str] = mapped_column(String(8), default="unidad", server_default="unidad", nullable=False)
    #: Dinero en centavos enteros, jamás flotante (criterio unificado ADR-018).
    precio_venta: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    #: Lo actualiza cada compra registrada (ADR-020). El catálogo solo lo lee.
    ultimo_costo: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    iva_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), server_default="0", nullable=False)
    #: Proyección del libro de movimientos. Puede quedar NEGATIVO y es un
    #: estado legítimo (ADR-020): la tienda ya vendió físicamente esa unidad.
    stock_actual: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal("0"), server_default="0", nullable=False
    )
    stock_minimo: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal("0"), server_default="0", nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Producto {self.id} {self.nombre!r}>"
