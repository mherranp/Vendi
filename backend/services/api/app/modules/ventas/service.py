"""Servicio de ventas y del sync offline: el corazón del POS (ADR-017/018/020).

## RLS hace el aislamiento; el servicio NO filtra por `tenant_id` a mano

Todo corre en la sesión de tenant (`vendi_app` + GUC `vendi.tenant_id`), que
es el «GUC del tenant en el lote» que firma ADR-017: el lote entero viaja en
una sesión cuya policy `tenant_isolation` acota lecturas y escrituras, y el
`WITH CHECK` rechaza un `tenant_id` inyectado. Los schemas además llevan
`extra="forbid"`, así que el payload ni siquiera acepta el campo.

## Una transacción por lote, un SAVEPOINT por operación (decisión 5)

`procesar_lote` hace `flush` pero NUNCA `commit`: el commit lo hace la
dependencia `sesion_de_tenant` al final del request (o el test), y con él
confirman o revientan juntas las ventas, los movimientos, el stock y los
eventos del outbox — la garantía del patrón. Cada operación corre dentro de
`begin_nested()`: un rechazo de dominio revierte SOLO esa operación y el
lote sigue; una `rechazada` nunca aborta el lote.

## Idempotencia: la fila es la prueba, la constraint es la red

No hay tabla de «ya procesados» (ADR-017): la PK que puso el cliente ES la
prueba. Reenviar la misma operación con el mismo payload es `duplicada`
(no-op, sin evento); con payload divergente es `rechazada`
`venta_id_divergente` (decisión 4: la trampa del QA del catálogo aquí es
rechazo explícito, porque hay dinero y stock de por medio). Y si una carrera
o un bug hace que algo se cuele, `ux_movimientos_origen` hace imposible
descontar dos veces el mismo origen (ADR-020).

## El reloj del cliente es dato, no árbitro

`creada_en_cliente` se guarda tal cual para el ticket; el orden de aplicación
es el de recepción (el orden del lote), los reportes suman por `recibida_en`
y el watermark del delta lo pone `now()` del servidor. Ninguna comparación de
negocio usa el reloj del dispositivo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalogo.models import Producto
from app.modules.catalogo.schemas import ProductoSalida
from app.modules.fiado.models import Cliente
from app.modules.fiado.schemas import AbonoSync
from app.modules.fiado.sync import (
    anular_credito_de_venta,
    comparar_cliente_con_la_aceptada,
    crear_credito_de_venta,
    registrar_abono_sync,
    registrar_cliente_sync,
)
from app.modules.inventario.stock import aplicar_movimiento
from app.modules.ventas.models import CajaSesion, Dispositivo, Venta, VentaItem
from app.modules.ventas.schemas import (
    DeltaSalida,
    DispositivoRegistrar,
    LoteSync,
    OperacionSync,
    ResultadoOperacion,
    VentaAnularSync,
    VentaCrearSync,
)
from vendi_core.errors.domain import ConflictError, DomainError, ValidationError
from vendi_core.events.service import DomainEventService

logger = structlog.get_logger()

#: Campos cuya divergencia convierte un reintento en `rechazada` (decisión 4):
#: los que definen el hecho de la venta. Si alguno difiere, NO es un reintento:
#: es otra venta con el mismo id, y alguien tiene que mirarla.
_CAMPOS_DEL_HECHO = (
    "consecutivo_local",
    "estado",
    "medio_pago",
    "total_centavos",
    "cliente_id",
    "creada_en_cliente",
)


class VentasService:
    """Operaciones de ventas y sync de UN negocio: el del GUC de la sesión."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        actor_id: str,
        puede_anular: bool,
        puede_fiar: bool = False,
        puede_gestionar_clientes: bool = False,
        puede_abonar: bool = False,
    ):
        self._session = session
        self._tenant_id = tenant_id
        self._actor_id = actor_id
        #: Lo deriva el router del token (`has_permission(user, "venta:anular")`).
        #: El servicio no lee claims: recibe el veredicto (ADR-015/ADR-023).
        self._puede_anular = puede_anular
        #: Mismo patrón (módulo 5, decisión 10): la venta fiada exige
        #: `fiado:crear` y la operación `cliente.crear` exige
        #: `cliente:gestionar`, ambos por operación. Fail-closed por defecto:
        #: quien construya el servicio sin los veredictos no fía ni crea
        #: clientes — los fixtures que venden fiado lo declaran.
        self._puede_fiar = puede_fiar
        self._puede_gestionar_clientes = puede_gestionar_clientes
        #: Ídem para `fiado.abonar` (cierre de D-27): el cobro offline exige
        #: `fiado:abonar` por operación — la de un almacenista es `rechazada`,
        #: no un 403 del lote.
        self._puede_abonar = puede_abonar
        #: El dispositivo del lote en curso (lo fija `procesar_lote` tras
        #: verificar que existe y es del tenant — vía RLS).
        self._dispositivo_id: uuid.UUID | None = None

    # --- Dispositivos ---------------------------------------------------------

    async def registrar_dispositivo(self, datos: DispositivoRegistrar) -> Dispositivo:
        """Alta de dispositivo. Idempotente por el UUID del cliente (ADR-017):
        re-registrar con el mismo id devuelve el existente sin duplicar."""
        if datos.id is not None:
            existente = await self._session.get(Dispositivo, datos.id)
            if existente is not None:
                return existente
        dispositivo = Dispositivo(tenant_id=self._tenant_id, nombre=datos.nombre)
        if datos.id is not None:
            dispositivo.id = datos.id
        try:
            async with self._session.begin_nested():
                # El alta va DENTRO del savepoint (mismo motivo que en
                # `_resolver_sesion_caja`): un `add` previo haría reventar el
                # INSERT fuera del savepoint y la transacción quedaría
                # abortada sin dónde revertir.
                self._session.add(dispositivo)
                await self._session.flush()
        except IntegrityError as exc:
            if "dispositivos_pkey" not in str(exc):
                # Solo el choque de la PK se traduce (mismo criterio que
                # `_traducir_integridad`): cualquier otro IntegrityError es
                # un fallo real y debe propagarse.
                raise
            # Dos registros concurrentes con el mismo id: el perdedor esperó
            # en el índice único al ganador y reventó al confirmar este. Tras
            # el rollback del savepoint se re-lee: el registro es idempotente,
            # se devuelve el existente (mismo patrón que el camino de ventas).
            existente = await self._session.get(Dispositivo, datos.id)
            if existente is not None:
                return existente
            # La fila que chocó es de OTRO negocio (invisible por RLS): no hay
            # existente que devolver. Es un conflicto tipado (409), no el 500
            # del IntegrityError original (BUG-4 del QA): el id lo generó otro
            # cliente y el choque es de dominio.
            # Sobre el oráculo («¿ese UUID existe en algún negocio?»): es
            # aceptable porque el id es un UUIDv4 inadivinable — quien puede
            # sondearlo ya lo conocía— y la respuesta no revela ningún dato
            # del tenant ajeno, solo la existencia del id en algún lugar;
            # mismo criterio que `producto_id_duplicado` del catálogo.
            raise ConflictError(
                "Ese id de dispositivo ya está en uso. Genera uno nuevo.",
                code="dispositivo_id_en_conflicto",
            ) from exc
        logger.info("dispositivo_registrado", dispositivo_id=str(dispositivo.id))
        return dispositivo

    # --- El lote --------------------------------------------------------------

    async def procesar_lote(self, lote: LoteSync) -> list[ResultadoOperacion]:
        """Aplica las operaciones de la cola de un dispositivo, en su orden.

        Una transacción (la del request), un SAVEPOINT por operación. El
        resultado es por operación y en el mismo orden del lote: el cliente
        marca como confirmadas las `aceptada` y las `duplicada`, y muestra al
        tendero las `rechazada` con su motivo.
        """
        dispositivo = await self._session.get(Dispositivo, lote.dispositivo_id)
        if dispositivo is None:
            # Un dispositivo de otro negocio es invisible por RLS: mismo 422
            # que uno inexistente (mismo criterio que `padre_no_encontrado`).
            raise ValidationError("El dispositivo no existe en tu negocio.", code="dispositivo_no_encontrado")
        self._dispositivo_id = dispositivo.id

        resultados: list[ResultadoOperacion] = []
        for operacion in lote.operaciones:
            resultado = await self._aplicar_operacion(operacion)
            resultados.append(resultado)
            if resultado.resultado == "aceptada":
                dispositivo.ultima_secuencia = max(dispositivo.ultima_secuencia, operacion.secuencia)
        dispositivo.ultima_sync = datetime.now(UTC)
        await self._session.flush()
        return resultados

    async def _aplicar_operacion(self, operacion: OperacionSync) -> ResultadoOperacion:
        """Un SAVEPOINT por operación: el rechazo revierte solo lo suyo."""
        try:
            async with self._session.begin_nested():
                if operacion.tipo == "venta.crear":
                    return await self._registrar_venta(operacion)
                if operacion.tipo == "venta.anular":
                    return await self._anular_venta(operacion)
                if operacion.tipo == "cliente.crear":
                    return await self._registrar_cliente(operacion)
                if operacion.tipo == "fiado.abonar":
                    return await self._registrar_abono(operacion)
                return self._rechazada(
                    operacion, "tipo_desconocido", f"Tipo de operación desconocido: {operacion.tipo!r}."
                )
        except IntegrityError as exc:
            # La red final: una constraint saltó dentro del savepoint (ya
            # revertido). Se traduce a rechazo de dominio; el lote sigue.
            return await self._traducir_integridad(operacion, exc)
        except DomainError as exc:
            if exc.code == "campos_desconocidos":
                # La defensa estructural de `_validar_datos` NO es un rechazo
                # por operación: es el request entero el que cae (422), como
                # antes de que existiera esta traducción.
                raise
            # Un rechazo de dominio del servicio del fiado (abono que excede
            # el saldo, crédito inexistente o no abonable, id divergente): el
            # savepoint ya se revirtió al propagar; se traduce a `rechazada`
            # por operación con el `code` como motivo y el lote sigue (cierre
            # de D-27, mismo criterio que `_traducir_integridad`).
            return self._rechazada(operacion, exc.code, exc.message, exc.details or None)

    async def _registrar_cliente(self, operacion: OperacionSync) -> ResultadoOperacion:
        """`cliente.crear` (módulo 5, decisión 2): el cliente del fiado pudo
        nacer offline; su id del dispositivo ES la PK (cierre de D-10)."""
        if not self._puede_gestionar_clientes:
            return self._rechazada(
                operacion,
                "permiso_ausente",
                "Crear clientes requiere el permiso cliente:gestionar.",
                {"permiso": "cliente:gestionar"},
            )
        return await registrar_cliente_sync(self._session, self._tenant_id, operacion)

    async def _registrar_abono(self, operacion: OperacionSync) -> ResultadoOperacion:
        """`fiado.abonar` (cierre de D-27): cobrar un fiado sin señal es tan
        normal como vender sin señal — el abono encola como cualquier otra
        operación. El permiso `fiado:abonar` se exige POR OPERACIÓN (mismo
        patrón que `puede_anular`): la operación de un almacenista es
        `rechazada`, no un 403 del lote entero."""
        if not self._puede_abonar:
            return self._rechazada(
                operacion,
                "permiso_ausente",
                "Cobrar un abono requiere el permiso fiado:abonar.",
                {"permiso": "fiado:abonar"},
            )
        datos = self._validar_datos(operacion, AbonoSync)
        if isinstance(datos, ResultadoOperacion):
            return datos
        if datos.metodo_pago == "efectivo":
            # La plata entra a la gaveta de la sesión abierta AL APLICARSE en
            # el servidor (patrón del abono online, decisión 9 del módulo
            # fiado): el `sesion_caja_id` no lo manda el cliente. Como en la
            # venta y la anulación, si no hay sesión abierta se abre la
            # implícita (ADR-018) — el cobro ocurrió físicamente y el lote no
            # lo rechaza. Va ANTES del bloqueo del crédito (sesión →
            # crédito): el orden que rompe el ciclo de espera con la
            # anulación de la venta fiada.
            await self._resolver_sesion_caja()
        return await registrar_abono_sync(self._session, self._tenant_id, self._actor_id, operacion, datos)

    @staticmethod
    def _rechazada(
        operacion: OperacionSync, motivo: str, mensaje: str, detalles: dict | None = None
    ) -> ResultadoOperacion:
        logger.info("operacion_rechazada", operacion_id=str(operacion.id), motivo=motivo, mensaje=mensaje)
        return ResultadoOperacion(
            id=operacion.id,
            tipo=operacion.tipo,
            resultado="rechazada",
            motivo=motivo,
            detalles={"mensaje": mensaje, **(detalles or {})},
        )

    @staticmethod
    def _duplicada(operacion: OperacionSync) -> ResultadoOperacion:
        logger.info("operacion_duplicada", operacion_id=str(operacion.id), tipo=operacion.tipo)
        return ResultadoOperacion(id=operacion.id, tipo=operacion.tipo, resultado="duplicada")

    async def _traducir_integridad(self, operacion: OperacionSync, exc: IntegrityError) -> ResultadoOperacion:
        detalle = str(exc)
        if "ux_ventas_consecutivo" in detalle:
            return self._rechazada(
                operacion,
                "consecutivo_duplicado",
                "Ese número de venta ya se usó en este dispositivo.",
            )
        if "ux_movimientos_origen" in detalle:
            # El movimiento de este origen ya existe: la operación se aplicó
            # antes (carrera de reintentos). Es duplicada, no error (ADR-020).
            return self._duplicada(operacion)
        if "ventas_pkey" in detalle:
            # El id choca con una fila ya insertada. Dos casos: la fila es de
            # OTRO negocio (la RLS la hace invisible) o es la MISMA venta que
            # un request concurrente acaba de aplicar — era invisible al leerla
            # (READ COMMITTED) y visible tras el commit del ganador. Tras el
            # rollback del savepoint se re-lee: idéntica → duplicada; divergente
            # o invisible → rechazada venta_id_divergente (decisión 4).
            existente = await self._session.get(Venta, operacion.id)
            if existente is not None:
                # Los datos ya se validaron en `_registrar_venta` antes del
                # flush que reventó: el model_validate no puede fallar aquí.
                datos = VentaCrearSync.model_validate(operacion.datos)
                return await self._comparar_con_la_aceptada(operacion, existente, datos)
            return self._rechazada(operacion, "venta_id_divergente", "Ese id de venta ya existe.")
        if "clientes_pkey" in detalle:
            # El id choca con una fila ya insertada (misma lógica que
            # `ventas_pkey`): si es visible, es el MISMO cliente (duplicada o
            # divergente); si no, es de otro negocio → rechazada tipada.
            if operacion.tipo == "cliente.crear":
                existente = await self._session.get(Cliente, operacion.id)
                if existente is not None:
                    return await comparar_cliente_con_la_aceptada(operacion, existente)
                return self._rechazada(operacion, "cliente_id_divergente", "Ese id de cliente ya existe.")
            # La única otra operación que inserta en `clientes` es la auto-alta
            # del placeholder de la venta fiada (`crear_credito_de_venta`): el
            # choque contra la PK invisible por RLS significa que el
            # `cliente_id` de la venta NO existe para este tenant. El motivo
            # honesto es `cliente_no_encontrado` (C-2 del QA adversarial): no
            # es un oráculo — no confirma que el id exista en otro negocio,
            # solo que no es usable aquí — y describe lo que pasó, a
            # diferencia del `cliente_id_divergente` anterior.
            return self._rechazada(
                operacion,
                "cliente_no_encontrado",
                "El cliente de la venta fiada no existe en tu negocio.",
                {"cliente_id": operacion.datos.get("cliente_id")},
            )
        if "ux_fiado_creditos_venta" in detalle:
            # El crédito de esta venta ya existe: la operación se aplicó
            # antes (carrera de reintentos). Es duplicada, no error — mismo
            # criterio que `ux_movimientos_origen` (ADR-020).
            return self._duplicada(operacion)
        raise

    # --- venta.crear ------------------------------------------------------------

    async def _registrar_venta(self, operacion: OperacionSync) -> ResultadoOperacion:
        datos = self._validar_datos(operacion, VentaCrearSync)
        if isinstance(datos, ResultadoOperacion):
            return datos

        existente = await self._session.get(Venta, operacion.id)
        if existente is not None:
            return await self._comparar_con_la_aceptada(operacion, existente, datos)

        error = self._reglas_de_negocio(operacion, datos)
        if error is not None:
            return error

        if datos.medio_pago == "fiado" and not self._puede_fiar:
            return self._rechazada(
                operacion,
                "permiso_ausente",
                "Fiar requiere el permiso fiado:crear.",
                {"permiso": "fiado:crear"},
            )

        # El libro se CONSOLIDA por producto (BUG-1 del QA):
        # `ux_movimientos_origen` es por (tipo, referencia_id, producto_id),
        # así que dos líneas del mismo producto en un ticket chocaban entre sí
        # y la venta se perdía tras una mistraducción a `duplicada`. Un
        # movimiento por (venta, producto) con la cantidad sumada; las líneas
        # del ticket (`ventas_items`) quedan tal cual. La consolidación va en
        # el ORDEN DEL TICKET: ese es el orden en que se insertan los
        # movimientos más abajo (ningún índice ni la lógica imponen uno —
        # `ux_movimientos_origen` es unico por clave, no por posición—, pero
        # el orden del ticket es el que el cliente ve y no hay motivo para
        # permutarlo).
        cantidad_por_producto: dict[uuid.UUID, Decimal] = {}
        for item in datos.items:
            cantidad_por_producto[item.producto_id] = cantidad_por_producto.get(item.producto_id, Decimal(0)) + (
                item.cantidad
            )

        productos: dict[uuid.UUID, Producto] = {}
        for producto_id in sorted(cantidad_por_producto):
            # SELECT ... FOR UPDATE sobre la fila del producto, ORDENADO por
            # producto_id (cierre de D-21, la misma receta que la compra —
            # decisión 9—): dos lotes concurrentes con el mismo surtido en
            # orden inverso adquieren los bloqueos en el MISMO orden y no se
            # interbloquean; lo único que cambia respecto al orden del ticket
            # es el orden de ADQUISICIÓN de los bloqueos, no el de los
            # movimientos. Sin el bloqueo, dos lotes concurrentes del mismo
            # tenant que venden el mismo producto leen el MISMO `stock_actual`
            # y el segundo commit pisa al primero con un valor stale (lost
            # update: el libro `movimientos_inventario` queda exacto pero la
            # proyección deriva). Se eligió el bloqueo de fila sobre un UPDATE
            # atómico (`stock_actual = stock_actual + :delta`): es lo
            # conservador y consistente con el FOR UPDATE de la anulación, y
            # mantiene el objeto ORM sincronizado para el resto del lote. El
            # perdedor espera al commit del ganador y re-lee el stock ya
            # descontado.
            producto = await self._session.get(Producto, producto_id, with_for_update=True)
            if producto is None:
                # Otro negocio o inexistente: la RLS lo hace invisible. Un
                # producto dado de baja lógica SÍ se acepta: la venta ocurrió
                # físicamente y el precio va congelado en el ítem (ADR-018).
                return self._rechazada(
                    operacion,
                    "producto_no_encontrado",
                    "Uno de los productos de la venta no existe en tu negocio.",
                    {"producto_id": str(producto_id)},
                )
            productos[producto_id] = producto

        sesion = await self._resolver_sesion_caja()

        assert self._dispositivo_id is not None  # lo fija procesar_lote al validar el dispositivo
        venta = Venta(
            id=operacion.id,
            tenant_id=self._tenant_id,
            dispositivo_id=self._dispositivo_id,
            sesion_caja_id=sesion.id,
            consecutivo_local=datos.consecutivo_local,
            estado=datos.estado,
            medio_pago=datos.medio_pago,
            total_centavos=datos.total_centavos,
            cliente_id=datos.cliente_id,
            creada_en_cliente=datos.creada_en_cliente,
            secuencia_dispositivo=operacion.secuencia,
        )
        self._session.add(venta)
        # El flush puede reventar contra `ux_ventas_consecutivo` (otra venta
        # con el mismo número en este dispositivo) o `ventas_pkey` (el id
        # existe en otro tenant, invisible por RLS). NO se captura aquí: un
        # IntegrityError capturado DENTRO del savepoint dejaría la
        # transacción abortada. Se deja propagar a `_aplicar_operacion`,
        # cuyo `begin_nested()` revierte solo esta operación antes de
        # traducir el error en `_traducir_integridad`.
        await self._session.flush()

        for item in datos.items:
            self._session.add(
                VentaItem(
                    tenant_id=self._tenant_id,
                    venta_id=venta.id,
                    producto_id=item.producto_id,
                    cantidad=item.cantidad,
                    precio_unitario_centavos=item.precio_unitario_centavos,
                )
            )

        # Una venta que sube ya anulada no mueve stock (decisión 9): su efecto
        # neto es cero y el libro queda limpio.
        if datos.estado == "completada":
            # En el ORDEN DEL TICKET (la consolidación), no en el orden
            # ordenado en que se tomaron los bloqueos: los movimientos del
            # libro quedan como antes del cierre de D-21.
            for producto_id, cantidad in cantidad_por_producto.items():
                await self._mover_stock(productos[producto_id], -cantidad, referencia_id=venta.id)

        cupo_excedido = False
        if datos.estado == "completada" and datos.medio_pago == "fiado" and venta.total_centavos > 0:
            # La venta fiada se convierte en crédito EN LA MISMA TRANSACCIÓN
            # (módulo 5, decisión 1): confirman o revientan juntas. Un fiado
            # de total 0 no genera crédito (no hay nada que deber). El cupo
            # se evalúa pero NUNCA se rechaza (ADR-018): el exceso viaja en
            # `detalles` para que la app lo muestre al confirmar el sync.
            cupo_excedido = await crear_credito_de_venta(self._session, self._tenant_id, venta, datos.fecha_vencimiento)

        await self._emitir(
            "venta.creada",
            venta,
            data={
                "venta_id": str(venta.id),
                "dispositivo_id": str(venta.dispositivo_id),
                "consecutivo_local": venta.consecutivo_local,
                "estado": venta.estado,
                "medio_pago": venta.medio_pago,
                "total_centavos": venta.total_centavos,
                "cliente_id": str(venta.cliente_id) if venta.cliente_id else None,
                "sesion_caja_id": str(venta.sesion_caja_id),
                "items": [
                    {
                        "producto_id": str(i.producto_id),
                        "cantidad": str(i.cantidad),
                        "precio_unitario_centavos": i.precio_unitario_centavos,
                    }
                    for i in datos.items
                ],
            },
        )
        logger.info("venta_registrada", venta_id=str(venta.id), estado=venta.estado)
        return ResultadoOperacion(
            id=operacion.id,
            tipo=operacion.tipo,
            resultado="aceptada",
            detalles={"cupo_excedido": True} if cupo_excedido else None,
        )

    def _validar_datos(self, operacion: OperacionSync, modelo):
        """`datos` se valida POR OPERACIÓN (decisión 6): una operación mal
        formada es `rechazada` y no arrastra el lote al 422.

        Excepción estructural: un campo que el schema NO CONOCE
        (`extra="forbid"`) no es contenido inválido — es un payload que
        habla otro idioma (un bug del cliente, o un `tenant_id` inyectado)
        y su lugar es el 422 del request entero, como defensa en profundidad
        del WITH CHECK de la RLS (ADR-017). El contenido mal formado (tipos,
        cotas, requeridos) sí sigue siendo `rechazada` por operación."""
        try:
            return modelo.model_validate(operacion.datos)
        except PydanticValidationError as exc:
            if any(error["type"] == "extra_forbidden" for error in exc.errors()):
                raise ValidationError(
                    "Los datos de una operación traen campos que el contrato no conoce.",
                    code="campos_desconocidos",
                    details={"operacion_id": str(operacion.id)},
                ) from exc
            return self._rechazada(
                operacion,
                "datos_invalidos",
                "Los datos de la operación no son válidos.",
                {"errores": [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()][:5]},
            )

    def _reglas_de_negocio(self, operacion: OperacionSync, datos: VentaCrearSync) -> ResultadoOperacion | None:
        """Fiado⇔cliente (ADR-018: «cliente_id NULL salvo fiado») y coherencia
        total/ítems (decisión 14): rechazos de dominio, por operación."""
        if datos.medio_pago == "fiado" and datos.cliente_id is None:
            return self._rechazada(
                operacion,
                "fiado_requiere_cliente",
                "Una venta fiada debe traer el cliente al que se le fía.",
            )
        if datos.medio_pago != "fiado" and datos.cliente_id is not None:
            return self._rechazada(
                operacion,
                "cliente_solo_en_fiado",
                "Solo una venta fiada lleva cliente.",
            )
        if datos.medio_pago != "fiado" and datos.fecha_vencimiento is not None:
            return self._rechazada(
                operacion,
                "fecha_vencimiento_solo_en_fiado",
                "Solo una venta fiada lleva fecha de vencimiento.",
            )
        suma = sum(i.cantidad * i.precio_unitario_centavos for i in datos.items)
        if suma != datos.total_centavos:
            return self._rechazada(
                operacion,
                "total_incoherente",
                "El total no cuadra con la suma de las líneas.",
                {"total_declarado": datos.total_centavos, "suma_de_items": str(suma)},
            )
        return None

    async def _comparar_con_la_aceptada(
        self, operacion: OperacionSync, existente: Venta, datos: VentaCrearSync
    ) -> ResultadoOperacion:
        """La fila ya existe con la PK del cliente: ¿es el MISMO hecho?

        Payload idéntico → `duplicada` (el reintento legítimo). Cualquier
        campo del hecho distinto → `rechazada` `venta_id_divergente` con los
        campos que difieren (decisión 4): jamás un no-op silencioso.
        """
        divergentes: list[str] = []
        for campo in _CAMPOS_DEL_HECHO:
            guardado = getattr(existente, campo)
            enviado = getattr(datos, campo)
            if campo == "creada_en_cliente":
                if guardado.replace(microsecond=0) != enviado.replace(microsecond=0):
                    divergentes.append(campo)
            elif str(guardado) != str(enviado):
                divergentes.append(campo)
        items_guardados = sorted(
            (str(i.producto_id), str(i.cantidad), i.precio_unitario_centavos)
            for i in await self._items_de(existente.id)
        )
        items_enviados = sorted(
            (str(i.producto_id), str(i.cantidad.normalize()), i.precio_unitario_centavos) for i in datos.items
        )
        # La cantidad guardada viene de NUMERIC(14,3) (p. ej. 1.000) y la
        # enviada de Decimal ("1"): se comparan como Decimal.
        if [(p, str(Decimal(c).normalize()), pr) for p, c, pr in items_guardados] != items_enviados:
            divergentes.append("items")
        if divergentes:
            return self._rechazada(
                operacion,
                "venta_id_divergente",
                "Ese id de venta ya existe con datos distintos. El servidor conserva la primera versión.",
                {"campos": divergentes},
            )
        return self._duplicada(operacion)

    async def _items_de(self, venta_id: uuid.UUID) -> list[VentaItem]:
        consulta = select(VentaItem).where(VentaItem.venta_id == venta_id)
        return list((await self._session.execute(consulta)).scalars().all())

    # --- venta.anular -----------------------------------------------------------

    async def _anular_venta(self, operacion: OperacionSync) -> ResultadoOperacion:
        """La anulación es una operación NUEVA, no destructiva (ADR-018):
        marca `completada → anulada` (la única mutación permitida), repone el
        stock con el delta inverso y emite `venta.anulada`. La venta original
        —ítems, totales, su evento `venta.creada`— no se toca."""
        if not self._puede_anular:
            return self._rechazada(
                operacion,
                "permiso_ausente",
                "Anular una venta requiere el permiso venta:anular.",
                {"permiso": "venta:anular"},
            )
        datos = self._validar_datos(operacion, VentaAnularSync)
        if isinstance(datos, ResultadoOperacion):
            return datos

        venta = await self._session.get(Venta, datos.venta_id, with_for_update=True)
        # SELECT ... FOR UPDATE: sin el bloqueo de la fila, dos requests
        # concurrentes (READ COMMITTED) pueden leer ambos `completada` y
        # reponer el stock DOS veces — `ux_movimientos_origen` NO los deduplica
        # porque cada uno referencia los movimientos a SU id de operación.
        # Con el bloqueo, el perdedor espera al commit del ganador y re-lee
        # `anulada`: sale como `duplicada` sin reponer ni re-emitir.
        if venta is None:
            return self._rechazada(operacion, "venta_no_encontrada", "La venta a anular no existe en tu negocio.")
        if venta.estado == "anulada":
            # Ya estaba anulada: reintento (mismo id u otro) → duplicada. No
            # se repone el stock dos veces ni se re-emite el evento.
            return self._duplicada(operacion)

        venta.estado = "anulada"
        # La reposición se consolida por producto, igual que el descuento del
        # alta (BUG-1): dos líneas del mismo producto son UN movimiento con la
        # cantidad sumada, no dos que chocarían en `ux_movimientos_origen`.
        cantidad_por_producto: dict[uuid.UUID, Decimal] = {}
        for item in await self._items_de(venta.id):
            cantidad_por_producto[item.producto_id] = cantidad_por_producto.get(item.producto_id, Decimal(0)) + (
                item.cantidad
            )
        for producto_id, cantidad in cantidad_por_producto.items():
            # FOR UPDATE como en el alta: la reposición también toca
            # `stock_actual`, y la misma carrera de lost update aplica si un
            # lote vende el producto mientras otro anula una venta suya.
            producto = await self._session.get(Producto, producto_id, with_for_update=True)
            if producto is not None:
                # La referencia es el id de la OPERACIÓN de anulación y el
                # tipo es `anulacion` (BUG-3 del QA): con tipo `venta`, una
                # anulación cuyo id de operación coincide con el id de la
                # venta chocaba contra los movimientos originales en
                # `ux_movimientos_origen` y salía `duplicada` sin anular.
                # El índice sigue deduplicando el reintento por (tipo,
                # referencia_id=operacion.id, producto_id).
                await self._mover_stock(producto, cantidad, tipo="anulacion", referencia_id=operacion.id)
        # La sesión de caja se resuelve (FOR UPDATE) ANTES de estampar
        # `anulada_en` — el mismo candado que `_registrar_venta` (decisión 5
        # del plan de caja), aquí por los dos huecos que dejaba estampar a
        # ciegas (I-1/I-2 de la revisión final de caja):
        # - Sin sesión abierta (entre el cierre de la noche y la apertura de
        #   mañana), la marca caía en el hueco: fuera de la ventana de la
        #   sesión cerrada y de la siguiente, y la devolución de efectivo
        #   desaparecía de TODO arqueo. El resolvedor abre la implícita y
        #   `abierta_en <= anulada_en` queda garantizado.
        # - La carrera con el cierre se serializa sobre la fila: si el cierre
        #   ganó, la consulta (que filtra `abierta`) ya no lo ve y la
        #   anulación cae en la implícita nueva; si ganó la anulación, el
        #   `calcular_desglose` del cierre la ve `anulada` y entra al SUM
        #   congelado. Nunca `anulada_en < cerrada_en` sin haber entrado.
        # Va DESPUÉS de los bloqueos de productos (mismo orden que
        # `_registrar_venta`: productos → sesión; el cierre solo toma la
        # sesión): el orden global es productos → sesión → crédito del fiado
        # — el crédito se bloquea DESPUÉS, en `anular_credito_de_venta`, y el
        # abono en efectivo del fiado respeta el mismo orden (sesión →
        # crédito), así que no hay ciclo de espera. Y corre dentro del
        # savepoint de la operación, como en el alta: un rechazo posterior
        # revierte también la implícita.
        await self._resolver_sesion_caja()
        # La marca de CUÁNDO se anuló (módulo 4, decisión 7 del plan de
        # caja): con ella, la devolución de efectivo de una venta anulada
        # tras el cierre cae en la sesión abierta en ese momento (ADR-021)
        # sin duplicar la venta como movimiento de caja. La venta CONSERVA
        # su `sesion_caja_id` original: `calcular_desglose` ubica la
        # devolución por la ventana `[abierta_en, cerrada_en)` que contiene
        # esta marca, no por la sesión de la venta.
        venta.anulada_en = datetime.now(UTC)
        if venta.medio_pago == "fiado":
            # La anulación de la venta fiada anula el crédito en la misma
            # transacción (módulo 5, decisión 3): los abonos son historia
            # intocable (ADR-022) y la devolución del dinero es un gesto de
            # caja MANUAL del tendero — «déjelo ahí a favor» es tan legítimo
            # como devolverla, y automatizarla decidiría por él.
            await anular_credito_de_venta(self._session, self._tenant_id, venta.id)
        await self._emitir(
            "venta.anulada",
            venta,
            data={
                "venta_id": str(venta.id),
                "dispositivo_id": str(venta.dispositivo_id),
                "consecutivo_local": venta.consecutivo_local,
                "total_centavos": venta.total_centavos,
                "medio_pago": venta.medio_pago,
            },
        )
        logger.info("venta_anulada", venta_id=str(venta.id))
        return ResultadoOperacion(id=operacion.id, tipo=operacion.tipo, resultado="aceptada")

    # --- Internas ---------------------------------------------------------------

    async def _resolver_sesion_caja(self) -> CajaSesion:
        """La sesión abierta del tenant, o una implícita nueva (ADR-018).

        La sesión abierta se lee con `FOR UPDATE` (módulo 4, decisión 5 del
        plan de caja): sin el bloqueo hay una carrera real con el cierre — el
        sync resuelve la sesión abierta, el cierre confirma en medio, y la
        venta inserta contra una sesión ya `cerrada`, huérfana de todo
        arqueo. Con el bloqueo, cierre y sync se serializan sobre la fila:
        quien llega segundo la ve `cerrada` (la consulta filtra `abierta`) y
        abre una implícita nueva. El orden de bloqueo es consistente entre
        módulos: productos → sesión → crédito del fiado. Los dos caminos que
        lo llaman (`_registrar_venta` y `_anular_venta`) toman la sesión
        DESPUÉS de los productos, la anulación toma DESPUÉS el crédito (vía
        `anular_credito_de_venta`), el abono en efectivo del fiado toma la
        sesión ANTES que el crédito y el cierre solo toma la sesión — nadie
        pide un bloqueo «hacia atrás», así que no hay ciclo de espera.

        La carrera de dos aperturas implícitas concurrentes la decide el
        índice único parcial `ux_caja_sesion_abierta` (ADR-021): quien pierde
        re-lee la ganadora. Una sola sesión abierta por tienda, siempre.
        """
        # FOR UPDATE desde el módulo 4 (decisión 5 del plan de caja): sin el
        # bloqueo, el sync puede resolver la sesión abierta, el CIERRE
        # confirmar en medio, y la venta insertar contra una sesión ya
        # `cerrada` — huérfana de todo arqueo. Con él, cierre y sync se
        # serializan sobre la fila: quien llega segundo la ve `cerrada` (la
        # consulta filtra `abierta`) y abre una implícita nueva. El orden de
        # bloqueo es consistente entre módulos: productos → sesión → crédito
        # del fiado. Quien llama toma la sesión DESPUÉS de los productos
        # (tanto `_registrar_venta` como `_anular_venta`), la anulación toma
        # DESPUÉS el crédito (vía `anular_credito_de_venta`), el abono en
        # efectivo del fiado toma la sesión ANTES que el crédito y el cierre
        # solo toma la sesión — nadie pide un bloqueo «hacia atrás», así que
        # no hay ciclo de espera. El costo (lotes concurrentes del mismo
        # tenant serializados en la fila) es despreciable a la escala de una
        # tienda.
        consulta = select(CajaSesion).where(CajaSesion.estado == "abierta").with_for_update()
        sesion = (await self._session.execute(consulta)).scalar_one_or_none()
        if sesion is not None:
            return sesion
        try:
            async with self._session.begin_nested():
                # El alta va DENTRO del savepoint: `begin_nested()` hace flush
                # de lo pendiente al tomar su snapshot, ANTES de emitir el
                # SAVEPOINT — un `add` previo haría reventar el INSERT fuera
                # del savepoint y la transacción quedaría abortada sin dónde
                # revertir (InvalidRequestError en el re-read de la ganadora).
                nueva = CajaSesion(tenant_id=self._tenant_id, abierta_por=self._actor_id, base_inicial=0)
                self._session.add(nueva)
                await self._session.flush()
        except IntegrityError as exc:
            if "ux_caja_sesion_abierta" not in str(exc):
                # Solo el choque de la apertura concurrente se traduce (mismo
                # criterio que `_traducir_integridad`): cualquier otro
                # IntegrityError es un fallo real y debe propagarse, no
                # esconderse tras un re-read sobre una sesión rota.
                raise
            # Otro request abrió la sesión primero: se usa la ganadora.
            sesion = (await self._session.execute(consulta)).scalar_one()
            return sesion
        logger.info("caja_sesion_implicita_abierta", sesion_id=str(nueva.id))
        return nueva

    async def _mover_stock(
        self, producto: Producto, delta: Decimal, *, referencia_id: uuid.UUID, tipo: str = "venta"
    ) -> None:
        """Un movimiento en el libro + la proyección + la alerta de umbral,
        todo en la misma transacción (ADR-020). El signo lo pone quien llama:
        la venta descuenta (`tipo='venta'`), su anulación repone
        (`tipo='anulacion'`). El stock puede quedar negativo y es legítimo.

        Desde el módulo 3, la aplicación vive en el punto único
        `inventario.stock.aplicar_movimiento` (decisión 1 del plan de
        inventario): es lo que hace que una venta que cruza el umbral emita
        `inventario.alerta_stock` sin que este servicio sepa nada de niveles.

        Quien llama carga el producto con `with_for_update=True` (ver
        `_registrar_venta` y `_anular_venta`): el read-modify-write de
        `stock_actual` solo es seguro con la fila bloqueada hasta el commit."""
        await aplicar_movimiento(
            self._session,
            tenant_id=self._tenant_id,
            producto=producto,
            delta=delta,
            tipo=tipo,
            referencia_id=referencia_id,
        )

    async def _emitir(self, evento: str, venta: Venta, *, data: dict) -> None:
        """Una sola vez por operación aceptada (ADR-017): el que llama aquí ya
        sabe que la operación va a confirmar; `duplicada` y `rechazada` nunca
        llegan. La policy del outbox ata el tenant_id al GUC."""
        await DomainEventService.emit(
            self._session,
            tenant_id=self._tenant_id,
            event_name=evento,
            resource_type="venta",
            resource_id=str(venta.id),
            data=data,
        )

    # --- Delta ------------------------------------------------------------------

    async def delta_productos(self, desde: datetime) -> DeltaSalida:
        """Los cambios del catálogo desde el watermark del dispositivo.

        El watermark de salida (`hasta`) lo pone el reloj DEL SERVIDOR, nunca
        el del cliente (ADR-017), y lleva un margen de 5 segundos: es
        `now() - interval '5 seconds'`, no `now()` pelado. Sin el margen, una
        edición cuya transacción confirmó ENTRE la captura del watermark y la
        lectura (su `updated_at` quedó por debajo del `hasta`) no llegaba en
        esta respuesta ni en ninguna posterior — el próximo `desde` del
        dispositivo ya era mayor que su `updated_at` y el catálogo quedaba
        stale en silencio (deuda D-18). El margen re-entrega lo confirmado en
        la ventana, y el solape es inocuo porque el cliente hace upsert por
        id (ver el docstring del endpoint `/sync/delta`). Las bajas lógicas
        llegan como tumbas en `eliminados` para que IndexedDB las quite.
        """
        ahora = (await self._session.execute(select(func.now() - text("interval '5 seconds'")))).scalar_one()
        toco = or_(
            func.coalesce(Producto.updated_at, Producto.created_at) > desde,
            Producto.deleted_at > desde,
        )
        filas = (await self._session.execute(select(Producto).where(toco))).scalars().all()
        vivos = [ProductoSalida.model_validate(f) for f in filas if f.deleted_at is None]
        eliminados = [f.id for f in filas if f.deleted_at is not None]
        return DeltaSalida(hasta=ahora, productos=vivos, eliminados=eliminados)
