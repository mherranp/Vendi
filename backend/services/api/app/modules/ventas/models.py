"""Modelos del módulo ventas y del soporte de sync offline (ADR-017/018/020/021).

Cinco tablas, todas de negocio (policy `tenant_isolation` puesta por la
migración 0005):

- `Dispositivo`: el registro de dispositivos que sincronizan (ADR-017).
- `CajaSesion`: la sesión de caja abierta por tienda (ADR-021; la tabla se
  crea aquí por la decisión 3 del plan; el arqueo es del módulo de caja).
- `Venta`: el hecho append-only con PK del cliente (ADR-018). Sin
  `SoftDeleteMixin`: no hay borrado, hay anulación (`completada → anulada`,
  la única mutación permitida).
- `VentaItem`: las líneas con el precio congelado en el momento de la venta.
- `MovimientoInventario`: el libro de stock por deltas (ADR-020; la tabla se
  crea aquí por la decisión 1 del plan; alertas y compras son del módulo 3).

La doble verdad temporal de ADR-018 vive en `Venta`: `creada_en_cliente` es
la marca del reloj del dispositivo (dato del ticket; puede mentir y no pasa
nada, porque NADIE la usa para ordenar) y `recibida_en` es la marca del
servidor (la única verdad temporal del sistema: reportes, P&L y forecast
suman por ella).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    UUID,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, TenantModel

#: Los dos estados de la venta append-only (ADR-018). La transición permitida
#: es exactamente una: completada → anulada.
ESTADOS_DE_VENTA: tuple[str, ...] = ("completada", "anulada")

#: Los medios de pago del MVP. La columna es texto libre («otros medios
#: registrados como dato», ADR-018); el conjunto cerrado lo aplica el schema.
MEDIOS_DE_PAGO: tuple[str, ...] = ("efectivo", "fiado")

#: Los cinco tipos del libro (ADR-020). Este módulo emite `venta` (el
#: descuento del alta) y `anulacion` (la reposición, BUG-3 del QA: con el
#: tipo `venta` la reposición chocaba con el movimiento original cuando el
#: id de la operación de anulación era el id de la venta); `compra`,
#: `ajuste` y `merma` son del módulo de inventario — la constraint ya los
#: admite para que no haga falta migrar nada entonces.
TIPOS_DE_MOVIMIENTO: tuple[str, ...] = ("venta", "compra", "ajuste", "merma", "anulacion")


class Dispositivo(Base, TenantModel):
    """Un dispositivo del negocio que sincroniza su cola (ADR-017).

    `ultima_secuencia` y `ultima_sync` son observabilidad (¿cuándo subió su
    último lote este equipo?), nunca árbitro de nada: la idempotencia la da
    la PK que el cliente puso en cada fila de dominio.
    """

    __tablename__ = "dispositivos"

    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    ultima_secuencia: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    ultima_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CajaSesion(Base, TenantModel):
    """Un turno de caja del negocio (ADR-021). UNA abierta por tienda: lo
    garantiza `ux_caja_sesion_abierta`, no el código."""

    __tablename__ = "caja_sesiones"
    __table_args__ = (
        Index(
            "ux_caja_sesion_abierta",
            "tenant_id",
            unique=True,
            postgresql_where=text("estado = 'abierta'"),
        ),
        CheckConstraint("estado IN ('abierta', 'cerrada')", name="ck_caja_sesiones_estado"),
        CheckConstraint("base_inicial >= 0", name="ck_caja_sesiones_base_no_negativa"),
    )

    abierta_por: Mapped[str] = mapped_column(String(120), nullable=False)
    abierta_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    base_inicial: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    cerrada_por: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    efectivo_esperado: Mapped[int | None] = mapped_column(Integer, nullable=True)
    efectivo_contado: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diferencia: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estado: Mapped[str] = mapped_column(String(16), default="abierta", server_default="abierta", nullable=False)


class Venta(Base, TenantModel):
    """Un hecho de venta, creado en el dispositivo y aceptado tal cual por el
    servidor (ADR-018). Append-only: jamás un UPDATE de ítems ni totales."""

    __tablename__ = "ventas"
    __table_args__ = (
        # El número del ticket: único por negocio Y dispositivo (multi-caja).
        Index("ux_ventas_consecutivo", "tenant_id", "dispositivo_id", "consecutivo_local", unique=True),
        # Predicado RLS como Index Cond + reportes por la marca del servidor.
        Index("ix_ventas_tenant_recibida", "tenant_id", "recibida_en"),
        CheckConstraint("estado IN ('completada', 'anulada')", name="ck_ventas_estado"),
        CheckConstraint("consecutivo_local > 0", name="ck_ventas_consecutivo_positivo"),
        CheckConstraint("total_centavos >= 0", name="ck_ventas_total_no_negativo"),
        CheckConstraint("secuencia_dispositivo > 0", name="ck_ventas_secuencia_positiva"),
    )

    dispositivo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dispositivos.id", ondelete="RESTRICT"), nullable=False
    )
    #: NOT NULL (decisión 13 del plan): el sync siempre resuelve a la sesión
    #: abierta del tenant o abre una implícita (ADR-018).
    sesion_caja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caja_sesiones.id", ondelete="RESTRICT"), nullable=False
    )
    #: El número que ve el tendero y va en el ticket. No es único por negocio:
    #: dos cajas repiten números (ADR-018, consecuencia firmada).
    consecutivo_local: Mapped[int] = mapped_column(Integer, nullable=False)
    estado: Mapped[str] = mapped_column(String(16), default="completada", server_default="completada", nullable=False)
    #: Texto: «efectivo | fiado | otros medios registrados como dato» (ADR-018).
    medio_pago: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Dinero en centavos enteros, jamás flotante (criterio unificado ADR-018).
    total_centavos: Mapped[int] = mapped_column(Integer, nullable=False)
    #: NULL salvo fiado. Sin FK: `clientes` es del módulo de fiado (decisión 8).
    cliente_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: La marca del reloj del dispositivo: dato del ticket, NO orden. Puede
    #: mentir (reloj manipulado) y el sistema no se entera ni le importa.
    creada_en_cliente: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: La marca del servidor: la única verdad temporal del sistema.
    recibida_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    #: La posición de esta venta en la cola FIFO local del dispositivo.
    secuencia_dispositivo: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Venta {self.id} #{self.consecutivo_local} {self.estado}>"


class VentaItem(Base, TenantModel):
    """Una línea de venta. El precio se congela aquí: el ticket no cambia
    aunque el catálogo cambie después (ADR-018)."""

    __tablename__ = "ventas_items"
    __table_args__ = (
        Index("ix_ventas_items_tenant_venta", "tenant_id", "venta_id"),
        CheckConstraint("cantidad > 0", name="ck_ventas_items_cantidad_positiva"),
        CheckConstraint("precio_unitario_centavos >= 0", name="ck_ventas_items_precio_no_negativo"),
    )

    venta_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ventas.id", ondelete="RESTRICT"), nullable=False
    )
    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False
    )
    #: Decimal (granel): el fruver se vende a 0,350 kg.
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    precio_unitario_centavos: Mapped[int] = mapped_column(Integer, nullable=False)


class MovimientoInventario(Base, TenantModel):
    """Una fila del libro de stock (ADR-020). Nunca se edita ni se borra: un
    error se corrige con otro movimiento. La venta descuenta (cantidad
    negativa, `tipo='venta'`); su anulación repone (positiva,
    `tipo='anulacion'`, con `referencia_id` = el id de la operación de
    anulación, no el de la venta: la venta ya tiene sus movimientos). El
    índice único admite que ambos compartan `referencia_id` — una anulación
    cuyo id de operación ES el id de la venta— porque difieren en `tipo`."""

    __tablename__ = "movimientos_inventario"
    __table_args__ = (
        # La idempotencia del sync con constraint, no con lógica (ADR-020).
        # `producto_id` va en la clave porque una venta tiene varios ítems
        # (decisión 2 del plan).
        Index("ux_movimientos_origen", "tenant_id", "tipo", "referencia_id", "producto_id", unique=True),
        Index("ix_movimientos_tenant_producto", "tenant_id", "producto_id"),
        CheckConstraint(
            "tipo IN (" + ", ".join(f"'{t}'" for t in TIPOS_DE_MOVIMIENTO) + ")",
            name="ck_movimientos_tipo",
        ),
        CheckConstraint("cantidad <> 0", name="ck_movimientos_cantidad_no_cero"),
    )

    tipo: Mapped[str] = mapped_column(String(16), nullable=False)
    #: NUMERIC con signo: la venta descuenta, la compra suma, la anulación repone.
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    #: El UUID de la venta (o de la operación de anulación) que causó la fila.
    referencia_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False
    )
