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
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalogo.models import Producto
from app.modules.catalogo.schemas import ProductoSalida
from app.modules.ventas.models import CajaSesion, Dispositivo, MovimientoInventario, Venta, VentaItem
from app.modules.ventas.schemas import (
    DeltaSalida,
    DispositivoRegistrar,
    LoteSync,
    OperacionSync,
    ResultadoOperacion,
    VentaAnularSync,
    VentaCrearSync,
)
from vendi_core.errors.domain import ValidationError
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

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: str, puede_anular: bool):
        self._session = session
        self._tenant_id = tenant_id
        self._actor_id = actor_id
        #: Lo deriva el router del token (`has_permission(user, "venta:anular")`).
        #: El servicio no lee claims: recibe el veredicto (ADR-015/ADR-023).
        self._puede_anular = puede_anular
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
        self._session.add(dispositivo)
        await self._session.flush()
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
                return self._rechazada(
                    operacion, "tipo_desconocido", f"Tipo de operación desconocido: {operacion.tipo!r}."
                )
        except IntegrityError as exc:
            # La red final: una constraint saltó dentro del savepoint (ya
            # revertido). Se traduce a rechazo de dominio; el lote sigue.
            return await self._traducir_integridad(operacion, exc)

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

        productos: list[Producto] = []
        for item in datos.items:
            producto = await self._session.get(Producto, item.producto_id)
            if producto is None:
                # Otro negocio o inexistente: la RLS lo hace invisible. Un
                # producto dado de baja lógica SÍ se acepta: la venta ocurrió
                # físicamente y el precio va congelado en el ítem (ADR-018).
                return self._rechazada(
                    operacion,
                    "producto_no_encontrado",
                    "Uno de los productos de la venta no existe en tu negocio.",
                    {"producto_id": str(item.producto_id)},
                )
            productos.append(producto)

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
            for item, producto in zip(datos.items, productos, strict=True):
                await self._mover_stock(producto, -item.cantidad, referencia_id=venta.id)

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
        return ResultadoOperacion(id=operacion.id, tipo=operacion.tipo, resultado="aceptada")

    def _validar_datos(self, operacion: OperacionSync, modelo):
        """`datos` se valida POR OPERACIÓN (decisión 6): una operación mal
        formada es `rechazada` y no arrastra el lote al 422."""
        try:
            return modelo.model_validate(operacion.datos)
        except PydanticValidationError as exc:
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
        for item in await self._items_de(venta.id):
            producto = await self._session.get(Producto, item.producto_id)
            if producto is not None:
                # La referencia es el id de la OPERACIÓN de anulación: los
                # movimientos de la venta ya existen con referencia_id=venta.
                await self._mover_stock(producto, item.cantidad, referencia_id=operacion.id)
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

        La carrera de dos aperturas implícitas concurrentes la decide el
        índice único parcial `ux_caja_sesion_abierta` (ADR-021): quien pierde
        re-lee la ganadora. Una sola sesión abierta por tienda, siempre.
        """
        consulta = select(CajaSesion).where(CajaSesion.estado == "abierta")
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

    async def _mover_stock(self, producto: Producto, delta: Decimal, *, referencia_id: uuid.UUID) -> None:
        """Un movimiento en el libro + la proyección, en la misma transacción
        (ADR-020). El signo lo pone quien llama: la venta descuenta, su
        anulación repone. El stock puede quedar negativo y es legítimo."""
        self._session.add(
            MovimientoInventario(
                tenant_id=self._tenant_id,
                tipo="venta",
                cantidad=delta,
                referencia_id=referencia_id,
                producto_id=producto.id,
            )
        )
        producto.stock_actual += delta

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

        El watermark de salida (`hasta`) es `now()` DEL SERVIDOR: el reloj
        del cliente nunca arbitra el drenado (ADR-017). Las bajas lógicas
        llegan como tumbas en `eliminados` para que IndexedDB las quite.
        """
        ahora = (await self._session.execute(select(func.now()))).scalar_one()
        toco = or_(
            func.coalesce(Producto.updated_at, Producto.created_at) > desde,
            Producto.deleted_at > desde,
        )
        filas = (await self._session.execute(select(Producto).where(toco))).scalars().all()
        vivos = [ProductoSalida.model_validate(f) for f in filas if f.deleted_at is None]
        eliminados = [f.id for f in filas if f.deleted_at is not None]
        return DeltaSalida(hasta=ahora, productos=vivos, eliminados=eliminados)
