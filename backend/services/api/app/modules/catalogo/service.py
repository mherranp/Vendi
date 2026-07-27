"""Servicio del catálogo: CRUD de productos sobre la sesión de tenant.

## RLS hace el aislamiento; el servicio NO filtra por `tenant_id` a mano

Toda consulta de este servicio corre en la sesión de tenant (`vendi_app` +
GUC `vendi.tenant_id`), así que la policy `tenant_isolation` es la que acota
lecturas y escrituras. Escribir `WHERE tenant_id = ...` a mano sería
redundante y —peor— daría la falsa sensación de que el aislamiento depende
del código de negocio. Lo que sí se filtra aquí es `deleted_at IS NULL`: eso
es semántica de negocio (borrado lógico), no aislamiento.

## Los eventos viajan en la transacción del llamante

`DomainEventService.emit` encola en `outbox_messages` dentro de la sesión
recibida. El servicio hace `flush` pero NUNCA `commit`: el commit lo hace la
dependencia `sesion_de_tenant` al final del request (o el test), y con él el
evento y la escritura de negocio confirman o revierten juntos — esa es toda
la garantía del patrón outbox. La policy `outbox_encolado_del_tenant`
exige que el `tenant_id` del evento sea el del GUC, así que los eventos del
catálogo SIEMPRE llevan el tenant del contexto, nunca uno del payload.

## El límite de productos por tier (ADR-010)

`LIMITES_PRODUCTOS_POR_TIER` fija 100 / 500 / sin límite (plan maestro §5).
Se verifica en la aplicación contando las filas VIVAS del negocio (la RLS
acota el `count` al tenant del GUC), como firma ADR-019: no es una
constraint de base. El tier llega por constructor; quién lo resuelve hoy es
la dependencia `tier_del_negocio` (decisión 2 del plan).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalogo.models import Producto
from app.modules.catalogo.schemas import ProductoActualizar, ProductoCrear
from vendi_core.errors.domain import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from vendi_core.events.service import DomainEventService

logger = structlog.get_logger()

#: Límite de productos por tier (plan maestro §5, ADR-010). `None` = sin
#: límite. Los límites de IA y empleados viven en sus módulos, no aquí.
LIMITES_PRODUCTOS_POR_TIER: dict[str, int | None] = {
    "gratis": 100,
    "light": 500,
    "pro": None,
}

#: Tier que la dependencia `tier_del_negocio` asigna mientras no exista el
#: módulo de suscripciones: el trial de Pro del plan maestro §5 (1 mes, sin
#: tarjeta) aplica a todo negocio registrado durante el piloto.
TIER_DEL_PILOTO = "pro"

#: Campos que un PATCH puede tocar. Ni `stock_actual` ni `ultimo_costo` están
#: aquí: los mueven inventario y compras (ADR-020).
_CAMPOS_EDITABLES = (
    "nombre",
    "codigo_barras",
    "categoria",
    "unidad_medida",
    "precio_venta",
    "iva_pct",
    "stock_minimo",
    "padre_id",
)


def _escapar_like(texto: str) -> str:
    """Los comodines de LIKE en la búsqueda del POS son texto, no patrón."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class CatalogoService:
    """Operaciones del catálogo de UN negocio: el del GUC de la sesión."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, tier: str = TIER_DEL_PILOTO):
        if tier not in LIMITES_PRODUCTOS_POR_TIER:
            raise ValueError(f"Tier desconocido: {tier!r}. Los válidos son {list(LIMITES_PRODUCTOS_POR_TIER)}.")
        self._session = session
        self._tenant_id = tenant_id
        self._tier = tier

    # --- Lectura -----------------------------------------------------------

    async def obtener(self, producto_id: uuid.UUID) -> Producto:
        producto = await self._session.get(Producto, producto_id)
        if producto is None or producto.deleted_at is not None:
            # Un id de otro negocio da el mismo 404 que uno inexistente: la
            # RLS lo hace invisible y no hay nada que filtrar.
            raise NotFoundError("El producto no existe.", code="producto_no_encontrado")
        return producto

    async def buscar_por_codigo(self, codigo: str) -> Producto:
        """El camino del escáner (ADR-024): un EAN resuelve a UN producto."""
        consulta = select(Producto).where(
            Producto.codigo_barras == codigo,
            Producto.deleted_at.is_(None),
        )
        producto = (await self._session.execute(consulta)).scalar_one_or_none()
        if producto is None:
            raise NotFoundError("Ningún producto tiene ese código de barras.", code="producto_no_encontrado")
        return producto

    async def listar(
        self,
        *,
        skip: int = 0,
        limit: int = 25,
        q: str | None = None,
        categoria: str | None = None,
    ) -> tuple[list[Producto], int]:
        base = select(Producto).where(Producto.deleted_at.is_(None))
        conteo = select(func.count()).select_from(Producto).where(Producto.deleted_at.is_(None))
        if q:
            patron = f"%{_escapar_like(q)}%"
            base = base.where(Producto.nombre.ilike(patron, escape="\\"))
            conteo = conteo.where(Producto.nombre.ilike(patron, escape="\\"))
        if categoria:
            base = base.where(Producto.categoria == categoria)
            conteo = conteo.where(Producto.categoria == categoria)
        total = (await self._session.execute(conteo)).scalar_one()
        filas = (
            (await self._session.execute(base.order_by(Producto.nombre, Producto.id).offset(skip).limit(limit)))
            .scalars()
            .all()
        )
        return list(filas), int(total)

    # --- Escritura ---------------------------------------------------------

    async def crear(self, datos: ProductoCrear) -> Producto:
        """Alta de producto. Idempotente por el UUID del cliente (ADR-017).

        Si el `id` ya existe y el producto está vivo, se devuelve tal cual:
        reenviar la misma creación es un no-op. Si existe pero está dado de
        baja, se rechaza: un UUID de cliente no se reutiliza jamás.
        """
        if datos.id is not None:
            existente = await self._session.get(Producto, datos.id)
            if existente is not None:
                if existente.deleted_at is None:
                    logger.info("producto_creado_idempotente", producto_id=str(existente.id))
                    return existente
                raise ConflictError(
                    "Ese id ya se usó para un producto dado de baja. Genera uno nuevo.",
                    code="producto_id_duplicado",
                )
        if datos.padre_id is not None:
            await self._exigir_padre(datos.padre_id)
        await self._exigir_cupo()

        producto = Producto(
            tenant_id=self._tenant_id,
            padre_id=datos.padre_id,
            nombre=datos.nombre,
            codigo_barras=datos.codigo_barras,
            categoria=datos.categoria,
            unidad_medida=datos.unidad_medida,
            precio_venta=datos.precio_venta,
            iva_pct=datos.iva_pct,
            stock_minimo=datos.stock_minimo,
        )
        if datos.id is not None:
            producto.id = datos.id
        self._session.add(producto)
        await self._flush_traduciendo_integridad()
        await self._emitir(
            "producto.creado",
            producto,
            data={
                "producto_id": str(producto.id),
                "nombre": producto.nombre,
                "codigo_barras": producto.codigo_barras,
                "precio_venta": producto.precio_venta,
                "iva_pct": str(producto.iva_pct),
            },
        )
        logger.info("producto_creado", producto_id=str(producto.id))
        return producto

    async def actualizar(self, producto_id: uuid.UUID, datos: ProductoActualizar) -> Producto:
        producto = await self.obtener(producto_id)
        if datos.padre_id is not None:
            if datos.padre_id == producto.id:
                raise ValidationError("Un producto no puede ser su propio padre.", code="padre_es_el_mismo")
            await self._exigir_padre(datos.padre_id)

        cambios: dict[str, dict[str, str]] = {}
        for campo in _CAMPOS_EDITABLES:
            nuevo = getattr(datos, campo)
            if nuevo is None:
                continue
            viejo = getattr(producto, campo)
            if nuevo != viejo:
                cambios[campo] = {"antes": str(viejo), "despues": str(nuevo)}
                setattr(producto, campo, nuevo)
        if not cambios:
            return producto

        await self._flush_traduciendo_integridad()
        await self._emitir("producto.actualizado", producto, data={"producto_id": str(producto.id), "cambios": cambios})
        logger.info("producto_actualizado", producto_id=str(producto.id), cambios=list(cambios))
        return producto

    async def eliminar(self, producto_id: uuid.UUID) -> None:
        """Borrado lógico. Anula el EAN para liberarlo: el índice único
        parcial de ADR-019 NO excluye filas borradas, y sin esto volver a
        crear el producto chocaría contra el índice para siempre. El EAN
        original viaja en el payload del evento."""
        producto = await self.obtener(producto_id)
        ean = producto.codigo_barras
        producto.deleted_at = datetime.now(UTC)
        producto.codigo_barras = None
        await self._session.flush()
        await self._emitir(
            "producto.eliminado",
            producto,
            data={"producto_id": str(producto.id), "nombre": producto.nombre, "codigo_barras": ean},
        )
        logger.info("producto_eliminado", producto_id=str(producto.id))

    # --- Internas ----------------------------------------------------------

    async def _exigir_padre(self, padre_id: uuid.UUID) -> None:
        """Postgres NO aplica RLS al verificar llaves foráneas: sin este
        chequeo, una variante podría colgar del producto de OTRO negocio."""
        padre = await self._session.get(Producto, padre_id)
        if padre is None or padre.deleted_at is not None:
            raise ValidationError("El producto padre no existe en tu negocio.", code="padre_no_encontrado")

    async def _exigir_cupo(self) -> None:
        """El límite del tier contra las filas VIVAS (ADR-019: en la
        aplicación, no en una constraint). La RLS acota el count al negocio."""
        limite = LIMITES_PRODUCTOS_POR_TIER[self._tier]
        if limite is None:
            return
        cuantos = (
            await self._session.execute(select(func.count()).select_from(Producto).where(Producto.deleted_at.is_(None)))
        ).scalar_one()
        if cuantos >= limite:
            raise PermissionDeniedError(
                f"Tu plan permite hasta {limite} productos. Amplía tu plan para seguir creando.",
                code="limite_de_productos_alcanzado",
                details={"tier": self._tier, "limite": limite},
            )

    async def _flush_traduciendo_integridad(self) -> None:
        """El índice único del EAN y la PK son las constraints de verdad; el
        servicio traduce su violación al sobre de errores de la API. Tras un
        `IntegrityError` la transacción queda abortada: quien llama (la
        dependencia o el test) hace rollback al propagar."""
        try:
            await self._session.flush()
        except IntegrityError as exc:
            detalle = str(exc)
            if "ux_productos_ean" in detalle:
                raise ConflictError(
                    "Ya existe un producto con ese código de barras en tu negocio.",
                    code="codigo_barras_duplicado",
                ) from exc
            if "productos_pkey" in detalle:
                # El id venía del cliente y choca con una fila que la RLS no
                # le deja ver (de otro negocio) o con una carrera de dos altas.
                raise ConflictError("Ese id de producto ya existe.", code="producto_id_duplicado") from exc
            raise

    async def _emitir(self, evento: str, producto: Producto, *, data: dict) -> None:
        await DomainEventService.emit(
            self._session,
            tenant_id=self._tenant_id,
            event_name=evento,
            resource_type="producto",
            resource_id=str(producto.id),
            data=data,
        )
