"""El puente entre el lote del sync y el fiado (decisiones 1-3 del plan).

`ventas/service.py` llama a estas funciones DENTRO del SAVEPOINT de cada
operación, igual que llama a `inventario.stock.aplicar_movimiento`:

- `registrar_cliente_sync`: la operación `cliente.crear`. El cliente del
  fiado pudo nacer offline en el mismo dispositivo (ADR-018 permite fiar
  sin red), y su id del dispositivo ES la PK — el cierre de D-10 por
  adopción, mismo patrón que `ventas` y `productos`.
- `crear_credito_de_venta`: la venta fiada se convierte en crédito en la
  misma transacción del lote. El cupo se evalúa pero NUNCA se rechaza
  (ADR-018): el exceso se registra en el log y viaja en el resultado.
- `anular_credito_de_venta`: la anulación de la venta fiada anula el
  crédito. Los abonos son historia intocable (ADR-022) y la devolución del
  dinero es un gesto manual de caja (decisión 3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fiado.models import ESTADOS_CON_DEUDA, Cliente, FiadoCredito
from app.modules.fiado.schemas import ClienteCrearSync
from app.modules.ventas.models import Venta
from app.modules.ventas.schemas import OperacionSync, ResultadoOperacion
from vendi_core.events.service import DomainEventService

logger = structlog.get_logger()

#: Campos cuya divergencia convierte un reintento de `cliente.crear` en
#: `rechazada` (mismo criterio que `_CAMPOS_DEL_HECHO` de ventas).
_CAMPOS_DEL_CLIENTE = ("nombre", "telefono", "nota", "limite_credito")

#: Nombre del alta mínima que hace `crear_credito_de_venta` cuando la venta
#: fiada sube sin su `cliente.crear` (decisión 2). Es también la SEÑAL del
#: upgrade: un `cliente.crear` que encuentra este nombre no es divergente,
#: es el dato real llegando tarde (ver `registrar_cliente_sync`).
NOMBRE_PLACEHOLDER = "(sin nombre)"


def _rechazada(operacion: OperacionSync, motivo: str, mensaje: str, detalles: dict | None = None) -> ResultadoOperacion:
    logger.info("operacion_rechazada", operacion_id=str(operacion.id), motivo=motivo, mensaje=mensaje)
    return ResultadoOperacion(
        id=operacion.id,
        tipo=operacion.tipo,
        resultado="rechazada",
        motivo=motivo,
        detalles={"mensaje": mensaje, **(detalles or {})},
    )


def _duplicada(operacion: OperacionSync) -> ResultadoOperacion:
    return ResultadoOperacion(id=operacion.id, tipo=operacion.tipo, resultado="duplicada")


async def comparar_cliente_con_la_aceptada(operacion: OperacionSync, existente: Cliente) -> ResultadoOperacion:
    """La fila ya existe con la PK del cliente: ¿es el MISMO cliente?

    Payload idéntico → `duplicada` (el reintento legítimo). Cualquier campo
    distinto → `rechazada` `cliente_id_divergente` con los campos que
    difieren: jamás un no-op silencioso (lección del catálogo).

    OJO: aquí solo llegan clientes REALES. Si la fila es el placeholder
    `(sin nombre)` del alta mínima, `registrar_cliente_sync` la desvía ANTES
    al upgrade — el placeholder no tiene datos que diverjan, tiene datos que
    faltan."""
    datos = ClienteCrearSync.model_validate(operacion.datos)
    divergentes = [c for c in _CAMPOS_DEL_CLIENTE if str(getattr(existente, c)) != str(getattr(datos, c))]
    if divergentes:
        return _rechazada(
            operacion,
            "cliente_id_divergente",
            "Ese id de cliente ya existe con datos distintos. El servidor conserva la primera versión.",
            {"campos": divergentes},
        )
    return _duplicada(operacion)


async def registrar_cliente_sync(
    session: AsyncSession, tenant_id: uuid.UUID, operacion: OperacionSync
) -> ResultadoOperacion:
    """Aplica una operación `cliente.crear` del lote. Idempotente por la PK
    que puso el dispositivo (ADR-017); el choque de PK lo traduce
    `_traducir_integridad` del servicio de ventas, que es quien la llama.

    Decisión (fix post-review de la tarea 7): si la PK existe pero es el
    PLACEHOLDER `(sin nombre)` del alta mínima —la venta fiada subió antes
    que su `cliente.crear`, ADR-018 permite fiar sin red— la operación NO es
    divergente: es el dato real llegando tarde. El placeholder se MEJORA en
    el lugar (nombre/telefono/nota/limite_credito adoptan el payload) y la
    operación sale `aceptada` con `detalles.placeholder_mejorado`. Sin esto
    el cliente quedaba irrechazablemente `(sin nombre)` para siempre: todo
    `cliente.crear` posterior chocaba con la divergencia. Un cliente ya
    nombrado sigue yendo por `comparar_cliente_con_la_aceptada`, donde la
    divergencia rechaza igual que antes."""
    try:
        datos = ClienteCrearSync.model_validate(operacion.datos)
    except PydanticValidationError as exc:
        return _rechazada(
            operacion,
            "datos_invalidos",
            "Los datos de la operación no son válidos.",
            {"errores": [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()][:5]},
        )
    existente = await session.get(Cliente, operacion.id)
    if existente is not None:
        if existente.nombre == NOMBRE_PLACEHOLDER:
            existente.nombre = datos.nombre
            existente.telefono = datos.telefono
            existente.nota = datos.nota
            existente.limite_credito = datos.limite_credito
            await session.flush()
            logger.info("cliente_placeholder_mejorado", cliente_id=str(existente.id))
            return ResultadoOperacion(
                id=operacion.id,
                tipo=operacion.tipo,
                resultado="aceptada",
                detalles={"placeholder_mejorado": True},
            )
        return await comparar_cliente_con_la_aceptada(operacion, existente)
    cliente = Cliente(
        id=operacion.id,
        tenant_id=tenant_id,
        nombre=datos.nombre,
        telefono=datos.telefono,
        nota=datos.nota,
        limite_credito=datos.limite_credito,
    )
    session.add(cliente)
    # El flush puede reventar contra `clientes_pkey` (el id existe en otro
    # tenant, invisible por RLS). NO se captura aquí: un IntegrityError
    # capturado DENTRO del savepoint dejaría la transacción abortada. Se
    # deja propagar a `_aplicar_operacion` (mismo criterio que la venta).
    await session.flush()
    logger.info("cliente_registrado_sync", cliente_id=str(cliente.id))
    return ResultadoOperacion(id=operacion.id, tipo=operacion.tipo, resultado="aceptada")


async def crear_credito_de_venta(session: AsyncSession, tenant_id: uuid.UUID, venta: Venta, fecha_vencimiento) -> bool:
    """La venta fiada se convierte en crédito (ADR-022). Devuelve True si el
    cupo del cliente quedó excedido — para que la operación aceptada lo
    muestre (decisión 8). El cupo NUNCA rechaza (ADR-018).

    Si el cliente no existe en el servidor (su `cliente.crear` fue
    rechazada, o la venta se fió a un id que nunca subió), se hace el alta
    mínima con placeholder `(sin nombre)` — editable después — en vez de
    perder el fiado (decisión 2): el cuaderno nunca pierde una deuda."""
    cliente = await session.get(Cliente, venta.cliente_id)
    if cliente is None:
        cliente = Cliente(id=venta.cliente_id, tenant_id=tenant_id, nombre=NOMBRE_PLACEHOLDER)
        session.add(cliente)
        await session.flush()
        logger.info("cliente_placeholder_creado", cliente_id=str(cliente.id), venta_id=str(venta.id))
    credito = FiadoCredito(
        tenant_id=tenant_id,
        cliente_id=cliente.id,
        venta_id=venta.id,
        monto_total=venta.total_centavos,
        saldo_pendiente=venta.total_centavos,
        fecha_vencimiento=fecha_vencimiento,
        estado="vigente",
    )
    session.add(credito)
    await session.flush()
    await DomainEventService.emit(
        session,
        tenant_id=tenant_id,
        event_name="fiado.credito_creado",
        resource_type="fiado_credito",
        resource_id=str(credito.id),
        data={
            "credito_id": str(credito.id),
            "cliente_id": str(cliente.id),
            "venta_id": str(venta.id),
            "monto_total": credito.monto_total,
            "fecha_vencimiento": str(credito.fecha_vencimiento) if credito.fecha_vencimiento else None,
        },
    )
    logger.info("fiado_credito_creado", credito_id=str(credito.id), venta_id=str(venta.id))
    if cliente.limite_credito is None:
        return False
    saldo = int(
        await session.scalar(
            select(func.coalesce(func.sum(FiadoCredito.saldo_pendiente), 0)).where(
                FiadoCredito.cliente_id == cliente.id, FiadoCredito.estado.in_(ESTADOS_CON_DEUDA)
            )
        )
    )
    if saldo > cliente.limite_credito:
        logger.info("fiado_cupo_excedido", cliente_id=str(cliente.id), limite=cliente.limite_credito, saldo=saldo)
        return True
    return False


async def anular_credito_de_venta(session: AsyncSession, tenant_id: uuid.UUID, venta_id: uuid.UUID) -> None:
    """La anulación de la venta fiada anula su crédito (decisión 3):
    `anulado` con saldo 0, en el mismo SAVEPOINT. Los abonos NO se tocan —
    el historial de pagos es la verdad (ADR-022) — y la devolución del
    dinero, si la hay, es un egreso de caja manual del tendero. El evento
    lleva `total_abonado` para que esa decisión sea informada."""
    credito = (
        await session.execute(select(FiadoCredito).where(FiadoCredito.venta_id == venta_id).with_for_update())
    ).scalar_one_or_none()
    if credito is None or credito.estado == "anulado":
        return
    total_abonado = credito.monto_total - credito.saldo_pendiente
    credito.estado = "anulado"
    credito.saldo_pendiente = 0
    credito.updated_at = datetime.now(UTC)
    await session.flush()
    await DomainEventService.emit(
        session,
        tenant_id=tenant_id,
        event_name="fiado.credito_anulado",
        resource_type="fiado_credito",
        resource_id=str(credito.id),
        data={
            "credito_id": str(credito.id),
            "cliente_id": str(credito.cliente_id),
            "venta_id": str(venta_id),
            "total_abonado": total_abonado,
        },
    )
    logger.info("fiado_credito_anulado", credito_id=str(credito.id), total_abonado=total_abonado)
