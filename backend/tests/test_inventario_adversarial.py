"""QA adversarial de inventario: ataques sobre stock, alertas, compras y ajustes.

Compañero de `test_inventario_servicio.py` y `test_inventario_alertas.py`, no
sustituto: aquello fija el camino feliz, la idempotencia y el mapa de niveles;
esto empuja las esquinas que el plan deja en penumbra — la merma como emisora
de alertas, el cruce de dos niveles de golpe, el nivel derivado del mínimo
VIGENTE (no del que había al alertar), dos ventas concurrentes que cruzan
juntas, dos compras concurrentes con los productos en orden inverso (la
regresión del deadlock), el tope de 200 ítems, la atomicidad de la compra que
revienta a mitad, los ids del vecino y la frontera del sync— y deja cada
comportamiento FIJO en un test.

Tres de estos tests DOCUMENTAN comportamientos discutibles a propósito (el
ajuste con id de OTRO tenant que sale 409 `ajuste_id_divergente`, el reintento
de un ajuste cuyo producto fue dado de baja entre intento y reintento que sale
422 en vez de devolver lo ya respondido, y la compra de costo cero que deja
`ultimo_costo = 0`): el assert es el comportamiento actual y la discusión vive
en `.superpowers/sdd/qa-adversarial-inventario-report.md`. Si alguno cambia a
un comportamiento distinto, el test se reescribe, no se borra.

El BUG encontrado (el cajero recibe `ultimo_costo` por `producto:leer`, contra
la decisión 10 del plan) NO tiene test aquí: está en el reporte con su
reproducción exacta, porque un test que lo fijara sería un test que documenta
el margen del negocio regalado.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from pydantic import ValidationError as ErrorDeEsquema
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.catalogo.models import Producto
from app.modules.inventario.schemas import AjusteCrear, CompraCrear
from app.modules.inventario.service import InventarioService
from app.modules.inventario.stock import aplicar_movimiento
from app.modules.ventas.schemas import LoteSync
from app.modules.ventas.service import VentasService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import ConflictError, ValidationError
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compra_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compras WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ajustes_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.inventario.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.compra.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """El escenario base del ataque: T1 con un dispositivo, un producto con
    stock 10 y mínimo 4 (mapa de niveles de ADR-020), un producto con stock 3
    y mínimo 0 (sin bajo ni crítico: el primer nivel alcanzable es agotado) y,
    en T2, un producto del vecino para las pruebas de aislamiento."""
    ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4(), "producto2": uuid.uuid4(), "ajeno": uuid.uuid4()}
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
        )
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual, stock_minimo) "
                "VALUES (:p, :t, 'Arroz 500g', 2500, 10, 4)"
            ),
            {"p": ids["producto"], "t": T1},
        )
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual, stock_minimo) "
                "VALUES (:p, :t, 'Huevo und', 600, 3, 0)"
            ),
            {"p": ids["producto2"], "t": T1},
        )
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                "VALUES (:p, :t, 'Panela del vecino', 1800, 7)"
            ),
            {"p": ids["ajeno"], "t": T2},
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
            yield InventarioService(session=s, tenant_id=T1, actor_id="qa-adversarial")
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


def _compra(semilla: dict, compra_id: uuid.UUID | None = None, **cambios) -> CompraCrear:
    cuerpo = {
        "proveedor_nombre": "Distribuidora La 33",
        "items": [{"producto_id": str(semilla["producto"]), "cantidad": "10", "costo_unitario_centavos": 2000}],
        **cambios,
    }
    if compra_id is not None:
        cuerpo["id"] = str(compra_id)
    return CompraCrear.model_validate(cuerpo)


def _ajuste(semilla: dict, ajuste_id: uuid.UUID, **cambios) -> AjusteCrear:
    cuerpo = {
        "id": str(ajuste_id),
        "tipo": "ajuste",
        "producto_id": str(semilla["producto"]),
        "stock_contado": "8",
        "motivo": "Conteo de cierre",
        **cambios,
    }
    return AjusteCrear.model_validate(cuerpo)


def _merma(semilla: dict, ajuste_id: uuid.UUID, cantidad: str, **cambios) -> AjusteCrear:
    datos = {"tipo": "merma", "cantidad": cantidad, "stock_contado": None, "motivo": "Se dañó", **cambios}
    return _ajuste(semilla, ajuste_id, **datos)


def _lote(semilla: dict, *operaciones: dict) -> LoteSync:
    return LoteSync.model_validate({"dispositivo_id": str(semilla["dispositivo"]), "operaciones": list(operaciones)})


def _op_venta(semilla: dict, cantidad: str, consecutivo: int) -> dict:
    total = int(Decimal(cantidad) * 2500)
    return {
        "id": str(uuid.uuid4()),
        "tipo": "venta.crear",
        "secuencia": consecutivo,
        "datos": {
            "consecutivo_local": consecutivo,
            "medio_pago": "efectivo",
            "total_centavos": total,
            "creada_en_cliente": "2026-07-28T10:00:00+00:00",
            "items": [
                {"producto_id": str(semilla["producto"]), "cantidad": cantidad, "precio_unitario_centavos": 2500}
            ],
        },
    }


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


async def _stock(pg_platform_url: str, producto_id: uuid.UUID) -> Decimal:
    fila = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=producto_id)
    return fila.stock_actual


async def _alertas(pg_platform_url: str) -> list[str]:
    """Los niveles de las alertas de T1, en orden de emisión."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            filas = (
                (
                    await conn.execute(
                        text(
                            "SELECT payload->'data'->>'nivel' FROM outbox_messages "
                            "WHERE routing_key = :k ORDER BY created_at, id"
                        ),
                        {"k": f"{T1}.inventario.alerta_stock"},
                    )
                )
                .scalars()
                .all()
            )
            return list(filas)
    finally:
        await engine.dispose()


async def _aplicar(servicio, semilla: dict, delta: str, tipo: str = "venta") -> None:
    """Un movimiento por el punto único, como lo haría el sync de ventas."""
    producto = await servicio._session.get(Producto, semilla["producto"], with_for_update=True)
    await aplicar_movimiento(
        servicio._session,
        tenant_id=T1,
        producto=producto,
        delta=Decimal(delta),
        tipo=tipo,
        referencia_id=uuid.uuid4(),
    )
    await servicio._session.commit()


# --- Alertas: la merma y el ajuste también pasan por el punto único ----------------


async def test_la_merma_que_cruza_el_umbral_emite_alerta_y_el_payload_no_lleva_pii(servicio, semilla, pg_platform_url):
    """La merma no es un camino aparte: su delta entra por `aplicar_movimiento`
    y el cruce emite `inventario.alerta_stock` como cualquier venta. El payload
    es el mínimo firmado (decisión 13): producto, nivel y cifras — nada de
    motivo, actor o proveedor."""
    creado = await servicio.registrar_ajuste(_merma(semilla, uuid.uuid4(), "8"))  # 10 → 2: ok → bajo
    await servicio._session.commit()
    assert creado.nivel == "bajo"

    assert await _alertas(pg_platform_url) == ["bajo"]
    fila = await _uno(
        pg_platform_url,
        "SELECT payload->'data' AS datos FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.inventario.alerta_stock",
    )
    assert set(fila.datos) == {"producto_id", "nivel", "stock_actual", "stock_minimo"}


async def test_el_ajuste_que_cruza_dos_niveles_de_golpe_emite_una_sola_alerta(servicio, semilla, pg_platform_url):
    """Conté 0 habiendo 10: ok → agotado saltando bajo y crítico. Un cruce, un
    evento — el del nivel final, no uno por nivel saltado."""
    creado = await servicio.registrar_ajuste(_ajuste(semilla, uuid.uuid4(), stock_contado="0", motivo="No queda nada"))
    await servicio._session.commit()
    assert creado.nivel == "agotado"
    assert await _alertas(pg_platform_url) == ["agotado"]


async def test_con_minimo_cero_llegar_a_cero_emite_agotado(servicio, semilla, pg_platform_url):
    """Sin mínimo configurado no hay bajo ni crítico (ADR-020): el primer —y
    único— cruce posible es el del cero. La merma que agota emite `agotado`."""
    creado = await servicio.registrar_ajuste(
        _merma(semilla, uuid.uuid4(), "3", producto_id=str(semilla["producto2"]))
    )  # 3 → 0, mínimo 0
    await servicio._session.commit()
    assert creado.nivel == "agotado"
    assert await _alertas(pg_platform_url) == ["agotado"]


async def test_la_merma_que_deja_el_stock_negativo_emite_agotado_y_el_negativo_se_ve(
    servicio, semilla, pg_platform_url
):
    """El negativo es legítimo (ADR-020): la merma de 5 habiendo 3 deja −2,
    emite `agotado` y el estado de stock lo muestra tal cual en `solo_alertas`
    — no lo recorta a cero ni lo esconde."""
    creado = await servicio.registrar_ajuste(_merma(semilla, uuid.uuid4(), "5", producto_id=str(semilla["producto2"])))
    await servicio._session.commit()
    assert creado.delta == -5 and creado.stock_resultante == -2 and creado.nivel == "agotado"

    assert await _alertas(pg_platform_url) == ["agotado"]
    assert await _stock(pg_platform_url, semilla["producto2"]) == Decimal("-2")
    alertas, total = await servicio.estado_stock(solo_alertas=True)
    assert total == 1
    assert alertas[0].producto_id == semilla["producto2"]
    assert alertas[0].stock_actual == Decimal("-2") and alertas[0].nivel == "agotado"


async def test_el_ajuste_al_alza_no_emite_y_rearma_el_umbral_para_la_venta(servicio, semilla, pg_platform_url):
    """El re-armado no es privilegio de la compra: el ajuste que sube MEJORA el
    nivel (no emite) y la venta que vuelve a cruzar hacia abajo alerta de nuevo
    — un evento por cruce real, ni spam ni silencio."""
    await _aplicar(servicio, semilla, "-7")  # 10 → 3: ok → bajo. EMITE (1).
    al_alza = await servicio.registrar_ajuste(
        _ajuste(semilla, uuid.uuid4(), stock_contado="20", motivo="Sobrante del conteo")
    )  # 3 → 20: bajo → ok. NO emite.
    await servicio._session.commit()
    assert al_alza.nivel == "ok"
    await _aplicar(servicio, semilla, "-18")  # 20 → 2: ok → bajo. EMITE (2).
    assert await _alertas(pg_platform_url) == ["bajo", "bajo"]


async def test_el_nivel_se_deriva_del_minimo_vigente_no_del_que_habia_al_alertar(servicio, semilla, pg_platform_url):
    """El tendero sube el mínimo de 4 a 30 ENTRE movimientos. Como el nivel se
    deriva y no se persiste (decisión 2), el siguiente movimiento compara con el
    mínimo VIGENTE: 10 → 9 es bajo → bajo (no emite) y 9 → 3 es bajo → crítico
    (emite `critico`, el nivel del mínimo nuevo — no el `ok` que diría el 4
    viejo)."""
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE productos SET stock_minimo = 30 WHERE id = :p"), {"p": semilla["producto"]})
    await engine.dispose()

    await _aplicar(servicio, semilla, "-1")  # 10 → 9 con mínimo 30: bajo → bajo. NO emite.
    await _aplicar(servicio, semilla, "-6")  # 9 → 3 con mínimo 30: bajo → crítico. EMITE.
    assert await _alertas(pg_platform_url) == ["critico"]


async def test_bajar_el_minimo_rearma_el_umbral_sin_evento(servicio, semilla, pg_platform_url):
    """La otra cara: stock 3 con mínimo 4 ya alertó `bajo`; el tendero baja el
    mínimo a 2 (sin movimiento: el nivel pasa a ok en silencio, coherente con
    «nunca al recuperarse») y la venta siguiente NO re-alerta — el cruce viejo
    quedó desactivado por la edición."""
    await _aplicar(servicio, semilla, "-7")  # 10 → 3: ok → bajo. EMITE.
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE productos SET stock_minimo = 2 WHERE id = :p"), {"p": semilla["producto"]})
    await engine.dispose()

    await _aplicar(servicio, semilla, "-1")  # 3 → 2 con mínimo 2: ok → ok. NO emite.
    assert await _alertas(pg_platform_url) == ["bajo"]


async def test_dos_ventas_concurrentes_que_cruzan_juntas_emiten_una_alerta_por_cruce(
    pg_app_url, semilla, pg_platform_url
):
    """Dos dispositivos venden 7 a la vez habiendo 10 (mínimo 4). El FOR UPDATE
    los serializa: el ganador cruza ok → bajo (emite `bajo`), el perdedor
    re-lee 3 y cruza bajo → agotado (emite `agotado`). Ni una sola alerta (el
    umbral se cruzó DOS veces, una por nivel) ni tres (no hay doble `bajo`):
    una por cruce, y el stock cuadra en −4."""

    async def venta_con_sesion_propia(consecutivo: int) -> None:
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                servicio = VentasService(session=s, tenant_id=T1, actor_id=f"caja-{consecutivo}", puede_anular=False)
                resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, "7", consecutivo)))
                assert [r.resultado for r in resultados] == ["aceptada"]
                await s.commit()
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    # `return_exceptions=True` y relanzar DESPUÉS: si una venta muriera (p. ej.
    # elegida víctima de un deadlock), `gather` propagaría de inmediato y la
    # tarea superviviente seguiría corriendo durante el teardown del fixture.
    resultados = await asyncio.gather(venta_con_sesion_propia(1), venta_con_sesion_propia(2), return_exceptions=True)
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            raise resultado

    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("-4")  # 10 - 7 - 7, ni una perdida
    assert await _alertas(pg_platform_url) == ["bajo", "agotado"]


# --- Compras: la regresión del deadlock, el tope y la atomicidad ---------------------


async def test_dos_compras_concurrentes_con_productos_en_orden_inverso_no_se_interbloquean(
    pg_app_url, semilla, pg_platform_url
):
    """LA regresión del deadlock: la compra A trae [P1, P2] y la B [P2, P1] —
    el orden de llegada es adversario por construcción. El servicio adquiere
    los FOR UPDATE ordenados por `producto_id` (decisión 9), así que ambas
    piden P1 primero y no hay ciclo: las dos confirman y el stock cuadra.
    Si el ordenamiento se rompe, este test muere por timeout de bloqueo."""

    def compra(items: list[dict]) -> CompraCrear:
        return _compra(semilla, uuid.uuid4(), items=items)

    async def compra_con_sesion_propia(items: list[dict]) -> None:
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                servicio = InventarioService(session=s, tenant_id=T1, actor_id="qa-adversarial")
                await servicio.registrar_compra(compra(items))
                await s.commit()
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    p1, p2 = str(semilla["producto"]), str(semilla["producto2"])
    compra_a = [
        {"producto_id": p1, "cantidad": "5", "costo_unitario_centavos": 100},
        {"producto_id": p2, "cantidad": "1", "costo_unitario_centavos": 100},
    ]
    compra_b = [  # el MISMO par, en orden inverso: sin la decisión 9, interbloqueo
        {"producto_id": p2, "cantidad": "2", "costo_unitario_centavos": 100},
        {"producto_id": p1, "cantidad": "7", "costo_unitario_centavos": 100},
    ]
    resultados = await asyncio.gather(
        compra_con_sesion_propia(compra_a), compra_con_sesion_propia(compra_b), return_exceptions=True
    )
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            raise resultado

    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("22")  # 10 + 5 + 7
    assert await _stock(pg_platform_url, semilla["producto2"]) == Decimal("6")  # 3 + 1 + 2


async def test_la_compra_de_200_items_cabe_entera(servicio, semilla, pg_platform_url):
    """El tope es 200 (decisión: acotar la transacción que retiene los bloqueos)
    y 200 CABE: 200 productos, 200 FOR UPDATE ordenados, 200 movimientos y el
    total del servidor exacto. La frontera se prueba por dentro, no solo el 422
    del 201."""
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO productos (id, tenant_id, nombre, precio_venta) "
                "SELECT gen_random_uuid(), :t, 'Granel ' || g, 100 FROM generate_series(1, 200) AS g"
            ),
            {"t": T1},
        )
        filas = (
            (
                await conn.execute(
                    text("SELECT id FROM productos WHERE tenant_id = :t AND nombre LIKE 'Granel %'"), {"t": T1}
                )
            )
            .scalars()
            .all()
        )
    await engine.dispose()
    assert len(filas) == 200

    compra = await servicio.registrar_compra(
        _compra(
            semilla,
            uuid.uuid4(),
            items=[{"producto_id": str(p), "cantidad": "1", "costo_unitario_centavos": 100} for p in filas],
        )
    )
    await servicio._session.commit()

    assert compra.total_centavos == 200 * 100
    movimientos = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM movimientos_inventario WHERE tenant_id = :t AND tipo = 'compra'",
        t=T1,
    )
    assert movimientos.n == 200


def test_la_compra_de_201_items_no_pasa_del_schema():
    """El 201 lo corta pydantic en la frontera (422 en la API): nunca una
    transacción de 201 bloqueos de fila retenidos a la vez."""
    with pytest.raises(ErrorDeEsquema):
        CompraCrear.model_validate(
            {
                "proveedor_nombre": "Distribuidora La 33",
                "items": [
                    {"producto_id": str(uuid.uuid4()), "cantidad": "1", "costo_unitario_centavos": 100}
                    for _ in range(201)
                ],
            }
        )


async def test_la_compra_que_revienta_a_mitad_no_deja_rastro(servicio, semilla, pg_platform_url):
    """La atomicidad bajo fuego: dos ítems, y uno es de un producto dado de
    baja. El 422 salta con el otro ítem YA procesado en la sesión (movimiento,
    stock y costo incluidos, si el orden alfabético lo puso primero): el
    rollback se lo lleva TODO — ni compra, ni ítems, ni movimientos, ni evento,
    y el stock del producto bueno intacto."""
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE productos SET deleted_at = now() WHERE id = :p"), {"p": semilla["producto2"]})
    await engine.dispose()

    with pytest.raises(ValidationError) as exc:
        await servicio.registrar_compra(
            _compra(
                semilla,
                uuid.uuid4(),
                items=[
                    {"producto_id": str(semilla["producto"]), "cantidad": "5", "costo_unitario_centavos": 100},
                    {"producto_id": str(semilla["producto2"]), "cantidad": "1", "costo_unitario_centavos": 100},
                ],
            )
        )
    assert exc.value.code == "producto_no_encontrado"
    await servicio._session.rollback()

    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM compras WHERE tenant_id = :t) AS compras, "
        "(SELECT count(*) FROM compra_items WHERE tenant_id = :t) AS items, "
        "(SELECT count(*) FROM movimientos_inventario WHERE tenant_id = :t) AS movimientos, "
        "(SELECT count(*) FROM outbox_messages WHERE routing_key = :k) AS eventos",
        t=T1,
        k=f"{T1}.compra.registrada",
    )
    assert (fila.compras, fila.items, fila.movimientos, fila.eventos) == (0, 0, 0, 0)
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("10")


async def test_la_compra_con_id_de_otro_tenant_es_409_y_no_toca_nada(servicio, semilla, pg_platform_url):
    """El `id` del cliente choca con una compra que EXISTE — en T2. La RLS la
    hace invisible al `get`, el INSERT revienta contra `compras_pkey` y el
    servicio lo traduce a 409 `compra_id_duplicado` (firmado en el router: «en
    este u otro negocio»). La compra del vecino queda intacta y aquí no se
    mueve ni stock ni evento."""
    compra_ajena = uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO compras (id, tenant_id, proveedor_nombre, total_centavos) "
                "VALUES (:c, :t, 'Proveedor del vecino', 9999)"
            ),
            {"c": compra_ajena, "t": T2},
        )
    await engine.dispose()

    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_compra(_compra(semilla, compra_ajena))
    assert exc.value.code == "compra_id_duplicado"
    await servicio._session.rollback()

    ajena = await _uno(pg_platform_url, "SELECT total_centavos FROM compras WHERE id = :c", c=compra_ajena)
    assert ajena.total_centavos == 9999, "la compra del vecino, intacta"
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("10")


async def test_la_compra_de_costo_cero_deja_ultimo_costo_en_cero(servicio, semilla, pg_platform_url):
    """DOCUMENTA el borde firmado del schema (`ge=0`): la bonificación del
    proveedor entra con costo 0, el total es 0 y `ultimo_costo` queda en 0 —
    lo que el P&L costeará (ADR-006) hasta la próxima compra con precio. La
    discusión (¿debería exigirse `observaciones` cuando el total es 0?) vive
    en el reporte."""
    compra = await servicio.registrar_compra(
        _compra(
            semilla,
            uuid.uuid4(),
            observaciones="Bonificación del proveedor",
            items=[{"producto_id": str(semilla["producto"]), "cantidad": "10", "costo_unitario_centavos": 0}],
        )
    )
    await servicio._session.commit()

    assert compra.total_centavos == 0
    fila = await _uno(
        pg_platform_url,
        "SELECT stock_actual, ultimo_costo FROM productos WHERE id = :p",
        p=semilla["producto"],
    )
    assert (fila.stock_actual, fila.ultimo_costo) == (20, 0)


# --- Ajustes: divergencias, vecinos y el reintento tardío ---------------------------


async def test_el_reintento_con_la_forma_del_otro_tipo_es_divergente(servicio, semilla):
    """Mismo id, pero el primer intento fue `ajuste` (conteo) y el reintento
    llega como `merma` (cantidad): NO es un reintento — es otro hecho con la
    misma ancla. 409 con los tres campos que difieren, y el servidor conserva
    la primera versión."""
    el_id = uuid.uuid4()
    await servicio.registrar_ajuste(_ajuste(semilla, el_id))
    await servicio._session.commit()

    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_ajuste(_merma(semilla, el_id, "3", motivo="Conteo de cierre"))
    assert exc.value.code == "ajuste_id_divergente"
    assert set(exc.value.details["campos"]) == {"tipo", "stock_contado", "cantidad"}


async def test_el_ajuste_con_producto_de_otro_tenant_es_422_sin_fuga(servicio, semilla):
    """El ajuste apunta a un producto que EXISTE — en T2. La RLS lo hace
    invisible al FOR UPDATE y el veredicto es el mismo que para un id
    inventado: 422 `producto_no_encontrado`, sin fila de ajuste y sin asomo
    de que el producto existe."""
    with pytest.raises(ValidationError) as exc:
        await servicio.registrar_ajuste(_ajuste(semilla, uuid.uuid4(), producto_id=str(semilla["ajeno"])))
    assert exc.value.code == "producto_no_encontrado"


async def test_el_ajuste_con_id_de_otro_tenant_es_409(servicio, semilla, pg_platform_url):
    """DOCUMENTA el espejo del caso firmado de compras: el `id` del ajuste
    choca con un ajuste que EXISTE — en T2. La RLS lo hace invisible al `get`,
    el INSERT revienta contra `ajustes_inventario_pkey` y sale 409
    `ajuste_id_divergente`. El comentario del código solo contempla la carrera
    de dos primeros intentos; el caso cross-tenant y su mensaje («Ese id de
    ajuste ya existe.») quedan fijados aquí y discutidos en el reporte."""
    ajuste_ajeno = uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ajustes_inventario (id, tenant_id, producto_id, tipo, stock_contado, delta, "
                "motivo, aplicado_por, stock_resultante) "
                "VALUES (:a, :t, :p, 'ajuste', 5, -2, 'Conteo del vecino', 'vecino', 5)"
            ),
            {"a": ajuste_ajeno, "t": T2, "p": semilla["ajeno"]},
        )
    await engine.dispose()

    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_ajuste(_ajuste(semilla, ajuste_ajeno))
    assert exc.value.code == "ajuste_id_divergente"
    await servicio._session.rollback()

    ajena = await _uno(pg_platform_url, "SELECT motivo FROM ajustes_inventario WHERE id = :a", a=ajuste_ajeno)
    assert ajena.motivo == "Conteo del vecino", "el ajuste del vecino, intacto"
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("10")


async def test_el_reintento_del_ajuste_con_el_producto_ya_dado_de_baja_es_422(servicio, semilla, pg_platform_url):
    """DOCUMENTA el borde del orden de validación: `registrar_ajuste` bloquea el
    producto ANTES de mirar si el id ya existe. Si el producto se dio de baja
    entre el intento y el reintento, el reintento IDÉNTICO sale 422
    `producto_no_encontrado` en vez de devolver lo ya respondido — la fila del
    ajuste existe y el stock no se mueve (no hay doble aplicación), pero la
    idempotencia del gesto queda rota. Cuestionable-firmado: la propuesta vive
    en el reporte."""
    el_id = uuid.uuid4()
    datos = _ajuste(semilla, el_id)
    primero = await servicio.registrar_ajuste(datos)
    await servicio._session.commit()
    assert primero.delta == -2

    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE productos SET deleted_at = now() WHERE id = :p"), {"p": semilla["producto"]})
    await engine.dispose()

    with pytest.raises(ValidationError) as exc:
        await servicio.registrar_ajuste(datos)
    assert exc.value.code == "producto_no_encontrado"
    await servicio._session.rollback()

    fila = await _uno(
        pg_platform_url,
        "SELECT delta FROM ajustes_inventario WHERE id = :a",
        a=el_id,
    )
    assert fila.delta == -2, "la primera versión sigue grabada: el gesto SÍ quedó anclado"


def test_el_motivo_de_dos_caracteres_no_pasa_del_schema():
    """`min_length=3` tras la limpieza: «ab» no es una justificación, es un
    desfalco con prisa. El 422 lo da pydantic, no la base."""
    with pytest.raises(ErrorDeEsquema):
        AjusteCrear.model_validate(
            {
                "id": str(uuid.uuid4()),
                "tipo": "ajuste",
                "producto_id": str(uuid.uuid4()),
                "stock_contado": "8",
                "motivo": "ab",
            }
        )


# --- La frontera del sync (D-22): inventario no viaja por el lote ---------------------


async def test_el_lote_con_tipo_inventario_ajustar_es_tipo_desconocido_y_no_toca_nada(
    pg_app_url, semilla, pg_platform_url
):
    """D-22, el test literal que faltaba: un lote con `tipo: "inventario.ajustar"`
    —payload de ajuste perfectamente formado, no una basura cualquiera— sale
    `rechazada` con `tipo_desconocido`. El ajuste es ONLINE-obligatorio
    (ADR-020): si el sync lo admitiera, su delta se calcularía contra un stock
    viejo y corrompería el contador de forma no conmutativa. Ni fila de ajuste,
    ni movimiento, ni stock tocado."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            servicio = VentasService(session=s, tenant_id=T1, actor_id="caja-1", puede_anular=False)
            operacion = {
                "id": str(uuid.uuid4()),
                "tipo": "inventario.ajustar",
                "secuencia": 1,
                "datos": {
                    "id": str(uuid.uuid4()),
                    "tipo": "ajuste",
                    "producto_id": str(semilla["producto"]),
                    "stock_contado": "0",
                    "motivo": "Conteo de cierre",
                },
            }
            resultados = await servicio.procesar_lote(_lote(semilla, operacion))
            assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "tipo_desconocido")]
            await s.commit()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()

    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM ajustes_inventario WHERE tenant_id = :t) AS ajustes, "
        "(SELECT count(*) FROM movimientos_inventario WHERE tenant_id = :t) AS movimientos",
        t=T1,
    )
    assert (fila.ajustes, fila.movimientos) == (0, 0)
    assert await _stock(pg_platform_url, semilla["producto"]) == Decimal("10")
