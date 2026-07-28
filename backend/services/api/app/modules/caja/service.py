"""Servicio de caja: apertura, movimientos manuales y el cierre con arqueo
(ADR-021).

## RLS hace el aislamiento; el servicio NO filtra por `tenant_id` a mano

Todo corre en la sesión de tenant (`vendi_app` + GUC `vendi.tenant_id`): la
policy `tenant_isolation` acota lecturas y escrituras y el `WITH CHECK`
rechaza un `tenant_id` inyectado. Los schemas llevan `extra="forbid"`, así
que el payload ni siquiera acepta el campo.

## UNA sesión abierta por tienda: la hace cumplir la base, no el código

`ux_caja_sesion_abierta` (índice único parcial, migración 0005) decide las
carreras de apertura — explícitas aquí, implícitas en el sync —: el perdedor
re-lee la ganadora y recibe un 409 tipado, nunca un 500.

## El arqueo: UNA función, suma desde el origen, se CONGELA al cerrar

`calcular_desglose` es la única función que calcula el esperado (decisión 3):
la usa el cierre (y congela el resultado en las columnas de la sesión), la
sesión actual (esperado vivo) y el forecast (saldo actual). Las ventas en
efectivo y los abonos NO se duplican como movimientos (ADR-021): se suman
desde su tabla de origen. Las columnas congeladas de una sesión `cerrada`
jamás se recalculan: el cierre de ayer sigue cuadrando mañana.

## Los eventos viajan en la transacción del llamante

El servicio hace `flush` pero NUNCA `commit`: confirma la dependencia
`sesion_de_tenant` al final del request (o el test), y con ella la sesión,
los movimientos y los eventos del outbox — la garantía del patrón.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.caja.models import CajaMovimiento
from app.modules.caja.schemas import (
    ArqueoConDesglose,
    DesgloseSalida,
    MovimientoCrear,
    SesionAbrir,
    SesionActualSalida,
    SesionCerrar,
)
from app.modules.catalogo.schemas import TOPE_PRECIO
from app.modules.ventas.models import CajaSesion, Venta
from vendi_core.errors.domain import ConflictError, NotFoundError, ValidationError
from vendi_core.events.service import DomainEventService

logger = structlog.get_logger()

#: Campos cuya divergencia convierte un reintento de movimiento en 409 (mismo
#: criterio que `_CAMPOS_DEL_AJUSTE` de inventario): si alguno difiere, NO es
#: un reintento — es otro movimiento con el mismo id, y alguien debe mirarlo.
_CAMPOS_DEL_MOVIMIENTO = ("tipo", "categoria", "monto", "motivo")


@dataclass(frozen=True)
class DesgloseArqueo:
    """La cuenta del arqueo (ADR-021). `esperado = base + ventas en efectivo
    + abonos en efectivo + ingresos − egresos − devoluciones`."""

    base_inicial: int
    ventas_efectivo: int
    abonos_efectivo: int
    ingresos: int
    egresos: int
    devoluciones: int

    @property
    def esperado(self) -> int:
        return (
            self.base_inicial
            + self.ventas_efectivo
            + self.abonos_efectivo
            + self.ingresos
            - self.egresos
            - self.devoluciones
        )

    def como_salida(self) -> DesgloseSalida:
        return DesgloseSalida(
            base_inicial=self.base_inicial,
            ventas_efectivo=self.ventas_efectivo,
            abonos_efectivo=self.abonos_efectivo,
            ingresos=self.ingresos,
            egresos=self.egresos,
            devoluciones=self.devoluciones,
            esperado=self.esperado,
        )


async def _abonos_en_efectivo_de_la_sesion(session: AsyncSession, sesion: CajaSesion) -> int:
    """0 hasta el módulo 5 (fiado, ADR-022): la tabla de abonos no existe.

    PUNTO DE CAMBIO ÚNICO (decisión 3): cuando el módulo 5 la cree, el
    `SUM(abonos en efectivo de la sesión)` va AQUÍ DENTRO y ni el arqueo, ni
    el esperado vivo, ni el forecast se tocan. El argumento `session` queda
    para esa firma futura."""
    return 0


async def calcular_desglose(session: AsyncSession, sesion: CajaSesion) -> DesgloseArqueo:
    """La cuenta del esperado de una sesión, sumada desde las tablas de
    origen (ADR-021). Es la ÚNICA función que la calcula (decisión 3).

    - Ventas en efectivo `completada` de la sesión. Las anuladas NO suman.
    - Devoluciones: ventas en efectivo `anulada` de OTRAS sesiones cuya
      `anulada_en` cayó dentro de la ventana de ésta — la anulación cae en
      la sesión abierta en ese momento (ADR-021, decisión 7). Las anuladas
      de la PROPIA sesión no se restan: ya están fuera del SUM de
      completadas y su efecto neto es cero; restarlas sería contarlas dos
      veces. Las anuladas pre-módulo (`anulada_en NULL`) no existen en
      operación real (pre-piloto) y quedan excluidas por el `IS NOT NULL`.
    - Movimientos manuales de la sesión, por tipo.
    - Abonos de fiado en efectivo: 0 (punto de cambio único, arriba).

    La ventana es `[abierta_en, cerrada_en)`; para la sesión abierta corre
    hasta ahora (el esperado VIVO)."""
    ventas_efectivo = await session.scalar(
        select(func.coalesce(func.sum(Venta.total_centavos), 0)).where(
            Venta.sesion_caja_id == sesion.id,
            Venta.medio_pago == "efectivo",
            Venta.estado == "completada",
        )
    )
    condiciones_devolucion = [
        Venta.medio_pago == "efectivo",
        Venta.estado == "anulada",
        Venta.anulada_en.is_not(None),
        Venta.anulada_en >= sesion.abierta_en,
        Venta.sesion_caja_id != sesion.id,
    ]
    if sesion.cerrada_en is not None:
        condiciones_devolucion.append(Venta.anulada_en < sesion.cerrada_en)
    devoluciones = await session.scalar(
        select(func.coalesce(func.sum(Venta.total_centavos), 0)).where(*condiciones_devolucion)
    )
    movimientos = await session.execute(
        select(CajaMovimiento.tipo, func.coalesce(func.sum(CajaMovimiento.monto), 0))
        .where(CajaMovimiento.sesion_caja_id == sesion.id)
        .group_by(CajaMovimiento.tipo)
    )
    por_tipo = dict(movimientos.all())
    return DesgloseArqueo(
        base_inicial=sesion.base_inicial,
        ventas_efectivo=int(ventas_efectivo),
        abonos_efectivo=await _abonos_en_efectivo_de_la_sesion(session, sesion),
        ingresos=int(por_tipo.get("ingreso", 0)),
        egresos=int(por_tipo.get("egreso", 0)),
        devoluciones=int(devoluciones),
    )


class CajaService:
    """Operaciones de caja de UN negocio: el del GUC de la sesión."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: str, puede_cerrar: bool):
        self._session = session
        self._tenant_id = tenant_id
        self._actor_id = actor_id
        #: Lo deriva el router del token (`has_permission(user, "caja:cerrar")`).
        #: El servicio no lee claims: recibe el veredicto (ADR-015/ADR-023) y
        #: lo usa para condicionar el esperado vivo (decisión 4) y la
        #: visibilidad de los `retiro_dueno` en el listado de movimientos
        #: (C-3 del QA). El GUARD de los endpoints de cierre está en el
        #: router, como manda ADR-023.
        self._puede_cerrar = puede_cerrar

    # --- Apertura -----------------------------------------------------------------

    async def abrir_sesion(self, datos: SesionAbrir) -> CajaSesion:
        """Apertura explícita con `base_inicial`. UNA abierta por tienda: si
        ya hay, el reintento idéntico (mismo `id` y misma base) devuelve la
        existente y cualquier otra apertura es 409 `caja_ya_abierta` con la
        sesión vigente en `details` (decisión 6)."""
        abierta = await self._sesion_abierta()
        if abierta is not None:
            if datos.id is not None and abierta.id == datos.id and abierta.base_inicial == datos.base_inicial:
                logger.info("caja_sesion_abierta_idempotente", sesion_id=str(abierta.id))
                return abierta
            raise ConflictError(
                "Ya hay una caja abierta en este negocio. Ciérrala antes de abrir otra.",
                code="caja_ya_abierta",
                details={"sesion_id": str(abierta.id)},
            )
        sesion = CajaSesion(tenant_id=self._tenant_id, abierta_por=self._actor_id, base_inicial=datos.base_inicial)
        if datos.id is not None:
            sesion.id = datos.id
        try:
            async with self._session.begin_nested():
                # El alta va DENTRO del savepoint (mismo motivo que en
                # `_resolver_sesion_caja` de ventas): un `add` previo haría
                # reventar el INSERT fuera del savepoint y la transacción
                # quedaría abortada sin dónde revertir.
                self._session.add(sesion)
                await self._session.flush()
        except IntegrityError as exc:
            detalle = str(exc)
            if "ux_caja_sesion_abierta" in detalle:
                # Apertura concurrente (explícita aquí o implícita en el
                # sync): gana una. El perdedor re-lee tras el rollback del
                # savepoint y recibe el 409 tipado con la ganadora.
                ganadora = await self._sesion_abierta()
                if (
                    ganadora is not None
                    and datos.id is not None
                    and ganadora.id == datos.id
                    and ganadora.base_inicial == datos.base_inicial
                ):
                    return ganadora
                raise ConflictError(
                    "Ya hay una caja abierta en este negocio. Ciérrala antes de abrir otra.",
                    code="caja_ya_abierta",
                    details={"sesion_id": str(ganadora.id) if ganadora else None},
                ) from exc
            if "caja_sesiones_pkey" in detalle:
                # El id venía del cliente y choca con una fila que la RLS no
                # le deja ver (de otro negocio): 409 tipado, no el 500 del
                # IntegrityError (mismo criterio que `dispositivo_id_en_conflicto`).
                raise ConflictError("Ese id de sesión ya existe.", code="sesion_id_duplicado") from exc
            # Solo esos dos choques se traducen: cualquier otro IntegrityError
            # es un fallo real y debe propagarse.
            raise
        await DomainEventService.emit(
            self._session,
            tenant_id=self._tenant_id,
            event_name="caja.sesion_abierta",
            resource_type="caja_sesion",
            resource_id=str(sesion.id),
            data={
                "sesion_id": str(sesion.id),
                "base_inicial": sesion.base_inicial,
                "abierta_por": sesion.abierta_por,
            },
        )
        logger.info("caja_sesion_abierta", sesion_id=str(sesion.id), base_inicial=sesion.base_inicial)
        return sesion

    async def sesion_actual(self) -> SesionActualSalida:
        """La sesión abierta con su esperado VIVO — solo para quien cierra
        (decisión 4): sin `caja:cerrar` el campo viaja en null con la misma
        forma, como `ultimo_costo` sin `compra:crear`."""
        sesion = await self._sesion_abierta()
        if sesion is None:
            raise NotFoundError("No hay una caja abierta en este negocio.", code="caja_sin_sesion_abierta")
        esperado: int | None = None
        if self._puede_cerrar:
            esperado = (await calcular_desglose(self._session, sesion)).esperado
        return SesionActualSalida(
            id=sesion.id,
            abierta_por=sesion.abierta_por,
            abierta_en=sesion.abierta_en,
            base_inicial=sesion.base_inicial,
            estado=sesion.estado,
            efectivo_esperado=esperado,
        )

    async def listar_sesiones(self, *, skip: int = 0, limit: int = 25) -> tuple[list[CajaSesion], int]:
        """El historial de arqueos (exige `caja:cerrar` en el router, decisión
        4): faltantes y sobrantes históricos son un reporte, no son del cajero."""
        total = (await self._session.execute(select(func.count()).select_from(CajaSesion))).scalar_one()
        filas = (
            (
                await self._session.execute(
                    select(CajaSesion).order_by(CajaSesion.abierta_en.desc(), CajaSesion.id).offset(skip).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(filas), int(total)

    # --- Movimientos ------------------------------------------------------------------

    async def registrar_movimiento(self, datos: MovimientoCrear) -> CajaMovimiento:
        """Ingreso o egreso manual, atado a la sesión ABIERTA (sin ella, 409
        `caja_sin_sesion_abierta`). La sesión se lee `FOR UPDATE` (mismo
        patrón que el cierre y el sync): el movimiento se serializa con el
        cierre y jamás se inserta contra una sesión ya cerrada. Idempotente
        por el `id` del cliente (REQUERIDO, decisión 6): reintento idéntico →
        la fila existente, sin duplicar ni re-emitir; divergente → 409
        `movimiento_id_divergente`."""
        existente = await self._session.get(CajaMovimiento, datos.id)
        if existente is not None:
            divergentes = [
                campo
                for campo in _CAMPOS_DEL_MOVIMIENTO
                if str(getattr(existente, campo)) != str(getattr(datos, campo))
            ]
            if divergentes:
                raise ConflictError(
                    "Ese id de movimiento ya existe con datos distintos. El servidor conserva la primera versión.",
                    code="movimiento_id_divergente",
                    details={"campos": divergentes},
                )
            logger.info("caja_movimiento_idempotente", movimiento_id=str(existente.id))
            return existente
        sesion = await self._sesion_abierta(bloqueo=True)
        if sesion is None:
            raise ConflictError(
                "No hay una caja abierta: abre la caja antes de registrar movimientos.",
                code="caja_sin_sesion_abierta",
            )
        movimiento = CajaMovimiento(
            id=datos.id,
            tenant_id=self._tenant_id,
            sesion_caja_id=sesion.id,
            tipo=datos.tipo,
            categoria=datos.categoria,
            monto=datos.monto,
            motivo=datos.motivo,
            registrado_por=self._actor_id,
        )
        self._session.add(movimiento)
        await self._flush_traduciendo_integridad()
        await DomainEventService.emit(
            self._session,
            tenant_id=self._tenant_id,
            event_name="caja.movimiento_registrado",
            resource_type="caja_movimiento",
            resource_id=str(movimiento.id),
            data={
                "movimiento_id": str(movimiento.id),
                "sesion_caja_id": str(movimiento.sesion_caja_id),
                "tipo": movimiento.tipo,
                "categoria": movimiento.categoria,
                "monto": movimiento.monto,
            },
        )
        logger.info("caja_movimiento_registrado", movimiento_id=str(movimiento.id), tipo=movimiento.tipo)
        return movimiento

    async def listar_movimientos(
        self, sesion_id: uuid.UUID | None, *, skip: int = 0, limit: int = 25
    ) -> tuple[list[CajaMovimiento], int]:
        """Los movimientos de una sesión (la abierta si no se pide otra).

        El `retiro_dueno` es tan sensible como el costo (C-3 del QA, la
        lección de la fuga de `ultimo_costo`): sin `caja:cerrar` NO aparece
        — ni en la lista ni en el total — aunque el cajero conozca el id de
        la sesión. El flag llega del token vía la dependencia, igual que el
        del esperado vivo (decisión 4)."""
        if sesion_id is None:
            sesion = await self._sesion_abierta()
            if sesion is None:
                raise NotFoundError("No hay una caja abierta en este negocio.", code="caja_sin_sesion_abierta")
            sesion_id = sesion.id
        elif await self._session.get(CajaSesion, sesion_id) is None:
            # La sesión de otro negocio es invisible por RLS: mismo 404.
            raise NotFoundError("La sesión de caja no existe.", code="caja_sesion_no_encontrada")
        filtro = [CajaMovimiento.sesion_caja_id == sesion_id]
        if not self._puede_cerrar:
            filtro.append(CajaMovimiento.categoria != "retiro_dueno")
        base = select(CajaMovimiento).where(*filtro)
        total = (
            await self._session.execute(select(func.count()).select_from(CajaMovimiento).where(*filtro))
        ).scalar_one()
        filas = (
            (
                await self._session.execute(
                    base.order_by(CajaMovimiento.created_at.desc(), CajaMovimiento.id).offset(skip).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(filas), int(total)

    # --- El cierre con arqueo ------------------------------------------------------------

    async def cerrar_sesion(self, sesion_id: uuid.UUID, datos: SesionCerrar) -> ArqueoConDesglose:
        """El arqueo: calcula el esperado desde las tablas de origen y lo
        CONGELA en las columnas de la sesión (ADR-021). Desde entonces nada
        lo reabre: ni una venta tardía, ni una anulación posterior.

        La fila se bloquea `FOR UPDATE` hasta el commit: el cierre, el alta
        de movimientos (que bloquea la sesión al resolverla) y el sync
        (decisión 5) se serializan — ni una venta ni un movimiento jamás
        quedan insertados contra una sesión ya cerrada. El reintento con el
        MISMO conteo devuelve el arqueo congelado sin recalcular (decisión
        6); con otro conteo es 409.
        """
        sesion = await self._session.get(CajaSesion, sesion_id, with_for_update=True)
        if sesion is None:
            # La sesión de otro negocio es invisible por RLS: mismo 404.
            raise NotFoundError("La sesión de caja no existe.", code="caja_sesion_no_encontrada")
        if sesion.estado == "cerrada":
            if sesion.efectivo_contado == datos.contado:
                logger.info("caja_cierre_idempotente", sesion_id=str(sesion.id))
                return self._arqueo(sesion, desglose=None)
            raise ConflictError(
                "Esta caja ya fue cerrada con otro conteo. El arqueo firmado no se reabre.",
                code="caja_ya_cerrada",
                details={"sesion_id": str(sesion.id), "diferencia": sesion.diferencia},
            )

        desglose = await calcular_desglose(self._session, sesion)
        esperado = desglose.esperado
        diferencia = datos.contado - esperado
        if abs(esperado) > TOPE_PRECIO or abs(diferencia) > TOPE_PRECIO:
            # Las columnas son `Integer`: sin esta cota, el UPDATE reventaría
            # con un `DataError` → 500 (I1 de inventario, misma receta).
            raise ValidationError(
                "Los montos del arqueo no caben en el sistema. Reporta esto a soporte.",
                code="total_fuera_de_rango",
            )
        sesion.estado = "cerrada"
        sesion.cerrada_por = self._actor_id
        sesion.cerrada_en = datetime.now(UTC)
        sesion.efectivo_esperado = esperado
        sesion.efectivo_contado = datos.contado
        sesion.diferencia = diferencia
        await self._session.flush()
        await DomainEventService.emit(
            self._session,
            tenant_id=self._tenant_id,
            event_name="caja.sesion_cerrada",
            resource_type="caja_sesion",
            resource_id=str(sesion.id),
            data={
                "sesion_id": str(sesion.id),
                "cerrada_por": sesion.cerrada_por,
                "base_inicial": desglose.base_inicial,
                "ventas_efectivo": desglose.ventas_efectivo,
                "abonos_efectivo": desglose.abonos_efectivo,
                "ingresos": desglose.ingresos,
                "egresos": desglose.egresos,
                "devoluciones": desglose.devoluciones,
                "efectivo_esperado": esperado,
                "efectivo_contado": datos.contado,
                "diferencia": diferencia,
            },
        )
        logger.info("caja_sesion_cerrada", sesion_id=str(sesion.id), diferencia=diferencia)
        return self._arqueo(sesion, desglose)

    # --- Internas ----------------------------------------------------------------

    async def _sesion_abierta(self, *, bloqueo: bool = False) -> CajaSesion | None:
        consulta = select(CajaSesion).where(CajaSesion.estado == "abierta")
        if bloqueo:
            # El alta del movimiento bloquea la fila igual que el cierre y el
            # sync: el movimiento se serializa con el cierre y, si llega
            # tarde, la re-lectura ya no la encuentra abierta y recibe el 409
            # — nunca se inserta contra una sesión ya cerrada (pasaría la FK
            # pero desaparecería de todo arqueo).
            consulta = consulta.with_for_update()
        return (await self._session.execute(consulta)).scalar_one_or_none()

    @staticmethod
    def _arqueo(sesion: CajaSesion, desglose: DesgloseArqueo | None) -> ArqueoConDesglose:
        return ArqueoConDesglose(
            id=sesion.id,
            abierta_por=sesion.abierta_por,
            abierta_en=sesion.abierta_en,
            base_inicial=sesion.base_inicial,
            estado=sesion.estado,
            cerrada_por=sesion.cerrada_por,
            cerrada_en=sesion.cerrada_en,
            efectivo_esperado=sesion.efectivo_esperado,
            efectivo_contado=sesion.efectivo_contado,
            diferencia=sesion.diferencia,
            desglose=desglose.como_salida() if desglose is not None else None,
        )

    async def _flush_traduciendo_integridad(self) -> None:
        """Las constraints son las de verdad; el servicio traduce su violación
        al sobre de errores de la API. Tras un `IntegrityError` la transacción
        queda abortada: quien llama (la dependencia o el test) hace rollback
        al propagar."""
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "caja_movimientos_pkey" in str(exc):
                # Carrera de dos PRIMEROS envíos con el mismo id de cliente, o
                # el id de una fila que la RLS no deja ver (mismo criterio
                # registrado en D-24): 409 tipado, nunca el 500 del IntegrityError.
                raise ConflictError("Ese id de movimiento ya existe.", code="movimiento_id_divergente") from exc
            raise
