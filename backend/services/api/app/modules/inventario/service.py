"""Servicio de inventario: compras, ajustes y estado de stock (ADR-020).

## RLS hace el aislamiento; el servicio NO filtra por `tenant_id` a mano

Todo corre en la sesión de tenant (`vendi_app` + GUC `vendi.tenant_id`): la
policy `tenant_isolation` acota lecturas y escrituras, y el `WITH CHECK`
rechaza un `tenant_id` inyectado. Los schemas llevan `extra="forbid"`, así
que el payload ni siquiera acepta el campo.

## ONLINE, no sync (decisión 3)

Compras y ajustes son gestos síncronos del usuario con respuesta HTTP
(201/404/409/422), no operaciones de la cola del dispositivo. El ajuste es
online-obligatorio por ADR-020: su delta se calcula contra el `stock_actual`
del servidor EN ESTE MOMENTO, con la fila del producto bloqueada FOR UPDATE.
Un ajuste offline llegaría con un delta calculado contra un stock viejo y
corrompería el contador de forma no conmutativa.

## Idempotencia: la fila es la prueba (ADR-017)

La compra acepta el UUID del cliente como PK (opcional, como el catálogo); el
ajuste lo EXIGE (decisión 4: la merma es un delta relativo y solo la ancla
hace seguro su reintento). El ajuste se graba SIEMPRE, incluso con delta
cero (decisión 5): es la prueba de idempotencia del conteo que cuadró. La
red final la ponen las constraints (`compras`/`ajustes_inventario` pkey,
`ux_movimientos_origen`).

## Los eventos viajan en la transacción del llamante

El servicio hace `flush` pero NUNCA `commit`: confirma la dependencia
`sesion_de_tenant` al final del request (o el test), y con ella la compra,
los movimientos, el stock y los eventos del outbox — la garantía del patrón.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

import structlog
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalogo.models import Producto
from app.modules.catalogo.schemas import TOPE_PRECIO
from app.modules.inventario.models import AjusteInventario, Compra, CompraItem
from app.modules.inventario.schemas import AjusteCreado, AjusteCrear, CompraCrear, StockSalida
from app.modules.inventario.stock import aplicar_movimiento, nivel_de_stock
from vendi_core.errors.domain import ConflictError, NotFoundError, ValidationError
from vendi_core.events.service import DomainEventService

logger = structlog.get_logger()

#: Campos cuya divergencia convierte un reintento de ajuste en 409 (mismo
#: criterio que `_CAMPOS_DEL_HECHO` de ventas): si alguno difiere, NO es un
#: reintento — es otro ajuste con el mismo id, y alguien tiene que mirarlo.
_CAMPOS_DEL_AJUSTE = ("tipo", "producto_id", "stock_contado", "cantidad", "motivo")


class InventarioService:
    """Operaciones de inventario de UN negocio: el del GUC de la sesión."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: str):
        self._session = session
        self._tenant_id = tenant_id
        self._actor_id = actor_id

    # --- Compras ----------------------------------------------------------------

    async def registrar_compra(self, datos: CompraCrear) -> Compra:
        """Registra la compra y, en la MISMA transacción: sus ítems, un
        movimiento `compra` por línea, la proyección `stock_actual` y
        `ultimo_costo` de cada producto, y el evento `compra.registrada`
        (ADR-020). Idempotente por el UUID del cliente: reenviar la MISMA
        compra devuelve la existente sin duplicar fila, stock ni evento;
        reenviar el mismo `id` con payload distinto es 409
        `compra_id_divergente` (cierre de D-19: la idempotencia no es ciega
        a la divergencia, mismo criterio que ajustes y ventas)."""
        if datos.id is not None:
            existente = await self._session.get(Compra, datos.id)
            if existente is not None:
                return await self._reintento_de_compra(existente, datos)

        # El total lo calcula el servidor por línea (decisión 7): la línea se
        # cuantiza a centavos enteros y el total es la suma de las líneas.
        total = 0
        for item in datos.items:
            linea = (item.cantidad * item.costo_unitario_centavos).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            total += int(linea)
        if total > TOPE_PRECIO:
            # Cada línea cabe por sí sola (cantidad ≤ TOPE_STOCK, costo ≤
            # TOPE_PRECIO), pero la SUMA no: `total_centavos` es un `Integer`
            # y sin esta cota el INSERT reventaba con un `DataError` → 500 en
            # vez del 422 que corresponde a una entrada rechazable.
            raise ValidationError(
                "El total de la compra no cabe en el sistema. Divide la factura en varias compras.",
                code="total_fuera_de_rango",
            )

        compra = Compra(
            tenant_id=self._tenant_id,
            proveedor_nombre=datos.proveedor_nombre,
            fecha=datos.fecha or datetime.now(UTC).date(),
            observaciones=datos.observaciones,
            total_centavos=total,
        )
        if datos.id is not None:
            compra.id = datos.id
        self._session.add(compra)
        await self._flush_traduciendo_integridad()

        for item in sorted(datos.items, key=lambda i: i.producto_id):
            # Ordenados por producto_id (decisión 9): dos compras concurrentes
            # con productos solapados adquieren los bloqueos en el MISMO orden
            # y no se interbloquean. El FOR UPDATE se toma ANTES de insertar el
            # ítem: el INSERT de la FK `compra_items → productos` toma un FOR
            # KEY SHARE sobre la fila del producto, y adquirir ese KEY SHARE
            # antes del FOR UPDATE es una escalada de bloqueo que interbloquea
            # dos compras concurrentes del MISMO producto (A tiene KEY SHARE y
            # pide FOR UPDATE; B tiene KEY SHARE y pide FOR UPDATE).
            producto = await self._producto_bloqueado(item.producto_id)
            self._session.add(
                CompraItem(
                    tenant_id=self._tenant_id,
                    compra_id=compra.id,
                    producto_id=item.producto_id,
                    cantidad=item.cantidad,
                    costo_unitario_centavos=item.costo_unitario_centavos,
                )
            )
            await aplicar_movimiento(
                self._session,
                tenant_id=self._tenant_id,
                producto=producto,
                delta=item.cantidad,
                tipo="compra",
                referencia_id=compra.id,
            )
            # Lo que el P&L costea (ADR-006/020): el costo de la ÚLTIMA compra.
            producto.ultimo_costo = item.costo_unitario_centavos

        await DomainEventService.emit(
            self._session,
            tenant_id=self._tenant_id,
            event_name="compra.registrada",
            resource_type="compra",
            resource_id=str(compra.id),
            data={
                "compra_id": str(compra.id),
                "proveedor_nombre": compra.proveedor_nombre,
                "fecha": compra.fecha.isoformat(),
                "total_centavos": compra.total_centavos,
                "items": [
                    {
                        "producto_id": str(i.producto_id),
                        "cantidad": str(i.cantidad),
                        "costo_unitario_centavos": i.costo_unitario_centavos,
                    }
                    for i in datos.items
                ],
            },
        )
        logger.info("compra_registrada", compra_id=str(compra.id), total_centavos=compra.total_centavos)
        return compra

    async def obtener_compra(self, compra_id: uuid.UUID) -> tuple[Compra, list[CompraItem]]:
        compra = await self._session.get(Compra, compra_id)
        if compra is None:
            # Un id de otro negocio da el mismo 404 que uno inexistente: la
            # RLS lo hace invisible y no hay nada que filtrar.
            raise NotFoundError("La compra no existe.", code="compra_no_encontrada")
        items = (
            (await self._session.execute(select(CompraItem).where(CompraItem.compra_id == compra.id))).scalars().all()
        )
        return compra, list(items)

    async def listar_compras(self, *, skip: int = 0, limit: int = 25) -> tuple[list[Compra], int]:
        total = (await self._session.execute(select(func.count()).select_from(Compra))).scalar_one()
        filas = (
            (
                await self._session.execute(
                    select(Compra).order_by(Compra.created_at.desc(), Compra.id).offset(skip).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(filas), int(total)

    # --- Ajustes y mermas ----------------------------------------------------------

    async def registrar_ajuste(self, datos: AjusteCrear) -> AjusteCreado:
        """Ajuste por conteo o merma, ONLINE (ADR-020). El delta se calcula
        contra el stock del servidor con la fila bloqueada FOR UPDATE:
        `stock_contado - stock_actual` en el ajuste; `-cantidad` en la merma.

        La fila del ajuste se graba SIEMPRE (incluso con delta cero: es la
        prueba de idempotencia, decisión 5). El movimiento del libro solo se
        escribe si delta ≠ 0 (`ck_movimientos_cantidad_no_cero`), con
        `referencia_id = ajuste.id`. Si el delta cruza un umbral hacia abajo,
        `aplicar_movimiento` emite la alerta en esta misma transacción."""
        producto = await self._producto_bloqueado(datos.producto_id)

        existente = await self._session.get(AjusteInventario, datos.id)
        if existente is not None:
            return self._reintento_de_ajuste(existente, datos, producto)

        if datos.tipo == "ajuste":
            assert datos.stock_contado is not None  # lo garantiza el schema
            delta = datos.stock_contado - producto.stock_actual
        else:
            assert datos.cantidad is not None
            delta = -datos.cantidad

        ajuste = AjusteInventario(
            id=datos.id,
            tenant_id=self._tenant_id,
            producto_id=datos.producto_id,
            tipo=datos.tipo,
            stock_contado=datos.stock_contado,
            cantidad=datos.cantidad,
            delta=delta,
            motivo=datos.motivo,
            aplicado_por=self._actor_id,
            stock_resultante=producto.stock_actual + delta,
        )
        self._session.add(ajuste)
        if delta != 0:
            await aplicar_movimiento(
                self._session,
                tenant_id=self._tenant_id,
                producto=producto,
                delta=delta,
                tipo=datos.tipo,
                referencia_id=ajuste.id,
            )
        await self._flush_traduciendo_integridad()
        logger.info("ajuste_registrado", ajuste_id=str(ajuste.id), tipo=ajuste.tipo, delta=str(delta))
        return self._salida(ajuste, producto)

    async def listar_ajustes(self, *, skip: int = 0, limit: int = 25) -> tuple[list[AjusteInventario], int]:
        total = (await self._session.execute(select(func.count()).select_from(AjusteInventario))).scalar_one()
        filas = (
            (
                await self._session.execute(
                    select(AjusteInventario)
                    .order_by(AjusteInventario.created_at.desc(), AjusteInventario.id)
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(filas), int(total)

    # --- Estado de stock ------------------------------------------------------------

    async def estado_stock(
        self, *, skip: int = 0, limit: int = 50, solo_alertas: bool = False
    ) -> tuple[list[StockSalida], int]:
        """El stock de cada producto con su nivel derivado (decisión 2: una
        sola función define el umbral — la misma que dispara la alerta).

        `solo_alertas=True` filtra en SQL lo que la app muestra como lista de
        pendientes: agotados (`stock <= 0`) o por debajo del mínimo. El orden
        es el de urgencia: agotados primero, luego por déficit."""
        base = select(Producto).where(Producto.deleted_at.is_(None))
        conteo = select(func.count()).select_from(Producto).where(Producto.deleted_at.is_(None))
        if solo_alertas:
            en_alerta = or_(
                Producto.stock_actual <= 0,
                and_(Producto.stock_minimo > 0, Producto.stock_actual < Producto.stock_minimo),
            )
            base = base.where(en_alerta)
            conteo = conteo.where(en_alerta)
        total = (await self._session.execute(conteo)).scalar_one()
        filas = (
            (
                await self._session.execute(
                    base.order_by(
                        (Producto.stock_actual <= 0).desc(),
                        (Producto.stock_actual - Producto.stock_minimo).asc(),
                        Producto.nombre,
                    )
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return (
            [
                StockSalida(
                    producto_id=f.id,
                    nombre=f.nombre,
                    stock_actual=f.stock_actual,
                    stock_minimo=f.stock_minimo,
                    nivel=nivel_de_stock(f.stock_actual, f.stock_minimo),
                )
                for f in filas
            ],
            int(total),
        )

    # --- Internas ----------------------------------------------------------------

    async def _producto_bloqueado(self, producto_id: uuid.UUID) -> Producto:
        """SELECT ... FOR UPDATE sobre la fila del producto: el read-modify-write
        de `stock_actual` y la comparación de nivel antes/después solo son
        seguros con la fila bloqueada hasta el commit (el lost update que el
        fix `49553da` cerró en ventas). Un producto de otro negocio es
        invisible por RLS y un dado de baja no se reabastece: mismo 422."""
        producto = await self._session.get(Producto, producto_id, with_for_update=True)
        if producto is None or producto.deleted_at is not None:
            raise ValidationError(
                "Uno de los productos no existe en tu negocio.",
                code="producto_no_encontrado",
                details={"producto_id": str(producto_id)},
            )
        return producto

    async def _reintento_de_compra(self, existente: Compra, datos: CompraCrear) -> Compra:
        """El id ya existe: ¿es la MISMA compra? Payload idéntico → se
        devuelve la existente (el reintento legítimo, sin duplicar stock ni
        evento). Cualquier campo distinto → 409 con los campos que difieren
        (cierre de D-19, espejo de `_reintento_de_ajuste`): jamás un no-op
        silencioso cuando hay stock y `ultimo_costo` de por medio.

        `fecha` solo se compara cuando el cliente la envía: si vino en NULL
        la puso el servidor y el reintento no puede reproducirla — compararla
        contra NULL marcaría divergente todo reintento legítimo de una compra
        sin fecha. El total no se compara: lo deriva el servidor de los ítems."""
        divergentes: list[str] = []
        if existente.proveedor_nombre != datos.proveedor_nombre:
            divergentes.append("proveedor_nombre")
        if datos.fecha is not None and existente.fecha != datos.fecha:
            divergentes.append("fecha")
        if existente.observaciones != datos.observaciones:
            divergentes.append("observaciones")
        # Comparación normalizada, como en ventas: la cantidad guardada viene
        # de NUMERIC(14,3) (10.000) y la enviada del schema (10) — Decimal las
        # iguala. El orden no importa y el schema prohíbe producto repetido.
        guardados = (
            (await self._session.execute(select(CompraItem).where(CompraItem.compra_id == existente.id)))
            .scalars()
            .all()
        )
        items_guardados = {(i.producto_id, i.cantidad, i.costo_unitario_centavos) for i in guardados}
        items_enviados = {(i.producto_id, i.cantidad, i.costo_unitario_centavos) for i in datos.items}
        if items_guardados != items_enviados:
            divergentes.append("items")
        if divergentes:
            raise ConflictError(
                "Ese id de compra ya existe con datos distintos. El servidor conserva la primera versión.",
                code="compra_id_divergente",
                details={"campos": divergentes},
            )
        logger.info("compra_registrada_idempotente", compra_id=str(existente.id))
        return existente

    def _reintento_de_ajuste(self, existente: AjusteInventario, datos: AjusteCrear, producto: Producto) -> AjusteCreado:
        """El id ya existe: ¿es el MISMO ajuste? Payload idéntico → se
        devuelve lo que se respondió la primera vez (el reintento legítimo,
        sin mover stock otra vez). Cualquier campo distinto → 409 con los
        campos que difieren (lección de divergencia del QA): jamás un no-op
        silencioso cuando hay stock de por medio."""
        divergentes: list[str] = []
        for campo in _CAMPOS_DEL_AJUSTE:
            guardado = getattr(existente, campo)
            enviado = getattr(datos, campo)
            if str(guardado) != str(enviado) and not (
                isinstance(guardado, Decimal) and isinstance(enviado, Decimal) and guardado == enviado
            ):
                divergentes.append(campo)
        if divergentes:
            raise ConflictError(
                "Ese id de ajuste ya existe con datos distintos. El servidor conserva la primera versión.",
                code="ajuste_id_divergente",
                details={"campos": divergentes},
            )
        logger.info("ajuste_registrado_idempotente", ajuste_id=str(existente.id))
        return self._salida(existente, producto)

    @staticmethod
    def _salida(ajuste: AjusteInventario, producto: Producto) -> AjusteCreado:
        return AjusteCreado(
            id=ajuste.id,
            tipo=ajuste.tipo,
            producto_id=ajuste.producto_id,
            stock_contado=ajuste.stock_contado,
            cantidad=ajuste.cantidad,
            delta=ajuste.delta,
            motivo=ajuste.motivo,
            aplicado_por=ajuste.aplicado_por,
            stock_resultante=ajuste.stock_resultante,
            created_at=ajuste.created_at,
            nivel=nivel_de_stock(ajuste.stock_resultante, producto.stock_minimo),
        )

    async def _flush_traduciendo_integridad(self) -> None:
        """Las constraints son las de verdad; el servicio traduce su violación
        al sobre de errores de la API. Tras un `IntegrityError` la transacción
        queda abortada: quien llama (la dependencia o el test) hace rollback
        al propagar."""
        try:
            await self._session.flush()
        except IntegrityError as exc:
            detalle = str(exc)
            if "compras_pkey" in detalle:
                # El id venía del cliente y choca con una fila que la RLS no
                # le deja ver (de otro negocio) o con una carrera de dos altas.
                raise ConflictError("Ese id de compra ya existe.", code="compra_id_duplicado") from exc
            if "ajustes_inventario_pkey" in detalle:
                # Carrera de dos PRIMEROS intentos con el mismo id de cliente
                # (el reintento normal lo resuelve `_reintento_de_ajuste`
                # antes de llegar aquí). El perdedor recibe un 409 tipado, no
                # el 500 del IntegrityError.
                raise ConflictError("Ese id de ajuste ya existe.", code="ajuste_id_divergente") from exc
            raise
