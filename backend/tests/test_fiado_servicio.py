"""`FiadoService` contra el PostgreSQL real, con el rol `vendi_app`.

Misma regla que `test_caja_servicio.py`: la base no se dobla. Aquí se fijan
los comportamientos firmados del módulo: el saldo por cliente como SUM
calculado en cada lectura (ADR-022), el cupo que nunca se materializa
(decisión 8), el abono que descuenta en la misma transacción al peso con el
CHECK como red, y el historial append-only.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.fiado.schemas import (
    AbonoCrear,
    ClienteCrear,
    ClienteEditar,
    CreditoReprogramar,
)
from app.modules.fiado.service import FiadoService
from app.modules.fiado.sync import anular_credito_de_venta
from app.modules.ventas.models import CajaSesion
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM fiado_abonos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM fiado_creditos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM clientes WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.fiado.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Un cliente en T1 con límite y otro en T2, un dispositivo y una sesión
    de caja abierta en T1 (para los abonos en efectivo). Limpieza total."""
    engine = create_async_engine(pg_platform_url)
    ids = {"cliente": uuid.uuid4(), "cliente_t2": uuid.uuid4(), "dispositivo": uuid.uuid4(), "sesion": uuid.uuid4()}
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text(
                "INSERT INTO clientes (id, tenant_id, nombre, telefono, limite_credito) "
                "VALUES (:c, :t, 'Don Carlos', '3001234567', 100000)"
            ),
            {"c": ids["cliente"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO clientes (id, tenant_id, nombre) VALUES (:c, :t, 'La vecina')"),
            {"c": ids["cliente_t2"], "t": T2},
        )
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) VALUES (:s, :t, 'dueno', 0)"),
            {"s": ids["sesion"], "t": T1},
        )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def servicio(pg_app_url: str, semilla):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield FiadoService(session=s, tenant_id=T1, actor_id="dueno-prueba")
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def _credito(
    pg_platform_url: str,
    semilla: dict,
    monto: int,
    saldo: int,
    estado: str = "vigente",
    vencimiento: str = "CURRENT_DATE + 10",
    cliente_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Un crédito por SQL (con su venta fiada): el alta de verdad es del
    sync (Tarea 7); aquí se siembra el estado ya aplicado."""
    venta_id, credito_id = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            consecutivo = (
                await conn.execute(text("SELECT count(*) FROM ventas WHERE tenant_id = :t"), {"t": T1})
            ).scalar_one() + 1
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                    "medio_pago, total_centavos, cliente_id, creada_en_cliente, secuencia_dispositivo) "
                    f"VALUES (:v, :t, :d, :s, {consecutivo}, 'fiado', :m, :c, now(), 1)"
                ),
                {
                    "v": venta_id,
                    "t": T1,
                    "d": semilla["dispositivo"],
                    "s": semilla["sesion"],
                    "m": monto,
                    "c": cliente_id or semilla["cliente"],
                },
            )
            await conn.execute(
                text(
                    f"INSERT INTO fiado_creditos (id, tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, "
                    f"fecha_vencimiento, estado) VALUES (:cr, :t, :c, :v, :m, :s, {vencimiento}, :e)"
                ),
                {
                    "cr": credito_id,
                    "t": T1,
                    "c": cliente_id or semilla["cliente"],
                    "v": venta_id,
                    "m": monto,
                    "s": saldo,
                    "e": estado,
                },
            )
    finally:
        await engine.dispose()
    return credito_id


async def _eventos(pg_platform_url: str, evento: str) -> list:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            filas = (
                await conn.execute(
                    text("SELECT payload FROM outbox_messages WHERE routing_key LIKE :k ORDER BY created_at"),
                    {"k": f"%.{evento}"},
                )
            ).all()
            return [f[0] for f in filas]
    finally:
        await engine.dispose()


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


# --- Clientes (Tarea 5) ---------------------------------------------------


@pytest.mark.asyncio
async def test_crear_cliente_y_releerlo(servicio):
    creado = await servicio.crear_cliente(
        ClienteCrear.model_validate({"nombre": "Doña Marta", "telefono": "+57 310 555 1234", "limite_credito": 50000})
    )
    assert creado.nombre == "Doña Marta" and creado.telefono == "573105551234"
    detalle = await servicio.obtener_cliente(creado.id)
    assert detalle.saldo_pendiente_total == 0 and detalle.cupo_excedido is False


@pytest.mark.asyncio
async def test_el_alta_es_idempotente_por_el_id_del_cliente(servicio):
    ancla = uuid.uuid4()
    datos = {"id": str(ancla), "nombre": "El pipe", "telefono": None}
    primero = await servicio.crear_cliente(ClienteCrear.model_validate(datos))
    segundo = await servicio.crear_cliente(ClienteCrear.model_validate(datos))
    assert segundo.id == primero.id
    with pytest.raises(ConflictError) as exc:
        await servicio.crear_cliente(ClienteCrear.model_validate({**datos, "nombre": "Otro nombre"}))
    assert exc.value.code == "cliente_id_divergente"


@pytest.mark.asyncio
async def test_el_saldo_por_cliente_es_un_sum_calculado(servicio, pg_platform_url, semilla):
    """ADR-022: el saldo NO se guarda. Vigente 40.000 + vencido 30.000 = 70.000;
    el saldado (99.000) no cuenta, y un edit al crédito se refleja al instante."""
    await _credito(pg_platform_url, semilla, 40000, 40000, estado="vigente")
    await _credito(pg_platform_url, semilla, 30000, 30000, estado="vencido", vencimiento="CURRENT_DATE - 2")
    await _credito(pg_platform_url, semilla, 99000, 0, estado="saldado")
    detalle = await servicio.obtener_cliente(semilla["cliente"])
    assert detalle.saldo_pendiente_total == 70000
    assert len(detalle.creditos) == 2  # solo los que deben


@pytest.mark.asyncio
async def test_el_cupo_es_calculado_nunca_guardado(servicio, pg_platform_url, semilla):
    """Decisión 8: límite 100.000, saldo 120.000 → excedido. Un abono que baja
    el saldo por debajo del límite apaga la señal sin tocar ninguna bandera."""
    await _credito(pg_platform_url, semilla, 120000, 120000)
    assert (await servicio.obtener_cliente(semilla["cliente"])).cupo_excedido is True
    sin_cupo = await servicio.crear_cliente(ClienteCrear.model_validate({"nombre": "Sin cupo"}))
    assert (await servicio.obtener_cliente(sin_cupo.id)).cupo_excedido is False


@pytest.mark.asyncio
async def test_el_cliente_del_vecino_es_invisible(servicio, semilla):
    with pytest.raises(NotFoundError) as exc:
        await servicio.obtener_cliente(semilla["cliente_t2"])
    assert exc.value.code == "cliente_no_encontrado"
    filas, total = await servicio.listar_clientes(None)
    assert all(f.nombre != "La vecina" for f in filas)


@pytest.mark.asyncio
async def test_editar_cliente_y_quitar_el_cupo(servicio, semilla):
    editado = await servicio.editar_cliente(
        semilla["cliente"],
        ClienteEditar.model_validate({"nombre": "Don Carlos (el de la esquina)", "limite_credito": None}),
    )
    assert editado.nombre == "Don Carlos (el de la esquina)" and editado.limite_credito is None


@pytest.mark.asyncio
async def test_buscar_por_nombre(servicio, semilla):
    filas, total = await servicio.listar_clientes("carlos")
    assert total == 1 and filas[0].nombre == "Don Carlos"
    filas, total = await servicio.listar_clientes("nadie-se-llama-así")
    assert total == 0 and filas == []


# --- Abonos, cuaderno y reprogramación (Tarea 6) ---------------------------


def _abono(monto: int, metodo: str = "efectivo", **cambios) -> AbonoCrear:
    return AbonoCrear.model_validate({"id": str(uuid.uuid4()), "monto": monto, "metodo_pago": metodo, **cambios})


@pytest.mark.asyncio
async def test_el_abono_descuenta_al_peso(servicio, pg_platform_url, semilla):
    """El candado firmado de ADR-022: crédito de 100, abonos de 30 + 30:
    saldo 40. El descuento va en la misma transacción del abono."""
    credito_id = await _credito(pg_platform_url, semilla, 100000, 100000)
    primero = await servicio.registrar_abono(credito_id, _abono(30000))
    assert primero.sesion_caja_id == semilla["sesion"]  # el efectivo cae en la sesión abierta (decisión 9)
    await servicio.registrar_abono(credito_id, _abono(30000))
    detalle = await servicio.obtener_credito(credito_id)
    assert detalle.saldo_pendiente == 40000
    assert [a.monto for a in detalle.abonos] == [30000, 30000]  # el historial (ADR-009)


@pytest.mark.asyncio
async def test_el_abono_mayor_que_el_saldo_es_422_tipado(servicio, pg_platform_url, semilla):
    """El candado de ADR-022 («abono de 41 revienta») con la traducción de la
    lección: el pre-chequeo da el 422; el CHECK es la red, no la regla."""
    credito_id = await _credito(pg_platform_url, semilla, 40000, 40000)
    with pytest.raises(ValidationError) as exc:
        await servicio.registrar_abono(credito_id, _abono(41000))
    assert exc.value.code == "abono_excede_saldo"
    assert (await servicio.obtener_credito(credito_id)).saldo_pendiente == 40000


@pytest.mark.asyncio
async def test_el_abono_que_salda_cierra_el_credito_y_emite_los_dos_eventos(servicio, pg_platform_url, semilla):
    credito_id = await _credito(pg_platform_url, semilla, 50000, 50000)
    await servicio.registrar_abono(credito_id, _abono(50000, "transferencia"))
    await servicio._session.commit()
    assert (await servicio.obtener_credito(credito_id)).estado == "saldado"
    abonos = await _eventos(pg_platform_url, "fiado.abono_registrado")
    saldados = await _eventos(pg_platform_url, "fiado.credito_saldado")
    assert len(abonos) == 1 and abonos[0]["data"]["saldo_restante"] == 0
    assert len(saldados) == 1 and saldados[0]["data"]["monto_total"] == 50000


@pytest.mark.asyncio
async def test_ni_un_saldado_ni_un_anulado_admiten_abonos(servicio, pg_platform_url, semilla):
    saldado = await _credito(pg_platform_url, semilla, 50000, 0, estado="saldado")
    anulado = await _credito(pg_platform_url, semilla, 50000, 0, estado="anulado")
    for credito_id in (saldado, anulado):
        with pytest.raises(ConflictError) as exc:
            await servicio.registrar_abono(credito_id, _abono(1000))
        assert exc.value.code == "credito_no_abonable"


@pytest.mark.asyncio
async def test_el_abono_en_efectivo_exige_caja_abierta(servicio, pg_platform_url, semilla):
    """Sin sesión abierta, el efectivo entraría a una gaveta que ningún
    arqueo mira: 409 `caja_sin_sesion_abierta` (decisión 9)."""
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE caja_sesiones SET estado = 'cerrada', cerrada_por = 'dueno', cerrada_en = now(), "
                "efectivo_esperado = 0, efectivo_contado = 0, diferencia = 0 WHERE id = :s"
            ),
            {"s": semilla["sesion"]},
        )
    await engine.dispose()
    credito_id = await _credito(pg_platform_url, semilla, 50000, 50000)
    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_abono(credito_id, _abono(10000))
    assert exc.value.code == "caja_sin_sesion_abierta"
    # La transferencia no toca la gaveta: pasa sin sesión y queda sin ella.
    abono = await servicio.registrar_abono(credito_id, _abono(10000, "transferencia"))
    assert abono.sesion_caja_id is None


@pytest.mark.asyncio
async def test_el_abono_es_idempotente_por_su_id(servicio, pg_platform_url, semilla):
    credito_id = await _credito(pg_platform_url, semilla, 80000, 80000)
    datos = _abono(20000)
    primero = await servicio.registrar_abono(credito_id, datos)
    segundo = await servicio.registrar_abono(credito_id, datos)
    assert segundo.id == primero.id
    assert (await servicio.obtener_credito(credito_id)).saldo_pendiente == 60000  # una sola vez
    # El MISMO id con otro monto no es un reintento: es divergencia (409).
    with pytest.raises(ConflictError) as exc2:
        await servicio.registrar_abono(
            credito_id, AbonoCrear.model_validate({"id": str(datos.id), "monto": 25000, "metodo_pago": "efectivo"})
        )
    assert exc2.value.code == "abono_id_divergente"
    # La nota también es parte del hecho: mismo id con otra nota no es un
    # reintento silencioso, es divergencia (409).
    with pytest.raises(ConflictError) as exc3:
        await servicio.registrar_abono(
            credito_id,
            AbonoCrear.model_validate(
                {"id": str(datos.id), "monto": 20000, "metodo_pago": "efectivo", "nota": "dejó el destajo"}
            ),
        )
    assert exc3.value.code == "abono_id_divergente"


@pytest.mark.asyncio
async def test_el_abono_al_credito_del_vecino_es_404(servicio, pg_platform_url, semilla, pg_app_url):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T2)
    try:
        async with factory() as s2:
            servicio_t2 = FiadoService(session=s2, tenant_id=T2, actor_id="dueno-t2")
            credito_de_t1 = await _credito(pg_platform_url, semilla, 50000, 50000)
            with pytest.raises(NotFoundError) as exc:
                # Transferencia: el efectivo resolvería ANTES la sesión de
                # caja (orden sesión → crédito, contra el deadlock con la
                # anulación) y T2 no tiene ninguna abierta — lo que se mide
                # aquí es que el crédito del vecino es invisible (404).
                await servicio_t2.registrar_abono(credito_de_t1, _abono(1000, "transferencia"))
            assert exc.value.code == "credito_no_encontrado"
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


@pytest.mark.asyncio
async def test_el_abono_y_la_anulacion_concurrentes_no_hacen_deadlock(servicio, pg_platform_url, semilla, pg_app_url):
    """La carrera de la revisión final: un abono en efectivo contra la
    anulación de la MISMA venta fiada. El orden de bloqueo global es sesión →
    crédito en TODOS los caminos (en ventas: productos → sesión → crédito; el
    cierre solo toma la sesión). Con el orden viejo del abono (crédito →
    sesión) este par era un deadlock: la anulación retiene la sesión y pide
    el crédito mientras el abono retenía el crédito y pedía la sesión — y el
    detector de Postgres mataba a uno con un 500 no traducido.

    La anulación reproduce el orden del camino de ventas con la sesión
    retenida un instante (la ventana en la que el abono pide sus bloqueos) y
    anula con la MISMA función que llama `_anular_venta`. El orden dominante
    —la anulación arranca antes y gana— es el afirmado: el abono, serializado
    detrás, relee el crédito ya `anulado` y sale con el 409 tipado (patrón
    asyncio.gather de los tests de carrera de caja)."""
    credito_id = await _credito(pg_platform_url, semilla, 50000, 50000)
    venta_id = uuid.UUID(
        (await _uno(pg_platform_url, "SELECT venta_id::text AS v FROM fiado_creditos WHERE id = :c", c=credito_id)).v
    )

    async def anulacion_con_sesion_retenida():
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                # Sesión FOR UPDATE primero, como `_anular_venta`. La pausa
                # con la fila retenida es la ventana en la que el abono pide
                # sus bloqueos: con el orden viejo el ciclo queda armado.
                await s.execute(select(CajaSesion).where(CajaSesion.estado == "abierta").with_for_update())
                await asyncio.sleep(0.3)
                await anular_credito_de_venta(s, T1, venta_id)
                await s.commit()
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    async def abono_con_sesion_propia():
        await asyncio.sleep(0.05)  # la anulación ya retiene la sesión
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                fiado = FiadoService(session=s, tenant_id=T1, actor_id="dueno-prueba")
                abono = await fiado.registrar_abono(credito_id, _abono(10000))
                await s.commit()
                return abono
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    resultados = await asyncio.wait_for(
        asyncio.gather(anulacion_con_sesion_retenida(), abono_con_sesion_propia(), return_exceptions=True),
        timeout=20,
    )
    anulacion, abono = resultados
    if isinstance(anulacion, BaseException):
        raise anulacion
    # La anulación ganó: el abono esperó la sesión, releyó el crédito ya
    # `anulado` y salió con el 409 tipado — nunca con un deadlock → 500.
    assert isinstance(abono, ConflictError) and abono.code == "credito_no_abonable"
    credito = await _uno(
        pg_platform_url, "SELECT estado, saldo_pendiente FROM fiado_creditos WHERE id = :c", c=credito_id
    )
    assert credito.estado == "anulado" and credito.saldo_pendiente == 0


@pytest.mark.asyncio
async def test_reprogramar_un_vencido_a_futuro_lo_devuelve_a_vigente(servicio, pg_platform_url, semilla):
    """«Deme hasta el otro viernes» (decisión 7): el `vencido` reprogramado
    vuelve a `vigente` y podrá volver a vencer con su recordatorio."""
    credito_id = await _credito(
        pg_platform_url, semilla, 50000, 50000, estado="vencido", vencimiento="CURRENT_DATE - 1"
    )
    reprogramado = await servicio.reprogramar_vencimiento(
        credito_id, CreditoReprogramar.model_validate({"fecha_vencimiento": "2099-01-15"})
    )
    assert reprogramado.estado == "vigente" and str(reprogramado.fecha_vencimiento) == "2099-01-15"
    saldado = await _credito(pg_platform_url, semilla, 50000, 0, estado="saldado")
    with pytest.raises(ConflictError) as exc:
        await servicio.reprogramar_vencimiento(
            saldado, CreditoReprogramar.model_validate({"fecha_vencimiento": "2099-01-15"})
        )
    assert exc.value.code == "credito_no_editable"


@pytest.mark.asyncio
async def test_el_cuaderno_lista_pendientes_por_defecto(servicio, pg_platform_url, semilla):
    await _credito(pg_platform_url, semilla, 40000, 40000)
    await _credito(pg_platform_url, semilla, 30000, 30000, estado="vencido", vencimiento="CURRENT_DATE - 3")
    await _credito(pg_platform_url, semilla, 99000, 0, estado="saldado")
    pendientes, total = await servicio.listar_creditos(None)
    assert total == 2 and all(c.estado in ("vigente", "vencido") for c in pendientes)
    assert all(c.cliente_nombre == "Don Carlos" for c in pendientes)
    todos, total_todos = await servicio.listar_creditos("todos")
    assert total_todos == 3
    vencidos, _ = await servicio.listar_creditos("vencido")
    assert len(vencidos) == 1 and vencidos[0].estado == "vencido"


@pytest.mark.asyncio
async def test_el_detalle_arma_el_wa_me_y_lo_omite_sin_telefono(servicio, pg_platform_url, semilla):
    # 4.300.000 centavos = $43.000: el mensaje va en PESOS, como se habla el
    # fiado — mostrar los centavos crudos inflaba la deuda 100x («$4.300.000»).
    credito_id = await _credito(pg_platform_url, semilla, 4_300_000, 4_300_000)
    detalle = await servicio.obtener_credito(credito_id)
    assert detalle.whatsapp_url is not None
    assert detalle.whatsapp_url.startswith("https://wa.me/573001234567?text=")
    assert "%2443.000" in detalle.whatsapp_url  # «$43.000» codificado
    # Con centavos de verdad se muestran los decimales: 43.050 → «$430,50».
    con_decimales = await _credito(pg_platform_url, semilla, 43050, 43050)
    assert "%24430%2C50" in (await servicio.obtener_credito(con_decimales)).whatsapp_url
    sin_telefono = await servicio.crear_cliente(ClienteCrear.model_validate({"nombre": "Sin número"}))
    # El servicio hace flush pero NUNCA commit: sin esta línea el cliente no
    # existe para la conexión de plataforma y el crédito revienta la FK.
    await servicio._session.commit()
    credito_sin = await _credito(pg_platform_url, semilla, 10000, 10000, cliente_id=sin_telefono.id)
    assert (await servicio.obtener_credito(credito_sin)).whatsapp_url is None
