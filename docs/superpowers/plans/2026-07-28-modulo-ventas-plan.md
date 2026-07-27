# Módulo ventas + sincronización offline (Fase 1, Etapa 1.2, módulo 2) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar el módulo crítico de Fase 1 —las ventas offline de ADR-018 sobre la capa de sincronización de ADR-017— con: la migración `0005_ventas` (tablas `dispositivos`, `caja_sesiones`, `ventas`, `ventas_items` y `movimientos_inventario`, todas con RLS + índices + grants), los permisos `venta:crear`/`venta:anular` repartidos según ADR-023 (el cajero crea pero NO anula), el endpoint `POST /api/v1/sync/lotes` con respuesta por operación (`aceptada`/`duplicada`/`rechazada`), idempotencia por UUID de cliente, una transacción por lote y un SAVEPOINT por operación, eventos outbox `venta.creada`/`venta.anulada` una sola vez por operación aceptada, descuento de stock por movimientos con el índice único de ADR-020 como segunda red de idempotencia, `GET /api/v1/sync/delta` para drenar el catálogo hacia los dispositivos, la anulación como operación nueva no destructiva, y el contrato OpenAPI regenerado con su cliente TS. Se cierra con el gate de módulo de la Etapa 1.2 del plan maestro de Fase 1.

**Architecture:** Se mantiene la arquitectura firmada: monolito modular FastAPI (`backend/services/api`) sobre `vendi-core`, RLS en schema único con los roles `vendi_app` (sin `BYPASSRLS`) y `vendi_platform` (con `BYPASSRLS`, owner, corre las migraciones). El módulo nuevo vive en `app/modules/ventas/`. Todo el sync corre sobre la **sesión de tenant** (`sesion_de_tenant`, GUC `vendi.tenant_id` sembrado por transacción): el lote entero viaja con el GUC del negocio del token y cada fila pasa la policy `tenant_isolation` — el `WITH CHECK` rechaza cualquier `tenant_id` inyectado (ADR-017). La venta es append-only con PK del cliente; la única mutación permitida es `completada → anulada`. El stock se descuenta por deltas en `movimientos_inventario` con `stock_actual` de `productos` como proyección actualizada en la misma transacción (ADR-020); las alertas de umbral, compras y ajustes son del módulo 3. La referencia a sesión de caja se resuelve en el servidor (sesión abierta del tenant o implícita, ADR-018); el arqueo es del módulo 4 (ADR-021). El fiado se registra como dato de la venta (`medio_pago`, `cliente_id`); el crédito lo crea el módulo 5 (ADR-022).

**Tech Stack:** Python 3.12 · FastAPI 0.139 · SQLAlchemy 2.0 async (asyncpg) · Alembic · PostgreSQL 17 RLS · Pydantic v2 · pytest + pytest-asyncio · ruff · uv · openapi-typescript (codegen).

**Spec fuente:**
- `docs/adr/adr-017-sincronizacion-offline-first.md` (el corazón: lotes, delta, ids de cliente, dispositivos, LWW por orden de recepción)
- `docs/adr/adr-018-modelo-de-ventas-offline.md` (ventas append-only, consecutivo por dispositivo, doble verdad temporal, anulación como evento, centavos enteros, sesión resuelta en servidor)
- `docs/adr/adr-020-inventario-y-compras.md` (stock por deltas, proyección `stock_actual`, índice único de idempotencia, stock negativo legítimo)
- `docs/adr/adr-023-multi-empleado-permisos.md` (`venta:crear`, `venta:anular`; el cajero no anula; extensión del check 23)
- `docs/adr/adr-021-caja-y-arqueo.md` (referencia: la tabla `caja_sesiones` y su índice único parcial de sesión abierta)
- `docs/adr/adr-022-fiado-y-clientes-tecnico.md` (referencia: la venta fiada; el crédito es de su módulo)
- Plantillas a imitar: `backend/services/api/alembic/versions/20260728_0004_catalogo.py`, `backend/services/api/app/modules/catalogo/` (service con flush-sin-commit, `_flush_traduciendo_integridad`, guard `exigir_permiso`), `backend/tests/test_aislamiento_productos.py`, `backend/tests/test_catalogo_servicio.py`, `backend/tests/test_catalogo_adversarial.py` y `backend/tests/api/test_catalogo_productos.py`.

## Global Constraints

- Todo artefacto en español riguroso (código, docstrings, commits, mensajes de error). Sin tildes ni eñes en identificadores técnicos que viajen en tokens, URLs o JSON (`dueno`, no `dueño`).
- Toda tabla nueva de dominio lleva `tenant_id` + policy RLS vía `enable_rls(op, ...)` + índice que empieza por `tenant_id`, verificada por test de aislamiento cross-tenant contra PostgreSQL real. Los tests de integración **fallan, no se omiten**, si falta el servicio.
- El candado invertido `backend/tests/test_privilegios_de_vendi_app.py` exige EXACTAMENTE `{SELECT, INSERT, UPDATE, DELETE}` para toda tabla de negocio: cualquier desviación de grants hay que justificarla y cablearla, no improvisarla.
- TDD en cada tarea: primero el test que falla (con la salida del fallo esperada), luego la implementación completa, luego el test en verde, luego el commit. Prohibido «similar a», «agregar validación», TODO o código elidido.
- Los errores de la API usan el sobre `{"success": false, "message": "...", "code": "..."}` (`vendi_core.errors.domain` + `ErrorHandlerMiddleware`). NO se usa `require_permission` de `vendi-core` en código nuevo: lanza `HTTPException` con cuerpo `{"detail": ...}` y rompería el formato.
- **Lecciones del QA adversarial del catálogo, aplicadas desde el diseño:** (1) toda entrada entera/decimal lleva cota `le=` contra su tipo de columna — un overflow de `Integer`/`Numeric(14,3)` sale como `DataError` → 500, no como 422 (BUG-2 del informe `.superpowers/sdd/qa-adversarial-report.md`); (2) ningún validador `mode="before"` asume `str` — lo que no es `str` pasa intacto para que pydantic lo rechace como 422 (BUG-1); (3) la idempotencia NO es ciega a la divergencia de payload: en el sync, mismo `id` con datos distintos es `rechazada` con motivo y `detalles`, no un no-op silencioso (propuesta del QA, adoptada aquí como criterio de módulo — ver decisión 4).
- Dinero SIEMPRE en centavos enteros (ADR-018); cantidades en `Decimal` (`Numeric(14,3)`), nunca flotante.
- El reloj del cliente es dato, no árbitro (ADR-017): `creada_en_cliente` se guarda tal cual para el ticket; el orden, los reportes y el delta usan marcas del servidor (`recibida_en`, `func.now()`).
- Los commits son por tarea, mensajes en español estilo oración. Nunca `git push` sin confirmación humana.
- Un ADR no se edita para cambiar de opinión: lo que este plan decide más allá de los ADRs queda listado en la sección siguiente, con su justificación.

## Decisiones de diseño tomadas en este plan (más allá de los ADRs)

1. **`movimientos_inventario` se crea AQUÍ, mínima, y no se difiere al módulo 3.** Sin ella las ventas no descuentan stock y el candado firmado de ADR-018 («el mismo lote dos veces deja una venta, UN movimiento de stock y un evento») no tendría objeto. Lo que se crea: la tabla con RLS, el índice único de idempotencia, el índice por producto, y el hook que inserta el movimiento de salida y actualiza la proyección `stock_actual` en la misma transacción del lote. Lo que SE DIFIERE al módulo 3 (inventario): las alertas de tres niveles con `inventario.alerta_stock` (su consumidor es el módulo de notificaciones ADR-025, que aún no existe), los ajustes online, las compras y sus tablas (`compras`, `compra_items`), y la reconstrucción del libro del runbook. El `tipo` ya admite los cuatro valores del ADR (`venta`, `compra`, `ajuste`, `merma`) para que el módulo 3 no migre nada.
2. **El índice único de idempotencia de movimientos es `(tenant_id, tipo, referencia_id, producto_id)`, no el `(tenant_id, tipo, referencia_id)` literal de ADR-020.** El ADR escribe el índice con tres columnas, pero una venta real tiene varios ítems y cada ítem necesita su propio movimiento con `referencia_id = venta_id`: con el índice literal, la segunda línea de un mismo ticket chocaría contra la primera y ninguna venta de más de un producto podría aplicarse. Añadir `producto_id` conserva intacta la garantía firmada (la misma venta aplicada dos veces produce los mismos movimientos, que chocan y se reconocen como duplicados) y es compatible con el candado del ADR. Queda registrado aquí porque los ADRs no se editan; si el módulo 3 quiere el índice literal, tendrá que proponer ADR nuevo.
3. **Integración con caja: la tabla `caja_sesiones` se crea completa en esta migración y el sync resuelve la sesión (abierta del tenant o implícita nueva); el arqueo, `caja_movimientos`, los endpoints y los eventos de caja son del módulo 4.** Justificación: ADR-018 firma que la venta referencia sesión de caja resuelta en servidor al sincronizar, y si las ventas del piloto se grabaran con `sesion_caja_id` NULL habría que re-procesarlas cuando llegue la caja (el arqueo las suma por sesión). La tabla es pequeña y su regla dura —una sesión abierta por tienda— la hace cumplir desde hoy el índice único parcial `(tenant_id) WHERE estado = 'abierta'` de ADR-021, que también protege la apertura implícita concurrente. La sesión implícita se abre con `base_inicial = 0` y `abierta_por = <usuario que sincroniza>`; el módulo 4 encontrará la tabla y sus filas ya vivas. **Tensión declarada:** ADR-021 dice «vender sin caja abierta es posible… pero entonces esa venta no entra al arqueo de ninguna sesión», mientras ADR-018 dice «si no hay ninguna, abre una implícita». Manda ADR-018: es el ADR de la venta, contempla explícitamente el índice de ADR-021 al decidirlo, y una venta con sesión siempre puede excluirse de un arqueo; una venta sin sesión nunca puede incluirse.
4. **Criterio ante divergencia de payload en reintentos: `rechazada` con motivo, no no-op silencioso ni 409 de request.** El QA del catálogo documentó la trampa («quien reintenta corrigiendo un typo cree que corrigió — y no corrigió») y propuso 409 con `details`. En el sync el 409 de request no aplica —la unidad de respuesta es la operación, no el lote—, así que el criterio es: mismo `id` y payload **idéntico** → `duplicada` (no-op, sin evento); mismo `id` y payload **divergente** (campos inmutables distintos: ítems, total, medio de pago, cliente, consecutivo, dispositivo, `creada_en_cliente`, estado) → `rechazada` con motivo `venta_id_divergente` y `detalles` con los campos que difieren. En una venta —dinero y stock append-only— la divergencia silenciosa es inaceptable: o es el mismo hecho, o es otro que el tendero tiene que resolver a cara vista. Para el CRUD del catálogo el comportamiento firmado en el módulo anterior no cambia (allí quedó documentado con test).
5. **El lote se procesa con UNA transacción y UN SAVEPOINT por operación; `rechazada` nunca aborta el lote.** ADR-017 fija «una transacción por lote». Las validaciones de dominio (duplicada, divergente, producto inexistente, consecutivo repetido, fiado sin cliente, total incoherente, anular sin permiso) son RESULTADOS por operación, no excepciones: se capturan, se revierte solo esa operación con su SAVEPOINT (`session.begin_nested()`, precedente: el runner de retención) y el lote sigue. Solo un fallo inesperado (caída de conexión) aborta el request entero con 500 — y entonces nada confirma, ni ventas ni eventos, que es exactamente la garantía outbox. Los eventos se emiten dentro de la misma transacción, una sola vez por operación `aceptada`; una `duplicada` o `rechazada` no emite (ADR-017).
6. **Los datos de cada operación se validan DOS veces con dos criterios distintos.** Estructura del request (lista de operaciones, `id`, `secuencia`, tope de lote): pydantic a nivel request → 422 entero, porque un request malformado es un bug del cliente y nada se aplicó. Contenido de `datos` de cada operación: `dict` genérico que el servicio valida con `VentaCrearSync.model_validate` / `VentaAnularSync.model_validate` DENTRO del procesamiento → una operación con datos inválidos es `rechazada` con motivo `datos_invalidos` y NO arrastra a las otras 199 del lote al 422. `tipo` es `str` libre (acotado en largo), no `Literal`: un tipo desconocido —un cliente viejo hablando con un servidor nuevo, o al revés— es `rechazada` con motivo `tipo_desconocido`, no un 422 del lote entero. Es la diferencia con el CRUD del catálogo (donde 422 lo cubre todo) y la razón es la semántica del lote: la unidad de fallo es la operación.
7. **Tamaño máximo del lote: 200 operaciones** (`min_length=1, max_length=200`), y máximo 500 ítems por venta. Justificación: la transacción del lote retiene bloqueos de fila (stock de los productos tocados) hasta el commit; 200 operaciones acota ese tiempo a algo despreciable a la escala de una tienda, coincide con el tope de paginación ya firmado (`limit le=200`), y un día entero de ventas offline de una tienda de barrio cabe en unos pocos lotes. El cliente drena su cola FIFO en lotes consecutivos; el tope no cambia ninguna garantía, solo acota la transacción.
8. **Integración con fiado: mínima, de datos y validación, sin crédito.** La venta fiada lleva `medio_pago = 'fiado'` y `cliente_id` obligatorio (operación `rechazada` con `fiado_requiere_cliente` si falta; y `cliente_solo_en_fiado` si trae cliente sin ser fiada — ADR-018: «`cliente_id` NULL salvo fiado»). La columna `cliente_id` NO lleva FK: la tabla `clientes` es del módulo 5 y el sync no puede rechazar una venta real porque su referencia aún no existe en servidor (el fiado sin red está permitido por ADR-018, y el servidor no rechaza aunque se supere el cupo). La creación del `fiado_creditos` es íntegramente del módulo 5, que tiene todo lo que necesita en la venta y en el evento `venta.creada` (que lleva `medio_pago`, `cliente_id` y total). Como los módulos se entregan en orden antes del piloto, no hay ventas reales que queden huérfanas de crédito.
9. **Una venta que sube ya `anulada` (anulada localmente antes de sincronizar, ADR-018) no genera movimientos de stock ni exige `venta:anular`.** El efecto neto en stock es cero (vendió y se anuló antes de que el sistema la conociera), así que el libro queda limpio: se registra la venta con su estado, sus ítems y su evento `venta.creada` (cuyo payload lleva `estado: "anulada"`), y nada más. Tampoco se emite `venta.anulada`: ese evento significa «una venta ACEPTADA fue anulada después», y aquí nunca hubo venta aceptada. El permiso es `venta:crear` — es el ciclo de vida pre-sync de la propia venta del cajero, no el gesto con dinero que ADR-023 reserva al dueño; la operación `venta.anular` (anular una venta ya aceptada por el servidor) sí exige `venta:anular` y un cajero recibe `rechazada` con `permiso_ausente` (ver 12).
10. **`GET /sync/delta` drena solo datos de referencia: el catálogo.** Devuelve `{hasta, productos, eliminados}`: productos vivos con `COALESCE(updated_at, created_at) > desde`, ids de productos con `deleted_at > desde` (tumbas para que el dispositivo los quite de su IndexedDB), y `hasta` = `now()` del servidor para usar como próximo `desde` — el watermark lo pone el reloj del servidor, nunca el del cliente (ADR-017). No incluye ventas (cada dispositivo ya conoce las suyas; el cruce de ventas entre cajas es un consumidor que no existe todavía, ADR-016) ni stock como stream aparte: `stock_actual` viaja dentro de cada producto, y como el sync lo actualiza en la misma transacción, el `updated_at` del producto lo refleja. El permiso es `producto:leer` (el cajero drena su catálogo para vender).
11. **`vendi_app` conserva los cuatro privilegios sobre las cinco tablas nuevas, incluidas las append-only.** `ventas`, `ventas_items` y `movimientos_inventario` son «nunca se edita ni se borra» por modelo, pero revocar `UPDATE`/`DELETE` obligaría a declararlas en `PRIVILEGIOS_DE_VENDI_APP`, y ese dict está atado a `TABLAS_DE_PLATAFORMA` por el test de consistencia: meterlas ahí las excluiría del candado de cobertura RLS, que es la protección que importa. Es la decisión 1 del plan del catálogo, misma letra y mismo motivo; el precedente firmado es `files`. La inmutabilidad la hace cumplir la lógica de aplicación (los servicios solo insertan; la única mutación es `estado` de la venta) más la RLS, y las correcciones de soporte corren con `vendi_platform`. El candado invertido pasa sin edición.
12. **El guard `exigir_permiso` se mueve a `app/dependencies.py`** (de `app/modules/catalogo/dependencies.py`, que lo reexporta para no tocar su router ni sus tests). Dos módulos importándolo desde un tercero de dominio crearía un acoplamiento catálogo→ventas sin sentido; `app.dependencies` es donde ya vive `exigir_admin_de_plataforma`, que existe por el mismo motivo. En el endpoint de lotes el guard de entrada es `venta:crear` (todo cajero sincroniza su cola) y el chequeo de `venta:anular` es POR OPERACIÓN dentro del servicio: una operación `venta.anular` sin el permiso es `rechazada` con `permiso_ausente` y no impide que el resto de la cola del cajero suba. El 403 por rol se sigue probando de verdad: un lote de solo anulaciones de un cajero devuelve todas sus operaciones rechazadas (y el test de API comprueba además el 403 de un endpoint protegido con `venta:anular`, ver Tarea 6).
13. **`sesion_caja_id` es NOT NULL y la resolución es siempre resolver-o-abrir** (ver decisión 3). La carrera de dos aperturas implícitas concurrentes la decide el índice único parcial: quien pierde re-lee la sesión ganadora y la usa. No hay sesión «fantasma»: toda venta sincronizada pertenece a una sesión real del tenant.
14. **El total de la venta se verifica contra sus ítems** (`sum(cantidad * precio_unitario_centavos) == total_centavos`, aritmética exacta de `Decimal`, sin redondeo: cantidades de tres decimales por precios enteros siempre terminan en entero o la cuenta está mal). Una venta con total incoherente es `rechazada` con `total_incoherente`: el total es el dato que cuadra la caja y el P&L, y aceptar un total que no cuadra con las líneas sería sembrar descuadres mudos. El precio queda congelado en el ítem (ADR-018): el servidor NO recalcula precios desde el catálogo — el dispositivo vendió a ese precio.
15. **Se regenera `docs/api/openapi-fase0.json`; NO se crea un congelado nuevo** (misma decisión 5 del plan del catálogo: fuente única del codegen y del job `frontend-contratos`). Se actualiza `docs/api/README.md` con las rutas y los `code` nuevos.

---

## Tarea 1: Migración `0005_ventas` — `dispositivos`, `caja_sesiones`, `ventas`, `ventas_items`, `movimientos_inventario`

**Files:**
- Create: `backend/tests/test_aislamiento_ventas.py` (primero: el test que falla)
- Create: `backend/services/api/alembic/versions/20260728_0005_ventas.py`

**Interfaces:**
- Consume: `vendi_core.db.rls.enable_rls` / `disable_rls`, fixtures `pg_app_url` / `pg_platform_url` y datos `T1`/`T2` de `backend/tests/datos_de_prueba.py`.
- Produce: las cinco tablas migradas, cada una con policy `tenant_isolation`, índice que empieza por `tenant_id`, checks y los índices únicos del modelo (consecutivo por dispositivo, sesión abierta única, idempotencia de movimientos), y grants por defecto (los cuatro) para `vendi_app` — el candado invertido pasa sin edición (decisión 11).

- [ ] **Paso 1: escribir el test de aislamiento que falla.** Crear `backend/tests/test_aislamiento_ventas.py`:

```python
"""Aislamiento cross-tenant y unicidades duras de las tablas del módulo ventas.

Hermano de `test_aislamiento_productos.py`, mismo criterio: SQL crudo con el
rol `vendi_app` y nada de ORM, para que ningún `WHERE` amable del ORM dé un
falso verde sobre una policy que no filtra. Las tablas las crea la migración
`0005_ventas`; hasta que existe, TODOS estos tests fallan — que es el punto
del paso TDD.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
)


@pytest_asyncio.fixture
async def ventas_de_los_dos_tenants(pg_platform_url: str):
    """Un dispositivo, una sesión, un producto, una venta con su ítem y su
    movimiento POR NEGOCIO — con el MISMO consecutivo en los dos (válido: la
    unicidad es por tenant+dispositivo). Limpia antes y después: la suite es
    re-entrante."""
    engine = create_async_engine(pg_platform_url)
    ids: dict[str, dict] = {}
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        for nombre, tenant in (("T1", T1), ("T2", T2)):
            producto = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                     "VALUES (:p, :t, 'Arroz 500g', 2500, 10)"),
                {"p": producto, "t": tenant},
            )
            dispositivo = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
                {"d": dispositivo, "t": tenant},
            )
            sesion = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por) VALUES (:s, :t, 'dueno')"),
                {"s": sesion, "t": tenant},
            )
            venta = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, "
                    "consecutivo_local, medio_pago, total_centavos, creada_en_cliente, "
                    "secuencia_dispositivo) "
                    "VALUES (:v, :t, :d, :s, 1, 'efectivo', 2500, now(), 1)"
                ),
                {"v": venta, "t": tenant, "d": dispositivo, "s": sesion},
            )
            await conn.execute(
                text("INSERT INTO ventas_items (tenant_id, venta_id, producto_id, cantidad, "
                     "precio_unitario_centavos) VALUES (:t, :v, :p, 1, 2500)"),
                {"t": tenant, "v": venta, "p": producto},
            )
            await conn.execute(
                text("INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                     "producto_id) VALUES (:t, 'venta', -1, :v, :p)"),
                {"t": tenant, "v": venta, "p": producto},
            )
            ids[nombre] = {"dispositivo": dispositivo, "sesion": sesion, "venta": venta, "producto": producto}
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def sesion_t1(pg_app_url: str, ventas_de_los_dos_tenants):
    """Sesión de `vendi_app` con el negocio T1 en contexto."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield s
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tabla",
    ["dispositivos", "caja_sesiones", "ventas", "ventas_items", "movimientos_inventario"],
)
async def test_select_solo_ve_las_filas_del_propio_tenant(sesion_t1, tabla):
    filas = (await sesion_t1.execute(text(f"SELECT tenant_id FROM {tabla}"))).all()
    assert len(filas) == 1
    assert filas[0][0] == T1


@pytest.mark.asyncio
async def test_insert_de_venta_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1, ventas_de_los_dos_tenants):
    ids = ventas_de_los_dos_tenants["T2"]
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(
            text(
                "INSERT INTO ventas (tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                "medio_pago, total_centavos, creada_en_cliente, secuencia_dispositivo) "
                "VALUES (:t, :d, :s, 99, 'efectivo', 100, now(), 99)"
            ),
            {"t": T2, "d": ids["dispositivo"], "s": ids["sesion"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_consecutivo_se_repite_entre_tenants_pero_no_en_el_mismo_dispositivo(sesion_t1, ventas_de_los_dos_tenants):
    """El fixture ya sembró el consecutivo 1 en T1 y en T2. Repetirlo en el
    mismo dispositivo de T1 revienta contra `ux_ventas_consecutivo`."""
    ids = ventas_de_los_dos_tenants["T1"]
    with pytest.raises(IntegrityError, match="ux_ventas_consecutivo"):
        await sesion_t1.execute(
            text(
                "INSERT INTO ventas (tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                "medio_pago, total_centavos, creada_en_cliente, secuencia_dispositivo) "
                "VALUES (:t, :d, :s, 1, 'efectivo', 100, now(), 2)"
            ),
            {"t": T1, "d": ids["dispositivo"], "s": ids["sesion"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_la_segunda_aplicacion_del_mismo_movimiento_choca_con_el_indice_unico(
    sesion_t1, ventas_de_los_dos_tenants
):
    """La red de idempotencia de ADR-020: `(tenant_id, tipo, referencia_id,
    producto_id)`. El reintento del mismo movimiento de salida no puede
    descontar dos veces: la base lo hace imposible."""
    ids = ventas_de_los_dos_tenants["T1"]
    with pytest.raises(IntegrityError, match="ux_movimientos_origen"):
        await sesion_t1.execute(
            text("INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                 "producto_id) VALUES (:t, 'venta', -1, :v, :p)"),
            {"t": T1, "v": ids["venta"], "p": ids["producto"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_una_segunda_sesion_abierta_en_el_mismo_tenant_no_cabe(sesion_t1):
    """La regla «una caja por tienda» de ADR-021 la hace cumplir el índice
    único parcial, no el código: la apertura implícita del sync se apoya en él."""
    with pytest.raises(IntegrityError, match="ux_caja_sesion_abierta"):
        await sesion_t1.execute(
            text("INSERT INTO caja_sesiones (tenant_id, abierta_por) VALUES (:t, 'otro')"),
            {"t": T1},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_una_sesion_cerrada_si_permite_abrir_otra(sesion_t1):
    await sesion_t1.execute(text("UPDATE caja_sesiones SET estado = 'cerrada', cerrada_en = now()"))
    await sesion_t1.execute(
        text("INSERT INTO caja_sesiones (tenant_id, abierta_por) VALUES (:t, 'otro')"),
        {"t": T1},
    )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_stock_puede_quedar_negativo(sesion_t1, ventas_de_los_dos_tenants):
    """ADR-020: el negativo es un estado legítimo (la tienda ya vendió
    físicamente esa unidad); ninguna constraint lo prohíbe."""
    ids = ventas_de_los_dos_tenants["T1"]
    await sesion_t1.execute(
        text("UPDATE productos SET stock_actual = stock_actual - 50 WHERE id = :p"),
        {"p": ids["producto"]},
    )
    stock = (await sesion_t1.execute(text("SELECT stock_actual FROM productos"))).scalar_one()
    assert stock < 0
    await sesion_t1.rollback()
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_aislamiento_ventas.py -q
```

Esperado: 10 errores/fallos con `relation "dispositivos" does not exist` (o `ventas`, según el orden de resolución de fixtures).

- [ ] **Paso 2: escribir la migración.** Crear `backend/services/api/alembic/versions/20260728_0005_ventas.py`:

```python
"""Ventas y sync offline: `dispositivos`, `caja_sesiones`, `ventas`,
`ventas_items` y `movimientos_inventario` (ADR-017/018/020/021).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-28

## Las cinco tablas y su porqué

- `dispositivos` (ADR-017): registro de los dispositivos del tenant que
  sincronizan. `ultima_secuencia` es la mayor `secuencia` de cola aplicada;
  `ultima_sync`, la marca del último lote. Ambas son observabilidad, no
  árbitro: la idempotencia la da la PK de cada fila de dominio.
- `caja_sesiones` (ADR-021, creada aquí por la decisión 3 del plan del
  módulo): una sesión de caja abierta por tienda, garantizada por el índice
  único parcial `(tenant_id) WHERE estado = 'abierta'`. El sync la usa para
  resolver la referencia de cada venta (abierta del tenant o implícita); el
  arqueo y `caja_movimientos` llegan con el módulo de caja.
- `ventas` (ADR-018): hecho append-only. PK = UUIDv4 del dispositivo;
  `consecutivo_local` único por `(tenant_id, dispositivo_id)` — es el número
  del ticket; doble verdad temporal (`creada_en_cliente` es dato del ticket,
  `recibida_en` es la verdad del servidor); `medio_pago` es texto libre
  acotado por la aplicación (efectivo/fiado hoy; «otros medios registrados
  como dato», ADR-018). `cliente_id` no lleva FK: la tabla `clientes` es del
  módulo de fiado (decisión 8). La única mutación permitida es
  `completada → anulada`.
- `ventas_items` (ADR-018): líneas con el precio CONGELADO en el momento de
  la venta. FK a `ventas` y a `productos` con RESTRICT: ni una venta ni un
  producto con historial se borran físicamente (el borrado del catálogo es
  lógico). Postgres NO aplica RLS al verificar llaves foráneas: que el
  producto sea del propio tenant lo garantiza el servicio, que lo lee por la
  sesión de tenant antes de insertar.
- `movimientos_inventario` (ADR-020, creada aquí por la decisión 1): el libro
  de stock. `cantidad` NUMERIC con signo (la venta descuenta, la anulación
  repone); `referencia_id` es el UUID de la venta (o de la operación de
  anulación) que lo causó. El índice único
  `(tenant_id, tipo, referencia_id, producto_id)` es la segunda red de
  idempotencia: incluye `producto_id` porque una venta tiene varios ítems y
  cada uno es un movimiento con la misma referencia (decisión 2).

## Grants

Los privilegios por defecto de 01-roles.sh conceden los cuatro a `vendi_app`
sobre toda tabla creada por `vendi_platform`, que es lo que el candado
invertido exige para tablas de negocio — incluidas las append-only (decisión
11 del plan, mismo criterio que `productos` y `files`). No se toca nada aquí
a propósito.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEDIOS_DE_PAGO = ("efectivo", "fiado")
TIPOS_DE_MOVIMIENTO = ("venta", "compra", "ajuste", "merma")


def _columnas_base() -> list[sa.Column]:
    """id (acepta el UUID del cliente; server_default para inserts en SQL),
    tenant_id y los timestamps de `TenantModel`."""
    return [
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "dispositivos",
        *_columnas_base(),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("ultima_secuencia", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("ultima_sync", sa.DateTime(timezone=True), nullable=True),
    )
    enable_rls(op, "dispositivos")  # crea ix_dispositivos_tenant_id

    op.create_table(
        "caja_sesiones",
        *_columnas_base(),
        sa.Column("abierta_por", sa.String(120), nullable=False),
        sa.Column("abierta_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("base_inicial", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cerrada_por", sa.String(120), nullable=True),
        sa.Column("cerrada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("efectivo_esperado", sa.Integer(), nullable=True),
        sa.Column("efectivo_contado", sa.Integer(), nullable=True),
        sa.Column("diferencia", sa.Integer(), nullable=True),
        sa.Column("estado", sa.String(16), server_default="abierta", nullable=False),
        sa.CheckConstraint("estado IN ('abierta', 'cerrada')", name="ck_caja_sesiones_estado"),
        sa.CheckConstraint("base_inicial >= 0", name="ck_caja_sesiones_base_no_negativa"),
    )
    # Una sesión ABIERTA por tienda (ADR-021): la regla la hace cumplir la
    # base. Empieza por tenant_id, así que sirve de índice del predicado RLS.
    op.execute(
        "CREATE UNIQUE INDEX ux_caja_sesion_abierta ON caja_sesiones (tenant_id) WHERE estado = 'abierta'"
    )
    enable_rls(op, "caja_sesiones", crear_indice=False)

    op.create_table(
        "ventas",
        *_columnas_base(),
        sa.Column(
            "dispositivo_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("dispositivos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # NOT NULL por la decisión 13 del plan: el sync siempre resuelve a la
        # sesión abierta del tenant o abre una implícita (ADR-018).
        sa.Column(
            "sesion_caja_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("caja_sesiones.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("consecutivo_local", sa.Integer(), nullable=False),
        sa.Column("estado", sa.String(16), server_default="completada", nullable=False),
        # Texto libre acotado por la aplicación: «efectivo | fiado | otros
        # medios registrados como dato» (ADR-018). Sin CHECK para que añadir
        # un medio no sea una migración.
        sa.Column("medio_pago", sa.String(24), nullable=False),
        sa.Column("total_centavos", sa.Integer(), nullable=False),
        # Sin FK: `clientes` es del módulo de fiado (decisión 8 del plan).
        sa.Column("cliente_id", sa.UUID(as_uuid=True), nullable=True),
        # La marca del reloj del dispositivo: dato del ticket, NO orden
        # (puede mentir; la verdad temporal es `recibida_en`, del servidor).
        sa.Column("creada_en_cliente", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recibida_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("secuencia_dispositivo", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("estado IN ('completada', 'anulada')", name="ck_ventas_estado"),
        sa.CheckConstraint("consecutivo_local > 0", name="ck_ventas_consecutivo_positivo"),
        sa.CheckConstraint("total_centavos >= 0", name="ck_ventas_total_no_negativo"),
        sa.CheckConstraint("secuencia_dispositivo > 0", name="ck_ventas_secuencia_positiva"),
    )
    # El número del ticket es único por negocio Y dispositivo (multi-caja,
    # ADR-018): dos cajas repiten números sin colisionar.
    op.create_index(
        "ux_ventas_consecutivo",
        "ventas",
        ["tenant_id", "dispositivo_id", "consecutivo_local"],
        unique=True,
    )
    # Empieza por tenant_id (predicado RLS como Index Cond) y ordena los
    # reportes y el P&L, que suman por la marca del SERVIDOR (ADR-018).
    op.create_index("ix_ventas_tenant_recibida", "ventas", ["tenant_id", "recibida_en"])
    enable_rls(op, "ventas", crear_indice=False)

    op.create_table(
        "ventas_items",
        *_columnas_base(),
        sa.Column(
            "venta_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("ventas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "producto_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("productos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("cantidad", sa.Numeric(14, 3), nullable=False),
        sa.Column("precio_unitario_centavos", sa.Integer(), nullable=False),
        sa.CheckConstraint("cantidad > 0", name="ck_ventas_items_cantidad_positiva"),
        sa.CheckConstraint("precio_unitario_centavos >= 0", name="ck_ventas_items_precio_no_negativo"),
    )
    op.create_index("ix_ventas_items_tenant_venta", "ventas_items", ["tenant_id", "venta_id"])
    enable_rls(op, "ventas_items", crear_indice=False)

    op.create_table(
        "movimientos_inventario",
        *_columnas_base(),
        sa.Column("tipo", sa.String(16), nullable=False),
        sa.Column("cantidad", sa.Numeric(14, 3), nullable=False),
        sa.Column("referencia_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "producto_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("productos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tipo IN (" + ", ".join(f"'{t}'" for t in TIPOS_DE_MOVIMIENTO) + ")",
            name="ck_movimientos_tipo",
        ),
        sa.CheckConstraint("cantidad <> 0", name="ck_movimientos_cantidad_no_cero"),
    )
    # La idempotencia del sync con constraint, no con lógica (ADR-020); con
    # `producto_id` porque una venta tiene varios ítems (decisión 2 del plan).
    op.create_index(
        "ux_movimientos_origen",
        "movimientos_inventario",
        ["tenant_id", "tipo", "referencia_id", "producto_id"],
        unique=True,
    )
    # El libro por producto (auditoría «¿por qué tengo menos arroz?»).
    op.create_index(
        "ix_movimientos_tenant_producto", "movimientos_inventario", ["tenant_id", "producto_id"]
    )
    enable_rls(op, "movimientos_inventario", crear_indice=False)


def downgrade() -> None:
    disable_rls(op, "movimientos_inventario", borrar_indice=False)
    op.drop_index("ix_movimientos_tenant_producto", table_name="movimientos_inventario")
    op.drop_index("ux_movimientos_origen", table_name="movimientos_inventario")
    op.drop_table("movimientos_inventario")
    disable_rls(op, "ventas_items", borrar_indice=False)
    op.drop_index("ix_ventas_items_tenant_venta", table_name="ventas_items")
    op.drop_table("ventas_items")
    disable_rls(op, "ventas", borrar_indice=False)
    op.drop_index("ix_ventas_tenant_recibida", table_name="ventas")
    op.drop_index("ux_ventas_consecutivo", table_name="ventas")
    op.drop_table("ventas")
    disable_rls(op, "caja_sesiones", borrar_indice=False)
    op.execute("DROP INDEX IF EXISTS ux_caja_sesion_abierta")
    op.drop_table("caja_sesiones")
    disable_rls(op, "dispositivos")
    op.drop_table("dispositivos")
```

- [ ] **Paso 3: aplicar la migración y verificar el DDL real.** Con el stack levantado (`bash scripts/dev.sh`):

```bash
bash scripts/migrate.sh
docker compose -f infra/docker-compose.yml exec -T postgres psql -U vendi_platform -d vendi -c "\d ventas" -c "\d movimientos_inventario" -c "\d caja_sesiones"
```

Esperado: `ventas` con las 14 columnas, los 4 checks, los índices `ux_ventas_consecutivo` (único) e `ix_ventas_tenant_recibida`, `Policies: tenant_isolation` y `Row Level Security: enabled (forced)`; `movimientos_inventario` con `ux_movimientos_origen` único de cuatro columnas; `caja_sesiones` con `ux_caja_sesion_abierta` parcial (`WHERE estado = 'abierta'`). Y el downgrade+upgrade corre:

```bash
docker compose -f infra/docker-compose.yml exec -T api alembic downgrade 0004 && docker compose -f infra/docker-compose.yml exec -T api alembic upgrade head
```

- [ ] **Paso 4: el test del Paso 1 pasa, y los tres candados siguen verdes.**

```bash
cd backend && uv run pytest tests/test_aislamiento_ventas.py -q
# Esperado: 10 passed
uv run pytest tests/test_rls_coverage.py tests/test_privilegios_de_vendi_app.py -q -m integration
# Esperado: todos passed (las cinco tablas entran solas en la cobertura RLS y los cuatro grants, sin tocar esos archivos)
```

- [ ] **Paso 5: commit**

```bash
git add backend/services/api/alembic/versions/20260728_0005_ventas.py backend/tests/test_aislamiento_ventas.py
git commit -m "Migración 0005: ventas, ítems, dispositivos, sesiones de caja y libro de movimientos con RLS e idempotencia por constraint"
```

**Criterios de aceptación:**
- `bash scripts/migrate.sh` aplica `0005` limpio sobre una base al día, y el `downgrade`+`upgrade` también corre.
- Los 10 tests de aislamiento pasan contra PostgreSQL real, 0 SKIPPED: cada tabla ve solo su tenant, el `WITH CHECK` rechaza el `tenant_id` inyectado, el consecutivo se repite entre tenants pero no en el mismo dispositivo, el movimiento duplicado choca contra `ux_movimientos_origen`, y la segunda sesión abierta revienta contra `ux_caja_sesion_abierta`.
- `test_rls_coverage.py` y `test_privilegios_de_vendi_app.py` verdes **sin edición**.

---

## Tarea 2: Modelos SQLAlchemy del módulo ventas

**Files:**
- Create: `backend/tests/test_ventas_modelo.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/ventas/__init__.py` (vacío)
- Create: `backend/services/api/app/modules/ventas/models.py`
- Modify: `backend/tests/test_rls_coverage.py` (un import: registra los modelos en el metadata del candado de nivel 1)

**Interfaces:**
- Consume: `vendi_core.db.base.Base`, `TenantModel` (PK UUID + `tenant_id` + timestamps). NO `SoftDeleteMixin`: las ventas y los movimientos son append-only (ADR-018/ADR-020), y los dispositivos y sesiones no se borran en el MVP.
- Produce: las cinco tablas registradas en `Base.metadata`, alineadas columna a columna con la migración 0005.

- [ ] **Paso 1: escribir el test que falla.** Crear `backend/tests/test_ventas_modelo.py`:

```python
"""Los modelos del módulo ventas contra el metadata, sin base de datos.

Es el nivel barato de los candados: corre en cada `pytest` y en cada PR. Lo
caro —que la base migrada tenga las policies, los índices y los grants— lo
cubren `test_rls_coverage.py`, `test_privilegios_de_vendi_app.py` y
`test_aislamiento_ventas.py`.
"""

from __future__ import annotations

from app.modules.ventas.models import CajaSesion, Dispositivo, MovimientoInventario, Venta, VentaItem
from sqlalchemy import CheckConstraint

from vendi_core.db.base import Base, verificar_indices_de_tenant


def test_ventas_tiene_las_columnas_de_adr_018():
    columnas = Venta.__table__.columns
    for nombre in (
        "id", "tenant_id", "created_at", "updated_at",
        "dispositivo_id", "sesion_caja_id", "consecutivo_local", "estado",
        "medio_pago", "total_centavos", "cliente_id", "creada_en_cliente",
        "recibida_en", "secuencia_dispositivo",
    ):
        assert nombre in columnas, f"falta la columna {nombre}"
    assert columnas["cliente_id"].nullable is True, "cliente_id es NULL salvo fiado (ADR-018)"
    assert columnas["sesion_caja_id"].nullable is False, "el sync siempre resuelve la sesión (decisión 13)"
    assert "deleted_at" not in columnas, "la venta es append-only: no hay borrado, hay anulación"


def test_ventas_items_congela_el_precio():
    columnas = VentaItem.__table__.columns
    for nombre in ("id", "tenant_id", "venta_id", "producto_id", "cantidad", "precio_unitario_centavos"):
        assert nombre in columnas, f"falta la columna {nombre}"


def test_movimientos_es_el_libro_con_referencia_de_origen():
    columnas = MovimientoInventario.__table__.columns
    for nombre in ("id", "tenant_id", "tipo", "cantidad", "referencia_id", "producto_id"):
        assert nombre in columnas, f"falta la columna {nombre}"
    assert "deleted_at" not in columnas, "un movimiento jamás se edita ni se borra (ADR-020)"


def test_la_regla_del_indice_de_tenant_se_cumple_con_los_modelos_registrados():
    for tabla in ("ventas", "ventas_items", "dispositivos", "caja_sesiones", "movimientos_inventario"):
        assert tabla not in verificar_indices_de_tenant(Base.metadata)


def test_los_indices_unicos_del_modelo():
    consecutivo = next(i for i in Venta.__table__.indexes if i.name == "ux_ventas_consecutivo")
    assert consecutivo.unique is True
    assert [c.name for c in consecutivo.columns] == ["tenant_id", "dispositivo_id", "consecutivo_local"]

    origen = next(i for i in MovimientoInventario.__table__.indexes if i.name == "ux_movimientos_origen")
    assert origen.unique is True
    assert [c.name for c in origen.columns] == ["tenant_id", "tipo", "referencia_id", "producto_id"], (
        "sin producto_id, la segunda línea de un ticket chocaría con la primera (decisión 2 del plan)"
    )

    abierta = next(i for i in CajaSesion.__table__.indexes if i.name == "ux_caja_sesion_abierta")
    assert abierta.unique is True
    assert [c.name for c in abierta.columns] == ["tenant_id"]
    assert abierta.dialect_options["postgresql"]["where"] is not None, "sin el WHERE solo cabría UNA sesión por negocio en toda su historia"


def test_los_checks_fijan_estados_cantidades_y_dinero():
    def nombres(modelo):
        return {c.name for c in modelo.__table__.constraints if isinstance(c, CheckConstraint)}

    assert {
        "ck_ventas_estado",
        "ck_ventas_consecutivo_positivo",
        "ck_ventas_total_no_negativo",
        "ck_ventas_secuencia_positiva",
    } <= nombres(Venta)
    assert {"ck_ventas_items_cantidad_positiva", "ck_ventas_items_precio_no_negativo"} <= nombres(VentaItem)
    assert {"ck_movimientos_tipo", "ck_movimientos_cantidad_no_cero"} <= nombres(MovimientoInventario)
    assert {"ck_caja_sesiones_estado", "ck_caja_sesiones_base_no_negativa"} <= nombres(CajaSesion)
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_ventas_modelo.py -q
```

Esperado: error de colección `ModuleNotFoundError: No module named 'app.modules.ventas'`.

- [ ] **Paso 2: implementar los modelos.** Crear `backend/services/api/app/modules/ventas/__init__.py` vacío y `backend/services/api/app/modules/ventas/models.py`:

```python
"""Modelos del módulo ventas y del soporte de sync offline (ADR-017/018/020/021).

Cinco tablas, todas de negocio (policy `tenant_isolation` puesta por la
migración 0005):

- `Dispositivo`: el registro de dispositivos que sincronizan (ADR-017).
- `CajaSesion`: la sesión de caja abierta por tienda (ADR-021; la tabla se
  crea aquí por la decisión 3 del plan; el arqueo es del módulo de caja).
- `Venta`: el hecho append-only con PK del cliente (ADR-018). Sin
  `SoftDeleteMixin`: no hay borrado, hay anulación (`completada → anulada`,
  la única mutación permitida).
- `VentaItem`: las líneas con el precio congelado en el momento de la venta.
- `MovimientoInventario`: el libro de stock por deltas (ADR-020; la tabla se
  crea aquí por la decisión 1 del plan; alertas y compras son del módulo 3).

La doble verdad temporal de ADR-018 vive en `Venta`: `creada_en_cliente` es
la marca del reloj del dispositivo (dato del ticket; puede mentir y no pasa
nada, porque NADIE la usa para ordenar) y `recibida_en` es la marca del
servidor (la única verdad temporal del sistema: reportes, P&L y forecast
suman por ella).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import UUID, BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, TenantModel

#: Los dos estados de la venta append-only (ADR-018). La transición permitida
#: es exactamente una: completada → anulada.
ESTADOS_DE_VENTA: tuple[str, ...] = ("completada", "anulada")

#: Los medios de pago del MVP. La columna es texto libre («otros medios
#: registrados como dato», ADR-018); el conjunto cerrado lo aplica el schema.
MEDIOS_DE_PAGO: tuple[str, ...] = ("efectivo", "fiado")

#: Los cuatro tipos del libro (ADR-020). Este módulo solo emite `venta`;
#: `compra`, `ajuste` y `merma` son del módulo de inventario — la constraint
#: ya los admite para que no haga falta migrar nada entonces.
TIPOS_DE_MOVIMIENTO: tuple[str, ...] = ("venta", "compra", "ajuste", "merma")


class Dispositivo(Base, TenantModel):
    """Un dispositivo del negocio que sincroniza su cola (ADR-017).

    `ultima_secuencia` y `ultima_sync` son observabilidad (¿cuándo subió su
    último lote este equipo?), nunca árbitro de nada: la idempotencia la da
    la PK que el cliente puso en cada fila de dominio.
    """

    __tablename__ = "dispositivos"

    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    ultima_secuencia: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    ultima_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CajaSesion(Base, TenantModel):
    """Un turno de caja del negocio (ADR-021). UNA abierta por tienda: lo
    garantiza `ux_caja_sesion_abierta`, no el código."""

    __tablename__ = "caja_sesiones"
    __table_args__ = (
        Index(
            "ux_caja_sesion_abierta",
            "tenant_id",
            unique=True,
            postgresql_where=text("estado = 'abierta'"),
        ),
        CheckConstraint("estado IN ('abierta', 'cerrada')", name="ck_caja_sesiones_estado"),
        CheckConstraint("base_inicial >= 0", name="ck_caja_sesiones_base_no_negativa"),
    )

    abierta_por: Mapped[str] = mapped_column(String(120), nullable=False)
    abierta_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    base_inicial: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    cerrada_por: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    efectivo_esperado: Mapped[int | None] = mapped_column(Integer, nullable=True)
    efectivo_contado: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diferencia: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estado: Mapped[str] = mapped_column(String(16), default="abierta", server_default="abierta", nullable=False)


class Venta(Base, TenantModel):
    """Un hecho de venta, creado en el dispositivo y aceptado tal cual por el
    servidor (ADR-018). Append-only: jamás un UPDATE de ítems ni totales."""

    __tablename__ = "ventas"
    __table_args__ = (
        # El número del ticket: único por negocio Y dispositivo (multi-caja).
        Index("ux_ventas_consecutivo", "tenant_id", "dispositivo_id", "consecutivo_local", unique=True),
        # Predicado RLS como Index Cond + reportes por la marca del servidor.
        Index("ix_ventas_tenant_recibida", "tenant_id", "recibida_en"),
        CheckConstraint("estado IN ('completada', 'anulada')", name="ck_ventas_estado"),
        CheckConstraint("consecutivo_local > 0", name="ck_ventas_consecutivo_positivo"),
        CheckConstraint("total_centavos >= 0", name="ck_ventas_total_no_negativo"),
        CheckConstraint("secuencia_dispositivo > 0", name="ck_ventas_secuencia_positiva"),
    )

    dispositivo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dispositivos.id", ondelete="RESTRICT"), nullable=False
    )
    #: NOT NULL (decisión 13 del plan): el sync siempre resuelve a la sesión
    #: abierta del tenant o abre una implícita (ADR-018).
    sesion_caja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caja_sesiones.id", ondelete="RESTRICT"), nullable=False
    )
    #: El número que ve el tendero y va en el ticket. No es único por negocio:
    #: dos cajas repiten números (ADR-018, consecuencia firmada).
    consecutivo_local: Mapped[int] = mapped_column(Integer, nullable=False)
    estado: Mapped[str] = mapped_column(String(16), default="completada", server_default="completada", nullable=False)
    #: Texto: «efectivo | fiado | otros medios registrados como dato» (ADR-018).
    medio_pago: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Dinero en centavos enteros, jamás flotante (criterio unificado ADR-018).
    total_centavos: Mapped[int] = mapped_column(Integer, nullable=False)
    #: NULL salvo fiado. Sin FK: `clientes` es del módulo de fiado (decisión 8).
    cliente_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: La marca del reloj del dispositivo: dato del ticket, NO orden. Puede
    #: mentir (reloj manipulado) y el sistema no se entera ni le importa.
    creada_en_cliente: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: La marca del servidor: la única verdad temporal del sistema.
    recibida_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    #: La posición de esta venta en la cola FIFO local del dispositivo.
    secuencia_dispositivo: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Venta {self.id} #{self.consecutivo_local} {self.estado}>"


class VentaItem(Base, TenantModel):
    """Una línea de venta. El precio se congela aquí: el ticket no cambia
    aunque el catálogo cambie después (ADR-018)."""

    __tablename__ = "ventas_items"
    __table_args__ = (
        Index("ix_ventas_items_tenant_venta", "tenant_id", "venta_id"),
        CheckConstraint("cantidad > 0", name="ck_ventas_items_cantidad_positiva"),
        CheckConstraint("precio_unitario_centavos >= 0", name="ck_ventas_items_precio_no_negativo"),
    )

    venta_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ventas.id", ondelete="RESTRICT"), nullable=False
    )
    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False
    )
    #: Decimal (granel): el fruver se vende a 0,350 kg.
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    precio_unitario_centavos: Mapped[int] = mapped_column(Integer, nullable=False)


class MovimientoInventario(Base, TenantModel):
    """Una fila del libro de stock (ADR-020). Nunca se edita ni se borra: un
    error se corrige con otro movimiento. La venta descuenta (cantidad
    negativa); su anulación repone (positiva, con `referencia_id` = el id de
    la operación de anulación, no el de la venta: la venta ya tiene sus
    movimientos y el índice único no admitiría los segundos)."""

    __tablename__ = "movimientos_inventario"
    __table_args__ = (
        # La idempotencia del sync con constraint, no con lógica (ADR-020).
        # `producto_id` va en la clave porque una venta tiene varios ítems
        # (decisión 2 del plan).
        Index("ux_movimientos_origen", "tenant_id", "tipo", "referencia_id", "producto_id", unique=True),
        Index("ix_movimientos_tenant_producto", "tenant_id", "producto_id"),
        CheckConstraint(
            "tipo IN (" + ", ".join(f"'{t}'" for t in TIPOS_DE_MOVIMIENTO) + ")",
            name="ck_movimientos_tipo",
        ),
        CheckConstraint("cantidad <> 0", name="ck_movimientos_cantidad_no_cero"),
    )

    tipo: Mapped[str] = mapped_column(String(16), nullable=False)
    #: NUMERIC con signo: la venta descuenta, la compra suma, la anulación repone.
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    #: El UUID de la venta (o de la operación de anulación) que causó la fila.
    referencia_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False
    )
```

- [ ] **Paso 3: registrar los modelos en el candado de nivel 1.** En `backend/tests/test_rls_coverage.py`, añadir junto a los imports de modelos:

```python
from app.modules.ventas.models import CajaSesion, Dispositivo, MovimientoInventario, Venta, VentaItem  # noqa: F401
```

- [ ] **Paso 4: verificar.**

```bash
cd backend && uv run pytest tests/test_ventas_modelo.py tests/test_rls_coverage.py -q -m 'not integration'
# Esperado: 7 passed (6 del modelo + 1 del candado de nivel 1)
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 5: commit**

```bash
git add backend/services/api/app/modules/ventas/__init__.py backend/services/api/app/modules/ventas/models.py backend/tests/test_ventas_modelo.py backend/tests/test_rls_coverage.py
git commit -m "Modelos del módulo ventas alineados con la migración 0005"
```

**Criterios de aceptación:** los 6 tests de modelo pasan sin base de datos; el candado de nivel 1 de RLS sigue verde con los cinco modelos registrados; `ruff` limpio.

---

## Tarea 3: Schemas Pydantic del sync y de ventas

**Files:**
- Create: `backend/tests/test_ventas_schemas.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/ventas/schemas.py`

**Interfaces:**
- Consume: `MEDIOS_DE_PAGO` y `ESTADOS_DE_VENTA` del modelo (una sola fuente); `TOPE_PRECIO` y `TOPE_STOCK` de `app.modules.catalogo.schemas` (las cotas aprendidas del BUG-2 del QA); `ProductoSalida` del catálogo (el delta devuelve productos con el contrato ya congelado).
- Produce: `DispositivoRegistrar`, `DispositivoSalida`, `VentaItemSync`, `VentaCrearSync`, `VentaAnularSync`, `OperacionSync`, `LoteSync`, `ResultadoOperacion`, `RespuestaLote`, `DeltaSalida`. Es el contrato que congela el OpenAPI: cada cambio aquí es un cambio de contrato.

- [ ] **Paso 1: escribir el test que falla.** Crear `backend/tests/test_ventas_schemas.py`:

```python
"""Validación de entrada del sync de ventas, sin base de datos.

Las cotas NO son cosméticas: un entero que desborda su columna sale como
`DataError` de Postgres → 500, no 422 (BUG-2 del QA del catálogo). Todo lo
que entra lleva cota contra su tipo de columna, y los validadores
`mode="before"` no asumen `str` (BUG-1).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.modules.catalogo.schemas import TOPE_PRECIO, TOPE_STOCK
from app.modules.ventas.schemas import (
    LoteSync,
    OperacionSync,
    VentaAnularSync,
    VentaCrearSync,
    VentaItemSync,
)
from pydantic import ValidationError

AHORA = datetime.now(UTC)


def _item(**campos) -> dict:
    return {"producto_id": str(uuid.uuid4()), "cantidad": "1", "precio_unitario_centavos": 2500, **campos}


def _venta(**campos) -> dict:
    return {
        "consecutivo_local": 1,
        "medio_pago": "efectivo",
        "total_centavos": 2500,
        "creada_en_cliente": AHORA.isoformat(),
        "items": [_item()],
        **campos,
    }


def test_una_venta_minima_valida():
    datos = VentaCrearSync.model_validate(_venta())
    assert datos.estado == "completada"
    assert datos.cliente_id is None
    assert datos.items[0].cantidad == Decimal("1")


def test_el_total_no_puede_desbordar_el_int32_de_la_columna():
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(total_centavos=TOPE_PRECIO + 1))
    assert VentaCrearSync.model_validate(_venta(total_centavos=TOPE_PRECIO)).total_centavos == TOPE_PRECIO


def test_la_cantidad_es_positiva_y_cabe_en_numeric_14_3():
    with pytest.raises(ValidationError):
        VentaItemSync.model_validate(_item(cantidad="0"))
    with pytest.raises(ValidationError):
        VentaItemSync.model_validate(_item(cantidad=str(TOPE_STOCK + 1)))
    # El granel: 0,350 kg es una cantidad legítima.
    assert VentaItemSync.model_validate(_item(cantidad="0.350")).cantidad == Decimal("0.350")


def test_el_precio_unitario_no_desborda():
    with pytest.raises(ValidationError):
        VentaItemSync.model_validate(_item(precio_unitario_centavos=-1))
    with pytest.raises(ValidationError):
        VentaItemSync.model_validate(_item(precio_unitario_centavos=TOPE_PRECIO + 1))


def test_el_medio_de_pago_es_uno_de_los_del_mvp():
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(medio_pago="tarjeta"))
    assert VentaCrearSync.model_validate(_venta(medio_pago="fiado", cliente_id=str(uuid.uuid4()))).medio_pago == "fiado"


def test_creada_en_cliente_debe_traer_zona_horaria():
    """El reloj del cliente es dato (se acepta 1970 o 2099, ADR-017), pero un
    timestamp naive no dice nada: sin offset no hay ticket interpretable."""
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(creada_en_cliente="2026-07-28T10:00:00"))
    lejano = VentaCrearSync.model_validate(_venta(creada_en_cliente="2099-01-01T00:00:00+00:00"))
    assert lejano.creada_en_cliente.year == 2099, "el reloj manipulado se guarda como DATO; no se rechaza"


def test_una_venta_sin_items_no_es_una_venta():
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(items=[]))


def test_campos_desconocidos_se_rechazan():
    """`extra="forbid"`: un `tenant_id` inyectado en el payload no se ignora,
    se rechaza — la defensa en profundidad del WITH CHECK de ADR-017."""
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(tenant_id=str(uuid.uuid4())))


def test_el_consecutivo_y_la_secuencia_son_positivos_y_acotados():
    with pytest.raises(ValidationError):
        VentaCrearSync.model_validate(_venta(consecutivo_local=0))
    with pytest.raises(ValidationError):
        OperacionSync(id=uuid.uuid4(), tipo="venta.crear", secuencia=0, datos=_venta())
    # secuencia es BIGINT en columna: la cota es 2^63-1.
    with pytest.raises(ValidationError):
        OperacionSync(id=uuid.uuid4(), tipo="venta.crear", secuencia=2**63, datos=_venta())


def test_el_lote_tiene_tope_de_200_operaciones():
    operacion = {"id": str(uuid.uuid4()), "tipo": "venta.crear", "secuencia": 1, "datos": _venta()}
    with pytest.raises(ValidationError):
        LoteSync(dispositivo_id=uuid.uuid4(), operaciones=[operacion] * 201)
    lote = LoteSync(dispositivo_id=uuid.uuid4(), operaciones=[operacion])
    assert lote.operaciones[0].tipo == "venta.crear"
    assert isinstance(lote.operaciones[0].datos, dict), "datos se valida por operación en el servicio (decisión 6)"


def test_el_tipo_es_texto_libre_acotado():
    """Un tipo desconocido es `rechazada` por operación, no 422 del lote
    (decisión 6): el schema solo acota el largo."""
    operacion = OperacionSync(id=uuid.uuid4(), tipo="venta.futurista", secuencia=1, datos={})
    assert operacion.tipo == "venta.futurista"


def test_anular_solo_necesita_la_venta():
    datos = VentaAnularSync.model_validate({"venta_id": str(uuid.uuid4())})
    assert datos.venta_id is not None
    with pytest.raises(ValidationError):
        VentaAnularSync.model_validate({})
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_ventas_schemas.py -q
```

Esperado: error de colección `ModuleNotFoundError: No module named 'app.modules.ventas.schemas'`.

- [ ] **Paso 2: implementar los schemas.** Crear `backend/services/api/app/modules/ventas/schemas.py`:

```python
"""Esquemas de entrada y salida del módulo ventas y del sync offline.

El contrato que consume el frontend (y la app del POS) sale de aquí vía
`openapi.json`: cada cambio es un cambio de contrato y se regenera
`docs/api/openapi-fase0.json` con su cliente TypeScript.

Reglas duras heredadas del QA del catálogo:

- Cotas `le=` contra el tipo de columna en TODO número de entrada: un
  overflow de `Integer` o `Numeric(14,3)` es un `DataError` → 500, no un 422.
- Dinero en centavos enteros; cantidades en `Decimal`; jamás flotante.
- `extra="forbid"` en los payloads de dominio: un campo inyectado (p. ej.
  `tenant_id`) se rechaza, no se ignora silenciosamente.
- `creada_en_cliente` exige zona horaria pero NO se acota en rango: el reloj
  del cliente es dato del ticket, no árbitro (ADR-017/018).

La validación de NEGOCIO por operación (fiado⇔cliente, total coherente con
los ítems, duplicados, divergencia) NO está aquí: la hace el servicio dentro
del procesamiento del lote para que una operación mala no arrastre a las
demás al 422 (decisión 6 del plan).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.catalogo.schemas import TOPE_PRECIO, TOPE_STOCK, ProductoSalida
from app.modules.ventas.models import ESTADOS_DE_VENTA, MEDIOS_DE_PAGO

#: Tope de la columna `BigInteger` (2^63 - 1) de `secuencia_dispositivo`.
TOPE_SECUENCIA = 9_223_372_036_854_775_807

#: Tope de operaciones por lote (decisión 7 del plan): acota la transacción
#: que retiene los bloqueos de fila del stock.
TOPE_OPERACIONES_POR_LOTE = 200

#: Tope de líneas por ticket: suficiente para cualquier venta de barrio.
TOPE_ITEMS_POR_VENTA = 500


def _exigir_con_zona(valor: datetime) -> datetime:
    if valor.tzinfo is None or valor.tzinfo.utcoffset(valor) is None:
        raise ValueError("La fecha debe traer zona horaria (offset): un timestamp sin zona no dice nada.")
    return valor


class DispositivoRegistrar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: UUID generado por el cliente (ADR-017): re-registrar es un no-op.
    id: uuid.UUID | None = None
    nombre: str = Field(min_length=1, max_length=120)

    _nombre_limpio = field_validator("nombre", mode="before")(
        # BUG-1 del QA: lo que no sea str pasa intacto y pydantic da 422.
        lambda v: " ".join(v.split()) if isinstance(v, str) else v
    )


class DispositivoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    ultima_secuencia: int
    ultima_sync: datetime | None = None


class VentaItemSync(BaseModel):
    """Una línea de ticket. El precio viene CONGELADO del dispositivo: el
    servidor no recalcula desde el catálogo (ADR-018, decisión 14)."""

    model_config = ConfigDict(extra="forbid")

    producto_id: uuid.UUID
    cantidad: Decimal = Field(gt=0, le=TOPE_STOCK)
    precio_unitario_centavos: int = Field(ge=0, le=TOPE_PRECIO)


class VentaCrearSync(BaseModel):
    """Los datos de una operación `venta.crear`. El id de la venta es el id
    de la OPERACIÓN (va en `OperacionSync.id`): es la PK que puso el cliente.

    Fiado⇔cliente y la coherencia total/ítems las verifica el servicio por
    operación (rechazada con motivo), no el schema — ver la cabecera.
    """

    model_config = ConfigDict(extra="forbid")

    consecutivo_local: int = Field(ge=1, le=TOPE_PRECIO)
    estado: Literal["completada", "anulada"] = "completada"
    medio_pago: Literal["efectivo", "fiado"]
    total_centavos: int = Field(ge=0, le=TOPE_PRECIO)
    cliente_id: uuid.UUID | None = None
    creada_en_cliente: datetime
    items: list[VentaItemSync] = Field(min_length=1, max_length=TOPE_ITEMS_POR_VENTA)

    _con_zona = field_validator("creada_en_cliente")(_exigir_con_zona)


class VentaAnularSync(BaseModel):
    """Los datos de una operación `venta.anular`: anular una venta YA
    ACEPTADA por el servidor. El id de la operación (`OperacionSync.id`) es
    el que referencian los movimientos de reposición de stock."""

    model_config = ConfigDict(extra="forbid")

    venta_id: uuid.UUID


class OperacionSync(BaseModel):
    """Una operación de la cola del dispositivo.

    `tipo` es texto libre acotado, no Literal: un tipo desconocido (cliente y
    servidor de versiones distintas) es `rechazada` por operación, no un 422
    del lote entero (decisión 6). `datos` viaja como dict y lo valida el
    servicio contra `VentaCrearSync`/`VentaAnularSync` por la misma razón.
    """

    model_config = ConfigDict(extra="forbid")

    #: El UUID del cliente. En `venta.crear` ES la PK de la venta; en
    #: `venta.anular` es el id de la operación de anulación.
    id: uuid.UUID
    tipo: str = Field(min_length=1, max_length=40)
    #: Posición FIFO en la cola local del dispositivo (ADR-017).
    secuencia: int = Field(ge=1, le=TOPE_SECUENCIA)
    datos: dict[str, Any] = Field(default_factory=dict)


class LoteSync(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispositivo_id: uuid.UUID
    operaciones: list[OperacionSync] = Field(min_length=1, max_length=TOPE_OPERACIONES_POR_LOTE)


class ResultadoOperacion(BaseModel):
    """El desenlace de UNA operación del lote (ADR-017):

    - `aceptada`: se aplicó (venta registrada/anulada, stock movido, evento
      encolado — todo en la transacción del lote).
    - `duplicada`: ya estaba aplicada exactamente igual; no-op sin evento.
    - `rechazada`: bien formada pero negada por el dominio; `motivo` es el
      `code` estable y `detalles` el contexto (campos divergentes, etc.).
    """

    id: uuid.UUID
    tipo: str
    resultado: Literal["aceptada", "duplicada", "rechazada"]
    motivo: str | None = None
    detalles: dict[str, Any] | None = None


class RespuestaLote(BaseModel):
    """Un resultado por operación, en el MISMO orden del lote."""

    resultados: list[ResultadoOperacion]


class DeltaSalida(BaseModel):
    """El drenado de datos de referencia hacia el dispositivo (ADR-017).

    `hasta` es la marca del SERVIDOR que el dispositivo guarda y devuelve
    como próximo `desde`: el watermark nunca lo pone el reloj del cliente.
    `eliminados` son tumbas: el dispositivo los quita de su IndexedDB.
    """

    hasta: datetime
    productos: list[ProductoSalida]
    eliminados: list[uuid.UUID]


__all__ = [
    "DeltaSalida",
    "DispositivoRegistrar",
    "DispositivoSalida",
    "ESTADOS_DE_VENTA",
    "LoteSync",
    "MEDIOS_DE_PAGO",
    "OperacionSync",
    "RespuestaLote",
    "ResultadoOperacion",
    "TOPE_OPERACIONES_POR_LOTE",
    "VentaAnularSync",
    "VentaCrearSync",
    "VentaItemSync",
]
```

- [ ] **Paso 3: verificar.**

```bash
cd backend && uv run pytest tests/test_ventas_schemas.py -q
# Esperado: 12 passed
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/ventas/schemas.py backend/tests/test_ventas_schemas.py
git commit -m "Schemas del sync de ventas: cotas de columnas, lote acotado y doble verdad temporal"
```

**Criterios de aceptación:** los 12 tests pasan; ningún número de entrada puede desbordar su columna; `creada_en_cliente` naive se rechaza pero 1970/2099 se aceptan como dato; el lote se corta en 200 operaciones; `ruff` limpio.

---

## Tarea 4: Permisos `venta:crear` / `venta:anular` en `vendi-core` (ADR-023)

**Files:**
- Modify: `backend/tests/test_auth_policies.py` (primero: los tests que fallan)
- Modify: `backend/libs/vendi-core/src/vendi_core/auth/policies.py`

**Interfaces:**
- Consume: `PERMISSION_CATALOG`, `PERMISOS_POR_ROL`, `roles_de_realm_del_grupo` (la siembra `app/scripts/seed.py` los lee: **no hay que tocar la siembra**, re-ejecutarla basta).
- Produce: los dos permisos de ventas declarados y repartidos: `dueno` ambos, `cajero` solo `venta:crear` (NO anula — es la decisión de ADR-023), `almacenista` ninguno (no vende).

- [ ] **Paso 1: actualizar los tests que fallan.** En `backend/tests/test_auth_policies.py`:

  a) En `test_el_catalogo_declara_los_permisos`, ampliar el conjunto esperado con los dos nuevos (añadir al import `PERM_VENTA_ANULAR` y `PERM_VENTA_CREAR`):

```python
def test_el_catalogo_declara_los_permisos():
    nombres = {p[0] for p in PERMISSION_CATALOG}
    assert nombres == {
        PERM_TENANT_READ,
        PERM_TENANT_CREATE,
        PERM_TENANT_UPDATE,
        PERM_TENANT_DELETE,
        PERM_PLATFORM_ADMIN,
        PERM_AUDIT_READ,
        PERM_PRODUCTO_LEER,
        PERM_PRODUCTO_EDITAR,
        PERM_VENTA_CREAR,
        PERM_VENTA_ANULAR,
    }
```

  b) Reemplazar `test_el_reparto_de_permisos_de_catalogo_es_el_de_adr_023` por:

```python
def test_el_reparto_de_permisos_es_el_de_adr_023():
    """El cajero VENDE pero no anula: anular es uno de los dos gestos con los
    que se desfalca una tienda y queda en manos del dueño en el MVP
    (ADR-023). El almacenista no vende: su trabajo es el estante."""
    assert PERMISOS_POR_ROL[ROL_CAJERO] == frozenset({PERM_PRODUCTO_LEER, PERM_VENTA_CREAR})
    assert PERM_VENTA_ANULAR not in PERMISOS_POR_ROL[ROL_CAJERO]
    assert PERMISOS_POR_ROL[ROL_ALMACENISTA] == frozenset({PERM_PRODUCTO_LEER, PERM_PRODUCTO_EDITAR})
    assert {PERM_PRODUCTO_LEER, PERM_PRODUCTO_EDITAR, PERM_VENTA_CREAR, PERM_VENTA_ANULAR} <= PERMISOS_POR_ROL[
        ROL_DUENO
    ]
```

  c) En `test_el_grupo_de_un_rol_mapea_el_rol_y_sus_permisos`, actualizar la aserción del cajero:

```python
    # El cajero ya vende (ADR-023): el grupo mapea el rol Y sus dos permisos.
    assert roles_de_realm_del_grupo(ROL_CAJERO) == sorted({ROL_CAJERO, PERM_PRODUCTO_LEER, PERM_VENTA_CREAR})
```

  d) El candado `test_todo_permiso_asignado_a_un_rol_esta_en_el_catalogo` (creado en el módulo catálogo) no se toca: pasa solo cuando el catálogo y el reparto están bien.

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_auth_policies.py -q
```

Esperado: fallos con `ImportError: cannot import name 'PERM_VENTA_CREAR'`.

- [ ] **Paso 2: implementar en `policies.py`.** En `backend/libs/vendi-core/src/vendi_core/auth/policies.py`:

  a) Tras los permisos de catálogo, añadir:

```python
# Ventas y sync offline (ADR-018/ADR-023). El cajero crea ventas pero NO las
# anula: anular es un gesto con dinero y queda en manos del dueño en el MVP.
PERM_VENTA_CREAR = "venta:crear"
PERM_VENTA_ANULAR = "venta:anular"
```

  b) Ampliar `PERMISSION_CATALOG` con dos entradas `(PERM_VENTA_CREAR, "venta")` y `(PERM_VENTA_ANULAR, "venta")`.

  c) Ampliar `_PERMISOS_DUENO` con `PERM_VENTA_CREAR` y `PERM_VENTA_ANULAR`, y dejar el reparto así:

```python
# ADR-023: el cajero consulta el catálogo y vende, pero NO edita el catálogo
# ni anula ventas (anular y arquear son los gestos con los que se desfalca
# una tienda; son del dueño en el MVP). El almacenista mantiene el catálogo y
# no vende. El resto de permisos de cada rol llega con su módulo.
_PERMISOS_CAJERO: frozenset[str] = frozenset({PERM_PRODUCTO_LEER, PERM_VENTA_CREAR})
_PERMISOS_ALMACENISTA: frozenset[str] = frozenset({PERM_PRODUCTO_LEER, PERM_PRODUCTO_EDITAR})
```

  d) Actualizar el comentario del bloque (el que dice «El reparto de ADR-023 para el catálogo…») por el párrafo de arriba.

- [ ] **Paso 3: verificar y resembrar el realm de desarrollo.**

```bash
cd backend && uv run pytest tests/test_auth_policies.py tests/test_auth_dependencies.py -q
# Esperado: todos passed
bash scripts/seed.sh
# Esperado: permisos_sembrados cuantos=10; los grupos quedan con el diff aplicado
```

La resiembra es idempotente: `ensure_realm_role` crea los dos roles de realm nuevos y `set_group_realm_roles` hace diff en los grupos (el cajero gana `venta:crear`; el dueño gana los dos).

- [ ] **Paso 4: commit**

```bash
git add backend/libs/vendi-core/src/vendi_core/auth/policies.py backend/tests/test_auth_policies.py
git commit -m "Permisos de ventas en el catálogo de Vendi: venta:crear para el cajero, venta:anular solo para el dueño (ADR-023)"
```

**Criterios de aceptación:** `test_auth_policies.py` verde con el reparto nuevo (cajero sin `venta:anular`, explícito); el candado «todo permiso asignado está en el catálogo» sigue verde; `bash scripts/seed.sh` siembra los dos roles de realm nuevos sin error.

---

## Tarea 5: Servicio de ventas y sync por lotes (`VentasService`)

**Files:**
- Create: `backend/tests/test_sync_idempotente.py` (primero: el candado de ADR-017/018/020 que falla)
- Create: `backend/tests/test_ventas_servicio.py` (primero: los tests que fallan)
- Create: `backend/services/api/app/modules/ventas/service.py`

**Interfaces:**
- Consume: sesión de tenant (RLS activo: el servicio NUNCA filtra por `tenant_id` a mano), `DomainEventService.emit` (outbox transaccional), errores de `vendi_core.errors.domain`, modelos `Producto` (catálogo) y los propios.
- Produce: registro de dispositivos idempotente; `procesar_lote` con una transacción, un SAVEPOINT por operación y resultado `aceptada`/`duplicada`/`rechazada`; aplicación de venta con ítems + movimientos de salida + proyección `stock_actual` + evento `venta.creada`; anulación no destructiva con movimiento inverso + evento `venta.anulada`; resolución de sesión de caja (abierta o implícita); `delta_productos` para el drenado.

- [ ] **Paso 1: escribir el candado de idempotencia que falla.** Crear `backend/tests/test_sync_idempotente.py`:

```python
"""EL candado del sync offline (ADR-017, ADR-018, ADR-020).

El mismo lote enviado DOS veces —el reintento de red del dispositivo, la
doble pulsación, el drenado reanudado a medias— deja exactamente: UNA venta,
UN movimiento de stock por ítem, la proyección descontada UNA vez y UN evento
`venta.creada`. La segunda aplicación se reporta `duplicada`, no error.

La base no se dobla: la idempotencia la dan la PK del cliente y el índice
único `ux_movimientos_origen`, y ambos solo existen en PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.ventas.schemas import LoteSync
from app.modules.ventas.service import VentasService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Un dispositivo y un producto con stock 10 en T1. Limpia antes y después."""
    ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4()}
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                 "VALUES (:p, :t, 'Arroz 500g', 2500, 10)"),
            {"p": ids["producto"], "t": T1},
        )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


def _lote(semilla: dict, venta_id: uuid.UUID) -> LoteSync:
    return LoteSync.model_validate(
        {
            "dispositivo_id": str(semilla["dispositivo"]),
            "operaciones": [
                {
                    "id": str(venta_id),
                    "tipo": "venta.crear",
                    "secuencia": 7,
                    "datos": {
                        "consecutivo_local": 42,
                        "medio_pago": "efectivo",
                        "total_centavos": 5000,
                        "creada_en_cliente": datetime.now(UTC).isoformat(),
                        "items": [
                            {"producto_id": str(semilla["producto"]), "cantidad": "2",
                             "precio_unitario_centavos": 2500}
                        ],
                    },
                }
            ],
        }
    )


async def _contar(pg_platform_url: str, sql: str, **params) -> int:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar_one()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_el_mismo_lote_dos_veces_deja_una_venta_un_movimiento_y_un_evento(
    pg_app_url: str, pg_platform_url: str, semilla
):
    venta_id = uuid.uuid4()
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        for esperado in ("aceptada", "duplicada"):
            async with factory() as s:
                servicio = VentasService(session=s, tenant_id=T1, actor_id="cajero-prueba", puede_anular=True)
                resultados = await servicio.procesar_lote(_lote(semilla, venta_id))
                assert [r.resultado for r in resultados] == [esperado]
                await s.commit()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()

    assert await _contar(pg_platform_url, "SELECT count(*) FROM ventas WHERE tenant_id = :t", t=T1) == 1
    assert (
        await _contar(
            pg_platform_url,
            "SELECT count(*) FROM movimientos_inventario WHERE tenant_id = :t AND tipo = 'venta'",
            t=T1,
        )
        == 1
    )
    stock = await _contar(
        pg_platform_url, "SELECT stock_actual::int FROM productos WHERE tenant_id = :t", t=T1
    )
    assert stock == 8, "el stock se descontó UNA vez, no dos"
    eventos = await _contar(
        pg_platform_url, "SELECT count(*) FROM outbox_messages WHERE routing_key = :k", k=f"{T1}.venta.creada"
    )
    assert eventos == 1, "una sola vez por operación aceptada (ADR-017): la duplicada NO re-emite"
```

- [ ] **Paso 2: escribir el resto de los tests del servicio que fallan.** Crear `backend/tests/test_ventas_servicio.py`:

```python
"""`VentasService` contra el PostgreSQL real, con el rol `vendi_app`.

Misma regla que `test_catalogo_servicio.py`: la base no se dobla. Aquí se
fijan los comportamientos firmados del sync que no son la idempotencia (esa
tiene su propio archivo): orden de recepción como verdad, reloj del cliente
como dato, sesión implícita, divergencia de payload, fiado y anulación.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.ventas.schemas import DispositivoRegistrar, LoteSync
from app.modules.ventas.service import VentasService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4(), "producto2": uuid.uuid4()}
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                 "VALUES (:p, :t, 'Arroz 500g', 2500, 10)"),
            {"p": ids["producto"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                 "VALUES (:p, :t, 'Huevo und', 600, 3)"),
            {"p": ids["producto2"], "t": T1},
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
            yield VentasService(session=s, tenant_id=T1, actor_id="cajero-prueba", puede_anular=True)
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


def _op_venta(semilla: dict, venta_id: uuid.UUID, secuencia: int = 1, **datos) -> dict:
    cuerpo = {
        "consecutivo_local": 1,
        "medio_pago": "efectivo",
        "total_centavos": 2500,
        "creada_en_cliente": datetime.now(UTC).isoformat(),
        "items": [
            {"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": 2500}
        ],
        **datos,
    }
    return {"id": str(venta_id), "tipo": "venta.crear", "secuencia": secuencia, "datos": cuerpo}


def _lote(semilla: dict, *operaciones: dict) -> LoteSync:
    return LoteSync.model_validate({"dispositivo_id": str(semilla["dispositivo"]), "operaciones": list(operaciones)})


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


# --- Dispositivos ---------------------------------------------------------------


async def test_registrar_dispositivo_es_idempotente_por_el_id_del_cliente(servicio):
    el_id = uuid.uuid4()
    primero = await servicio.registrar_dispositivo(DispositivoRegistrar(id=el_id, nombre="Caja 1"))
    segundo = await servicio.registrar_dispositivo(DispositivoRegistrar(id=el_id, nombre="Caja 1"))
    assert primero.id == segundo.id == el_id


# --- Aplicación de ventas -------------------------------------------------------


async def test_aplicar_una_venta_descuenta_stock_abre_sesion_implicita_y_emite_evento(
    servicio, semilla, pg_platform_url
):
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4())))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()

    fila = await _uno(pg_platform_url, "SELECT estado, medio_pago FROM ventas WHERE tenant_id = :t", t=T1)
    assert fila.estado == "completada"
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == Decimal("9")
    sesiones = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta'",
        t=T1,
    )
    assert sesiones.n == 1, "ADR-018: sin sesión abierta, el servidor abre UNA implícita"
    eventos = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k", k=f"{T1}.venta.creada"
    )
    assert eventos.n == 1


async def test_la_segunda_venta_reusa_la_sesion_implicita(servicio, semilla, pg_platform_url):
    await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), secuencia=1)))
    await servicio.procesar_lote(
        _lote(semilla, _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2))
    )
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM caja_sesiones WHERE tenant_id = :t", t=T1)
    assert fila.n == 1


async def test_el_stock_puede_quedar_negativo_y_la_venta_se_acepta(servicio, semilla, pg_platform_url):
    """ADR-020: la tienda ya vendió físicamente esa unidad; bloquear la venta
    por el stock del servidor rompería justo el escenario del offline."""
    datos = {"items": [{"producto_id": str(semilla["producto2"]), "cantidad": "5",
                        "precio_unitario_centavos": 600}], "total_centavos": 3000}
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), **datos)))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto2"])
    assert stock.stock_actual == Decimal("-2")


async def test_el_reloj_del_cliente_es_dato_y_la_verdad_es_recibida_en(servicio, semilla, pg_platform_url):
    """El escenario de QA «reloj adelantado/atrasado»: se acepta y se guarda
    para el ticket, pero el orden lo da el servidor."""
    datos = {"creada_en_cliente": "1999-12-31T23:00:00-05:00"}
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), **datos)))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT creada_en_cliente, recibida_en FROM ventas WHERE tenant_id = :t", t=T1)
    assert fila.creada_en_cliente.year == 1999, "el dato del ticket se conserva tal cual"
    assert fila.recibida_en.year >= 2026, "la verdad temporal es del servidor"


async def test_las_operaciones_se_aplican_en_el_orden_del_lote_no_del_reloj(servicio, semilla, pg_platform_url):
    """Fuera de orden: la secuencia 2 llega en el mismo lote ANTES que la 1
    (la cola del dispositivo se reordenó). Las dos se aceptan y el orden de
    recepción es la verdad (ADR-017)."""
    v2, v1 = uuid.uuid4(), uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(
            semilla,
            _op_venta(semilla, v2, secuencia=2, consecutivo_local=2),
            _op_venta(semilla, v1, secuencia=1, consecutivo_local=1),
        )
    )
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada"]
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas WHERE tenant_id = :t", t=T1)
    assert fila.n == 2
    dispositivo = await _uno(
        pg_platform_url, "SELECT ultima_secuencia FROM dispositivos WHERE id = :d", d=semilla["dispositivo"]
    )
    assert dispositivo.ultima_secuencia == 2


# --- Rechazos de dominio (por operación, sin abortar el lote) --------------------


async def test_payload_divergente_con_el_mismo_id_es_rechazada_con_detalles(servicio, semilla, pg_platform_url):
    """Decisión 4 del plan: la trampa del QA del catálogo aquí es rechazo
    explícito. O es el mismo hecho, o es otro que el tendero resuelve a cara
    vista — nunca un no-op silencioso con dinero de por medio."""
    venta_id = uuid.uuid4()
    await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, venta_id)))
    await servicio._session.commit()

    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, venta_id, total_centavos=9999)))
    assert [r.resultado for r in resultados] == ["rechazada"]
    assert resultados[0].motivo == "venta_id_divergente"
    assert "total_centavos" in resultados[0].detalles["campos"]
    fila = await _uno(pg_platform_url, "SELECT total_centavos FROM ventas WHERE id = :v", v=venta_id)
    assert fila.total_centavos == 2500, "la divergencia NO pisa la venta aceptada"


async def test_un_producto_que_no_existe_rechaza_solo_esa_operacion(servicio, semilla, pg_platform_url):
    fantasma = _op_venta(
        semilla, uuid.uuid4(), secuencia=1,
        items=[{"producto_id": str(uuid.uuid4()), "cantidad": "1", "precio_unitario_centavos": 100}],
        total_centavos=100,
    )
    buena = _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2)
    resultados = await servicio.procesar_lote(_lote(semilla, fantasma, buena))
    assert [r.resultado for r in resultados] == ["rechazada", "aceptada"]
    assert resultados[0].motivo == "producto_no_encontrado"
    await servicio._session.commit()
    fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM ventas WHERE tenant_id = :t", t=T1)
    assert fila.n == 1, "la buena se aplicó: una operación mala no arrastra el lote"


async def test_el_fiado_exige_cliente_y_el_efectivo_lo_prohibe(servicio, semilla):
    sin_cliente = _op_venta(semilla, uuid.uuid4(), medio_pago="fiado")
    con_cliente = _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2,
                            cliente_id=str(uuid.uuid4()))
    resultados = await servicio.procesar_lote(_lote(semilla, sin_cliente, con_cliente))
    assert [(r.resultado, r.motivo) for r in resultados] == [
        ("rechazada", "fiado_requiere_cliente"),
        ("rechazada", "cliente_solo_en_fiado"),
    ]


async def test_el_total_debe_cuadrar_con_los_items(servicio, semilla):
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), total_centavos=9999)))
    assert [r.resultado for r in resultados] == ["rechazada"]
    assert resultados[0].motivo == "total_incoherente"


async def test_datos_mal_formados_rechazan_la_operacion_no_el_lote(servicio, semilla):
    """Decisión 6: `datos` se valida por operación dentro del servicio."""
    mala = {"id": str(uuid.uuid4()), "tipo": "venta.crear", "secuencia": 1, "datos": {"consecutivo_local": "x"}}
    buena = _op_venta(semilla, uuid.uuid4(), secuencia=2, consecutivo_local=2)
    resultados = await servicio.procesar_lote(_lote(semilla, mala, buena))
    assert [r.resultado for r in resultados] == ["rechazada", "aceptada"]
    assert resultados[0].motivo == "datos_invalidos"


async def test_un_tipo_desconocido_es_rechazada_no_422(servicio, semilla):
    futura = {"id": str(uuid.uuid4()), "tipo": "compra.registrar", "secuencia": 1, "datos": {}}
    resultados = await servicio.procesar_lote(_lote(semilla, futura))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "tipo_desconocido")]


async def test_el_consecutivo_repetido_en_el_mismo_dispositivo_se_rechaza(servicio, semilla):
    await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4())))
    await servicio._session.commit()
    # Otro id de venta, mismo consecutivo: es OTRA venta con el número ya dado.
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), secuencia=2)))
    assert [r.resultado for r in resultados] == ["rechazada"]
    assert resultados[0].motivo == "consecutivo_duplicado"


# --- Anulación como operación nueva ----------------------------------------------


async def _vender(servicio, semilla, venta_id: uuid.UUID, secuencia: int = 1) -> None:
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, venta_id, secuencia=secuencia)))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()


async def test_anular_repone_stock_emite_evento_y_no_toca_la_venta_original(servicio, semilla, pg_platform_url):
    venta_id = uuid.uuid4()
    await _vender(servicio, semilla, venta_id)

    anulacion_id = uuid.uuid4()
    op = {"id": str(anulacion_id), "tipo": "venta.anular", "secuencia": 2, "datos": {"venta_id": str(venta_id)}}
    resultados = await servicio.procesar_lote(_lote(semilla, op))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()

    fila = await _uno(
        pg_platform_url, "SELECT estado, total_centavos FROM ventas WHERE id = :v", v=venta_id
    )
    assert fila.estado == "anulada"
    assert fila.total_centavos == 2500, "append-only: la anulación NO modifica la venta original"
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == Decimal("10"), "el delta inverso repuso el stock"
    movimientos = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM movimientos_inventario WHERE tenant_id = :t AND producto_id = :p",
        t=T1, p=semilla["producto"],
    )
    assert movimientos.n == 2, "salida y reposición: el libro cuenta las dos (ADR-020)"
    for clave, cuantos in ((f"{T1}.venta.creada", 1), (f"{T1}.venta.anulada", 1)):
        fila = await _uno(pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k", k=clave)
        assert fila.n == cuantos, f"{clave}: {cuantos}"


async def test_anular_dos_veces_es_duplicada_y_no_repone_dos_veces(servicio, semilla, pg_platform_url):
    venta_id = uuid.uuid4()
    await _vender(servicio, semilla, venta_id)
    op = {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 2, "datos": {"venta_id": str(venta_id)}}
    assert [r.resultado for r in await servicio.procesar_lote(_lote(semilla, op))] == ["aceptada"]
    await servicio._session.commit()

    # Reintento del MISMO lote de anulación (mismo id de operación):
    assert [r.resultado for r in await servicio.procesar_lote(_lote(semilla, op))] == ["duplicada"]
    # Y una anulación NUEVA sobre la venta ya anulada también es duplicada:
    op2 = {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 3, "datos": {"venta_id": str(venta_id)}}
    assert [r.resultado for r in await servicio.procesar_lote(_lote(semilla, op2))] == ["duplicada"]
    await servicio._session.commit()
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == Decimal("10")
    fila = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k", k=f"{T1}.venta.anulada"
    )
    assert fila.n == 1


async def test_el_cajero_no_puede_anular(servicio, semilla, pg_platform_url):
    """ADR-023: anular es del dueño. El servicio lo sabe por `puede_anular`
    (el router lo deriva del token); la operación se rechaza y la cola del
    cajero sigue drenando."""
    venta_id = uuid.uuid4()
    await _vender(servicio, semilla, venta_id)
    servicio_cajero = VentasService(
        session=servicio._session, tenant_id=T1, actor_id="cajero-prueba", puede_anular=False
    )
    op = {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 2, "datos": {"venta_id": str(venta_id)}}
    resultados = await servicio_cajero.procesar_lote(_lote(semilla, op))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "permiso_ausente")]
    fila = await _uno(pg_platform_url, "SELECT estado FROM ventas WHERE id = :v", v=venta_id)
    assert fila.estado == "completada"


async def test_anular_una_venta_que_no_existe_es_rechazada(servicio, semilla):
    op = {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 1, "datos": {"venta_id": str(uuid.uuid4())}}
    resultados = await servicio.procesar_lote(_lote(semilla, op))
    assert [(r.resultado, r.motivo) for r in resultados] == [("rechazada", "venta_no_encontrada")]


async def test_una_venta_que_sube_ya_anulada_no_mueve_stock(servicio, semilla, pg_platform_url):
    """ADR-018: anulada localmente antes de sincronizar, sube ya anulada.
    Decisión 9: efecto neto cero — sin movimientos, sin venta.anulada, y el
    evento venta.creada lleva el estado en el payload."""
    resultados = await servicio.procesar_lote(_lote(semilla, _op_venta(semilla, uuid.uuid4(), estado="anulada")))
    assert [r.resultado for r in resultados] == ["aceptada"]
    await servicio._session.commit()
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == Decimal("10")
    movimientos = await _uno(
        pg_platform_url, "SELECT count(*) AS n FROM movimientos_inventario WHERE tenant_id = :t", t=T1
    )
    assert movimientos.n == 0
    fila = await _uno(pg_platform_url, "SELECT estado FROM ventas WHERE tenant_id = :t", t=T1)
    assert fila.estado == "anulada", "la trazabilidad vale más que una fila de menos (ADR-018)"


# --- Delta -----------------------------------------------------------------------


async def test_el_delta_devuelve_los_cambios_desde_el_watermark(servicio, semilla, pg_platform_url):
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        viejo = (
            await conn.execute(text("SELECT created_at FROM productos WHERE id = :p"), {"p": semilla["producto"]})
        ).scalar_one()
    await engine.dispose()

    desde = viejo  # justo en la creación: el producto NO debe salir (>)
    delta = await servicio.delta_productos(desde)
    assert semilla["producto"] not in [p.id for p in delta.productos]

    # Una venta toca el stock del producto → updated_at → aparece en el delta:
    await _vender(servicio, semilla, uuid.uuid4())
    delta = await servicio.delta_productos(desde)
    assert semilla["producto"] in [p.id for p in delta.productos]
    assert delta.hasta > desde, "el watermark lo pone el servidor (ADR-017)"

    # Y una baja lógica llega como tumba:
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE productos SET deleted_at = now(), codigo_barras = NULL WHERE id = :p"),
            {"p": semilla["producto2"]},
        )
    await engine.dispose()
    delta = await servicio.delta_productos(desde)
    assert semilla["producto2"] in delta.eliminados
    assert semilla["producto2"] not in [p.id for p in delta.productos]
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_sync_idempotente.py tests/test_ventas_servicio.py -q
```

Esperado: error de colección `ModuleNotFoundError: No module named 'app.modules.ventas.service'`.

- [ ] **Paso 3: implementar el servicio.** Crear `backend/services/api/app/modules/ventas/service.py`:

```python
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
                return self._rechazada(operacion, "tipo_desconocido", f"Tipo de operación desconocido: {operacion.tipo!r}.")
        except IntegrityError as exc:
            # La red final: una constraint saltó dentro del savepoint (ya
            # revertido). Se traduce a rechazo de dominio; el lote sigue.
            return self._traducir_integridad(operacion, exc)

    @staticmethod
    def _rechazada(operacion: OperacionSync, motivo: str, mensaje: str, detalles: dict | None = None) -> ResultadoOperacion:
        logger.info("operacion_rechazada", operacion_id=str(operacion.id), motivo=motivo, mensaje=mensaje)
        return ResultadoOperacion(
            id=operacion.id, tipo=operacion.tipo, resultado="rechazada", motivo=motivo,
            detalles={"mensaje": mensaje, **(detalles or {})},
        )

    @staticmethod
    def _duplicada(operacion: OperacionSync) -> ResultadoOperacion:
        logger.info("operacion_duplicada", operacion_id=str(operacion.id), tipo=operacion.tipo)
        return ResultadoOperacion(id=operacion.id, tipo=operacion.tipo, resultado="duplicada")

    def _traducir_integridad(self, operacion: OperacionSync, exc: IntegrityError) -> ResultadoOperacion:
        detalle = str(exc)
        if "ux_ventas_consecutivo" in detalle:
            return self._rechazada(
                operacion, "consecutivo_duplicado",
                "Ese número de venta ya se usó en este dispositivo.",
            )
        if "ux_movimientos_origen" in detalle:
            # El movimiento de este origen ya existe: la operación se aplicó
            # antes (carrera de reintentos). Es duplicada, no error (ADR-020).
            return self._duplicada(operacion)
        if "ventas_pkey" in detalle:
            # El id choca con una fila que la RLS no deja ver (otro negocio).
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
                    operacion, "producto_no_encontrado",
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

        for item, producto in zip(datos.items, productos, strict=True):
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
                operacion, "datos_invalidos",
                "Los datos de la operación no son válidos.",
                {"errores": [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()][:5]},
            )

    def _reglas_de_negocio(self, operacion: OperacionSync, datos: VentaCrearSync) -> ResultadoOperacion | None:
        """Fiado⇔cliente (ADR-018: «cliente_id NULL salvo fiado») y coherencia
        total/ítems (decisión 14): rechazos de dominio, por operación."""
        if datos.medio_pago == "fiado" and datos.cliente_id is None:
            return self._rechazada(
                operacion, "fiado_requiere_cliente",
                "Una venta fiada debe traer el cliente al que se le fía.",
            )
        if datos.medio_pago != "fiado" and datos.cliente_id is not None:
            return self._rechazada(
                operacion, "cliente_solo_en_fiado",
                "Solo una venta fiada lleva cliente.",
            )
        suma = sum(i.cantidad * i.precio_unitario_centavos for i in datos.items)
        if suma != datos.total_centavos:
            return self._rechazada(
                operacion, "total_incoherente",
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
                operacion, "venta_id_divergente",
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
                operacion, "permiso_ausente",
                "Anular una venta requiere el permiso venta:anular.",
                {"permiso": "venta:anular"},
            )
        datos = self._validar_datos(operacion, VentaAnularSync)
        if isinstance(datos, ResultadoOperacion):
            return datos

        venta = await self._session.get(Venta, datos.venta_id)
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
        nueva = CajaSesion(tenant_id=self._tenant_id, abierta_por=self._actor_id, base_inicial=0)
        self._session.add(nueva)
        try:
            async with self._session.begin_nested():
                await self._session.flush()
        except IntegrityError:
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
```

- [ ] **Paso 4: verificar.**

```bash
cd backend && uv run pytest tests/test_sync_idempotente.py tests/test_ventas_servicio.py -q
# Esperado: 1 + 19 passed
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 5: commit**

```bash
git add backend/services/api/app/modules/ventas/service.py backend/tests/test_sync_idempotente.py backend/tests/test_ventas_servicio.py
git commit -m "Servicio de ventas y sync por lotes: idempotencia por PK de cliente, savepoint por operación, stock por deltas y anulación no destructiva"
```

**Criterios de aceptación:** el candado de idempotencia pasa (una venta, un movimiento, un evento tras dos envíos idénticos; la proyección descontada una vez); la divergencia de payload es `rechazada` con `detalles.campos`; las operaciones se aplican en orden de recepción; el reloj de 1999 se conserva como dato con `recibida_en` del servidor; la anulación repone stock una sola vez y no toca la venta original; el cajero (`puede_anular=False`) recibe `permiso_ausente`; la sesión implícita se abre una sola vez; `ruff` limpio.

---

## Tarea 6: Dependencias, router y montaje en la app

**Files:**
- Create: `backend/tests/api/test_ventas_sync.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/ventas/dependencies.py`
- Create: `backend/services/api/app/modules/ventas/router.py`
- Modify: `backend/services/api/app/dependencies.py` (mover `exigir_permiso` — decisión 12)
- Modify: `backend/services/api/app/modules/catalogo/dependencies.py` (importarla de su nueva casa, reexportando)
- Modify: `backend/services/api/app/factory.py` (montar el router; actualizar la descripción)
- Modify: `backend/tests/api/conftest.py` (la limpieza borra también las tablas del módulo de los tenants de prueba)

**Interfaces:**
- Consume: `sesion_de_tenant`, `contexto_de_tenant` (`app.dependencies`), `exigir_negocio_activo` (`app.modules.tenants.dependencies`), `get_current_user` (`vendi_core.auth.dependencies`), `has_permission` (`vendi_core.auth.policies`).
- Produce: `POST /api/v1/dispositivos`, `POST /api/v1/sync/lotes`, `GET /api/v1/sync/delta`, protegidos por `venta:crear` (los dos primeros) y `producto:leer` (el delta).

- [ ] **Paso 1: mover `exigir_permiso` a `app/dependencies.py`** (decisión 12). Añadir al final de `backend/services/api/app/dependencies.py`:

```python
def exigir_permiso(permiso: str) -> Callable:
    """Fábrica de guards: exige un permiso del token, con sobre estándar.

    La autorización lee SOLO el token (`realm_access.roles`), sin consulta a
    base de datos en la ruta caliente (ADR-015/ADR-023). Es fábrica propia y
    NO `require_permission` de `vendi-core` por el mismo motivo por el que
    existe `exigir_admin_de_plataforma`: aquella lanza `HTTPException`
    (cuerpo `{"detail": ...}`) y toda la API contesta con el sobre
    `{"success": false, "message": ..., "code": ...}`. El 403 es la respuesta
    correcta y esperada cuando falta el permiso.
    """

    async def _comprobar(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not has_permission(user, permiso):
            raise PermissionDeniedError(
                f"Esta operación requiere el permiso {permiso}.",
                code="permiso_ausente",
                details={"permiso": permiso},
            )
        return user

    return _comprobar
```

(y añadir `from collections.abc import Callable` a los imports del archivo). En `backend/services/api/app/modules/catalogo/dependencies.py`: borrar la definición local de `exigir_permiso` y añadir `from app.dependencies import exigir_permiso` — el nombre sigue reexportado en su `__all__`, así que su router y sus tests no se tocan. Limpiar los imports que queden sin uso en ese archivo (`Callable`, y `get_current_user` / `has_permission` / `PermissionDeniedError` si solo los usaba la fábrica): `ruff` los delata en la verificación del paso 7.

- [ ] **Paso 2: preparar la limpieza de los tests de API.** En `backend/tests/api/conftest.py`, dentro de `_borrar()` del fixture `limpiar_tenants_de_prueba`, añadir **antes** del `DELETE FROM productos` (orden de FK: primero quien referencia):

```python
                for tabla in ("movimientos_inventario", "ventas_items", "ventas", "caja_sesiones", "dispositivos"):
                    await conn.execute(
                        text(f"DELETE FROM {tabla} WHERE tenant_id = ANY(:ids)"),
                        {"ids": list(ids)},
                    )
```

(sin esto, las ventas de los tenants de prueba se acumulan entre corridas y los consecutivos acabarían chocando: la suite tiene que ser re-entrante).

- [ ] **Paso 3: escribir los tests de API que fallan.** Crear `backend/tests/api/test_ventas_sync.py`:

```python
"""Los endpoints del sync (`/api/v1/dispositivos`, `/api/v1/sync/*`) contra el
PostgreSQL real.

Misma regla que `test_catalogo_productos.py`: la base no se dobla. Cada test
crea su negocio por el camino real y opera con tokens de roles distintos,
porque lo que se mide aquí es quién puede hacer qué — el cajero sincroniza y
vende, pero NO anula (ADR-023).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_con_rol, usuario_de_plataforma
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.auth.policies import ROL_CAJERO, ROL_DUENO

pytestmark = pytest.mark.integration


def _admin(cliente, validador, token: str = "tok-admin") -> dict:
    validador.registrar(token, usuario_de_plataforma())
    return {"Authorization": f"Bearer {token}"}


def _crear_negocio(cliente, validador, nombre: str) -> str:
    respuesta = cliente.post(
        "/api/v1/platform/tenants", json={"nombre": PREFIJO_PRUEBA + nombre}, headers=_admin(cliente, validador)
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _cabeceras_de(validador, rol: str, tenant_id: str, token: str) -> dict:
    validador.registrar(token, usuario_con_rol(rol, uuid.UUID(tenant_id)))
    return {"Authorization": f"Bearer {token}"}


def _alta_producto(cliente, cabeceras, precio: int = 2500, stock=None) -> str:
    cuerpo = {"nombre": "Arroz 500g", "precio_venta": precio}
    respuesta = cliente.post("/api/v1/productos", json=cuerpo, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _registrar_dispositivo(cliente, cabeceras) -> str:
    respuesta = cliente.post("/api/v1/dispositivos", json={"nombre": "Caja 1"}, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _lote(dispositivo_id: str, producto_id: str, *operaciones: dict) -> dict:
    if not operaciones:
        operaciones = (
            {
                "id": str(uuid.uuid4()),
                "tipo": "venta.crear",
                "secuencia": 1,
                "datos": {
                    "consecutivo_local": 1,
                    "medio_pago": "efectivo",
                    "total_centavos": 2500,
                    "creada_en_cliente": datetime.now(UTC).isoformat(),
                    "items": [
                        {"producto_id": producto_id, "cantidad": "1", "precio_unitario_centavos": 2500}
                    ],
                },
            },
        )
    return {"dispositivo_id": dispositivo_id, "operaciones": list(operaciones)}


def _montar(cliente, validador, nombre: str, rol: str = ROL_DUENO, token: str = "tok-d"):
    negocio = _crear_negocio(cliente, validador, nombre)
    cabeceras = _cabeceras_de(validador, rol, negocio, token)
    producto = _alta_producto(cliente, cabeceras)
    dispositivo = _registrar_dispositivo(cliente, cabeceras)
    return cabeceras, producto, dispositivo


# --- Dispositivos -----------------------------------------------------------------


def test_registrar_dispositivo_devuelve_201_y_es_idempotente(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras, _, _ = _montar(cliente, validador, "Sync 1")
    el_id = str(uuid.uuid4())

    primero = cliente.post("/api/v1/dispositivos", json={"id": el_id, "nombre": "Caja 1"}, headers=cabeceras)
    segundo = cliente.post("/api/v1/dispositivos", json={"id": el_id, "nombre": "Caja 1"}, headers=cabeceras)

    assert primero.status_code == 201
    assert segundo.status_code == 201
    assert segundo.json()["id"] == el_id


def test_registrar_dispositivo_exige_venta_crear(app_con_base):
    """El almacenista no vende (ADR-023): tampoco registra cajas."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Sync 2")
    almacenista = _cabeceras_de(validador, "almacenista", negocio, "tok-a2")

    respuesta = cliente.post("/api/v1/dispositivos", json={"nombre": "X"}, headers=almacenista)
    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "permiso_ausente"


# --- El lote ------------------------------------------------------------------------


def test_el_lote_se_aplica_y_responde_por_operacion(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 3")

    respuesta = cliente.post("/api/v1/sync/lotes", json=_lote(dispositivo, producto), headers=cabeceras)

    assert respuesta.status_code == 200, respuesta.text
    resultados = respuesta.json()["resultados"]
    assert [r["resultado"] for r in resultados] == ["aceptada"]


def test_el_mismo_lote_dos_veces_por_http_es_duplicada_la_segunda(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 4")
    lote = _lote(dispositivo, producto)

    assert cliente.post("/api/v1/sync/lotes", json=lote, headers=cabeceras).status_code == 200
    reintento = cliente.post("/api/v1/sync/lotes", json=lote, headers=cabeceras)

    assert reintento.status_code == 200
    assert [r["resultado"] for r in reintento.json()["resultados"]] == ["duplicada"]


def test_un_dispositivo_de_otro_negocio_es_un_422_no_una_fuga(app_con_base):
    """El dispositivo existe — pero en otro tenant. La RLS lo hace invisible
    y la respuesta no revela ni que existe (mismo criterio que el 404 del
    catálogo, aquí 422 por venir en el cuerpo)."""
    cliente, validador, _ = app_con_base
    _, producto, dispositivo_ajeno = _montar(cliente, validador, "Sync 5A", token="tok-d5a")
    cabeceras_b, _, _ = _montar(cliente, validador, "Sync 5B", token="tok-d5b")

    respuesta = cliente.post("/api/v1/sync/lotes", json=_lote(dispositivo_ajeno, producto), headers=cabeceras_b)
    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "dispositivo_no_encontrado"


def test_un_tenant_inyectado_en_el_payload_da_422(app_con_base):
    """`extra="forbid"` como defensa en profundidad del WITH CHECK (ADR-017)."""
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 6")
    lote = _lote(dispositivo, producto)
    lote["operaciones"][0]["datos"]["tenant_id"] = str(uuid.uuid4())

    respuesta = cliente.post("/api/v1/sync/lotes", json=lote, headers=cabeceras)
    assert respuesta.status_code == 422


def test_el_lote_se_corta_en_200_operaciones(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 7")
    lote = _lote(dispositivo, producto)
    lote["operaciones"] = lote["operaciones"] * 201

    assert cliente.post("/api/v1/sync/lotes", json=lote, headers=cabeceras).status_code == 422


def test_el_cajero_sincroniza_y_vende_pero_su_anulacion_se_rechaza(app_con_base):
    """ADR-023 en el sync: el guard del endpoint es `venta:crear` (el cajero
    drena su cola), y la anulación se rechaza POR OPERACIÓN con
    `permiso_ausente` — la cola del cajero no se detiene por ella."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Sync 8")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d8")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c8")
    producto = _alta_producto(cliente, dueno)
    dispositivo = _registrar_dispositivo(cliente, cajero)

    # El cajero vende:
    venta_id = str(uuid.uuid4())
    lote_venta = _lote(dispositivo, producto)
    lote_venta["operaciones"][0]["id"] = venta_id
    respuesta = cliente.post("/api/v1/sync/lotes", json=lote_venta, headers=cajero)
    assert [r["resultado"] for r in respuesta.json()["resultados"]] == ["aceptada"]

    # ...pero NO anula:
    lote_anula = _lote(
        dispositivo, producto,
        {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 2, "datos": {"venta_id": venta_id}},
    )
    respuesta = cliente.post("/api/v1/sync/lotes", json=lote_anula, headers=cajero)
    resultado = respuesta.json()["resultados"][0]
    assert resultado["resultado"] == "rechazada"
    assert resultado["motivo"] == "permiso_ausente"

    # Y el dueño sí:
    respuesta = cliente.post("/api/v1/sync/lotes", json=lote_anula, headers=dueno)
    assert [r["resultado"] for r in respuesta.json()["resultados"]] == ["aceptada"]


def test_un_negocio_suspendido_no_sincroniza(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Sync 9")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d9")
    producto = _alta_producto(cliente, cabeceras)
    dispositivo = _registrar_dispositivo(cliente, cabeceras)
    cliente.patch(
        f"/api/v1/platform/tenants/{negocio}", json={"estado": "suspendido"}, headers=_admin(cliente, validador)
    )

    respuesta = cliente.post("/api/v1/sync/lotes", json=_lote(dispositivo, producto), headers=cabeceras)
    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "tenant_suspendido"


# --- El delta -----------------------------------------------------------------------


def test_el_delta_baja_el_catalogo_y_las_tumbas(app_con_base):
    cliente, validador, _ = app_con_base
    cabeceras, producto, dispositivo = _montar(cliente, validador, "Sync 10")

    desde = "2020-01-01T00:00:00+00:00"
    respuesta = cliente.get(f"/api/v1/sync/delta?desde={desde}", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert producto in [p["id"] for p in cuerpo["productos"]]
    assert cuerpo["eliminados"] == []
    hasta = cuerpo["hasta"]

    # Sin cambios desde el watermark devuelto: nada nuevo.
    respuesta = cliente.get(f"/api/v1/sync/delta?desde={hasta}", headers=cabeceras)
    assert respuesta.json()["productos"] == []

    # Una baja lógica llega como tumba:
    assert cliente.delete(f"/api/v1/productos/{producto}", headers=cabeceras).status_code == 204
    respuesta = cliente.get(f"/api/v1/sync/delta?desde={desde}", headers=cabeceras)
    assert producto in respuesta.json()["eliminados"]


def test_el_delta_no_muestra_el_catalogo_del_vecino(app_con_base):
    cliente, validador, _ = app_con_base
    _montar(cliente, validador, "Sync 11A", token="tok-d11a")
    cabeceras_b, _, _ = _montar(cliente, validador, "Sync 11B", token="tok-d11b")

    respuesta = cliente.get("/api/v1/sync/delta?desde=2020-01-01T00:00:00+00:00", headers=cabeceras_b)
    assert len(respuesta.json()["productos"]) == 1, "solo el producto del negocio B, no el del A"


def test_el_delta_valida_el_watermark(app_con_base):
    """Sin `desde` es 422 de FastAPI (query param requerido); con fecha naive
    es 422 tipado del handler — un watermark sin zona no dice nada."""
    cliente, validador, _ = app_con_base
    cabeceras, _, _ = _montar(cliente, validador, "Sync 12")

    assert cliente.get("/api/v1/sync/delta", headers=cabeceras).status_code == 422
    respuesta = cliente.get("/api/v1/sync/delta?desde=2020-01-01", headers=cabeceras)
    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "fecha_sin_zona"
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/api/test_ventas_sync.py -q
```

Esperado: 11-12 fallos con `404`/`405` en todo (`/api/v1/dispositivos` y `/api/v1/sync/*` no existen aún) y errores de import de `app.modules.ventas.dependencies`.

- [ ] **Paso 4: implementar las dependencias.** Crear `backend/services/api/app/modules/ventas/dependencies.py`:

```python
"""Dependencias del módulo `ventas`.

El guard de permisos vive en `app.dependencies.exigir_permiso` (decisión 12
del plan: dos módulos lo usan; su casa es la de `exigir_admin_de_plataforma`,
que existe por el mismo motivo).
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import exigir_permiso, sesion_de_tenant
from app.modules.tenants.dependencies import exigir_negocio_activo
from app.modules.ventas.service import VentasService
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.auth.policies import PERM_PRODUCTO_LEER, PERM_VENTA_ANULAR, PERM_VENTA_CREAR, has_permission
from vendi_core.tenant.context import TenantContext

exigir_venta_crear = exigir_permiso(PERM_VENTA_CREAR)
exigir_venta_anular = exigir_permiso(PERM_VENTA_ANULAR)
exigir_producto_leer = exigir_permiso(PERM_PRODUCTO_LEER)


async def servicio_de_ventas(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
    user: UserContext = Depends(get_current_user),
) -> VentasService:
    """El servicio del negocio del token, con la sesión que la RLS acota.

    `exigir_negocio_activo` va primero: un negocio suspendido no sincroniza
    (403 `tenant_suspendido`). El veredicto sobre anular se deriva AQUÍ del
    token y viaja al servicio como flag: el servicio no lee claims (la
    autorización lee solo el JWT, ADR-015/ADR-023), y la operación
    `venta.anular` de un cajero se rechaza por operación, no con un 403 del
    lote entero (decisión 12 del plan).
    """
    return VentasService(
        session=session,
        tenant_id=tenant.tenant_id,
        actor_id=user.user_id,
        puede_anular=has_permission(user, PERM_VENTA_ANULAR),
    )


__all__ = [
    "exigir_producto_leer",
    "exigir_venta_anular",
    "exigir_venta_crear",
    "servicio_de_ventas",
]
```

- [ ] **Paso 5: implementar el router.** Crear `backend/services/api/app/modules/ventas/router.py`:

```python
"""Ventas y sync offline: `/api/v1/dispositivos` y `/api/v1/sync/*`.

El endpoint que hace al POS offline-first (ADR-017). Todo trabaja con la
sesión de TENANT (rol `vendi_app`, RLS activo): ningún handler recibe un
`tenant_id` por URL, cuerpo o cabecera — el lote entero corre con el GUC del
negocio del token y cada fila pasa la policy (el `WITH CHECK` rechaza un
`tenant_id` inyectado, y los schemas llevan `extra="forbid"` para rechazarlo
antes).

Los permisos (ADR-023): registrar dispositivo y sincronizar el lote exigen
`venta:crear` (el cajero drena su cola); el delta exige `producto:leer`. La
anulación NO se guarda en el router: es por operación dentro del lote
(decisión 12 del plan), porque un 403 del lote entero detendría la cola del
cajero por una sola operación prohibida.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status

from app.modules.ventas.dependencies import (
    exigir_producto_leer,
    exigir_venta_crear,
    servicio_de_ventas,
)
from app.modules.ventas.schemas import (
    DeltaSalida,
    DispositivoRegistrar,
    DispositivoSalida,
    LoteSync,
    RespuestaLote,
)
from app.modules.ventas.service import VentasService
from vendi_core.auth.context import UserContext
from vendi_core.errors.domain import ValidationError
from vendi_core.models.responses import ErrorResponse

router = APIRouter(tags=["ventas"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    422: {"model": ErrorResponse, "description": "Request malformado (validación de estructura)"},
}


@router.post(
    "/dispositivos",
    response_model=DispositivoSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un dispositivo del negocio",
    responses=_RESPUESTAS_COMUNES,
)
async def registrar_dispositivo(
    datos: DispositivoRegistrar,
    servicio: VentasService = Depends(servicio_de_ventas),
    _actor: UserContext = Depends(exigir_venta_crear),
) -> DispositivoSalida:
    """Acepta el `id` que traiga el cliente (ADR-017): re-registrar con el
    mismo id devuelve el existente, sin duplicar fila."""
    return DispositivoSalida.model_validate(await servicio.registrar_dispositivo(datos))


@router.post(
    "/sync/lotes",
    response_model=RespuestaLote,
    summary="Aplicar un lote de operaciones de la cola del dispositivo",
    responses=_RESPUESTAS_COMUNES,
)
async def sincronizar_lote(
    lote: LoteSync,
    servicio: VentasService = Depends(servicio_de_ventas),
    _actor: UserContext = Depends(exigir_venta_crear),
) -> RespuestaLote:
    """Una transacción por lote, un resultado por operación
    (`aceptada`/`duplicada`/`rechazada`), en el orden del lote.

    HTTP 200 aunque haya operaciones rechazadas: el lote SE PROCESÓ; el
    desenlace de cada operación viaja en su resultado. Los 4xx de este
    endpoint significan «el request entero es inválido», no «una operación
    falló»."""
    return RespuestaLote(resultados=await servicio.procesar_lote(lote))


@router.get(
    "/sync/delta",
    response_model=DeltaSalida,
    summary="Descargar los cambios del catálogo desde un watermark",
    responses=_RESPUESTAS_COMUNES,
)
async def delta_de_sync(
    desde: datetime = Query(description="Watermark devuelto como `hasta` por el delta anterior (o una fecha inicial)"),
    servicio: VentasService = Depends(servicio_de_ventas),
    _actor: UserContext = Depends(exigir_producto_leer),
) -> DeltaSalida:
    """El drenado hacia los dispositivos (ADR-017): productos modificados
    desde `desde` y tumbas de los dados de baja. El próximo watermark es el
    `hasta` de la respuesta — lo pone el reloj del servidor, nunca el del
    cliente."""
    if desde.tzinfo is None or desde.tzinfo.utcoffset(desde) is None:
        # FastAPI parsea "2020-01-01" como datetime naive sin error; un
        # watermark sin zona no dice nada (mismo criterio que
        # `creada_en_cliente` en los schemas).
        raise ValidationError("El parámetro `desde` debe traer zona horaria (offset).", code="fecha_sin_zona")
    return await servicio.delta_productos(desde)
```

- [ ] **Paso 6: montar el router en la app.** En `backend/services/api/app/factory.py`:

  a) Añadir el import junto a los de los otros routers:

```python
from app.modules.ventas.router import router as router_ventas
```

  b) Montarlo tras `router_catalogo`:

```python
    app.include_router(router_catalogo, prefix="/api/v1")
    app.include_router(router_ventas, prefix="/api/v1")
```

  c) Actualizar la línea de `DESCRIPCION` por:

```python
API regional de Vendi. Fase 1: fundación + catálogo + ventas con sync offline.
```

- [ ] **Paso 7: verificar.**

```bash
cd backend && uv run pytest tests/api/test_ventas_sync.py -q
# Esperado: 12 passed
uv run pytest tests/api -q
# Esperado: toda la carpeta verde (los tests del catálogo y tenants no se tocan y siguen pasando)
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 8: commit**

```bash
git add backend/services/api/app/modules/ventas/dependencies.py backend/services/api/app/modules/ventas/router.py backend/services/api/app/dependencies.py backend/services/api/app/modules/catalogo/dependencies.py backend/services/api/app/factory.py backend/tests/api/test_ventas_sync.py backend/tests/api/conftest.py
git commit -m "Endpoints del sync offline: registro de dispositivos, lotes con resultado por operación y delta del catálogo"
```

**Criterios de aceptación:** los 12 tests del router pasan contra el stack real, 0 SKIPPED; el cajero sincroniza y vende pero su anulación es `rechazada` con `permiso_ausente` (y el dueño anula); un dispositivo de otro negocio es 422 sin fuga; el `tenant_id` inyectado es 422; el lote se corta en 200; el delta devuelve productos y tumbas solo del propio negocio con watermark del servidor; `tests/api` completo verde; `ruff` limpio.

---

## Tarea 7: Extender el check 23 de `verify-setup.sh` (candado de ADR-023)

**Files:**
- Modify: `scripts/verify-setup.sh` (bloque del check 23, ~líneas 699-754)

**Interfaces:**
- Consume: el generador de tokens de ejemplo de la Admin API que el check 23 ya usa para inspeccionar `realm_access.roles` del token del dueño demo.
- Produce: el check falla si el token del dueño no trae `venta:crear` y `venta:anular` — «un permiso que nadie tiene en el token del dueño es un bug de siembra, no de autorización» (ADR-023).

- [ ] **Paso 1: extender el bloque Python del check 23.** En `scripts/verify-setup.sh`, dentro del heredoc `python3 - <<'PY'` del check 23, ampliar el bucle de permisos:

```python
for permiso in ("producto:leer", "producto:editar", "venta:crear", "venta:anular"):
    if permiso not in roles:
        problemas.append(
            f"realm_access.roles no trae '{permiso}' (ADR-023: el grupo dueno debe mapearlo; "
            "un permiso ausente del token del dueno es un bug de siembra, ejecuta scripts/seed.sh)"
        )
```

y el mensaje del `ok`:

```bash
        ok "aud=${KEYCLOAK_AUDIENCE:-vendi-backend}, rol de negocio y permisos de catálogo y ventas en el token del dueño"
```

- [ ] **Paso 2: verificar contra el stack.**

```bash
bash scripts/seed.sh && bash scripts/verify-setup.sh 2>&1 | grep -E "^\[(OK|FALLO|OMITIDO)\].*23"
# Esperado: [OK] 23 ... permisos de catálogo y ventas en el token del dueño
```

Prueba negativa (obligatoria): quitar temporalmente `venta:anular` del mapeo del grupo `dueno` en la consola de Keycloak (`https://accounts.vendi.co`, con `--resolve accounts.vendi.co:443:127.0.0.1`), re-ejecutar el check y verlo fallar con el mensaje de siembra; restaurar con `bash scripts/seed.sh` y ver el OK.

- [ ] **Paso 3: commit**

```bash
git add scripts/verify-setup.sh
git commit -m "El check 23 exige los permisos de ventas en el token del dueño (ADR-023)"
```

**Criterios de aceptación:** el check 23 pasa con la siembra al día y falla —con mensaje accionable— si falta cualquiera de los cuatro permisos.

---

## Tarea 8: Congelar el OpenAPI y regenerar el cliente TypeScript

**Files:**
- Modify: `docs/api/openapi-fase0.json` (regenerado, mismo archivo — decisión 15 del plan)
- Modify: `docs/api/README.md` (tabla de rutas y códigos)
- Modify: `frontend/projects/libs/data-access/src/lib/api-client/openapi.json` e `index.ts` (salida del codegen)

**Interfaces:**
- Consume: la API viva con `DOCS_PUBLICOS=true` y `scripts/codegen-api-client.sh` en modo congelado.
- Produce: el contrato con las 3 rutas nuevas; el cliente TS regenerado sin deriva (`codegen + git diff --exit-code` en 0).

- [ ] **Paso 1: regenerar el contrato congelado desde la API viva.** Con el stack levantado y la migración aplicada:

```bash
curl -sS --resolve api.vendi.co:443:127.0.0.1 https://api.vendi.co/openapi.json \
  | python3 -c 'import json,sys; json.dump(json.load(sys.stdin), open("docs/api/openapi-fase0.json","w"), indent=2, ensure_ascii=False, sort_keys=True)'
python3 -c 'import json; d=json.load(open("docs/api/openapi-fase0.json")); print(sorted(p for p in d["paths"] if "sync" in p or "dispositivos" in p))'
# Esperado: ['/api/v1/dispositivos', '/api/v1/sync/delta', '/api/v1/sync/lotes']
```

`sort_keys=True` e `indent=2` no son cosméticos: sin orden estable, cada regeneración produce un diff ilegible.

- [ ] **Paso 2: actualizar `docs/api/README.md`.** Añadir a la tabla de rutas:

```markdown
| `POST /api/v1/dispositivos` | `venta:crear` | registro de dispositivo; acepta `id` del cliente (idempotente, ADR-017) |
| `POST /api/v1/sync/lotes` | `venta:crear` | lote de ≤200 operaciones; 200 con resultado por operación (`aceptada`/`duplicada`/`rechazada`); eventos una sola vez por aceptada |
| `GET /api/v1/sync/delta` | `producto:leer` | cambios del catálogo desde `desde`; `hasta` es el próximo watermark (reloj del servidor); `eliminados` son tumbas |
```

y a la lista de `code` estables: `dispositivo_no_encontrado`, `fecha_sin_zona`, y los motivos de `rechazada` (viajan en `ResultadoOperacion.motivo`, no como `code` de error HTTP): `tipo_desconocido`, `datos_invalidos`, `venta_id_divergente`, `producto_no_encontrado`, `consecutivo_duplicado`, `fiado_requiere_cliente`, `cliente_solo_en_fiado`, `total_incoherente`, `venta_no_encontrada`, `permiso_ausente`.

- [ ] **Paso 3: regenerar el cliente y demostrar que no hay deriva.**

```bash
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh
cd frontend && npm run build:libs && npx ng build vendi-admin
# Esperado: build de libs y de vendi-admin en verde (contrato.ts sigue compilando)
git add docs/api frontend/projects/libs/data-access/src/lib/api-client
git diff --cached --stat
```

- [ ] **Paso 4: commit**

```bash
git commit -m "Contrato OpenAPI con las rutas del sync offline y cliente TypeScript regenerado"
```

**Criterios de aceptación:** el OpenAPI congelado contiene las rutas de `dispositivos` y `sync` con sus schemas (`LoteSync`, `RespuestaLote`, `DeltaSalida`); el job `frontend-contratos` del CI (codegen contra el congelado + `git diff --exit-code`) queda en verde; `vendi-admin` compila contra el cliente regenerado.

---

## Tarea 9: Cierre del módulo — gate de la Etapa 1.2 y `docs/estado.md`

**Files:**
- Modify: `docs/estado.md` (sección nueva del módulo ventas, con fecha de corte y evidencia comando+salida)
- Modify: `docs/deuda-tecnica.md` (solo si quedó deuda nueva; si no, no se toca)

- [x] **Paso 1: ejecutar el gate completo del módulo** (idéntico al de cualquier módulo de la Etapa 1.2):

```bash
bash scripts/migrate.sh
cd backend && uv run pytest -q
# Esperado: toda la suite verde; los tests nuevos integration corren (0 SKIPPED)
uv run pytest -q -m integration
# Esperado: verde, 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git diff --exit-code
# Esperado: salida 0 (sin deriva de contrato)
```

Gate por módulo (del plan maestro de Fase 1), verificado ítem a ítem:
- [x] Migración con RLS + índice + grants, revisada por el agente de seguridad.
- [x] Tests de integración con aislamiento cross-tenant nuevo por tabla (`test_aislamiento_ventas.py`: las cinco tablas), 0 SKIPPED.
- [x] El candado del sync (`test_sync_idempotente.py`): el mismo lote dos veces deja una venta, un movimiento y un evento.
- [x] OpenAPI congelado actualizado + codegen + `contrato.ts` sigue compilando.
- [x] Eventos de outbox emitidos según ADR-018 (`venta.creada`/`venta.anulada`, clave `<tenant_id>.venta.*`); `pytest -m integration` verde; `ruff` verde.

- [x] **Paso 2: actualizar `docs/estado.md`.** Añadir una sección «Módulo ventas (Fase 1, Etapa 1.2)» con: fecha de corte, qué se entregó (tablas, endpoints del sync, permisos, eventos, idempotencia), y **al lado de cada afirmación el comando que la demuestra** con su salida pegada (regla del documento: no promete nada que un comando no demuestre). Candidatas a entrada en `docs/deuda-tecnica.md` con vencimiento si el ejecutor decide registrarlas: (a) `cliente_id` sin FK hasta que el módulo de fiado cree `clientes` (vence: módulo 5); (b) `caja_sesiones` existe y se puebla sin endpoints propios hasta el módulo de caja (vence: módulo 4); (c) las alertas de umbral de stock no existen hasta el módulo 3 — el negativo ya es visible en `stock_actual` pero nadie notifica (vence: módulo 3). Si se registran, que sea con el formato del registro (qué es, por qué se aceptó, riesgo, vencimiento, candados mientras tanto).

- [x] **Paso 3: commit de cierre**

```bash
git add docs/estado.md docs/deuda-tecnica.md
git commit -m "Módulo ventas cerrado: gate de la Etapa 1.2 verificado y estado actualizado"
```

---

## Superficie de ataque para QA — módulo ventas y sync offline

Para el agente de QA adversarial de la Etapa 1.4 (agente distinto del implementador; su KPI son hallazgos). Los escenarios marcados (firmado) ya tienen test que los fija: verificarlos, no «redescubrirlos»; el hallazgo sería que el test miente.

- **Idempotencia (el corazón):** el mismo lote 3 veces (una venta, un movimiento por ítem, un evento — firmado); el mismo lote partido en dos envíos que se solapan a medias (las operaciones solapadas son `duplicada`, las nuevas `aceptada`, y el stock cuadra al peso); dos lotes DISTINTOS que traen la misma venta (mismo id, mismo payload: la segunda es `duplicada`); mismo id con payload divergente (rechazada `venta_id_divergente` con `detalles.campos` — firmado; verificar que la primera versión sobrevive intacta y que el evento sigue siendo uno).
- **Carreras:** el mismo lote desde DOS requests concurrentes (row lock de la venta o de `ux_movimientos_origen`: una gana, la otra sale `duplicada` vía savepoint — nunca dos ventas ni doble descuento ni 500); dos aperturas implícitas de sesión concurrentes (una sola `caja_sesiones` abierta; la perdedora usa la ganadora); dos ventas concurrentes con el mismo `consecutivo_local` (una `aceptada`, otra `rechazada` `consecutivo_duplicado`).
- **Reloj del cliente:** `creada_en_cliente` en 1970, en 2099, con offset raro (`+14:00`) — siempre `aceptada`, siempre conservada, y `recibida_en` siempre del servidor (firmado). Dos ventas con el reloj del cliente invertido respecto a su secuencia: el orden de aplicación es el del lote, no el de las marcas (firmado). Un `desde` de delta en el futuro (lista vacía, no error) y un `hasta` reusado (sin duplicados en el borde del segundo: el filtro es `>` estricto — si dos cambios caen en el MISMO microsegundo del watermark, uno se pierde: comprobar si es alcanzable y, si lo es, registrar como deuda con vencimiento).
- **Anulación:** anular dos veces con el mismo id de operación y con ids distintos (las dos `duplicada`, stock repuesto una vez, un solo `venta.anulada` — firmado); anular una venta de otro negocio por id adivinado (`venta_no_encontrada`, sin fuga); anular una venta que subió ya anulada (`duplicada`: ya estaba anulada — verificar que NO se revierte stock que nunca se descontó: el libro debe quedar en cero movimientos para esa venta); anular con token de cajero (`rechazada` `permiso_ausente`, la venta sigue `completada` — firmado).
- **Stock:** venta que deja el stock negativo (aceptada — firmado); secuencia venta→anulación→venta del mismo producto: `stock_actual = SUM(movimientos)` en cada paso (la invariante del libro de ADR-020); una venta de un producto dado de baja lógica entre la venta física y el sync (aceptada, stock descontado — decisión del servicio, verificar que queda documentada).
- **Aislamiento:** dispositivo/producto/venta del vecino por id en lote y en anulación (rechazadas o 422, nunca 200 ni fuga — firmado); delta del vecino (vacío — firmado); `tenant_id` inyectado en `datos`, en la operación y en el lote (422 por `extra="forbid"` — firmado para `datos`; verificar los otros dos niveles); un lote del negocio A con `dispositivo_id` de A pero ítems con `producto_id` del negocio B (`rechazada` `producto_no_encontrado`, y NADA del lote toca al vecino).
- **Validación y bordes:** `total_centavos` y `precio_unitario_centavos` en 2^31 y 2^31−1 (422, nunca 500 — lección BUG-2); `cantidad` que desborda `Numeric(14,3)` (422); `secuencia` en 2^63 (422); `creada_en_cliente` naive (422 — firmado); `datos` con tipos absurdos (`"items": 5`, `"items": [1,2]`) → `rechazada` `datos_invalidos`, no 422 ni 500 (firmado para el camino feliz: QA debe probar los absurdos); lote de 201 operaciones (422 — firmado); lote vacío (422); venta de 501 ítems (422); `tipo` desconocido, vacío y de 200 caracteres (rechazada `tipo_desconocido` / 422 por largo); total que no cuadra con los ítems por un centavo (`rechazada` `total_incoherente` — firmado); cantidades de granel (`0.350 kg × $2.500 = 875` exacto, `0.333 × 100 = 33.3` NO entero → ¿`total_incoherente`? — verificar el comportamiento con decimales periódicos y documentarlo).
- **El lote como transacción:** provocar un fallo a mitad de lote (p. ej. matar la conexión con `pg_terminate_backend` durante el request) y comprobar que no queda NI UNA venta ni movimiento ni evento del lote — la garantía outbox es del lote entero (decisión 5).
- **Permisos:** almacenista en `/dispositivos` y `/sync/lotes` (403 `permiso_ausente` — firmado para dispositivos); sin token (401); negocio suspendido a media sesión (403 `tenant_suspendido` en el siguiente request — firmado).
- **Eventos:** payload de `venta.creada` exactamente lo pactado (sin PII extra; el `cliente_id` solo va si es fiado); un lote de 50 ventas aceptadas deja exactamente 50 `venta.creada` con routing key `<tenant>.venta.creada` (ni 49 ni 51); un lote con 25 aceptadas y 25 duplicadas deja 25.

---

## Self-Review

- **Cobertura del spec:** ADR-017 (ids de cliente como PK, lotes con resultado por operación, transacción por lote, GUC del tenant, `dispositivos`, delta con watermark del servidor, eventos una sola vez por aceptada, LWW por orden de recepción) → Tareas 1, 3, 5, 6. ADR-018 (append-only, consecutivo por dispositivo, doble verdad temporal, anulación como operación nueva, centavos enteros, fiado sin red sin rechazo, sesión resuelta en servidor, multi-caja) → Tareas 1, 2, 3, 5. ADR-020 (movimiento de salida al aplicar la venta, proyección `stock_actual` en la misma transacción, idempotencia por constraint, stock negativo, deltas conmutativos fuera de orden) → Tareas 1, 2, 5 + decisión 1. ADR-023 (`venta:crear`/`venta:anular`, cajero no anula, candados, check 23) → Tareas 4, 5, 6, 7. ADR-021 (tabla `caja_sesiones` + índice único parcial, como referencia de integración) → Tarea 1 + decisión 3. ADR-022 (fiado como dato, crédito diferido) → Tareas 2, 5 + decisión 8. Lecciones del QA del catálogo (cotas `le=`, validadores sin asunción de `str`, divergencia explícita) → Global Constraints, Tarea 3, decisión 4. Items del encargo 1-8 → Tareas 1-9.
- **Placeholders:** ninguno. Todo paso lleva código completo, comando exacto y salida esperada. Los conteos de tests son los escritos; si el ejecutor añade casos, ajusta el número (los comandos de verificación de gate son de suite, no de conteo).
- **Consistencia de tipos/contratos:** nombres de columnas, índices y checks coinciden entre migración (Tarea 1), modelos (Tarea 2) y tests de metadata; los motivos de `rechazada` coinciden entre servicio, tests de servicio, tests de API y la tabla de `docs/api/README.md`; los eventos usan la firma real de `DomainEventService.emit` y la clave `<tenant_id>.venta.*` que ADR-018 firma; los schemas reusan `TOPE_PRECIO`/`TOPE_STOCK`/`ProductoSalida` del catálogo en vez de duplicarlos.
- **Riesgos conocidos y declarados:** (1) el índice único de movimientos incluye `producto_id` — desviación deliberada y justificada del literal de ADR-020 (decisión 2); (2) `cliente_id` queda sin FK hasta el módulo de fiado (decisión 8, candidata a deuda con vencimiento); (3) `caja_sesiones` se puebla sin endpoints de caja hasta el módulo 4 (decisión 3); (4) el filtro del delta usa `>` estricto sobre timestamps: dos cambios en el mismo microsegundo del watermark perderían uno — queda en la superficie de QA; (5) un `IntegrityError` de FK (`ventas_items_producto_id_fkey`, carrera con un borrado físico que hoy no existe) saldría como 500 por `_traducir_integridad`: es inalcanzable con borrado lógico y RESTRICT, y si el QA lo alcanza, va a deuda.
