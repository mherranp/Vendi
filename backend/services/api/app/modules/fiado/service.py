"""Servicio del fiado y los clientes: el cuaderno (ADR-009/ADR-022).

## RLS hace el aislamiento; el servicio NO filtra por `tenant_id` a mano

Todo corre en la sesión de tenant (`vendi_app` + GUC `vendi.tenant_id`): la
policy `tenant_isolation` acota lecturas y escrituras y el `WITH CHECK`
rechaza un `tenant_id` inyectado. Los schemas llevan `extra="forbid"`, así
que el payload ni siquiera acepta el campo.

## El saldo por cliente NO se guarda

Es `SUM(saldo_pendiente)` de los créditos `vigente`/`vencido`, calculado en
cada lectura (ADR-022). El cupo se evalúa contra esa suma en el momento de
consultar (decisión 8): una bandera guardada se desactualizaría con cada
abono, anulación o edición del límite; el cálculo nunca miente.

## El abono descuenta en la misma transacción, con la fila bloqueada

El crédito se lee `FOR UPDATE` hasta el commit: dos abonos concurrentes del
mismo crédito se serializan y el CHECK `saldo_pendiente >= 0` es la red
final (ADR-022). El abono en efectivo además bloquea la sesión de caja
abierta — el mismo patrón que `registrar_movimiento` de caja — porque su
plata entra al arqueo de esa sesión (decisión 9).

## Los eventos viajan en la transacción del llamante

El servicio hace `flush` pero NUNCA `commit`: confirma la dependencia
`sesion_de_tenant` al final del request (o el test), y con ella el abono,
el saldo y los eventos del outbox — la garantía del patrón.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import quote

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.caja.reportes import ZONA_LOCAL
from app.modules.fiado.models import ESTADOS_CON_DEUDA, Cliente, FiadoAbono, FiadoCredito
from app.modules.fiado.schemas import (
    AbonoCrear,
    AbonoSalida,
    ClienteConSaldo,
    ClienteCrear,
    ClienteDetalleSalida,
    ClienteEditar,
    ClienteSalida,
    CreditoDetalleSalida,
    CreditoReprogramar,
    CreditoResumenSalida,
)
from app.modules.ventas.models import CajaSesion
from vendi_core.errors.domain import ConflictError, NotFoundError, ValidationError
from vendi_core.events.service import DomainEventService

logger = structlog.get_logger()

#: Campos cuya divergencia convierte un reintento en 409 (mismo criterio que
#: `_CAMPOS_DEL_MOVIMIENTO` de caja): si alguno difiere NO es un reintento.
_CAMPOS_DEL_CLIENTE = ("nombre", "telefono", "nota", "limite_credito")
_CAMPOS_DEL_ABONO = ("monto", "metodo_pago", "nota")


def construir_whatsapp_url(cliente: Cliente, credito: FiadoCredito) -> str | None:
    """El `wa.me` prearmado (ADR-022: WhatsApp manual, coste cero — es
    exactamente cómo el tendero ya cobra). 10 dígitos = celular colombiano
    sin indicativo: se antepone 57. `None` si no hay teléfono."""
    if not cliente.telefono:
        return None
    numero = cliente.telefono if len(cliente.telefono) > 10 else "57" + cliente.telefono
    # El saldo vive en centavos; el mensaje lo lee una persona: en PESOS, que
    # es como se habla el fiado. Los decimales solo aparecen cuando los hay
    # («$43.000», «$430,50») — mostrar los centavos crudos como si fueran
    # pesos inflaba la deuda 100x (revisión final del módulo).
    pesos, centavos = divmod(credito.saldo_pendiente, 100)
    monto = f"${pesos:,}".replace(",", ".")
    if centavos:
        monto += f",{centavos:02d}"
    mensaje = f"Hola {cliente.nombre}, te recuerdo el fiado de {monto} que tienes pendiente conmigo. ¿Cuándo me lo puedes pagar?"
    return f"https://wa.me/{numero}?text={quote(mensaje)}"


class FiadoService:
    """El cuaderno de UN negocio: el del GUC de la sesión."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: str):
        self._session = session
        self._tenant_id = tenant_id
        self._actor_id = actor_id

    # --- Clientes ---------------------------------------------------------------

    async def crear_cliente(self, datos: ClienteCrear) -> ClienteSalida:
        """Alta online. Idempotente por el `id` del cliente (ADR-017):
        reintento idéntico → el existente; divergente → 409; choque con una
        fila que la RLS no deja ver → 409 tipado (criterio
        `dispositivo_id_en_conflicto`: el id es un UUIDv4 inadivinable)."""
        if datos.id is not None:
            existente = await self._session.get(Cliente, datos.id)
            if existente is not None:
                divergentes = [c for c in _CAMPOS_DEL_CLIENTE if str(getattr(existente, c)) != str(getattr(datos, c))]
                if divergentes:
                    raise ConflictError(
                        "Ese id de cliente ya existe con datos distintos. El servidor conserva la primera versión.",
                        code="cliente_id_divergente",
                        details={"campos": divergentes},
                    )
                logger.info("cliente_idempotente", cliente_id=str(existente.id))
                return ClienteSalida.model_validate(existente)
        cliente = Cliente(
            tenant_id=self._tenant_id,
            nombre=datos.nombre,
            telefono=datos.telefono,
            nota=datos.nota,
            limite_credito=datos.limite_credito,
        )
        if datos.id is not None:
            cliente.id = datos.id
        try:
            async with self._session.begin_nested():
                # El alta va DENTRO del savepoint (mismo motivo que en
                # `_resolver_sesion_caja` de ventas): un `add` previo haría
                # reventar el INSERT fuera del savepoint.
                self._session.add(cliente)
                await self._session.flush()
        except IntegrityError as exc:
            if "clientes_pkey" not in str(exc):
                raise
            raise ConflictError(
                "Ese id de cliente ya está en uso. Genera uno nuevo.", code="cliente_id_en_conflicto"
            ) from exc
        logger.info("cliente_creado", cliente_id=str(cliente.id))
        return ClienteSalida.model_validate(cliente)

    async def listar_clientes(
        self, q: str | None, *, skip: int = 0, limit: int = 25
    ) -> tuple[list[ClienteConSaldo], int]:
        """La libreta con la deuda viva de cada uno: SUM de `vigente`/`vencido`
        calculado en la consulta (ADR-022), nunca una columna."""
        saldos = (
            select(
                FiadoCredito.cliente_id.label("cliente_id"),
                func.coalesce(func.sum(FiadoCredito.saldo_pendiente), 0).label("saldo"),
            )
            .where(FiadoCredito.estado.in_(ESTADOS_CON_DEUDA))
            .group_by(FiadoCredito.cliente_id)
            .subquery()
        )
        filtro = []
        if q:
            filtro.append(Cliente.nombre.ilike(f"%{q}%"))
        total = (await self._session.execute(select(func.count()).select_from(Cliente).where(*filtro))).scalar_one()
        filas = (
            await self._session.execute(
                select(Cliente, func.coalesce(saldos.c.saldo, 0))
                .outerjoin(saldos, saldos.c.cliente_id == Cliente.id)
                .where(*filtro)
                .order_by(Cliente.nombre, Cliente.id)
                .offset(skip)
                .limit(limit)
            )
        ).all()
        return [self._con_saldo(cliente, int(saldo)) for cliente, saldo in filas], int(total)

    async def obtener_cliente(self, cliente_id: uuid.UUID) -> ClienteDetalleSalida:
        """La ficha: datos, saldo calculado y los fiados con deuda, ordenados
        por lo que vence primero (los sin fecha, al final: no prometen día)."""
        cliente = await self._session.get(Cliente, cliente_id)
        if cliente is None:
            # El cliente de otro negocio es invisible por RLS: mismo 404.
            raise NotFoundError("El cliente no existe.", code="cliente_no_encontrado")
        saldo = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(FiadoCredito.saldo_pendiente), 0)).where(
                    FiadoCredito.cliente_id == cliente.id, FiadoCredito.estado.in_(ESTADOS_CON_DEUDA)
                )
            )
        )
        creditos = (
            (
                await self._session.execute(
                    select(FiadoCredito)
                    .where(FiadoCredito.cliente_id == cliente.id, FiadoCredito.estado.in_(ESTADOS_CON_DEUDA))
                    .order_by(FiadoCredito.fecha_vencimiento.asc().nulls_last(), FiadoCredito.created_at)
                )
            )
            .scalars()
            .all()
        )
        con_saldo = self._con_saldo(cliente, saldo)
        return ClienteDetalleSalida(
            **con_saldo.model_dump(),
            creditos=[self._resumen(credito, cliente.nombre) for credito in creditos],
        )

    async def editar_cliente(self, cliente_id: uuid.UUID, datos: ClienteEditar) -> ClienteSalida:
        """Edición parcial. `null` explícito borra el valor (quitar el cupo
        vuelve a «sin tope»). El cliente no se borra (decisión 13)."""
        cliente = await self._session.get(Cliente, cliente_id)
        if cliente is None:
            raise NotFoundError("El cliente no existe.", code="cliente_no_encontrado")
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(cliente, campo, valor)
        cliente.updated_at = datetime.now(UTC)
        await self._session.flush()
        logger.info("cliente_editado", cliente_id=str(cliente.id))
        return ClienteSalida.model_validate(cliente)

    # --- El cuaderno (créditos) ---------------------------------------------------

    async def listar_creditos(
        self, estado: str | None, *, skip: int = 0, limit: int = 25
    ) -> tuple[list[CreditoResumenSalida], int]:
        """El cuaderno: por defecto solo lo que se debe (`vigente` + `vencido`),
        lo que vence primero arriba. `estado="todos"` incluye la historia."""
        filtro = []
        if estado is None:
            filtro.append(FiadoCredito.estado.in_(ESTADOS_CON_DEUDA))
        elif estado != "todos":
            filtro.append(FiadoCredito.estado == estado)
        total = (
            await self._session.execute(select(func.count()).select_from(FiadoCredito).where(*filtro))
        ).scalar_one()
        filas = (
            await self._session.execute(
                select(FiadoCredito, Cliente.nombre)
                .join(Cliente, FiadoCredito.cliente_id == Cliente.id)
                .where(*filtro)
                .order_by(FiadoCredito.fecha_vencimiento.asc().nulls_last(), FiadoCredito.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
        ).all()
        return [self._resumen(credito, nombre) for credito, nombre in filas], int(total)

    async def obtener_credito(self, credito_id: uuid.UUID) -> CreditoDetalleSalida:
        """La pantalla del fiado: su historial de pagos (ADR-009: es la
        verdad y no se reescribe) y el `wa.me` prearmado para cobrarle."""
        credito = await self._session.get(FiadoCredito, credito_id)
        if credito is None:
            raise NotFoundError("El crédito no existe.", code="credito_no_encontrado")
        cliente = await self._session.get(Cliente, credito.cliente_id)
        abonos = (
            (
                await self._session.execute(
                    select(FiadoAbono)
                    .where(FiadoAbono.credito_id == credito.id)
                    .order_by(FiadoAbono.created_at, FiadoAbono.id)
                )
            )
            .scalars()
            .all()
        )
        salida = CreditoDetalleSalida.model_validate(credito)
        salida.cliente_nombre = cliente.nombre if cliente is not None else None
        salida.abonos = [AbonoSalida.model_validate(a) for a in abonos]
        salida.whatsapp_url = construir_whatsapp_url(cliente, credito) if cliente is not None else None
        return salida

    async def reprogramar_vencimiento(self, credito_id: uuid.UUID, datos: CreditoReprogramar) -> CreditoResumenSalida:
        """«Deme hasta el otro viernes». Un `vencido` reprogramado a futuro
        (o dejado sin fecha) vuelve a `vigente` — la transición ES el
        anti-duplicado del recordatorio, así que esto no rompe nada
        (decisión 7) —; un `saldado`/`anulado` ya no se toca."""
        credito = await self._session.get(FiadoCredito, credito_id, with_for_update=True)
        if credito is None:
            raise NotFoundError("El crédito no existe.", code="credito_no_encontrado")
        if credito.estado in ("saldado", "anulado"):
            raise ConflictError(
                f"Este crédito está {credito.estado}: ya no se reprograma.",
                code="credito_no_editable",
                details={"estado": credito.estado},
            )
        credito.fecha_vencimiento = datos.fecha_vencimiento
        if credito.estado == "vencido" and (
            datos.fecha_vencimiento is None or datos.fecha_vencimiento >= datetime.now(ZONA_LOCAL).date()
        ):
            credito.estado = "vigente"
        credito.updated_at = datetime.now(UTC)
        await self._session.flush()
        logger.info("fiado_credito_reprogramado", credito_id=str(credito.id), fecha=str(datos.fecha_vencimiento))
        return self._resumen(credito, None)

    # --- Abonos -------------------------------------------------------------------

    async def registrar_abono(self, credito_id: uuid.UUID, datos: AbonoCrear) -> AbonoSalida:
        """Un pago contra el crédito que el usuario tocó (ADR-022).

        - Idempotente por el `id` REQUERIDO del cliente (es dinero: la ancla
          hace seguro el reintento tras un timeout). Reintento idéntico → el
          abono existente, sin descontar dos veces ni re-emitir; divergente →
          409 `abono_id_divergente`.
        - El crédito se bloquea `FOR UPDATE` hasta el commit: dos abonos
          concurrentes se serializan y el CHECK `saldo_pendiente >= 0` es la
          red final (ADR-022).
        - Abono mayor que el saldo → 422 `abono_excede_saldo` (pre-chequeo;
          la carrera la cierra el CHECK, traducido al mismo 422).
        - `efectivo` exige sesión abierta y guarda su `sesion_caja_id`
          (decisión 9: su plata entra al arqueo de esa sesión; los demás
          métodos no tocan la gaveta). La sesión se resuelve y bloquea
          ANTES que el crédito — sesión → crédito, el mismo orden que el
          camino de ventas (productos → sesión → crédito): con el orden
          inverso, un abono concurrente con la anulación de la misma venta
          fiada era un deadlock que salía como 500 no traducido.
        - Al llegar a 0: `saldado` y evento `fiado.credito_saldado`. Un
          `saldado` nunca vuelve a `vigente` (ADR-022).
        """
        existente = await self._session.get(FiadoAbono, datos.id)
        if existente is not None:
            divergentes = [c for c in _CAMPOS_DEL_ABONO if str(getattr(existente, c)) != str(getattr(datos, c))]
            if existente.credito_id != credito_id:
                divergentes.append("credito_id")
            if divergentes:
                raise ConflictError(
                    "Ese id de abono ya existe con datos distintos. El servidor conserva la primera versión.",
                    code="abono_id_divergente",
                    details={"campos": divergentes},
                )
            logger.info("fiado_abono_idempotente", abono_id=str(existente.id))
            return AbonoSalida.model_validate(existente)

        sesion_caja_id: uuid.UUID | None = None
        if datos.metodo_pago == "efectivo":
            # FOR UPDATE como en `registrar_movimiento` de caja: el abono se
            # serializa con el cierre y jamás cae en una sesión ya cerrada.
            # Va ANTES del bloqueo del crédito (sesión → crédito): es el
            # orden que usan `_registrar_venta` y `_anular_venta`, y romperlo
            # aquí armaba un ciclo de espera con la anulación de la misma
            # venta fiada (ella retiene la sesión y pide el crédito).
            sesion = (
                await self._session.execute(select(CajaSesion).where(CajaSesion.estado == "abierta").with_for_update())
            ).scalar_one_or_none()
            if sesion is None:
                raise ConflictError(
                    "No hay una caja abierta: el abono en efectivo entra a la gaveta y necesita su sesión.",
                    code="caja_sin_sesion_abierta",
                )
            sesion_caja_id = sesion.id

        credito = await self._session.get(FiadoCredito, credito_id, with_for_update=True)
        if credito is None:
            raise NotFoundError("El crédito no existe.", code="credito_no_encontrado")
        if credito.estado in ("saldado", "anulado"):
            raise ConflictError(
                f"Este crédito está {credito.estado}: no admite abonos.",
                code="credito_no_abonable",
                details={"estado": credito.estado},
            )
        if datos.monto > credito.saldo_pendiente:
            raise ValidationError(
                "El abono es mayor que lo que debe: ajusta el monto al saldo.",
                code="abono_excede_saldo",
                details={"saldo_pendiente": credito.saldo_pendiente},
            )

        abono = FiadoAbono(
            id=datos.id,
            tenant_id=self._tenant_id,
            credito_id=credito.id,
            sesion_caja_id=sesion_caja_id,
            monto=datos.monto,
            metodo_pago=datos.metodo_pago,
            registrado_por=self._actor_id,
            nota=datos.nota,
        )
        self._session.add(abono)
        credito.saldo_pendiente -= datos.monto
        if credito.saldo_pendiente == 0:
            credito.estado = "saldado"
        credito.updated_at = datetime.now(UTC)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            detalle = str(exc)
            if "ck_fiado_creditos_saldo_no_negativo" in detalle or "ck_fiado_creditos_saldo_acotado" in detalle:
                # La red de ADR-022 atrapando una carrera que el FOR UPDATE
                # hace casi imposible: mismo 422 tipado, nunca un 500 mudo.
                raise ValidationError(
                    "El abono es mayor que lo que debe: ajusta el monto al saldo.",
                    code="abono_excede_saldo",
                ) from exc
            if "fiado_abonos_pkey" in detalle:
                # Dos PRIMEROS envíos concurrentes con el mismo id, o el id
                # de una fila que la RLS no deja ver (criterio D-24).
                raise ConflictError("Ese id de abono ya existe.", code="abono_id_divergente") from exc
            raise
        await DomainEventService.emit(
            self._session,
            tenant_id=self._tenant_id,
            event_name="fiado.abono_registrado",
            resource_type="fiado_abono",
            resource_id=str(abono.id),
            data={
                "abono_id": str(abono.id),
                "credito_id": str(credito.id),
                "cliente_id": str(credito.cliente_id),
                "monto": abono.monto,
                "metodo_pago": abono.metodo_pago,
                "saldo_restante": credito.saldo_pendiente,
            },
        )
        if credito.estado == "saldado":
            await DomainEventService.emit(
                self._session,
                tenant_id=self._tenant_id,
                event_name="fiado.credito_saldado",
                resource_type="fiado_credito",
                resource_id=str(credito.id),
                data={
                    "credito_id": str(credito.id),
                    "cliente_id": str(credito.cliente_id),
                    "venta_id": str(credito.venta_id),
                    "monto_total": credito.monto_total,
                },
            )
        logger.info("fiado_abono_registrado", abono_id=str(abono.id), saldo_restante=credito.saldo_pendiente)
        return AbonoSalida.model_validate(abono)

    # --- Internas -------------------------------------------------------------------

    @staticmethod
    def _con_saldo(cliente: Cliente, saldo: int) -> ClienteConSaldo:
        base = ClienteSalida.model_validate(cliente)
        return ClienteConSaldo(
            **base.model_dump(),
            saldo_pendiente_total=saldo,
            cupo_excedido=cliente.limite_credito is not None and saldo > cliente.limite_credito,
        )

    @staticmethod
    def _resumen(credito: FiadoCredito, cliente_nombre: str | None) -> CreditoResumenSalida:
        salida = CreditoResumenSalida.model_validate(credito)
        salida.cliente_nombre = cliente_nombre
        return salida
