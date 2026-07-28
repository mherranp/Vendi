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

from app.modules.fiado.models import ESTADOS_CON_DEUDA, Cliente, FiadoCredito
from app.modules.fiado.schemas import (
    ClienteConSaldo,
    ClienteCrear,
    ClienteDetalleSalida,
    ClienteEditar,
    ClienteSalida,
    CreditoResumenSalida,
)
from vendi_core.errors.domain import ConflictError, NotFoundError

# En la Tarea 6 estos imports crecen con: FiadoAbono (models); AbonoCrear,
# AbonoSalida, CreditoDetalleSalida, CreditoReprogramar (schemas); ZONA_LOCAL
# (app.modules.caja.reportes); CajaSesion (app.modules.ventas.models);
# DomainEventService (vendi_core.events.service); ValidationError
# (vendi_core.errors.domain).

logger = structlog.get_logger()

#: Campos cuya divergencia convierte un reintento en 409 (mismo criterio que
#: `_CAMPOS_DEL_MOVIMIENTO` de caja): si alguno difiere NO es un reintento.
_CAMPOS_DEL_CLIENTE = ("nombre", "telefono", "nota", "limite_credito")
_CAMPOS_DEL_ABONO = ("monto", "metodo_pago")


def construir_whatsapp_url(cliente: Cliente, credito: FiadoCredito) -> str | None:
    """El `wa.me` prearmado (ADR-022: WhatsApp manual, coste cero — es
    exactamente cómo el tendero ya cobra). 10 dígitos = celular colombiano
    sin indicativo: se antepone 57. `None` si no hay teléfono."""
    if not cliente.telefono:
        return None
    numero = cliente.telefono if len(cliente.telefono) > 10 else "57" + cliente.telefono
    monto = f"${credito.saldo_pendiente:,}".replace(",", ".")
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

    # --- Internas (las usa también la Tarea 6) ------------------------------------

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
