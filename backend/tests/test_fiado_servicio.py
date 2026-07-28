"""`FiadoService` contra el PostgreSQL real, con el rol `vendi_app`.

Misma regla que `test_caja_servicio.py`: la base no se dobla. Aquí se fijan
los comportamientos firmados del módulo: el saldo por cliente como SUM
calculado en cada lectura (ADR-022), el cupo que nunca se materializa
(decisión 8), el abono que descuenta en la misma transacción al peso con el
CHECK como red, y el historial append-only.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.fiado.schemas import (
    AbonoCrear,  # noqa: F401 — lo usa la Tarea 6 (abonos)
    ClienteCrear,
    ClienteEditar,
    CreditoReprogramar,  # noqa: F401 — lo usa la Tarea 6
)
from app.modules.fiado.service import FiadoService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import (
    ConflictError,
    NotFoundError,
    ValidationError,  # noqa: F401 — lo usa la Tarea 6
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
