# Módulo caja y finanzas: sesiones, arqueo, P&L simple y forecast 30d (Fase 1, Etapa 1.2, módulo 4) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar el cuarto módulo de negocio del MVP —la caja de ADR-021 y las finanzas simples de ADR-006— con: la migración `0008_caja` (tabla `caja_movimientos` con RLS + índices + checks; `caja_sesiones` NO se recrea —existe completa desde la 0005 con todas las columnas del arqueo— y solo gana dos CHECK de consistencia del cierre; `ventas` gana `anulada_en` para que la devolución de una anulación tardía caiga en la sesión abierta sin duplicar nada), los cinco permisos del reparto firmado (`caja:leer`, `caja:abrir`, `caja:cerrar`, `caja:movimiento`, `reporte:leer` — el cajero abre y mueve caja pero NO cierra ni ve reportes; el almacenista no toca caja), los endpoints REST online de apertura/movimientos/cierre (el cierre calcula el arqueo —`esperado = base + ventas efectivo completadas de la sesión + abonos (0 hasta el módulo 5) + ingresos − egresos − devoluciones`—, lo CONGELA en las columnas de la sesión y emite `caja.sesion_cerrada` con el resumen), el esperado vivo de la sesión abierta con salida condicionada por permiso (el cajero NO lo ve, lección de la fuga de `ultimo_costo`), el cambio quirúrgico en ventas (`_resolver_sesion_caja` bloquea la fila FOR UPDATE y `_anular_venta` estampa `anulada_en`), el P&L simple por período (día/semana/mes en `America/Bogota`, ventas completadas por `recibida_en`, costo desde `ultimo_costo` ACTUAL declarado, egresos/ingresos de caja, compras como flujo informativo) y el forecast a 30 días con cada número declarando su fuente (saldo actual + promedio de ventas efectivo 30d + cobros de fiado 0 declarados − promedio de egresos 30d), el cierre de D-11 (endpoints de caja) y D-15 (`exigir_venta_anular` se borra: este módulo no le da uso y su vencimiento lo manda), la extensión del check 23, el contrato OpenAPI regenerado con su cliente TS, y el gate de módulo de la Etapa 1.2.

**Architecture:** Se mantiene la arquitectura firmada: monolito modular FastAPI (`backend/services/api`) sobre `vendi-core`, RLS en schema único con los roles `vendi_app` (sin `BYPASSRLS`) y `vendi_platform` (con `BYPASSRLS`, owner, corre las migraciones). El módulo nuevo vive en `app/modules/caja/` (servicio de caja + servicio de reportes, un router). Todo corre sobre la **sesión de tenant** (`sesion_de_tenant`, GUC `vendi.tenant_id`): ningún handler recibe `tenant_id` por URL, cuerpo o cabecera. `caja_sesiones` se queda en `ventas/models.py` (nació ahí por la decisión 3 del plan de ventas; moverla sería churn sin beneficio, mismo criterio que `movimientos_inventario` en el plan de inventario); `caja_movimientos` nace en `caja/models.py`. Los endpoints son REST ONLINE puros (patrón inventario): NADA de este módulo entra al lote del sync; la apertura implícita del sync sigue exactamente igual (firmada en ADR-018 y en la decisión 3 del plan de ventas — aquí solo se documenta). El arqueo NO duplica ventas ni abonos como movimientos (ADR-021): los suma desde su tabla de origen en el momento del cierre y congela el resultado. Las fechas se guardan en UTC; el «día» del P&L y la ventana de la sesión se calculan en `America/Bogota` (ADR-021). El fiado no existe todavía (módulo 5, ADR-022): los abonos en efectivo del arqueo y los cobros del forecast son 0 con su punto de cambio único documentado.

**Tech Stack:** Python 3.12 · FastAPI 0.139 · SQLAlchemy 2.0 async (asyncpg) · Alembic · PostgreSQL 17 RLS · Pydantic v2 · `zoneinfo` (stdlib) · pytest + pytest-asyncio · ruff · uv · openapi-typescript (codegen).

**Spec fuente:**
- `docs/adr/adr-021-caja-y-arqueo.md` (el corazón: una sesión abierta por tienda, arqueo desde las tablas de origen, congelamiento, centavos enteros, día en `America/Bogota`, eventos de caja, candados)
- `docs/adr/adr-006-finanzas-simples.md` (P&L simple y forecast 30d; se calculan de lo que ya se registra; la pantalla declara de qué datos sale)
- `docs/adr/adr-023-multi-empleado-permisos.md` (`caja:leer/abrir/cerrar/movimiento`, `reporte:leer`; el cajero no cierra ni ve reportes; candado de autorización y extensión del check 23)
- `docs/adr/adr-018-modelo-de-ventas-offline.md` (la sesión implícita del sync; `recibida_en` como única verdad temporal — el P&L suma por ella)
- `docs/adr/adr-020-inventario-y-compras.md` (`ultimo_costo` es lo que el P&L costea)
- `docs/adr/adr-022-fiado-y-clientes-tecnico.md` (referencia: los abonos y cobros de fiado son del módulo 5; aquí quedan como 0 declarado con punto de cambio único)
- Plantillas a imitar: `backend/services/api/alembic/versions/20260728_0007_inventario.py`, `backend/services/api/app/modules/inventario/` (service con flush-sin-commit, `_flush_traduciendo_integridad`, guards en `dependencies.py`), `backend/services/api/app/modules/ventas/models.py` (`CajaSesion`), `backend/services/api/app/modules/ventas/service.py` (`_resolver_sesion_caja`, `_anular_venta`), `backend/tests/test_aislamiento_ventas.py`, `backend/tests/test_inventario_servicio.py` y `backend/tests/api/test_inventario_api.py`.

## Global Constraints

- Todo artefacto en español riguroso (código, docstrings, commits, mensajes de error). Sin tildes ni eñes en identificadores técnicos que viajen en tokens, URLs o JSON (`dueno`, `retiro_dueno`, no `dueño`/`retiro_dueño`).
- Toda tabla nueva de dominio lleva `tenant_id` + policy RLS vía `enable_rls(op, ...)` + índice que empieza por `tenant_id`, verificada por test de aislamiento cross-tenant contra PostgreSQL real. Los tests de integración **fallan, no se omiten**, si falta el servicio. 0 SKIPPED en cualquier gate.
- El candado invertido `backend/tests/test_privilegios_de_vendi_app.py` exige EXACTAMENTE `{SELECT, INSERT, UPDATE, DELETE}` para toda tabla de negocio: `caja_movimientos` recibe los cuatro por defecto y el candado pasa sin edición (misma decisión que las tablas append-only de ventas e inventario).
- TDD en cada tarea: primero el test que falla (con la salida del fallo esperada), luego la implementación completa, luego el test en verde, luego el commit. Prohibido «similar a», «agregar validación», TODO o código elidido.
- Los errores de la API usan el sobre `{"success": false, "message": "...", "code": "..."}` (`vendi_core.errors.domain` + `ErrorHandlerMiddleware`). NO se usa `require_permission` de `vendi-core`: el guard es `exigir_permiso` de `app.dependencies`.
- **Lecciones de los módulos anteriores, aplicadas desde el diseño:** (1) toda entrada entera lleva cota `le=TOPE_PRECIO` contra su columna `Integer` — un overflow sale como `DataError` → 500, no como 422 (BUG-2 del catálogo); (2) los totales calculados en el servidor (el `esperado` y la `diferencia` del arqueo) se cotan antes de escribir y su desbordamiento es un 422 tipado `total_fuera_de_rango` (I1 de inventario); (3) ningún validador `mode="before"` asume `str` (BUG-1 del catálogo); (4) la idempotencia NO es ciega a la divergencia: mismo `id` con datos distintos es 409 con los campos que difieren, nunca un no-op silencioso; (5) read-modify-write siempre con la fila bloqueada `FOR UPDATE` hasta el commit (el cierre bloquea la sesión; el sync, desde este módulo, también); (6) todo `IntegrityError` esperable se traduce a un error tipado del sobre — nada de 500 mudos; (7) las salidas con datos sensibles se condicionan por permiso y el campo sensible viaja en `null`, no desaparece del esquema (la fuga de `ultimo_costo`, que ya se resolvió así).
- Dinero SIEMPRE en centavos enteros (ADR-018/ADR-021); cantidades en `Decimal`, nunca flotante. Los montos de caja (`base_inicial`, `monto`, `contado`, `esperado`, `diferencia`) son enteros con signo solo donde el modelo lo admite (`diferencia` puede ser negativa: faltante).
- El reloj del cliente es dato, no árbitro (ADR-017): el P&L y el forecast suman por `recibida_en` y `created_at` del servidor; el «día» se calcula en `America/Bogota` con `zoneinfo` (ADR-021), jamás con la fecha del request sin anclar.
- El arqueo cerrado NO se recalcula jamás: las columnas congeladas son la única fuente para una sesión `cerrada`. La función que calcula el esperado se usa exactamente dos veces: al cerrar (y su resultado se congela) y para el esperado VIVO de la sesión abierta (sesión actual y saldo del forecast).
- Los commits son por tarea, mensajes en español estilo oración. Nunca `git push` sin confirmación humana.
- Un ADR no se edita para cambiar de opinión: lo que este plan decide más allá de los ADRs queda listado en la sección siguiente, con su justificación.

## Decisiones de diseño tomadas en este plan (más allá de los ADRs)

1. **La migración `0008` NO recrea `caja_sesiones`: ya existe completa desde la `0005`** (decisión 3 del plan de ventas) con `cerrada_por`, `cerrada_en`, `efectivo_esperado`, `efectivo_contado`, `diferencia` y el índice único parcial de sesión abierta. La `0008` crea `caja_movimientos`, añade dos CHECK a `caja_sesiones` (el cierre es completo o no es: `estado='cerrada'` exige las cinco columnas del arqueo no nulas; `efectivo_contado >= 0`) y añade `ventas.anulada_en` (ver decisión 7). Verificado contra `backend/services/api/alembic/versions/20260728_0005_ventas.py` líneas 87-105: no falta ninguna columna del modelo firmado en ADR-021.
2. **La `nota` de ADR-021 se materializa como `motivo` obligatorio** (`Text NOT NULL`, 3-300 caracteres limpios), la convención que ya tienen los ajustes de inventario: un movimiento de caja sin justificación es un desfalco con buenos modales. La `categoria` es la lista cerrada corta del ADR —`arriendo`, `servicios`, `retiro_dueno`, `otro`— con CHECK en base y `Literal` en el schema; ampliarla exige migración, a propósito (el P&L agrupa por ella).
3. **UNA función calcula el esperado: `calcular_desglose(session, sesion)`.** La usa el cierre (y congela su resultado), la sesión actual (esperado vivo) y el forecast (saldo actual). Los abonos de fiado en efectivo entran por `_abonos_en_efectivo_de_la_sesion()`, que hoy retorna 0 con el punto de cambio único documentado: cuando el módulo 5 cree su tabla, el `SUM` va ahí dentro y ni el arqueo ni el forecast se tocan. Si la cuenta del arqueo viviera en tres sitios, divergiría en el primer refactor.
4. **El cajero NO ve el esperado: `efectivo_esperado` viaja en `null` sin `caja:cerrar`** (mismo patrón que `ultimo_costo` en `null` sin `compra:crear`). ADR-023 firma que el cajero no cierra ni ve reportes; el esperado vivo le diría exactamente cuánta plata debería haber en la gaveta en cada momento — la cifra con la que se cuadra un faltante antes de que el dueño arquee. El cajero ve la sesión (estado, base, `abierta_en`) y los movimientos, que es lo que el POS necesita para operar; el historial de arqueos (`GET /caja/sesiones`) exige `caja:cerrar` directamente, porque faltantes y sobrantes históricos son un reporte.
5. **El cierre bloquea la sesión `FOR UPDATE` y, desde este módulo, el sync también** (`_resolver_sesion_caja` pasa a leer la sesión abierta con `with_for_update=True`). Sin los dos bloqueos hay una carrera real: el sync resuelve la sesión abierta, el cierre confirma, y la venta inserta después contra una sesión ya `cerrada` — quedaría huérfana de todo arqueo. Con los dos, cierre y sync se serializan sobre la fila de la sesión: quien llega segundo ve la sesión cerrada y abre una implícita nueva. El costo (los lotes concurrentes del mismo tenant se serializan en esa fila) es despreciable a la escala de una tienda, y no hay inversión de orden de bloqueo: el camino del sync es sesión → productos; el del cierre es solo sesión (lee ventas y movimientos sin bloquearlas). **La venta que sincroniza tarde tras el cierre cae en la sesión NUEVA** (implícita o explícita), nunca en la cerrada: el congelamiento es estructural, no un convencio.
6. **El cierre es idempotente por reintento con el mismo conteo.** Un `POST` de cierre que ya confirmó (timeout del cliente, reintento) encuentra la sesión `cerrada`: mismo `contado` → devuelve el arqueo congelado (200, sin desglose — no se recalcula, ver Global Constraints); `contado` distinto → 409 `caja_ya_cerrada`. La apertura acepta `id` opcional del cliente (patrón ADR-017): reintento idéntico → la sesión existente; ya hay abierta con otro id otra base → 409 `caja_ya_abierta` con la sesión vigente en `details`. El movimiento EXIGE `id` del cliente (como el ajuste): es dinero y un reenvío tras timeout sin ancla duplicaría plata en la cuenta; el reintento idéntico es no-op y el divergente es 409 `movimiento_id_divergente`.
7. **Las devoluciones caen en la sesión abierta SIN duplicar nada: `ventas.anulada_en`.** ADR-021 firma que anular una venta de una sesión ya cerrada no reabre su arqueo y que «la anulación cae en la sesión abierta en ese momento». La única forma de cumplirlo sin duplicar la venta como movimiento (prohibido por el mismo ADR) es saber CUÁNDO se anuló: `anulada_en` (nueva columna, la estampa `_anular_venta`; la única mutación de la venta sigue siendo `completada → anulada`). El esperado de la sesión abierta resta las ventas en efectivo `anulada` con `anulada_en` dentro de su ventana **cuya `sesion_caja_id` es OTRA** (las de la propia sesión ya están excluidas del `SUM` de completadas: su efecto neto es cero y restarlas sería contarlas dos veces). Las anulaciones pre-módulo no existen en operación real (pre-piloto) y quedan con `anulada_en NULL` — excluidas por el `IS NOT NULL`, declarado.
8. **P&L: el costo de lo vendido es `Σ cantidad × ultimo_costo ACTUAL` del producto**, declarado en la respuesta. Es la fuente más simple y honesta: ADR-020 ya firma que `ultimo_costo` es «lo que el P&L costea», y la alternativa (costo histórico por movimiento) exigiría un libro de costos que el MVP no tiene — inventar precisión que el dato no respalda sería menos honesto que declarar la aproximación. El redondeo es al total (un solo `quantize` ROUND_HALF_UP), declarado. Las **compras del período viajan como línea informativa de flujo y NO se restan del resultado** (reponen inventario: restarlas haría que un mes de reabastecimiento pareciera pérdida en el cuaderno); el resultado operativo es `ventas_netas − costo_de_lo_vendido + ingresos_caja − egresos_caja`. El período es `dia`/`semana`(lunes)/`mes` anclado a `America/Bogota`, con `fecha` opcional para mirar otro día/semana/mes; los límites son `[medianoche Bogotá, medianoche Bogotá)` convertidos a UTC y las ventas entran por `recibida_en` (la verdad del servidor, ADR-018); las compras entran por su `fecha` de factura comparada contra las fechas Bogotá de la ventana.
9. **El forecast nace YA, con el alcance honesto que los datos de hoy permiten** (ADR-006 lo firma como parte del MVP; diferirlo sería incumplir el ADR por miedo a declarar). Fórmula: `saldo_proyectado = saldo_actual + ventas_proyectadas + cobros_fiado(0) − egresos_proyectados`. `saldo_actual` es el esperado vivo de la sesión abierta (0 si no hay, declarado). `ventas_proyectadas` es el total de ventas en efectivo completadas de los últimos 30 días (promedio diario × 30 con los días sin datos contando 0: conservador con la tienda nueva, y la respuesta lleva `dias_con_datos`). Los **cobros de fiado son 0 hasta el módulo 5**, declarado en `fuentes` con su punto de cambio. Los «egresos recurrentes» de ADR-021 no tienen fuente en el MVP (no hay tabla de gastos recurrentes): el proxy honesto es el total de egresos de caja de los últimos 30 días, declarado como tal — la pantalla dice de qué sale cada número, que es la condición firmada de ADR-006.
10. **Los endpoints son REST online puros; la apertura implícita del sync NO cambia de criterio** (ya firmada: resuelve a la abierta o abre implícita con `base_inicial = 0`). Si ya hay sesión abierta, la apertura explícita es 409 `caja_ya_abierta` con la sesión vigente en `details` — **no hay camino en el MVP para «ponerle la base» a una sesión implícita ya abierta**: el arqueo cuadra igual (el esperado usa base 0 y el conteo físico incluye la base real; la diferencia lo explica), y si el piloto pide la base editable vendrá con su decisión. Declarado aquí para que nadie lo «arregle» a escondidas.
11. **D-15 se cierra BORRANDO `exigir_venta_anular`.** Su vencimiento dice «módulo 4; si nada lo usa, se borra»: este módulo es caja y finanzas, la anulación del piloto sigue viajando por el sync (chequeo por operación, decisión 12 del plan de ventas), y ningún endpoint nuevo la usa. Se retira la definición y su entrada en `__all__`; `PERM_VENTA_ANULAR` sigue importado porque `servicio_de_ventas` lo usa para derivar `puede_anular`. D-11 se cierra sola (los endpoints de caja existen). D-10 no se toca (vence en el módulo 5).
12. **Cinco permisos nuevos en el catálogo cerrado; el reparto es ADR-023 literal.** `_PERMISOS_DUENO` gana los cinco; `_PERMISOS_CAJERO` gana `caja:leer`, `caja:abrir`, `caja:movimiento` (NO `caja:cerrar`, NO `reporte:leer`); `_PERMISOS_ALMACENISTA` no gana ninguno. Los de fiado/cliente del catálogo de ADR-023 (`cliente:gestionar`, `fiado:crear`, `fiado:abonar`) NO se siembran aquí: son del módulo 5, y un permiso sembrado sin endpoints que lo ejerzan promete lo que el sistema no cumple. El tier Pro/Light de P&L y forecast (ADR-010) se aplica en la capa de producto, no en la autorización (ADR-021): aquí solo manda `reporte:leer`. El check 23 se extiende a los cinco permisos contra el token del dueño.
13. **Se regenera `docs/api/openapi-fase0.json`; NO se crea un congelado nuevo** (fuente única del codegen y del job `frontend-contratos`). Se actualiza `docs/api/README.md` con las 8 rutas y los `code` nuevos.

---

## Tarea 1: Migración `0008_caja` — `caja_movimientos`, CHECKs del cierre y `ventas.anulada_en`

**Files:**
- Create: `backend/tests/test_aislamiento_caja.py` (primero: el test que falla)
- Create: `backend/services/api/alembic/versions/20260728_0008_caja.py`

**Interfaces:**
- Consume: `vendi_core.db.rls.enable_rls` / `disable_rls`, fixtures `pg_app_url` / `pg_platform_url` y datos `T1`/`T2` de `backend/tests/datos_de_prueba.py`. La tabla `caja_sesiones` y el índice `ux_caja_sesion_abierta` de la migración `0005`.
- Produce: `caja_movimientos` migrada con policy `tenant_isolation`, dos índices que empiezan por `tenant_id`, sus CHECK, la FK a `caja_sesiones` con RESTRICT y grants por defecto; `ck_caja_sesiones_cierre_completo` y `ck_caja_sesiones_contado_no_negativo` sobre `caja_sesiones`; `ventas.anulada_en`.

- [ ] **Paso 1: escribir el test de aislamiento que falla.** Crear `backend/tests/test_aislamiento_caja.py`:

```python
"""Aislamiento cross-tenant y reglas duras de `caja_movimientos` (módulo caja).

Hermano de `test_aislamiento_ventas.py`, mismo criterio: SQL crudo con el rol
`vendi_app` y nada de ORM, para que ningún `WHERE` amable dé un falso verde
sobre una policy que no filtra. La tabla la crea la migración `0008_caja`;
hasta que existe, TODOS estos tests fallan — que es el punto del paso TDD.
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
    "DELETE FROM caja_movimientos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Una sesión abierta POR NEGOCIO y un movimiento en la de T1. Limpia
    antes y después: la suite es re-entrante."""
    engine = create_async_engine(pg_platform_url)
    ids = {"T1": uuid.uuid4(), "T2": uuid.uuid4(), "movimiento": uuid.uuid4()}
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        for nombre, tenant in (("T1", T1), ("T2", T2)):
            await conn.execute(
                text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) "
                     "VALUES (:s, :t, 'dueno', 50000)"),
                {"s": ids[nombre], "t": tenant},
            )
        await conn.execute(
            text("INSERT INTO caja_movimientos (id, tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, registrado_por) "
                 "VALUES (:m, :t, :s, 'egreso', 'servicios', 12000, 'Recibo de la luz', 'dueno')"),
            {"m": ids["movimiento"], "t": T1, "s": ids["T1"]},
        )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def sesion_t1(pg_app_url: str, semilla):
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
async def test_select_solo_ve_los_movimientos_del_propio_tenant(sesion_t1):
    filas = (await sesion_t1.execute(text("SELECT tenant_id FROM caja_movimientos"))).all()
    assert len(filas) == 1
    assert filas[0][0] == T1


@pytest.mark.asyncio
async def test_insert_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1, semilla):
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(
            text("INSERT INTO caja_movimientos (tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, registrado_por) "
                 "VALUES (:t, :s, 'ingreso', 'otro', 100, 'inyectado', 'dueno')"),
            {"t": T2, "s": semilla["T2"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tipo,categoria,monto",
    [
        ("transferencia", "otro", 100),      # tipo fuera de la lista cerrada
        ("ingreso", "ropa", 100),            # categoría fuera de la lista cerrada
        ("egreso", "otro", 0),               # monto cero: un movimiento de cero no es movimiento
        ("egreso", "otro", -5000),           # monto negativo: el signo lo da el tipo
    ],
)
async def test_los_checks_rechazan_tipo_categoria_y_monto_invalidos(sesion_t1, semilla, tipo, categoria, monto):
    with pytest.raises(IntegrityError):
        await sesion_t1.execute(
            text("INSERT INTO caja_movimientos (tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, registrado_por) "
                 "VALUES (:t, :s, :tipo, :cat, :monto, 'prueba de check', 'dueno')"),
            {"t": T1, "s": semilla["T1"], "tipo": tipo, "cat": categoria, "monto": monto},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_movimiento_exige_sesion_existente(sesion_t1):
    """FK RESTRICT: ningún movimiento huérfano de sesión (ni siquiera contra
    un UUID al azar: Postgres no aplica RLS al verificar llaves foráneas)."""
    with pytest.raises(IntegrityError, match="caja_movimientos_sesion_caja_id_fkey"):
        await sesion_t1.execute(
            text("INSERT INTO caja_movimientos (tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, registrado_por) "
                 "VALUES (:t, :s, 'ingreso', 'otro', 100, 'huerfano', 'dueno')"),
            {"t": T1, "s": uuid.uuid4()},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_cierre_es_completo_o_no_es(sesion_t1, semilla):
    """`ck_caja_sesiones_cierre_completo`: marcar `cerrada` sin las cinco
    columnas del arqueo revienta. El arqueo a medias no existe (ADR-021)."""
    with pytest.raises(IntegrityError, match="ck_caja_sesiones_cierre_completo"):
        await sesion_t1.execute(
            text("UPDATE caja_sesiones SET estado = 'cerrada' WHERE id = :s"),
            {"s": semilla["T1"]},
        )
    await sesion_t1.rollback()
    # Y con las cinco, cierra.
    await sesion_t1.execute(
        text("UPDATE caja_sesiones SET estado = 'cerrada', cerrada_por = 'dueno', cerrada_en = now(), "
             "efectivo_esperado = 38000, efectivo_contado = 38000, diferencia = 0 WHERE id = :s"),
        {"s": semilla["T1"]},
    )
    await sesion_t1.commit()


@pytest.mark.asyncio
async def test_ventas_tiene_anulada_en(pg_platform_url: str, semilla):
    """La columna que hace caer la devolución en la sesión abierta (decisión 7)."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            dispositivo = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
                {"d": dispositivo, "t": T1},
            )
            venta = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                     "medio_pago, total_centavos, creada_en_cliente, secuencia_dispositivo, estado, anulada_en) "
                     "VALUES (:v, :t, :d, :s, 1, 'efectivo', 2500, now(), 1, 'anulada', now())"),
                {"v": venta, "t": T1, "d": dispositivo, "s": semilla["T1"]},
            )
            fila = (
                await conn.execute(text("SELECT estado, anulada_en IS NOT NULL FROM ventas WHERE id = :v"), {"v": venta})
            ).one()
            assert fila == ("anulada", True)
            await conn.execute(text("DELETE FROM ventas WHERE id = :v"), {"v": venta})
            await conn.execute(text("DELETE FROM dispositivos WHERE id = :d"), {"d": dispositivo})
    finally:
        await engine.dispose()
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_aislamiento_caja.py -q
# Esperado: todos fallan — relation "caja_movimientos" does not exist (y el de anulada_en por la columna)
```

- [ ] **Paso 2: escribir la migración.** Crear `backend/services/api/alembic/versions/20260728_0008_caja.py`:

```python
"""Caja: `caja_movimientos`, los CHECK del cierre completo y `ventas.anulada_en`
(ADR-021, decisiones 1, 2 y 7 del plan del módulo).

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-28

## Qué crea y qué NO crea

- `caja_sesiones` NO se recrea: existe completa desde la `0005` (decisión 3
  del plan de ventas) con todas las columnas del arqueo y el índice único
  parcial de sesión abierta. Aquí solo gana dos CHECK: el cierre es completo
  o no es (`cerrada` exige `cerrada_por`, `cerrada_en`, `efectivo_esperado`,
  `efectivo_contado` y `diferencia` no nulas — el arqueo a medias no existe),
  y el conteo físico no es negativo.
- `caja_movimientos` (ADR-021): ingresos y egresos manuales con `tipo`,
  `categoria` de lista cerrada (`arriendo`, `servicios`, `retiro_dueno`,
  `otro` — ampliarla exige migración, a propósito: el P&L agrupa por ella),
  `monto` en centavos enteros estrictamente positivo (el signo lo da el
  tipo), `motivo` obligatorio (decisión 2: la `nota` del ADR como `motivo`,
  la convención del ajuste de inventario) y la sesión a la que pertenecen,
  con FK RESTRICT: ni un movimiento huérfano ni una sesión con movimientos
  se borran físicamente. Las ventas en efectivo y los abonos de fiado NO se
  duplican aquí: el arqueo los suma desde su tabla de origen (ADR-021).
- `ventas.anulada_en` (decisión 7): cuándo se anuló la venta. Sin ella, la
  devolución de efectivo de una venta anulada tras el cierre no podría caer
  en la sesión abierta —como firma ADR-021— sin duplicar la venta como
  movimiento, que el mismo ADR prohíbe. NULL en las anulaciones anteriores
  a esta migración (no hay operación real pre-piloto): el cálculo las
  excluye con `IS NOT NULL`, declarado.

## Grants

Los privilegios por defecto conceden los cuatro a `vendi_app` sobre toda
tabla creada por `vendi_platform` — incluida esta, aunque por modelo sus
filas no se editan ni se borran (misma decisión que las append-only de
ventas e inventario; el candado invertido pasa sin edición).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIPOS_DE_MOVIMIENTO_CAJA = ("ingreso", "egreso")
CATEGORIAS_DE_MOVIMIENTO = ("arriendo", "servicios", "retiro_dueno", "otro")


def upgrade() -> None:
    op.create_table(
        "caja_movimientos",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sesion_caja_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("caja_sesiones.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tipo", sa.String(8), nullable=False),
        sa.Column("categoria", sa.String(24), nullable=False),
        sa.Column("monto", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("registrado_por", sa.String(120), nullable=False),
        sa.CheckConstraint(
            "tipo IN (" + ", ".join(f"'{t}'" for t in TIPOS_DE_MOVIMIENTO_CAJA) + ")",
            name="ck_caja_movimientos_tipo",
        ),
        sa.CheckConstraint(
            "categoria IN (" + ", ".join(f"'{c}'" for c in CATEGORIAS_DE_MOVIMIENTO) + ")",
            name="ck_caja_movimientos_categoria",
        ),
        sa.CheckConstraint("monto > 0", name="ck_caja_movimientos_monto_positivo"),
    )
    # El arqueo suma por sesión; el P&L y el forecast suman por fecha del
    # servidor. Ambos empiezan por tenant_id (predicado RLS como Index Cond).
    op.create_index("ix_caja_movimientos_tenant_sesion", "caja_movimientos", ["tenant_id", "sesion_caja_id"])
    op.create_index("ix_caja_movimientos_tenant_created", "caja_movimientos", ["tenant_id", "created_at"])
    enable_rls(op, "caja_movimientos", crear_indice=False)

    # El arqueo se congela entero o no se congela (ADR-021).
    op.create_check_constraint(
        "ck_caja_sesiones_cierre_completo",
        "caja_sesiones",
        "estado = 'abierta' OR (cerrada_por IS NOT NULL AND cerrada_en IS NOT NULL AND "
        "efectivo_esperado IS NOT NULL AND efectivo_contado IS NOT NULL AND diferencia IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_caja_sesiones_contado_no_negativo",
        "caja_sesiones",
        "efectivo_contado IS NULL OR efectivo_contado >= 0",
    )

    # Cuándo se anuló la venta: la devolución de efectivo cae en la sesión
    # abierta en ese momento (ADR-021, decisión 7 del plan).
    op.add_column("ventas", sa.Column("anulada_en", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ventas", "anulada_en")
    op.drop_constraint("ck_caja_sesiones_contado_no_negativo", "caja_sesiones", type_="check")
    op.drop_constraint("ck_caja_sesiones_cierre_completo", "caja_sesiones", type_="check")
    disable_rls(op, "caja_movimientos", borrar_indice=False)
    op.drop_index("ix_caja_movimientos_tenant_created", table_name="caja_movimientos")
    op.drop_index("ix_caja_movimientos_tenant_sesion", table_name="caja_movimientos")
    op.drop_table("caja_movimientos")
```

- [ ] **Paso 3: migrar y verificar.**

```bash
bash scripts/migrate.sh
# Esperado: ...  -> 0008
cd backend && uv run pytest tests/test_aislamiento_caja.py -q
# Esperado: 9 passed (1 select + 1 with check + 4 checks parametrizados + 1 FK + 1 cierre completo + 1 anulada_en) — 0 SKIPPED
uv run pytest tests/test_privilegios_de_vendi_app.py -q
# Esperado: verde sin tocarlo (los cuatro grants por defecto)
uv run pytest -q -m integration
# Esperado: toda la suite verde, 0 SKIPPED (las migraciones 0005/0007 no se tocan)
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/alembic/versions/20260728_0008_caja.py backend/tests/test_aislamiento_caja.py
git commit -m "Migración 0008: caja_movimientos, cierre completo por CHECK y ventas.anulada_en"
```

**Criterios de aceptación:** `caja_movimientos` existe con RLS, dos índices que empiezan por `tenant_id`, sus tres CHECK y la FK RESTRICT; un `SELECT` de T1 no ve filas de T2 y el `INSERT` con tenant ajeno lo bloquea el `WITH CHECK`; tipo/categoría/monto inválidos revientan contra su CHECK; el cierre a medias revienta contra `ck_caja_sesiones_cierre_completo`; `ventas.anulada_en` existe y se escribe; el candado invertido de privilegios pasa sin edición; suite de integración verde, 0 SKIPPED.

---

## Tarea 2: Modelos — `CajaMovimiento` en `caja/models.py` y `Venta.anulada_en`

**Files:**
- Create: `backend/tests/test_caja_modelos.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/caja/__init__.py`
- Create: `backend/services/api/app/modules/caja/models.py`
- Modify: `backend/services/api/app/modules/ventas/models.py` (la columna `anulada_en` en `Venta`)

**Interfaces:**
- Consume: `CajaSesion` de `app.modules.ventas.models` (la tabla NO se mueve de módulo: nació en la `0005` y allí se queda, mismo criterio que `movimientos_inventario` en el plan de inventario).
- Produce: `CajaMovimiento` (mapea la tabla de la Tarea 1) y las constantes `TIPOS_DE_MOVIMIENTO_CAJA` / `CATEGORIAS_DE_MOVIMIENTO`, única definición que también usa el schema.

- [ ] **Paso 1: escribir el test de metadata que falla.** Crear `backend/tests/test_caja_modelos.py`:

```python
"""El modelo `CajaMovimiento` coincide con la migración 0008: mismas columnas,
mismos índices, mismos CHECK. Contra el PostgreSQL real, no contra el recuerdo."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.caja.models import CATEGORIAS_DE_MOVIMIENTO, TIPOS_DE_MOVIMIENTO_CAJA, CajaMovimiento

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def meta(pg_platform_url: str):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            columnas = (
                await conn.execute(
                    text("SELECT column_name, is_nullable, data_type FROM information_schema.columns "
                         "WHERE table_name = 'caja_movimientos' ORDER BY ordinal_position")
                )
            ).all()
            indices = (
                await conn.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'caja_movimientos'"))
            ).all()
            checks = (
                await conn.execute(
                    text("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                         "WHERE conrelid = 'caja_movimientos'::regclass AND contype = 'c'")
                )
            ).all()
            checks_sesiones = (
                await conn.execute(
                    text("SELECT conname FROM pg_constraint WHERE conrelid = 'caja_sesiones'::regclass AND contype = 'c'")
                )
            ).scalars().all()
            col_anulada = (
                await conn.execute(
                    text("SELECT is_nullable FROM information_schema.columns "
                         "WHERE table_name = 'ventas' AND column_name = 'anulada_en'")
                )
            ).scalar_one()
            yield {
                "columnas": {c.column_name: c for c in columnas},
                "indices": {i.indexname: i.indexdef for i in indices},
                "checks": {c.conname: c.pg_get_constraintdef for c in checks},
                "checks_sesiones": set(checks_sesiones),
                "anulada_en_nullable": col_anulada,
            }
    finally:
        await engine.dispose()


def test_las_columnas_son_las_de_la_migracion(meta):
    esperadas = {
        "id", "tenant_id", "created_at", "updated_at", "sesion_caja_id",
        "tipo", "categoria", "monto", "motivo", "registrado_por",
    }
    assert set(meta["columnas"]) == esperadas
    for obligatoria in esperadas - {"updated_at"}:
        assert meta["columnas"][obligatoria].is_nullable == "NO", obligatoria


def test_los_indices_empiezan_por_tenant_id(meta):
    for nombre in ("ix_caja_movimientos_tenant_sesion", "ix_caja_movimientos_tenant_created"):
        assert nombre in meta["indices"]
        # La PRIMERA columna del índice es tenant_id (predicado RLS como Index Cond).
        assert "btree (tenant_id," in meta["indices"][nombre]


def test_los_checks_son_los_firmados(meta):
    # pg_get_constraintdef normaliza el IN a `= ANY (ARRAY[...])`: se
    # verifica el contenido, no la forma literal.
    for literal in ("ingreso", "egreso"):
        assert literal in meta["checks"]["ck_caja_movimientos_tipo"]
    for literal in ("arriendo", "servicios", "retiro_dueno", "otro"):
        assert literal in meta["checks"]["ck_caja_movimientos_categoria"]
    assert "monto > 0" in meta["checks"]["ck_caja_movimientos_monto_positivo"]


def test_los_checks_del_cierre_completo_estan_en_caja_sesiones(meta):
    assert "ck_caja_sesiones_cierre_completo" in meta["checks_sesiones"]
    assert "ck_caja_sesiones_contado_no_negativo" in meta["checks_sesiones"]


def test_anulada_en_es_nullable(meta):
    assert meta["anulada_en_nullable"] == "YES"


def test_el_modelo_orm_mapea_exactamente_esas_columnas(meta):
    assert set(CajaMovimiento.__table__.columns.keys()) == set(meta["columnas"])
    # Las constantes del modelo son la única definición de las listas cerradas:
    # el schema las reusa (nadie las repite a mano).
    assert TIPOS_DE_MOVIMIENTO_CAJA == ("ingreso", "egreso")
    assert CATEGORIAS_DE_MOVIMIENTO == ("arriendo", "servicios", "retiro_dueno", "otro")
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_caja_modelos.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.caja'
```

- [ ] **Paso 2: escribir el modelo.** Crear `backend/services/api/app/modules/caja/__init__.py` (archivo vacío, como el de los demás módulos) y `backend/services/api/app/modules/caja/models.py`:

```python
"""Modelos del módulo caja: los movimientos manuales (ADR-021).

`caja_sesiones` NO se mueve a este módulo: nació en `ventas/models.py`
(módulo 2, decisión 3 de su plan) y allí se queda — este módulo la importa.
Moverla sería churn sin beneficio, mismo criterio que `movimientos_inventario`
en el plan de inventario.

Las ventas en efectivo y los abonos de fiado NO son filas de esta tabla: el
arqueo los suma desde su tabla de origen (ADR-021). Duplicarlos sería dos
fuentes de verdad para el mismo peso.
"""

from __future__ import annotations

import uuid

from sqlalchemy import UUID, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, TenantModel

#: Ingreso o egreso manual de la gaveta (ADR-021). El signo lo da el tipo;
#: `monto` es estrictamente positivo.
TIPOS_DE_MOVIMIENTO_CAJA: tuple[str, ...] = ("ingreso", "egreso")

#: La lista cerrada corta de ADR-021. Ampliarla exige migración, a propósito:
#: el P&L agrupa los egresos por categoría y una categoría libre sería una
#: categoría por tendero.
CATEGORIAS_DE_MOVIMIENTO: tuple[str, ...] = ("arriendo", "servicios", "retiro_dueno", "otro")


class CajaMovimiento(Base, TenantModel):
    """Un ingreso o egreso manual de la gaveta (ADR-021). Append-only por
    modelo: un error se corrige con otro movimiento, nunca editando éste.

    La PK es el UUID del cliente (REQUERIDO en el schema, decisión 6: es
    dinero — solo la ancla hace seguro el reintento tras un timeout)."""

    __tablename__ = "caja_movimientos"
    __table_args__ = (
        Index("ix_caja_movimientos_tenant_sesion", "tenant_id", "sesion_caja_id"),
        Index("ix_caja_movimientos_tenant_created", "tenant_id", "created_at"),
        CheckConstraint("tipo IN ('ingreso', 'egreso')", name="ck_caja_movimientos_tipo"),
        CheckConstraint(
            "categoria IN ('arriendo', 'servicios', 'retiro_dueno', 'otro')",
            name="ck_caja_movimientos_categoria",
        ),
        CheckConstraint("monto > 0", name="ck_caja_movimientos_monto_positivo"),
    )

    sesion_caja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caja_sesiones.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(8), nullable=False)
    categoria: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Dinero en centavos enteros, estrictamente positivo (el signo es el tipo).
    monto: Mapped[int] = mapped_column(Integer, nullable=False)
    #: La justificación obligatoria (decisión 2): un movimiento sin motivo es
    #: un desfalco con buenos modales.
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    registrado_por: Mapped[str] = mapped_column(String(120), nullable=False)
```

- [ ] **Paso 3: añadir `anulada_en` al modelo `Venta`.** En `backend/services/api/app/modules/ventas/models.py`, tras la columna `recibida_en` de `Venta`:

```python
    #: Cuándo se anuló (NULL mientras esté completada). Lo estampa
    #: `_anular_venta` desde el módulo 4 (decisión 7 del plan de caja): es lo
    #: que permite que la devolución de efectivo de una venta anulada tras el
    #: cierre caiga en la sesión abierta —como firma ADR-021— sin duplicar
    #: la venta como movimiento de caja.
    anulada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

y actualizar el párrafo del docstring de cabecera de `Venta` («La única mutación permitida es `completada → anulada`») para mencionar que la anulación estampa `anulada_en`.

- [ ] **Paso 4: verificar.**

```bash
cd backend && uv run pytest tests/test_caja_modelos.py -q
# Esperado: 6 passed
uv run pytest -q -m integration
# Esperado: verde, 0 SKIPPED (la columna nueva es nullable: nada existente se rompe)
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 5: commit**

```bash
git add backend/services/api/app/modules/caja/__init__.py backend/services/api/app/modules/caja/models.py backend/services/api/app/modules/ventas/models.py backend/tests/test_caja_modelos.py
git commit -m "Modelo CajaMovimiento y ventas.anulada_en (ADR-021)"
```

**Criterios de aceptación:** el modelo mapea exactamente las columnas, índices y CHECK de la migración; las constantes de listas cerradas viven una sola vez (modelo) y las reusa el schema; `Venta.anulada_en` existe nullable; suite verde, 0 SKIPPED; `ruff` limpio.

---

## Tarea 3: Schemas de caja y de reportes

**Files:**
- Create: `backend/tests/test_caja_schemas.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/caja/schemas.py`

**Interfaces:**
- Consume: `TOPE_PRECIO` y `_limpiar_texto` de `app.modules.catalogo.schemas`; `TIPOS_DE_MOVIMIENTO_CAJA` y `CATEGORIAS_DE_MOVIMIENTO` del modelo (Tarea 2).
- Produce: `SesionAbrir`, `SesionCerrar`, `MovimientoCrear` (entradas, `extra="forbid"`), `SesionSalida`, `SesionActualSalida`, `ArqueoSalida`, `ArqueoConDesglose`, `DesgloseSalida`, `MovimientoSalida` (salidas), y los de reportes `PyLSalida` / `ForecastSalida`.

- [ ] **Paso 1: escribir los tests de schema que fallan.** Crear `backend/tests/test_caja_schemas.py`:

```python
"""Schemas de caja y reportes: cotas contra la columna, motivo limpio y
obligatorio, listas cerradas, `extra="forbid"`. Sin base de datos."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.caja.schemas import MovimientoCrear, SesionAbrir, SesionCerrar


def test_la_apertura_valida_minima():
    datos = SesionAbrir.model_validate({})
    assert datos.base_inicial == 0 and datos.id is None


def test_la_base_no_es_negativa_ni_desborda_el_integer():
    with pytest.raises(ValidationError):
        SesionAbrir.model_validate({"base_inicial": -1})
    with pytest.raises(ValidationError):
        SesionAbrir.model_validate({"base_inicial": 2**31})  # DataError → 500 sin la cota (BUG-2)
    assert SesionAbrir.model_validate({"base_inicial": 2**31 - 1}).base_inicial == 2**31 - 1


def test_la_apertura_acepta_el_id_del_cliente():
    el_id = str(uuid.uuid4())
    assert SesionAbrir.model_validate({"id": el_id, "base_inicial": 50000}).id == uuid.UUID(el_id)


def test_el_cierre_exige_conteo_valido():
    with pytest.raises(ValidationError):
        SesionCerrar.model_validate({})  # el conteo es requerido: arquear es contar
    with pytest.raises(ValidationError):
        SesionCerrar.model_validate({"contado": -100})
    with pytest.raises(ValidationError):
        SesionCerrar.model_validate({"contado": 2**31})
    assert SesionCerrar.model_validate({"contado": 0}).contado == 0  # gaveta vacía: legítimo


def test_el_movimiento_exige_id_tipo_categoria_monto_y_motivo():
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({"tipo": "egreso", "categoria": "otro", "monto": 100, "motivo": "x" * 3})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({"id": str(uuid.uuid4()), "categoria": "otro", "monto": 100, "motivo": "x" * 3})


def test_el_monto_es_estrictamente_positivo_y_cabezon():
    base = {"id": str(uuid.uuid4()), "tipo": "ingreso", "categoria": "otro", "motivo": "Venta de la nevera vieja"}
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "monto": 0})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "monto": -500})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "monto": 2**31})


def test_tipo_y_categoria_son_listas_cerradas():
    base = {"id": str(uuid.uuid4()), "monto": 100, "motivo": "Retiro para el banco"}
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "tipo": "transferencia", "categoria": "otro"})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "tipo": "egreso", "categoria": "ropa"})
    ok = MovimientoCrear.model_validate({**base, "tipo": "egreso", "categoria": "retiro_dueno"})
    assert ok.categoria == "retiro_dueno"


def test_el_motivo_se_limpia_antes_de_la_cota_y_no_admite_vacios():
    base = {"id": str(uuid.uuid4()), "tipo": "egreso", "categoria": "servicios", "monto": 12000}
    limpio = MovimientoCrear.model_validate({**base, "motivo": "  Recibo   de\n la  luz  "})
    assert limpio.motivo == "Recibo de la luz"
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "motivo": "   "})  # limpia a "" y choca con min_length
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "motivo": "ab"})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "motivo": "x" * 301})


def test_los_validadores_before_no_asumen_str():
    """Lo que no es str pasa intacto para que pydantic lo rechace como 422
    (BUG-1 del QA del catálogo): nunca un AttributeError → 500."""
    base = {"id": str(uuid.uuid4()), "tipo": "egreso", "categoria": "otro", "monto": 100}
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "motivo": 123})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate({**base, "motivo": ["lista"]})


def test_extra_forbid_en_las_tres_entradas():
    with pytest.raises(ValidationError):
        SesionAbrir.model_validate({"base_inicial": 0, "tenant_id": str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        SesionCerrar.model_validate({"contado": 0, "tenant_id": str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        MovimientoCrear.model_validate(
            {"id": str(uuid.uuid4()), "tipo": "ingreso", "categoria": "otro", "monto": 1,
             "motivo": "prueba", "tenant_id": str(uuid.uuid4())}
        )
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_caja_schemas.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.caja.schemas'
```

- [ ] **Paso 2: escribir los schemas.** Crear `backend/services/api/app/modules/caja/schemas.py`:

```python
"""Schemas del módulo caja y de los reportes (ADR-021/ADR-006).

El contrato que consume el frontend sale de aquí vía `openapi.json`: cada
cambio es un cambio de contrato (se regenera el congelado y el cliente TS).

Dinero SIEMPRE en centavos enteros, con cota `le=TOPE_PRECIO` contra la
columna `Integer` (un overflow saldría como `DataError` → 500, no como 422:
BUG-2 del QA del catálogo). El `motivo` se limpia ANTES de las cotas de
largo y ningún validador `mode="before"` asume `str` (BUG-1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.caja.models import CATEGORIAS_DE_MOVIMIENTO, TIPOS_DE_MOVIMIENTO_CAJA
from app.modules.catalogo.schemas import TOPE_PRECIO, _limpiar_texto

# --- Entradas ---------------------------------------------------------------


class SesionAbrir(BaseModel):
    """Apertura explícita de la caja del día. `id` es el UUID del cliente
    (ADR-017): reenviar la misma apertura devuelve la sesión existente."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    #: La base con la que arranca la gaveta. 0 es legítimo (es la base de la
    #: sesión implícita del sync, ADR-018).
    base_inicial: int = Field(default=0, ge=0, le=TOPE_PRECIO)


class SesionCerrar(BaseModel):
    """El arqueo: el conteo físico de la gaveta. El servidor calcula el
    esperado y la diferencia y los CONGELA en la sesión (ADR-021)."""

    model_config = ConfigDict(extra="forbid")

    contado: int = Field(ge=0, le=TOPE_PRECIO)


class MovimientoCrear(BaseModel):
    """Un ingreso o egreso manual de la gaveta.

    `id` es REQUERIDO (decisión 6): es dinero, y solo la ancla hace seguro
    el reintento tras un timeout. El `motivo` es obligatorio: un movimiento
    de caja sin justificación es un desfalco con buenos modales."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    tipo: Literal[*TIPOS_DE_MOVIMIENTO_CAJA]
    categoria: Literal[*CATEGORIAS_DE_MOVIMIENTO]
    monto: int = Field(gt=0, le=TOPE_PRECIO)
    motivo: str = Field(min_length=3, max_length=300)

    # La limpieza va ANTES de min_length: un motivo de puros espacios choca
    # con la cota, no se cuela como "".
    _motivo_limpio = field_validator("motivo", mode="before")(_limpiar_texto)


# --- Salidas de caja ---------------------------------------------------------


class SesionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    abierta_por: str
    abierta_en: datetime
    base_inicial: int
    estado: str


class SesionActualSalida(SesionSalida):
    """La sesión abierta con su esperado VIVO — solo para quien cierra caja.

    `efectivo_esperado` viaja en `null` sin `caja:cerrar` (decisión 4, mismo
    patrón que `ultimo_costo` sin `compra:crear`): el esperado en vivo es la
    cifra con la que se cuadra un faltante antes de que el dueño arquee, y
    ADR-023 firma que el cajero no cierra ni ve reportes. El campo sigue en
    el esquema; lo que cambia con el permiso es su valor, no la forma."""

    efectivo_esperado: int | None = None


class DesgloseSalida(BaseModel):
    """La cuenta del arqueo (ADR-021: «una cuenta, no una pantalla mágica»).

    `esperado = base + ventas_efectivo + abonos_efectivo + ingresos
    − egresos − devoluciones`. `abonos_efectivo` es 0 hasta el módulo 5
    (fiado, ADR-022) — declarado en `docs/api/README.md`."""

    base_inicial: int
    ventas_efectivo: int
    abonos_efectivo: int
    ingresos: int
    egresos: int
    devoluciones: int
    esperado: int


class ArqueoSalida(BaseModel):
    """Una sesión con su arqueo congelado (o abierta, con los campos del
    cierre en null). Las columnas congeladas son la única fuente para una
    sesión cerrada: jamás se recalculan."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    abierta_por: str
    abierta_en: datetime
    base_inicial: int
    estado: str
    cerrada_por: str | None = None
    cerrada_en: datetime | None = None
    efectivo_esperado: int | None = None
    efectivo_contado: int | None = None
    diferencia: int | None = None


class ArqueoConDesglose(ArqueoSalida):
    """La respuesta del cierre: el arqueo congelado más la cuenta que lo
    produjo. En el REINTENTO del cierre (mismo conteo) el desglose es null:
    no se recalcula — el arqueo está congelado (Global Constraints)."""

    desglose: DesgloseSalida | None = None


class MovimientoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sesion_caja_id: uuid.UUID
    tipo: str
    categoria: str
    monto: int
    motivo: str
    registrado_por: str
    created_at: datetime | None = None


# --- Salidas de reportes (ADR-006) -------------------------------------------


class PyLSalida(BaseModel):
    """El P&L simple del período. Cada número declara su fuente en `fuentes`
    (ADR-006: la pantalla dice de qué datos sale — condición firmada)."""

    periodo: str
    desde: datetime
    hasta: datetime
    ventas_netas_centavos: int
    ventas_efectivo_centavos: int
    ventas_fiado_centavos: int
    #: Informativo: lo anulado en el período NO entra a las ventas netas.
    ventas_anuladas_centavos: int
    costo_de_lo_vendido_centavos: int
    margen_bruto_centavos: int
    ingresos_caja_centavos: int
    egresos_caja_centavos: int
    #: Flujo informativo: NO se resta del resultado (decisión 8).
    compras_proveedores_centavos: int
    resultado_operativo_centavos: int
    fuentes: dict[str, str]


class ForecastSalida(BaseModel):
    """El forecast a 30 días: una proyección explicada, no una promesa
    (ADR-006). Cada número declara su fuente; lo que no tiene fuente todavía
    (cobros de fiado) viaja en 0 y lo dice."""

    dias: int
    saldo_actual_centavos: int
    ventas_proyectadas_centavos: int
    cobros_fiado_proyectados_centavos: int
    egresos_proyectados_centavos: int
    saldo_proyectado_centavos: int
    dias_con_datos: int
    fuentes: dict[str, str]


__all__ = [
    "ArqueoConDesglose",
    "ArqueoSalida",
    "DesgloseSalida",
    "ForecastSalida",
    "MovimientoCrear",
    "MovimientoSalida",
    "PyLSalida",
    "SesionAbrir",
    "SesionActualSalida",
    "SesionCerrar",
    "SesionSalida",
]
```

- [ ] **Paso 3: verificar.**

```bash
cd backend && uv run pytest tests/test_caja_schemas.py -q
# Esperado: 10 passed
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/caja/schemas.py backend/tests/test_caja_schemas.py
git commit -m "Schemas del módulo caja y de los reportes P&L y forecast"
```

**Criterios de aceptación:** los 10 tests pasan; ningún monto de entrada puede desbordar su columna `Integer` (422, nunca 500); tipo y categoría son listas cerradas reusadas del modelo; el motivo se limpia antes de la cota y no admite vacíos; los validadores `before` no asumen `str`; `extra="forbid"` en las tres entradas; `ruff` limpio.

---

## Tarea 4: Los cinco permisos de caja y reportes en `vendi-core` (ADR-023)

**Files:**
- Modify: `backend/libs/vendi-core/src/vendi_core/auth/policies.py`
- Modify: `backend/tests/test_auth_policies.py`

**Interfaces:**
- Consume: el patrón vigente (constantes `PERM_*`, `PERMISSION_CATALOG`, `_PERMISOS_DUENO/_CAJERO/_ALMACENISTA`, `PERMISOS_POR_ROL` como semilla).
- Produce: `caja:leer`, `caja:abrir`, `caja:cerrar`, `caja:movimiento` y `reporte:leer` en el catálogo; el dueño los tiene los cinco; el cajero tiene `caja:leer`/`caja:abrir`/`caja:movimiento` y NO `caja:cerrar` ni `reporte:leer`; el almacenista ninguno. Los permisos de fiado/cliente NO se siembran (decisión 12).

- [ ] **Paso 1: escribir el test que falla.** En `backend/tests/test_auth_policies.py`, reemplazar `test_el_reparto_de_permisos_es_el_de_adr_023` por:

```python
def test_el_reparto_de_permisos_es_el_de_adr_023():
    """El cajero ABRE su caja y registra movimientos, pero NO la cierra y NO
    ve reportes: anular y arquear son los dos gestos con los que se desfalca
    una tienda y quedan en manos del dueño en el MVP (ADR-023). El
    almacenista no toca caja: su trabajo es que el estante y el sistema
    digan lo mismo."""
    assert PERMISOS_POR_ROL[ROL_CAJERO] == frozenset(
        {PERM_PRODUCTO_LEER, PERM_VENTA_CREAR, PERM_CAJA_LEER, PERM_CAJA_ABRIR, PERM_CAJA_MOVIMIENTO}
    )
    assert PERM_CAJA_CERRAR not in PERMISOS_POR_ROL[ROL_CAJERO]
    assert PERM_REPORTE_LEER not in PERMISOS_POR_ROL[ROL_CAJERO]
    assert PERMISOS_POR_ROL[ROL_ALMACENISTA] == frozenset(
        {PERM_PRODUCTO_LEER, PERM_PRODUCTO_EDITAR, PERM_INVENTARIO_AJUSTAR, PERM_COMPRA_CREAR}
    )
    assert {
        PERM_PRODUCTO_LEER,
        PERM_PRODUCTO_EDITAR,
        PERM_VENTA_CREAR,
        PERM_VENTA_ANULAR,
        PERM_INVENTARIO_AJUSTAR,
        PERM_COMPRA_CREAR,
        PERM_CAJA_LEER,
        PERM_CAJA_ABRIR,
        PERM_CAJA_CERRAR,
        PERM_CAJA_MOVIMIENTO,
        PERM_REPORTE_LEER,
    } <= PERMISOS_POR_ROL[ROL_DUENO]
```

y añadir los cinco nombres al import de `vendi_core.auth.policies` del archivo (`PERM_CAJA_ABRIR`, `PERM_CAJA_CERRAR`, `PERM_CAJA_LEER`, `PERM_CAJA_MOVIMIENTO`, `PERM_REPORTE_LEER`).

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_auth_policies.py -q
# Esperado: ImportError: cannot import name 'PERM_CAJA_LEER' from 'vendi_core.auth.policies'
```

- [ ] **Paso 2: añadir los permisos al catálogo y al reparto.** En `backend/libs/vendi-core/src/vendi_core/auth/policies.py`, tras el bloque de inventario y compras:

```python
# Caja y reportes (ADR-021/ADR-023). El cajero abre su caja y registra
# movimientos, pero NO cierra ni ve reportes: cerrar/arquear es el segundo
# gesto con el que se desfalca una tienda, junto a anular, y queda en manos
# del dueño en el MVP. El almacenista no toca caja.
PERM_CAJA_LEER = "caja:leer"
PERM_CAJA_ABRIR = "caja:abrir"
PERM_CAJA_CERRAR = "caja:cerrar"
PERM_CAJA_MOVIMIENTO = "caja:movimiento"
PERM_REPORTE_LEER = "reporte:leer"
```

En `PERMISSION_CATALOG`, tras `(PERM_COMPRA_CREAR, "compra")`:

```python
    (PERM_CAJA_LEER, "caja"),
    (PERM_CAJA_ABRIR, "caja"),
    (PERM_CAJA_CERRAR, "caja"),
    (PERM_CAJA_MOVIMIENTO, "caja"),
    (PERM_REPORTE_LEER, "reporte"),
```

En `_PERMISOS_DUENO`, añadir los cinco nombres al set. Y reemplazar el bloque del cajero/almacenista (con su comentario actualizado):

```python
# ADR-023: el cajero consulta el catálogo, vende, abre su caja y registra
# movimientos, pero NO edita el catálogo, NO anula ventas, NO ajusta
# inventario, NO registra compras, NO cierra la caja y NO ve reportes
# (anular y arquear son los gestos con los que se desfalca una tienda; son
# del dueño en el MVP). El almacenista mantiene el catálogo, ajusta el
# inventario y registra las compras; no vende ni toca caja ni fiado. Los
# permisos de fiado/cliente llegan con el módulo 5 (ADR-022).
_PERMISOS_CAJERO: frozenset[str] = frozenset(
    {PERM_PRODUCTO_LEER, PERM_VENTA_CREAR, PERM_CAJA_LEER, PERM_CAJA_ABRIR, PERM_CAJA_MOVIMIENTO}
)
_PERMISOS_ALMACENISTA: frozenset[str] = frozenset(
    {PERM_PRODUCTO_LEER, PERM_PRODUCTO_EDITAR, PERM_INVENTARIO_AJUSTAR, PERM_COMPRA_CREAR}
)
```

- [ ] **Paso 3: verificar y resembrar el realm local.**

```bash
cd backend && uv run pytest tests/test_auth_policies.py -q
# Esperado: todos passed (el candado «PERMISOS_POR_ROL ⊆ PERMISSION_CATALOG» pasa solo)
bash scripts/seed.sh
# Esperado: [OK] Siembra completa. — el grupo cajero queda con caja:leer/abrir/movimiento y el dueno con los cinco
```

- [ ] **Paso 4: commit**

```bash
git add backend/libs/vendi-core/src/vendi_core/auth/policies.py backend/tests/test_auth_policies.py
git commit -m "Permisos de caja y reportes en el catálogo y el reparto (ADR-023)"
```

**Criterios de aceptación:** el catálogo tiene los 17 permisos (12 + 5); el reparto es exactamente el de ADR-023 para caja y reportes (cajero sin `caja:cerrar` ni `reporte:leer`; almacenista sin nada de caja; dueño con todo lo de su negocio); los permisos de fiado/cliente NO están sembrados; el candado del catálogo pasa; la siembra aplica el diff en el realm local.

---

## Tarea 5: Servicio de caja (`CajaService`) — apertura, movimientos y el arqueo que se congela

**Files:**
- Create: `backend/tests/test_caja_servicio.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/caja/service.py`

**Interfaces:**
- Consume: `CajaSesion` y `Venta` de `app.modules.ventas.models`, `CajaMovimiento` y los schemas de las Tareas 2-3, `DomainEventService.emit`, los errores de `vendi_core.errors.domain`, `TOPE_PRECIO` del catálogo.
- Produce: `CajaService(session, tenant_id, actor_id, puede_cerrar)` con `abrir_sesion`, `sesion_actual`, `registrar_movimiento`, `listar_movimientos`, `cerrar_sesion`, `listar_sesiones`; la función de módulo `calcular_desglose(session, sesion) -> DesgloseArqueo` (única que calcula el esperado, decisión 3) y el dataclass `DesgloseArqueo`.

- [ ] **Paso 1: escribir los tests de servicio que fallan.** Crear `backend/tests/test_caja_servicio.py`:

```python
"""`CajaService` contra el PostgreSQL real, con el rol `vendi_app`.

Misma regla que `test_ventas_servicio.py`: la base no se dobla. Aquí se fijan
los comportamientos firmados del módulo: una sesión abierta por tienda (la
hace cumplir el índice, no el código); el arqueo que suma desde las tablas
de origen y se CONGELA al cerrar; la venta que sincroniza tras el cierre y
cae en la sesión nueva; la devolución de una anulación tardía que cae en la
sesión abierta (ADR-021).
"""

from __future__ import annotations

import asyncio
import itertools
import uuid

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.caja.schemas import MovimientoCrear, SesionAbrir, SesionCerrar
from app.modules.caja.service import CajaService, calcular_desglose
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import ConflictError, NotFoundError
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM caja_movimientos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.caja.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)

_CONSECUTIVO = itertools.count(1)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Un dispositivo en T1 (para insertar ventas por SQL con `recibida_en`
    controlada) y limpieza total antes y después: la suite es re-entrante."""
    engine = create_async_engine(pg_platform_url)
    ids = {"dispositivo": uuid.uuid4()}
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
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
            yield CajaService(session=s, tenant_id=T1, actor_id="dueno-prueba", puede_cerrar=True)
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


async def _venta(
    pg_platform_url: str,
    semilla: dict,
    sesion_id: uuid.UUID,
    total: int,
    medio_pago: str = "efectivo",
    estado: str = "completada",
    recibida_en: str = "now()",
    anulada_en: str | None = None,
) -> uuid.UUID:
    """Una venta por SQL con la marca del servidor controlada (el arqueo y el
    P&L suman por `recibida_en`, no por el reloj del cliente)."""
    venta_id = uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                    "medio_pago, total_centavos, creada_en_cliente, recibida_en, secuencia_dispositivo, "
                    f"estado, anulada_en) VALUES (:v, :t, :d, :s, {next(_CONSECUTIVO)}, :mp, :total, "
                    f"now(), {recibida_en}, 1, :estado, {anulada_en or 'NULL'})"
                ),
                {"v": venta_id, "t": T1, "d": semilla["dispositivo"], "s": sesion_id, "mp": medio_pago,
                 "total": total, "estado": estado},
            )
    finally:
        await engine.dispose()
    return venta_id


def _movimiento(monto: int, tipo: str = "ingreso", categoria: str = "otro", motivo: str = "Prueba de movimiento", **cambios) -> MovimientoCrear:
    return MovimientoCrear.model_validate(
        {"id": str(uuid.uuid4()), "tipo": tipo, "categoria": categoria, "monto": monto, "motivo": motivo, **cambios}
    )


# --- Apertura -----------------------------------------------------------------


async def test_abrir_caja_crea_la_sesion_y_emite_el_evento(servicio, pg_platform_url):
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()

    assert sesion.estado == "abierta" and sesion.base_inicial == 50000 and sesion.abierta_por == "dueno-prueba"
    evento = await _uno(
        pg_platform_url,
        "SELECT payload->'data'->>'base_inicial' AS base FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.caja.sesion_abierta",
    )
    assert evento.base == "50000"


async def test_la_segunda_apertura_es_409_con_la_sesion_vigente(servicio):
    primera = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    with pytest.raises(ConflictError) as exc:
        await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 30000}))
    assert exc.value.code == "caja_ya_abierta"
    assert exc.value.details["sesion_id"] == str(primera.id)


async def test_la_apertura_es_idempotente_por_el_id_del_cliente(servicio, pg_platform_url):
    el_id = uuid.uuid4()
    primera = await servicio.abrir_sesion(SesionAbrir.model_validate({"id": str(el_id), "base_inicial": 50000}))
    await servicio._session.commit()
    segunda = await servicio.abrir_sesion(SesionAbrir.model_validate({"id": str(el_id), "base_inicial": 50000}))
    await servicio._session.commit()
    assert segunda.id == primera.id == el_id
    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM caja_sesiones WHERE tenant_id = :t) AS sesiones, "
        "(SELECT count(*) FROM outbox_messages WHERE routing_key = :k) AS eventos",
        t=T1, k=f"{T1}.caja.sesion_abierta",
    )
    assert (fila.sesiones, fila.eventos) == (1, 1)


async def test_dos_aperturas_concurrentes_dejan_una_sola_sesion(pg_app_url, semilla, pg_platform_url):
    """La regla «una caja por tienda» la hace cumplir `ux_caja_sesion_abierta`
    bajo carrera: una gana, la otra recibe un 409 tipado — nunca un 500."""
    async def apertura_con_sesion_propia(base: int) -> str:
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                servicio = CajaService(session=s, tenant_id=T1, actor_id="cajero-prueba", puede_cerrar=False)
                try:
                    await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": base}))
                    await s.commit()
                    return "abierta"
                except ConflictError as exc:
                    await s.rollback()
                    assert exc.value.code == "caja_ya_abierta"
                    return "conflicto"
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    resultados = await asyncio.gather(apertura_con_sesion_propia(50000), apertura_con_sesion_propia(30000))
    assert sorted(resultados) == ["abierta", "conflicto"]
    fila = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM caja_sesiones WHERE tenant_id = :t AND estado = 'abierta'",
        t=T1,
    )
    assert fila.n == 1


# --- Movimientos ------------------------------------------------------------------


async def test_registrar_movimiento_lo_ata_a_la_sesion_abierta_y_emite_evento(servicio, pg_platform_url):
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    movimiento = await servicio.registrar_movimiento(_movimiento(12000, tipo="egreso", categoria="servicios", motivo="Recibo de la luz"))
    await servicio._session.commit()

    assert movimiento.sesion_caja_id == sesion.id and movimiento.registrado_por == "dueno-prueba"
    evento = await _uno(
        pg_platform_url,
        "SELECT payload->'data'->>'monto' AS monto, payload->'data'->>'tipo' AS tipo "
        "FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.caja.movimiento_registrado",
    )
    assert (evento.monto, evento.tipo) == ("12000", "egreso")


async def test_el_movimiento_sin_sesion_abierta_es_409(servicio):
    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_movimiento(_movimiento(5000, motivo="Retiro para el banco"))
    assert exc.value.code == "caja_sin_sesion_abierta"


async def test_el_movimiento_es_idempotente_y_el_divergente_es_409(servicio, pg_platform_url):
    await servicio.abrir_sesion(SesionAbrir.model_validate({}))
    await servicio._session.commit()
    datos = _movimiento(7000, motivo="Retiro para el banco", tipo="egreso", categoria="retiro_dueno")
    primero = await servicio.registrar_movimiento(datos)
    await servicio._session.commit()
    segundo = await servicio.registrar_movimiento(datos)  # reintento byte-idéntico
    await servicio._session.commit()
    assert segundo.id == primero.id
    fila = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM caja_movimientos WHERE tenant_id = :t",
        t=T1,
    )
    assert fila.n == 1  # ni doble movimiento ni doble evento
    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_movimiento(
            _movimiento(9999, id=str(datos.id), motivo="Retiro para el banco", tipo="egreso", categoria="retiro_dueno")
        )
    assert exc.value.code == "movimiento_id_divergente"
    assert "monto" in exc.value.details["campos"]


# --- El arqueo --------------------------------------------------------------------


async def test_el_arqueo_suma_desde_las_tablas_de_origen_y_cuadra_al_peso(servicio, semilla, pg_platform_url):
    """El candado de ADR-021: `esperado = base + ventas efectivo completadas
    + abonos (0, módulo 5) + ingresos − egresos − devoluciones`; la venta
    fiada NO suma y la anulada de la propia sesión tampoco."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    await _venta(pg_platform_url, semilla, sesion.id, 10000)                                # efectivo: +10.000
    await _venta(pg_platform_url, semilla, sesion.id, 4000, medio_pago="fiado")             # fiado: NO suma
    await _venta(pg_platform_url, semilla, sesion.id, 2500, estado="anulada", anulada_en="now()")  # anulada propia: NO suma
    await servicio.registrar_movimiento(_movimiento(20000, motivo="Consignación del dueño"))
    await servicio.registrar_movimiento(_movimiento(8000, tipo="egreso", categoria="servicios", motivo="Recibo del agua"))
    await servicio._session.commit()

    arqueo = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 72500}))
    await servicio._session.commit()

    assert arqueo.efectivo_esperado == 50000 + 10000 + 0 + 20000 - 8000 - 0
    assert arqueo.diferencia == 72500 - 72000  # sobrante de 500 centavos
    assert arqueo.estado == "cerrada" and arqueo.cerrada_por == "dueno-prueba"
    assert arqueo.desglose is not None
    assert (arqueo.desglose.ventas_efectivo, arqueo.desglose.ingresos, arqueo.desglose.egresos) == (10000, 20000, 8000)
    assert arqueo.desglose.abonos_efectivo == 0  # declarado: los abonos son del módulo 5
    evento = await _uno(
        pg_platform_url,
        "SELECT payload->'data'->>'efectivo_esperado' AS esperado, payload->'data'->>'diferencia' AS diferencia "
        "FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.caja.sesion_cerrada",
    )
    assert (evento.esperado, evento.diferencia) == ("72000", "500")


async def test_el_arqueo_con_faltante_da_diferencia_negativa(servicio, semilla, pg_platform_url):
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    await _venta(pg_platform_url, semilla, sesion.id, 10000)
    arqueo = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 55000}))
    await servicio._session.commit()
    assert arqueo.efectivo_esperado == 60000
    assert arqueo.diferencia == -5000  # faltante


async def test_el_arqueo_se_congela_y_nada_lo_reabre(servicio, semilla, pg_platform_url):
    """El cierre de ayer sigue cuadrando mañana (ADR-021): una venta insertada
    DESPUÉS contra la sesión cerrada (carrera perdida, SQL directo) NO cambia
    las columnas congeladas, y la anulación posterior tampoco."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    await _venta(pg_platform_url, semilla, sesion.id, 10000)
    arqueo = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()
    # Tardía y anulada: dos mutaciones posteriores contra la sesión cerrada.
    await _venta(pg_platform_url, semilla, sesion.id, 999999)
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE ventas SET estado = 'anulada', anulada_en = now() WHERE tenant_id = :t"), {"t": T1})
    await engine.dispose()

    fila = await _uno(
        pg_platform_url,
        "SELECT efectivo_esperado, efectivo_contado, diferencia FROM caja_sesiones WHERE id = :s",
        s=sesion.id,
    )
    assert (fila.efectivo_esperado, fila.efectivo_contado, fila.diferencia) == (10000, 10000, 0)


async def test_el_reintento_del_cierre_devuelve_lo_congelado_y_el_otro_conteo_es_409(servicio):
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    primero = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 0}))
    await servicio._session.commit()
    # Timeout del cliente y reintento con el MISMO conteo: el arqueo congelado,
    # sin recalcular el desglose (no hay segunda emisión del evento).
    reintento = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 0}))
    assert reintento.efectivo_esperado == primero.efectivo_esperado == 0
    assert reintento.desglose is None
    with pytest.raises(ConflictError) as exc:
        await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 100}))
    assert exc.value.code == "caja_ya_cerrada"


async def test_cerrar_una_sesion_desconocida_es_404_sin_fuga(servicio):
    """La sesión de otro negocio es invisible por RLS: mismo 404 que una
    inexistente (mismo criterio que `compra_no_encontrada`)."""
    with pytest.raises(NotFoundError) as exc:
        await servicio.cerrar_sesion(uuid.uuid4(), SesionCerrar.model_validate({"contado": 0}))
    assert exc.value.code == "caja_sesion_no_encontrada"


async def test_la_devolucion_de_una_venta_de_sesion_cerrada_cae_en_la_sesion_abierta(servicio, semilla, pg_platform_url):
    """ADR-021: «la anulación cae en la sesión abierta en ese momento». La
    sesión A cierra cuadrada; al día siguiente se anula una venta en efectivo
    de A y la plata sale de la gaveta de B: el esperado VIVO de B la resta.
    (La anulación por el camino real del sync es Tarea 6; aquí se fija el
    cálculo del desglose.)"""
    sesion_a = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    venta_vieja = await _venta(pg_platform_url, semilla, sesion_a.id, 10000)
    await servicio.cerrar_sesion(sesion_a.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()

    sesion_b = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE ventas SET estado = 'anulada', anulada_en = now() WHERE id = :v"),
            {"v": venta_vieja},
        )
    await engine.dispose()

    desglose = await calcular_desglose(servicio._session, sesion_b)
    assert desglose.devoluciones == 10000
    assert desglose.esperado == 50000 - 10000  # base de B menos la devolución


async def test_la_sesion_actual_muestra_el_esperado_vivo_solo_a_quien_cierra(pg_app_url, semilla, pg_platform_url):
    """Decisión 4 (la lección de la fuga de `ultimo_costo`): el esperado vivo
    es del dueño; el cajero recibe el campo en null con la MISMA forma."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            dueno = CajaService(session=s, tenant_id=T1, actor_id="dueno-prueba", puede_cerrar=True)
            sesion = await dueno.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
            await s.commit()
            await _venta(pg_platform_url, semilla, sesion.id, 10000)
            vista_dueno = await dueno.sesion_actual()
            assert vista_dueno.efectivo_esperado == 60000
            cajero = CajaService(session=s, tenant_id=T1, actor_id="cajero-prueba", puede_cerrar=False)
            vista_cajero = await cajero.sesion_actual()
            assert vista_cajero.id == sesion.id and vista_cajero.base_inicial == 50000
            assert vista_cajero.efectivo_esperado is None
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def test_sin_sesion_abierta_la_actual_es_404(servicio):
    with pytest.raises(NotFoundError) as exc:
        await servicio.sesion_actual()
    assert exc.value.code == "caja_sin_sesion_abierta"
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_caja_servicio.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.caja.service'
```

- [ ] **Paso 2: escribir el servicio.** Crear `backend/services/api/app/modules/caja/service.py`:

```python
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
        #: lo usa para condicionar el esperado vivo (decisión 4). El GUARD de
        #: los endpoints de cierre está en el router, como manda ADR-023.
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
        `caja_sin_sesion_abierta`). Idempotente por el `id` del cliente
        (REQUERIDO, decisión 6): reintento idéntico → la fila existente, sin
        duplicar ni re-emitir; divergente → 409 `movimiento_id_divergente`."""
        existente = await self._session.get(CajaMovimiento, datos.id)
        if existente is not None:
            divergentes = [
                campo for campo in _CAMPOS_DEL_MOVIMIENTO if str(getattr(existente, campo)) != str(getattr(datos, campo))
            ]
            if divergentes:
                raise ConflictError(
                    "Ese id de movimiento ya existe con datos distintos. El servidor conserva la primera versión.",
                    code="movimiento_id_divergente",
                    details={"campos": divergentes},
                )
            logger.info("caja_movimiento_idempotente", movimiento_id=str(existente.id))
            return existente
        sesion = await self._sesion_abierta()
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
        """Los movimientos de una sesión (la abierta si no se pide otra)."""
        if sesion_id is None:
            sesion = await self._sesion_abierta()
            if sesion is None:
                raise NotFoundError("No hay una caja abierta en este negocio.", code="caja_sin_sesion_abierta")
            sesion_id = sesion.id
        elif await self._session.get(CajaSesion, sesion_id) is None:
            # La sesión de otro negocio es invisible por RLS: mismo 404.
            raise NotFoundError("La sesión de caja no existe.", code="caja_sesion_no_encontrada")
        base = select(CajaMovimiento).where(CajaMovimiento.sesion_caja_id == sesion_id)
        total = (
            await self._session.execute(select(func.count()).select_from(CajaMovimiento).where(CajaMovimiento.sesion_caja_id == sesion_id))
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

        La fila se bloquea `FOR UPDATE` hasta el commit: el cierre y el sync
        (que desde este módulo también bloquea la sesión al resolverla,
        decisión 5) se serializan — una venta jamás queda insertada contra
        una sesión ya cerrada. El reintento con el MISMO conteo devuelve el
        arqueo congelado sin recalcular (decisión 6); con otro conteo es 409.
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

    async def _sesion_abierta(self) -> CajaSesion | None:
        consulta = select(CajaSesion).where(CajaSesion.estado == "abierta")
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
```

- [ ] **Paso 3: verificar.**

```bash
cd backend && uv run pytest tests/test_caja_servicio.py -q
# Esperado: 15 passed — 0 SKIPPED
uv run pytest -q -m integration
# Esperado: verde, 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/caja/service.py backend/tests/test_caja_servicio.py
git commit -m "Servicio de caja: apertura única, movimientos idempotentes y arqueo que se congela"
```

**Criterios de aceptación:** los 15 tests de servicio pasan contra PostgreSQL real, 0 SKIPPED; una sola sesión abierta por tienda incluso bajo aperturas concurrentes (una gana, la otra 409 tipado); el movimiento sin sesión abierta es 409 y su reintento divergente 409 con los campos; el arqueo cuadra al peso con ventas de ambos medios (la fiada no suma), movimientos y devoluciones; diferencia positiva y negativa; el arqueo congelado no se reabre por venta tardía ni por anulación posterior; el reintento del cierre devuelve lo congelado sin recalcular; el esperado vivo lo ve solo quien cierra; `ruff` limpio.

---

## Tarea 6: El cambio quirúrgico en ventas — `FOR UPDATE` al resolver la sesión y `anulada_en` al anular

**Files:**
- Modify: `backend/services/api/app/modules/ventas/service.py` (`_resolver_sesion_caja` bloquea; `_anular_venta` estampa `anulada_en`)
- Modify: `backend/tests/test_caja_servicio.py` (los dos tests del camino real del sync; la semilla gana un producto)

**Interfaces:**
- Consume: nada nuevo; endurece dos puntos del servicio de ventas existente.
- Produce: la garantía de que una venta jamás queda insertada contra una sesión ya `cerrada` (decisión 5), y la marca que hace caer la devolución en la sesión abierta (decisión 7).

- [ ] **Paso 1: escribir los tests que fallan.** En `backend/tests/test_caja_servicio.py`, en la tupla `BORRADO`, añadir tras la línea de `dispositivos`:

```python
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.inventario.%'",
```

En la fixture `semilla`, tras el `INSERT` del dispositivo, añadir el producto (las ventas por el camino real del sync descuentan stock) y su id al dict:

```python
        await conn.execute(
            text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                 "VALUES (:p, :t, 'Arroz 500g', 2500, 100)"),
            {"p": ids["producto"], "t": T1},
        )
```

con `ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4()}`.

Y al final del archivo, añadir (los imports nuevos van arriba: `from app.modules.ventas.schemas import LoteSync` y `from app.modules.ventas.service import VentasService`):

```python
# --- El camino real del sync contra la sesión (Tarea 6) ---------------------------


def _lote_venta(dispositivo_id: uuid.UUID, producto_id: uuid.UUID, total: int, consecutivo: int = 1) -> LoteSync:
    return LoteSync.model_validate(
        {
            "dispositivo_id": str(dispositivo_id),
            "operaciones": [
                {
                    "id": str(uuid.uuid4()),
                    "tipo": "venta.crear",
                    "secuencia": 1,
                    "datos": {
                        "consecutivo_local": consecutivo,
                        "medio_pago": "efectivo",
                        "total_centavos": total,
                        "creada_en_cliente": "2026-07-28T10:00:00+00:00",
                        "items": [{"producto_id": str(producto_id), "cantidad": "1", "precio_unitario_centavos": total}],
                    },
                }
            ],
        }
    )


async def test_la_venta_que_sincroniza_tras_el_cierre_cae_en_la_sesion_nueva(servicio, semilla, pg_platform_url):
    """El congelamiento es estructural (decisión 5): cerrada la sesión A, la
    venta que llega tarde por el sync NO entra a A (su arqueo firmado no se
    toca): el resolvedor abre una implícita nueva y la venta cae ahí."""
    sesion_a = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    await _venta(pg_platform_url, semilla, sesion_a.id, 10000)
    arqueo = await servicio.cerrar_sesion(sesion_a.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()
    assert arqueo.efectivo_esperado == 10000

    ventas = VentasService(session=servicio._session, tenant_id=T1, actor_id="cajero-prueba", puede_anular=False)
    resultados = await ventas.procesar_lote(_lote_venta(semilla["dispositivo"], semilla["producto"], 4000))
    await servicio._session.commit()
    assert resultados[0].resultado == "aceptada"

    fila = await _uno(
        pg_platform_url,
        "SELECT sesion_caja_id FROM ventas WHERE id = :v",
        v=uuid.UUID(resultados[0].id) if isinstance(resultados[0].id, str) else resultados[0].id,
    )
    assert fila.sesion_caja_id != sesion_a.id
    sesion_nueva = await _uno(
        pg_platform_url,
        "SELECT base_inicial, abierta_por FROM caja_sesiones WHERE id = :s AND estado = 'abierta'",
        s=fila.sesion_caja_id,
    )
    assert sesion_nueva.base_inicial == 0  # implícita, como manda ADR-018
    congelado = await _uno(
        pg_platform_url,
        "SELECT efectivo_esperado, diferencia FROM caja_sesiones WHERE id = :s",
        s=sesion_a.id,
    )
    assert (congelado.efectivo_esperado, congelado.diferencia) == (10000, 0)


async def test_anular_por_el_sync_estampa_anulada_en_y_la_devolucion_cae_en_la_sesion_abierta(
    servicio, semilla, pg_platform_url
):
    """El camino real completo de ADR-021: la venta se vende y se cobra en la
    sesión A, A cierra cuadrada, y al día siguiente el dueño la anula — la
    plata sale de la gaveta de B y el esperado vivo de B la resta (decisión 7)."""
    ventas = VentasService(session=servicio._session, tenant_id=T1, actor_id="dueno-prueba", puede_anular=True)
    sesion_a = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 0}))
    await servicio._session.commit()
    lote = _lote_venta(semilla["dispositivo"], semilla["producto"], 10000)
    [resultado] = await ventas.procesar_lote(lote)
    await servicio._session.commit()
    venta_id = resultado.id if isinstance(resultado.id, uuid.UUID) else uuid.UUID(resultado.id)

    await servicio.cerrar_sesion(sesion_a.id, SesionCerrar.model_validate({"contado": 10000}))
    await servicio._session.commit()
    sesion_b = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 50000}))
    await servicio._session.commit()

    anulacion = LoteSync.model_validate(
        {
            "dispositivo_id": str(semilla["dispositivo"]),
            "operaciones": [
                {"id": str(uuid.uuid4()), "tipo": "venta.anular", "secuencia": 2, "datos": {"venta_id": str(venta_id)}}
            ],
        }
    )
    [resultado_anulacion] = await ventas.procesar_lote(anulacion)
    await servicio._session.commit()
    assert resultado_anulacion.resultado == "aceptada"

    fila = await _uno(
        pg_platform_url,
        "SELECT estado, anulada_en IS NOT NULL AS marcada FROM ventas WHERE id = :v",
        v=venta_id,
    )
    assert (fila.estado, fila.marcada) == ("anulada", True)
    desglose = await calcular_desglose(servicio._session, sesion_b)
    assert desglose.devoluciones == 10000
    assert desglose.esperado == 50000 - 10000
    # Y el arqueo firmado de A sigue intacto: el cierre de ayer cuadra mañana.
    congelado = await _uno(
        pg_platform_url,
        "SELECT efectivo_esperado, diferencia FROM caja_sesiones WHERE id = :s",
        s=sesion_a.id,
    )
    assert (congelado.efectivo_esperado, congelado.diferencia) == (10000, 0)
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_caja_servicio.py -q -k "sync_estampa or tras_el_cierre"
# Esperado: FAILED — la anulación no estampa anulada_en (marcada == False) y la venta
# tardía... (esta última ya podría pasar por el resolvedor secuencial: el candado
# fuerte es la carrera, ver superficie de QA; lo que se fija aquí es el comportamiento)
```

- [ ] **Paso 2: bloquear la sesión al resolverla en el sync.** En `backend/services/api/app/modules/ventas/service.py`, en `_resolver_sesion_caja`, reemplazar la consulta por:

```python
        # FOR UPDATE desde el módulo 4 (decisión 5 del plan de caja): sin el
        # bloqueo, el sync puede resolver la sesión abierta, el CIERRE
        # confirmar en medio, y la venta insertar contra una sesión ya
        # `cerrada` — huérfana de todo arqueo. Con él, cierre y sync se
        # serializan sobre la fila: quien llega segundo la ve `cerrada` (la
        # consulta filtra `abierta`) y abre una implícita nueva. No hay
        # inversión de orden de bloqueo: este camino es sesión → productos;
        # el del cierre es solo sesión. El costo (lotes concurrentes del
        # mismo tenant serializados en la fila) es despreciable a la escala
        # de una tienda.
        consulta = select(CajaSesion).where(CajaSesion.estado == "abierta").with_for_update()
```

y actualizar el docstring del método para mencionar el bloqueo y la carrera con el cierre.

- [ ] **Paso 3: estampar `anulada_en` al anular.** En el mismo archivo, en `_anular_venta`, tras `venta.estado = "anulada"`:

```python
        # La marca de CUÁNDO se anuló (módulo 4, decisión 7 del plan de
        # caja): con ella, la devolución de efectivo de una venta anulada
        # tras el cierre cae en la sesión abierta en ese momento (ADR-021)
        # sin duplicar la venta como movimiento de caja.
        venta.anulada_en = datetime.now(UTC)
```

- [ ] **Paso 4: verificar.**

```bash
cd backend && uv run pytest tests/test_caja_servicio.py -q
# Esperado: 17 passed — 0 SKIPPED
uv run pytest tests/test_ventas_servicio.py tests/test_sync_idempotente.py tests/test_ventas_fixes_qa.py tests/test_ventas_adversarial.py tests/api/test_ventas_sync.py -q
# Esperado: toda la suite de ventas verde (el bloqueo y la columna no cambian ningún comportamiento existente)
uv run pytest -q -m integration
# Esperado: verde, 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 5: commit**

```bash
git add backend/services/api/app/modules/ventas/service.py backend/tests/test_caja_servicio.py
git commit -m "El sync bloquea la sesión al resolverla y la anulación estampa anulada_en"
```

**Criterios de aceptación:** la venta que sincroniza tras el cierre cae en una sesión implícita nueva y el arqueo de la cerrada queda intacto; la anulación por el camino real del sync estampa `anulada_en` y la devolución descuenta el esperado vivo de la sesión abierta; la suite completa de ventas sigue verde; 0 SKIPPED; `ruff` limpio.

---

## Tarea 7: Servicio de reportes (`ReportesService`) — P&L simple y forecast 30d

**Files:**
- Create: `backend/tests/test_reportes_servicio.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/caja/reportes.py`

**Interfaces:**
- Consume: `calcular_desglose` de `caja.service` (saldo actual = esperado vivo, decisión 3), `Venta`/`VentaItem`/`CajaSesion` de ventas, `Producto` del catálogo, `Compra` de inventario, `CajaMovimiento`, los schemas de reportes de la Tarea 3.
- Produce: `ReportesService(session, tenant_id)` con `pyl(periodo, fecha)` y `forecast()`, y la función `ventana_del_periodo(periodo, fecha)`.

- [ ] **Paso 1: escribir los tests que fallan.** Crear `backend/tests/test_reportes_servicio.py`:

```python
"""`ReportesService` contra el PostgreSQL real: el P&L simple y el forecast
de ADR-006, con el día en America/Bogota (ADR-021) y cada número declarando
su fuente.

Las marcas se siembran por SQL con `recibida_en` controlada: el P&L suma por
la verdad del servidor (ADR-018), no por el reloj del test.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import date

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.caja.reportes import ReportesService, ventana_del_periodo
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM caja_movimientos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compra_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compras WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
)

_CONSECUTIVO = itertools.count(1)

# Un instante fijo: martes 2026-07-28 10:00 en Bogotá (15:00 UTC).
DIA = date(2026, 7, 28)
EN_PUNTO = "'2026-07-28T15:00:00+00:00'"


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Dispositivo, producto (ultimo_costo 1500) y sesión con movimientos en
    T1; una venta en T2 para probar el aislamiento de los reportes."""
    engine = create_async_engine(pg_platform_url)
    ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4(), "sesion": uuid.uuid4()}
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual, ultimo_costo) "
                 "VALUES (:p, :t, 'Arroz 500g', 2500, 100, 1500)"),
            {"p": ids["producto"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) "
                 "VALUES (:s, :t, 'dueno', 50000)"),
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
            yield ReportesService(session=s, tenant_id=T1)
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def _venta(pg_platform_url, semilla, total, medio_pago="efectivo", estado="completada",
                 recibida_en=EN_PUNTO, con_item=False, cantidad="2") -> uuid.UUID:
    venta_id = uuid.uuid4()
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                    f"medio_pago, total_centavos, creada_en_cliente, recibida_en, secuencia_dispositivo, estado) "
                    f"VALUES (:v, :t, :d, :s, {next(_CONSECUTIVO)}, :mp, :total, now(), {recibida_en}, 1, :estado)"
                ),
                {"v": venta_id, "t": T1, "d": semilla["dispositivo"], "s": semilla["sesion"],
                 "mp": medio_pago, "total": total, "estado": estado},
            )
            if con_item:
                await conn.execute(
                    text("INSERT INTO ventas_items (tenant_id, venta_id, producto_id, cantidad, precio_unitario_centavos) "
                         f"VALUES (:t, :v, :p, {cantidad}, :precio)"),
                    {"t": T1, "v": venta_id, "p": semilla["producto"], "precio": total},
                )
    finally:
        await engine.dispose()
    return venta_id


async def _compra(pg_platform_url, total: int, fecha: str = "'2026-07-28'") -> None:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(f"INSERT INTO compras (tenant_id, proveedor_nombre, fecha, total_centavos) "
                     f"VALUES (:t, 'Distribuidora La 33', {fecha}, :total)"),
                {"t": T1, "total": total},
            )
    finally:
        await engine.dispose()


async def _movimiento(pg_platform_url, semilla, monto: int, tipo: str = "egreso",
                      creado: str = EN_PUNTO) -> None:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO caja_movimientos (tenant_id, sesion_caja_id, tipo, categoria, monto, motivo, "
                     f"registrado_por, created_at) VALUES (:t, :s, :tipo, 'otro', :monto, 'Prueba', 'dueno', {creado})"),
                {"t": T1, "s": semilla["sesion"], "tipo": tipo, "monto": monto},
            )
    finally:
        await engine.dispose()


# --- El P&L ---------------------------------------------------------------------


async def test_el_pyl_del_dia_suma_lo_firmado_y_declara_sus_fuentes(servicio, semilla, pg_platform_url):
    await _venta(pg_platform_url, semilla, 10000, con_item=True)          # efectivo, 2 und × costo 1500
    await _venta(pg_platform_url, semilla, 4000, medio_pago="fiado")      # fiado: cuenta en netas, no en caja
    await _venta(pg_platform_url, semilla, 7000, estado="anulada")        # anulada: NO cuenta
    await _compra(pg_platform_url, 50000)
    await _movimiento(pg_platform_url, semilla, 8000)
    await _movimiento(pg_platform_url, semilla, 5000, tipo="ingreso")

    pyl = await servicio.pyl("dia", DIA)

    assert pyl.ventas_netas_centavos == 14000
    assert (pyl.ventas_efectivo_centavos, pyl.ventas_fiado_centavos) == (10000, 4000)
    assert pyl.ventas_anuladas_centavos == 7000  # informativo: fuera de las netas
    assert pyl.costo_de_lo_vendido_centavos == 3000  # 2 × 1500, ultimo_costo ACTUAL
    assert pyl.margen_bruto_centavos == 11000
    assert pyl.compras_proveedores_centavos == 50000  # flujo informativo: NO se resta
    assert (pyl.ingresos_caja_centavos, pyl.egresos_caja_centavos) == (5000, 8000)
    assert pyl.resultado_operativo_centavos == 11000 + 5000 - 8000
    assert "ultimo_costo" in pyl.fuentes["costo_de_lo_vendido"]
    assert "NO se resta" in pyl.fuentes["compras_proveedores"]


async def test_el_dia_es_el_de_bogota_no_el_de_utc(servicio, semilla, pg_platform_url):
    """Las 8:30pm del 28 en Colombia ya son el 29 en UTC: la venta cuenta en
    el día Bogotá que le corresponde (ADR-021)."""
    await _venta(pg_platform_url, semilla, 10000, recibida_en="'2026-07-29T01:30:00+00:00'")
    dia_28 = await servicio.pyl("dia", date(2026, 7, 28))
    dia_29 = await servicio.pyl("dia", date(2026, 7, 29))
    assert dia_28.ventas_netas_centavos == 10000
    assert dia_29.ventas_netas_centavos == 0


async def test_la_semana_arranca_en_lunes_y_el_mes_en_dia_uno(servicio, semilla, pg_platform_url):
    # Domingo 26 de julio, mediodía Bogotá: semana del lunes 20, no del 27.
    await _venta(pg_platform_url, semilla, 3000, recibida_en="'2026-07-26T17:00:00+00:00'")
    # 30 de junio: fuera del mes de julio.
    await _venta(pg_platform_url, semilla, 9000, recibida_en="'2026-06-30T17:00:00+00:00'")
    semana_del_28 = await servicio.pyl("semana", DIA)
    semana_del_26 = await servicio.pyl("semana", date(2026, 7, 26))
    mes_julio = await servicio.pyl("mes", DIA)
    assert semana_del_28.ventas_netas_centavos == 0
    assert semana_del_26.ventas_netas_centavos == 3000
    assert mes_julio.ventas_netas_centavos == 3000
    # Los límites viajan en UTC y cuadran con medianoche Bogotá.
    desde, hasta = ventana_del_periodo("dia", DIA)
    assert desde.isoformat() == "2026-07-28T05:00:00+00:00"
    assert hasta.isoformat() == "2026-07-29T05:00:00+00:00"


async def test_el_costo_es_el_ultimo_costo_actual_aunque_cambie_tras_la_venta(servicio, semilla, pg_platform_url):
    """La fuente honesta (decisión 8): si el costo cambió después de la venta,
    el P&L usa el de HOY y lo declara — no inventa un costo histórico que el
    modelo no guarda."""
    await _venta(pg_platform_url, semilla, 5000, con_item=True, cantidad="2")
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE productos SET ultimo_costo = 2000 WHERE id = :p"), {"p": semilla["producto"]})
    await engine.dispose()
    pyl = await servicio.pyl("dia", DIA)
    assert pyl.costo_de_lo_vendido_centavos == 4000  # 2 × 2000, el costo actual


async def test_el_pyl_no_ve_el_negocio_de_al_lado(servicio, pg_platform_url):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            dispositivo, sesion = uuid.uuid4(), uuid.uuid4()
            await conn.execute(
                text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja T2')"),
                {"d": dispositivo, "t": T2},
            )
            await conn.execute(
                text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por) VALUES (:s, :t, 'dueno')"),
                {"s": sesion, "t": T2},
            )
            await conn.execute(
                text("INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                     f"medio_pago, total_centavos, creada_en_cliente, recibida_en, secuencia_dispositivo) "
                     f"VALUES (:v, :t, :d, :s, 1, 'efectivo', 999000, now(), {EN_PUNTO}, 1)"),
                {"v": uuid.uuid4(), "t": T2, "d": dispositivo, "s": sesion},
            )
    finally:
        await engine.dispose()
    pyl = await servicio.pyl("dia", DIA)
    assert pyl.ventas_netas_centavos == 0  # la RLS hace invisible la venta de T2


# --- El forecast --------------------------------------------------------------------


async def test_el_forecast_suma_saldo_mas_promedios_menos_egresos(servicio, semilla, pg_platform_url):
    """La fórmula honesta (decisión 9): saldo vivo de la sesión abierta +
    ventas en efectivo de los últimos 30d + cobros de fiado (0, declarado) −
    egresos de caja de los últimos 30d."""
    # `now()` en ambas: la ventana del forecast son los últimos 30d desde la
    # corrida, y una fecha fija quedaría fuera de ella con el tiempo.
    await _venta(pg_platform_url, semilla, 10000, recibida_en="now()")  # efectivo: sesión abierta y ventana 30d
    await _venta(pg_platform_url, semilla, 4000, medio_pago="fiado", recibida_en="now()")  # fiado: no es caja
    await _movimiento(pg_platform_url, semilla, 8000, creado="now()")

    forecast = await servicio.forecast()

    # OJO (corrección de la ejecución, commit bad5544): el egreso de 8000 está
    # registrado contra la sesión abierta, así que ENTRA en el esperado vivo
    # (base + ventas + ingresos − egresos, ADR-021). El plan afirmaba 60000
    # olvidando su propio egreso.
    assert forecast.saldo_actual_centavos == 50000 + 10000 - 8000  # base + venta − egreso
    assert forecast.ventas_proyectadas_centavos == 10000  # promedio diario × 30 con días en 0
    assert forecast.cobros_fiado_proyectados_centavos == 0  # sin fuente hasta el módulo 5: declarado
    assert forecast.egresos_proyectados_centavos == 8000
    assert forecast.saldo_proyectado_centavos == 52000 + 10000 + 0 - 8000
    assert forecast.dias_con_datos == 1
    assert "módulo 5" in forecast.fuentes["cobros_fiado"]
    assert "egresos de caja de los últimos 30" in forecast.fuentes["egresos_proyectados"]


async def test_el_forecast_sin_sesion_abierta_parte_de_cero_y_lo_declara(pg_app_url, semilla, pg_platform_url):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            # Cierra la sesión sembrada: sin abierta, el saldo parte de 0.
            await s.execute(text("UPDATE caja_sesiones SET estado = 'cerrada', cerrada_por = 'dueno', cerrada_en = now(), "
                                 "efectivo_esperado = 50000, efectivo_contado = 50000, diferencia = 0"))
            servicio = ReportesService(session=s, tenant_id=T1)
            forecast = await servicio.forecast()
            assert forecast.saldo_actual_centavos == 0
            assert "sin sesión abierta" in forecast.fuentes["saldo_actual"]
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_reportes_servicio.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.caja.reportes'
```

- [ ] **Paso 2: escribir el servicio de reportes.** Crear `backend/services/api/app/modules/caja/reportes.py`:

```python
"""Servicio de reportes: el P&L simple y el forecast a 30 días (ADR-006).

## Todo se calcula de lo que ya se registra — nada pide dato nuevo al usuario

Ventas (`recibida_en`, la verdad del servidor — ADR-018), ítems ×
`ultimo_costo` ACTUAL (ADR-020: «lo que el P&L costea»), compras por su
fecha de factura, y `caja_movimientos` (ADR-021). Cada número de la
respuesta declara su fuente en `fuentes`: la pantalla dice de qué datos
sale, que es la condición firmada de ADR-006.

## El día es el de America/Bogota; las marcas se guardan en UTC (ADR-021)

La ventana del período se construye como medianoches en `America/Bogota` y
se convierte a UTC para consultar. Anclarla al UTC crudo del servidor
movería al «día siguiente» todo lo vendido después de las 7pm en Colombia.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.caja.models import CajaMovimiento
from app.modules.caja.schemas import ForecastSalida, PyLSalida
from app.modules.caja.service import calcular_desglose
from app.modules.catalogo.models import Producto
from app.modules.inventario.models import Compra
from app.modules.ventas.models import CajaSesion, Venta, VentaItem

logger = structlog.get_logger()

#: El «día» del P&L y del cierre (ADR-021). Única zona del MVP (moneda y
#: operación únicas: Colombia); multi-zona no existe en el roadmap.
ZONA_LOCAL = ZoneInfo("America/Bogota")

#: La ventana del forecast (ADR-006) y del promedio que lo alimenta.
DIAS_DE_FORECAST = 30

PERIODOS: tuple[str, ...] = ("dia", "semana", "mes")


def ventana_del_periodo(periodo: str, fecha: date | None) -> tuple[datetime, datetime]:
    """`[desde, hasta)` en UTC del período anclado a America/Bogota.

    `dia` es la fecha Bogotá; `semana` arranca el LUNES de esa fecha; `mes`,
    su día 1. La ancla por defecto es HOY en Bogotá — nunca la fecha UTC del
    servidor, que a las 7pm de Colombia ya es «mañana»."""
    ancla = fecha or datetime.now(ZONA_LOCAL).date()
    if periodo == "semana":
        inicio = ancla - timedelta(days=ancla.weekday())
        fin = inicio + timedelta(days=7)
    elif periodo == "mes":
        inicio = ancla.replace(day=1)
        fin = (inicio.replace(day=28) + timedelta(days=7)).replace(day=1)
    else:  # dia
        inicio, fin = ancla, ancla + timedelta(days=1)
    desde = datetime(inicio.year, inicio.month, inicio.day, tzinfo=ZONA_LOCAL).astimezone(UTC)
    hasta = datetime(fin.year, fin.month, fin.day, tzinfo=ZONA_LOCAL).astimezone(UTC)
    return desde, hasta


class ReportesService:
    """P&L y forecast de UN negocio: el del GUC de la sesión (la RLS acota
    cada SUM; ningún reporte filtra por `tenant_id` a mano)."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self._session = session
        self._tenant_id = tenant_id

    # --- P&L ---------------------------------------------------------------------

    async def pyl(self, periodo: str, fecha: date | None) -> PyLSalida:
        """El P&L simple del período: ventas netas, costo de lo vendido,
        movimientos de caja y compras (flujo informativo, decisión 8)."""
        desde, hasta = ventana_del_periodo(periodo, fecha)
        # Las fechas Bogotá de la ventana, para las compras (su `fecha` es la
        # de la factura: un DATE sin zona).
        desde_fecha = desde.astimezone(ZONA_LOCAL).date()
        hasta_fecha = hasta.astimezone(ZONA_LOCAL).date()

        por_medio = dict(
            (
                await self._session.execute(
                    select(Venta.medio_pago, func.coalesce(func.sum(Venta.total_centavos), 0))
                    .where(Venta.estado == "completada", Venta.recibida_en >= desde, Venta.recibida_en < hasta)
                    .group_by(Venta.medio_pago)
                )
            ).all()
        )
        ventas_netas = sum(int(v) for v in por_medio.values())
        anuladas = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(Venta.total_centavos), 0)).where(
                    Venta.estado == "anulada", Venta.recibida_en >= desde, Venta.recibida_en < hasta
                )
            )
        )
        costo = await self._session.scalar(
            select(func.coalesce(func.sum(VentaItem.cantidad * func.coalesce(Producto.ultimo_costo, 0)), 0))
            .join(Venta, VentaItem.venta_id == Venta.id)
            .join(Producto, VentaItem.producto_id == Producto.id)
            .where(Venta.estado == "completada", Venta.recibida_en >= desde, Venta.recibida_en < hasta)
        )
        # Redondeo al TOTAL, declarado (decisión 8): granel × costo da
        # fracciones de centavo; una sola cuantización, no una por línea.
        costo_centavos = int(Decimal(costo).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        compras = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(Compra.total_centavos), 0)).where(
                    Compra.fecha >= desde_fecha, Compra.fecha < hasta_fecha
                )
            )
        )
        movimientos = dict(
            (
                await self._session.execute(
                    select(CajaMovimiento.tipo, func.coalesce(func.sum(CajaMovimiento.monto), 0))
                    .where(CajaMovimiento.created_at >= desde, CajaMovimiento.created_at < hasta)
                    .group_by(CajaMovimiento.tipo)
                )
            ).all()
        )
        ingresos = int(movimientos.get("ingreso", 0))
        egresos = int(movimientos.get("egreso", 0))
        margen = ventas_netas - costo_centavos
        resultado = margen + ingresos - egresos
        logger.info("pyl_calculado", periodo=periodo, ventas_netas=ventas_netas, resultado=resultado)
        return PyLSalida(
            periodo=periodo,
            desde=desde,
            hasta=hasta,
            ventas_netas_centavos=ventas_netas,
            ventas_efectivo_centavos=int(por_medio.get("efectivo", 0)),
            ventas_fiado_centavos=int(por_medio.get("fiado", 0)),
            ventas_anuladas_centavos=anuladas,
            costo_de_lo_vendido_centavos=costo_centavos,
            margen_bruto_centavos=margen,
            ingresos_caja_centavos=ingresos,
            egresos_caja_centavos=egresos,
            compras_proveedores_centavos=compras,
            resultado_operativo_centavos=resultado,
            fuentes={
                "ventas_netas": (
                    "Suma de ventas completadas (efectivo + fiado) recibidas por el servidor en el período; "
                    "las anuladas no cuentan."
                ),
                "costo_de_lo_vendido": (
                    "Suma de cantidad × ultimo_costo ACTUAL de cada producto: el costo de la última compra "
                    "de hoy, no necesariamente el del día de la venta (ADR-020). Redondeo al total."
                ),
                "compras_proveedores": (
                    "Suma de compras con fecha de factura en el período. Flujo informativo: NO se resta "
                    "del resultado porque repone inventario."
                ),
                "ingresos_caja": "Suma de movimientos manuales de ingreso de caja del período.",
                "egresos_caja": "Suma de movimientos manuales de egreso de caja del período.",
                "resultado_operativo": "ventas_netas − costo_de_lo_vendido + ingresos_caja − egresos_caja.",
            },
        )

    # --- Forecast --------------------------------------------------------------------

    async def forecast(self) -> ForecastSalida:
        """La proyección a 30 días con el alcance honesto de los datos de hoy
        (decisión 9): saldo vivo + promedio de ventas en efectivo + cobros de
        fiado (0, sin fuente hasta el módulo 5) − promedio de egresos de caja.

        «Promedio diario × 30» con los días sin datos contando 0 equivale al
        total de los últimos 30 días — y es conservador con la tienda nueva,
        que es donde una proyección optimista haría daño. Los «egresos
        recurrentes» de ADR-021 no tienen fuente en el MVP (no hay tabla de
        gastos recurrentes): el proxy declarado es el total de egresos de
        caja del mismo período. Es una proyección explicada, no una promesa
        (ADR-006)."""
        desde = datetime.now(UTC) - timedelta(days=DIAS_DE_FORECAST)
        ventas_30d = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(Venta.total_centavos), 0)).where(
                    Venta.estado == "completada", Venta.medio_pago == "efectivo", Venta.recibida_en >= desde
                )
            )
        )
        egresos_30d = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(CajaMovimiento.monto), 0)).where(
                    CajaMovimiento.tipo == "egreso", CajaMovimiento.created_at >= desde
                )
            )
        )
        dias_con_datos = int(
            await self._session.scalar(
                select(func.count(func.distinct(func.date(func.timezone("America/Bogota", Venta.recibida_en))))).where(
                    Venta.estado == "completada", Venta.recibida_en >= desde
                )
            )
        )
        sesion = (
            await self._session.execute(select(CajaSesion).where(CajaSesion.estado == "abierta"))
        ).scalar_one_or_none()
        saldo = 0
        if sesion is not None:
            # El saldo actual ES el esperado vivo de la sesión abierta: la
            # misma función del arqueo (decisión 3), jamás una copia.
            saldo = (await calcular_desglose(self._session, sesion)).esperado
        cobros = 0  # ADR-022 (módulo 5): la tabla de abonos no existe.
        proyectado = saldo + ventas_30d + cobros - egresos_30d
        logger.info("forecast_calculado", saldo=saldo, proyectado=proyectado)
        return ForecastSalida(
            dias=DIAS_DE_FORECAST,
            saldo_actual_centavos=saldo,
            ventas_proyectadas_centavos=ventas_30d,
            cobros_fiado_proyectados_centavos=cobros,
            egresos_proyectados_centavos=egresos_30d,
            saldo_proyectado_centavos=proyectado,
            dias_con_datos=dias_con_datos,
            fuentes={
                "saldo_actual": (
                    "Esperado vivo de la sesión de caja abierta (base + ventas en efectivo + movimientos − "
                    "devoluciones). Con 0 y «sin sesión abierta» cuando no hay caja abierta."
                ),
                "ventas_proyectadas": (
                    "Promedio diario de ventas en efectivo completadas de los últimos 30 días × 30 "
                    "(los días sin datos cuentan 0 — conservador con la tienda nueva)."
                ),
                "cobros_fiado": "0: los abonos y vencimientos de fiado llegan con el módulo 5 (ADR-022).",
                "egresos_proyectados": (
                    "Total de egresos de caja de los últimos 30 días. No hay gastos recurrentes "
                    "registrables en el MVP: es el proxy honesto, declarado."
                ),
                "saldo_proyectado": "saldo_actual + ventas_proyectadas + cobros_fiado − egresos_proyectados.",
            },
        )
```

- [ ] **Paso 3: verificar.**

```bash
cd backend && uv run pytest tests/test_reportes_servicio.py -q
# Esperado: 7 passed — 0 SKIPPED
uv run pytest -q -m integration
# Esperado: verde, 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/caja/reportes.py backend/tests/test_reportes_servicio.py
git commit -m "Reportes: P&L simple por período en America/Bogota y forecast 30d con fuentes declaradas"
```

**Criterios de aceptación:** los 7 tests pasan, 0 SKIPPED; el P&L excluye la venta anulada de las netas y la muestra como línea informativa; el día es el de Bogotá (la venta de las 8:30pm Colombia cuenta en su día); semana arranca en lunes y mes en día 1 con límites UTC exactos; el costo es `ultimo_costo` actual declarado; la RLS hace invisible el negocio de al lado; el forecast suma saldo vivo + promedios y declara cada fuente, con cobros de fiado en 0 explícito; `ruff` limpio.

---

## Tarea 8: Dependencias, router y montaje en la app

**Files:**
- Create: `backend/tests/api/test_caja_api.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/caja/dependencies.py`
- Create: `backend/services/api/app/modules/caja/router.py`
- Modify: `backend/services/api/app/factory.py` (importar y montar el router)
- Modify: `backend/tests/api/conftest.py` (la limpieza borra también `caja_movimientos`)

**Interfaces:**
- Consume: `exigir_permiso`, `sesion_de_tenant` de `app.dependencies`; `exigir_negocio_activo` de `app.modules.tenants.dependencies`; los permisos de la Tarea 4; `PagedList` de `vendi_core.models.pagination`; `ErrorResponse`.
- Produce: 8 rutas — `POST /api/v1/caja/sesiones`, `GET /api/v1/caja/sesiones/actual`, `GET /api/v1/caja/sesiones`, `POST /api/v1/caja/sesiones/{sesion_id}/cerrar`, `POST /api/v1/caja/movimientos`, `GET /api/v1/caja/movimientos`, `GET /api/v1/reportes/pyl`, `GET /api/v1/reportes/forecast` — con guards por permiso y sobre de error estándar.

- [ ] **Paso 1: escribir los tests de API que fallan.** Crear `backend/tests/api/test_caja_api.py`:

```python
"""Los endpoints de caja y reportes contra el PostgreSQL real.

Misma regla que `test_inventario_api.py`: la base no se dobla, y cada test
crea su negocio por el camino real y opera con tokens de roles distintos,
porque lo que se mide aquí es quién puede hacer qué (ADR-023): el cajero
abre y mueve caja pero NO cierra, NO ve el esperado, NO ve el historial y
NO ve reportes; el almacenista no toca caja.
"""

from __future__ import annotations

import uuid

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_con_rol, usuario_de_plataforma

from vendi_core.auth.policies import ROL_ALMACENISTA, ROL_CAJERO, ROL_DUENO

pytestmark = pytest.mark.integration


def _admin(validador, token: str = "tok-admin") -> dict:
    validador.registrar(token, usuario_de_plataforma())
    return {"Authorization": f"Bearer {token}"}


def _crear_negocio(cliente, validador, nombre: str) -> str:
    respuesta = cliente.post(
        "/api/v1/platform/tenants", json={"nombre": PREFIJO_PRUEBA + nombre}, headers=_admin(validador)
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _cabeceras_de(validador, rol: str, tenant_id: str, token: str) -> dict:
    validador.registrar(token, usuario_con_rol(rol, uuid.UUID(tenant_id)))
    return {"Authorization": f"Bearer {token}"}


def _abrir(cliente, cabeceras, base: int = 50000) -> dict:
    respuesta = cliente.post("/api/v1/caja/sesiones", json={"base_inicial": base}, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _movimiento(**cambios) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "tipo": "egreso",
        "categoria": "servicios",
        "monto": 12000,
        "motivo": "Recibo de la luz",
        **cambios,
    }


# --- Apertura, movimientos y cierre -------------------------------------------------


def test_abrir_caja_devuelve_201_y_la_segunda_apertura_es_409(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 1")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d1")

    sesion = _abrir(cliente, cabeceras)
    assert sesion["estado"] == "abierta" and sesion["base_inicial"] == 50000

    segunda = cliente.post("/api/v1/caja/sesiones", json={"base_inicial": 30000}, headers=cabeceras)
    assert segunda.status_code == 409
    assert segunda.json()["code"] == "caja_ya_abierta"


def test_el_cajero_abre_y_mueve_caja_pero_no_cierra(app_con_base):
    """El reparto firmado de ADR-023: abrir y registrar movimientos es del
    cajero; cerrar/arquear es el gesto con dinero que queda en el dueño."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 2")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c2")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d2")

    sesion = _abrir(cliente, cajero, base=40000)
    alta = cliente.post("/api/v1/caja/movimientos", json=_movimiento(), headers=cajero)
    assert alta.status_code == 201, alta.text
    assert alta.json()["sesion_caja_id"] == sesion["id"]

    cierre_cajero = cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 40000}, headers=cajero)
    assert cierre_cajero.status_code == 403 and cierre_cajero.json()["code"] == "permiso_ausente"
    # Y el dueño sí cierra (distingue «deniega porque no lo tiene» de «deniega siempre»).
    cierre_dueno = cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 28000}, headers=dueno)
    assert cierre_dueno.status_code == 200, cierre_dueno.text
    cuerpo = cierre_dueno.json()
    assert cuerpo["efectivo_esperado"] == 28000  # base 40.000 − egreso 12.000
    assert cuerpo["diferencia"] == 0
    assert cuerpo["desglose"]["egresos"] == 12000


def test_el_almacenista_no_toca_caja(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 3")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a3")

    assert cliente.post("/api/v1/caja/sesiones", json={"base_inicial": 0}, headers=almacenista).status_code == 403
    assert cliente.get("/api/v1/caja/sesiones/actual", headers=almacenista).status_code == 403
    assert cliente.post("/api/v1/caja/movimientos", json=_movimiento(), headers=almacenista).status_code == 403
    assert cliente.get("/api/v1/caja/sesiones", headers=almacenista).status_code == 403


def test_el_cajero_no_ve_el_esperado_ni_el_historial(app_con_base):
    """Decisión 4: el esperado vivo viaja en null sin `caja:cerrar` (misma
    forma, mismo patrón que `ultimo_costo`), y el historial de arqueos es
    del dueño."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 4")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d4")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c4")
    _abrir(cliente, dueno, base=50000)

    vista_dueno = cliente.get("/api/v1/caja/sesiones/actual", headers=dueno)
    assert vista_dueno.status_code == 200 and vista_dueno.json()["efectivo_esperado"] == 50000
    vista_cajero = cliente.get("/api/v1/caja/sesiones/actual", headers=cajero)
    assert vista_cajero.status_code == 200
    assert "efectivo_esperado" in vista_cajero.json() and vista_cajero.json()["efectivo_esperado"] is None
    assert cliente.get("/api/v1/caja/sesiones", headers=cajero).status_code == 403
    assert cliente.get("/api/v1/caja/sesiones", headers=dueno).json()["total"] == 1


def test_el_movimiento_valida_cotas_motivo_y_forma(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 5")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d5")
    _abrir(cliente, cabeceras)

    # Monto que desborda Integer → 422, nunca 500 (lección BUG-2).
    assert cliente.post("/api/v1/caja/movimientos", json=_movimiento(monto=2**31), headers=cabeceras).status_code == 422
    assert cliente.post("/api/v1/caja/movimientos", json=_movimiento(monto=0), headers=cabeceras).status_code == 422
    assert cliente.post("/api/v1/caja/movimientos", json=_movimiento(motivo="  "), headers=cabeceras).status_code == 422
    assert cliente.post("/api/v1/caja/movimientos", json=_movimiento(categoria="ropa"), headers=cabeceras).status_code == 422
    # Un tenant_id inyectado → 422 por extra="forbid".
    assert cliente.post(
        "/api/v1/caja/movimientos", json=_movimiento(tenant_id=str(uuid.uuid4())), headers=cabeceras
    ).status_code == 422


def test_el_movimiento_sin_sesion_abierta_es_409(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 6")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d6")

    respuesta = cliente.post("/api/v1/caja/movimientos", json=_movimiento(), headers=cabeceras)
    assert respuesta.status_code == 409
    assert respuesta.json()["code"] == "caja_sin_sesion_abierta"


def test_el_reintento_del_movimiento_no_duplica_y_el_divergente_es_409(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 7")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d7")
    _abrir(cliente, cabeceras)

    datos = _movimiento()
    primero = cliente.post("/api/v1/caja/movimientos", json=datos, headers=cabeceras)
    segundo = cliente.post("/api/v1/caja/movimientos", json=datos, headers=cabeceras)
    assert primero.status_code == 201 and segundo.status_code == 201
    assert segundo.json()["id"] == datos["id"]
    lista = cliente.get("/api/v1/caja/movimientos", headers=cabeceras)
    assert lista.json()["total"] == 1
    divergente = cliente.post("/api/v1/caja/movimientos", json={**datos, "monto": 9999}, headers=cabeceras)
    assert divergente.status_code == 409 and divergente.json()["code"] == "movimiento_id_divergente"


def test_cerrar_desconocida_es_404_y_el_reintento_del_cierre_no_reabre(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 8")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d8")

    assert cliente.post(
        f"/api/v1/caja/sesiones/{uuid.uuid4()}/cerrar", json={"contado": 0}, headers=cabeceras
    ).status_code == 404

    sesion = _abrir(cliente, cabeceras, base=0)
    primero = cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 0}, headers=cabeceras)
    reintento = cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 0}, headers=cabeceras)
    assert primero.status_code == 200 and reintento.status_code == 200
    assert reintento.json()["efectivo_esperado"] == 0 and reintento.json()["desglose"] is None
    otro_conteo = cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 100}, headers=cabeceras)
    assert otro_conteo.status_code == 409 and otro_conteo.json()["code"] == "caja_ya_cerrada"


def test_la_caja_de_otro_negocio_es_invisible(app_con_base):
    cliente, validador, _ = app_con_base
    negocio_a = _crear_negocio(cliente, validador, "Caja 9A")
    negocio_b = _crear_negocio(cliente, validador, "Caja 9B")
    cab_a = _cabeceras_de(validador, ROL_DUENO, negocio_a, "tok-d9a")
    cab_b = _cabeceras_de(validador, ROL_DUENO, negocio_b, "tok-d9b")
    sesion = _abrir(cliente, cab_a)

    # Cerrar la sesión del vecino: 404 (la RLS la hace invisible), no 200 ni 500.
    assert cliente.post(f"/api/v1/caja/sesiones/{sesion['id']}/cerrar", json={"contado": 0}, headers=cab_b).status_code == 404
    assert cliente.get("/api/v1/caja/sesiones", headers=cab_b).json()["total"] == 0
    assert cliente.get(f"/api/v1/caja/movimientos?sesion_id={sesion['id']}", headers=cab_b).status_code == 404


# --- Reportes ---------------------------------------------------------------------


def test_el_pyl_y_el_forecast_son_del_dueno(app_con_base):
    """ADR-023: el cajero no ve reportes; el almacenista tampoco."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 10")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d10")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c10")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a10")

    for cabeceras in (cajero, almacenista):
        assert cliente.get("/api/v1/reportes/pyl", headers=cabeceras).status_code == 403
        assert cliente.get("/api/v1/reportes/forecast", headers=cabeceras).status_code == 403

    pyl = cliente.get("/api/v1/reportes/pyl?periodo=dia", headers=dueno)
    assert pyl.status_code == 200, pyl.text
    cuerpo = pyl.json()
    assert cuerpo["ventas_netas_centavos"] == 0
    assert "ultimo_costo" in cuerpo["fuentes"]["costo_de_lo_vendido"]
    forecast = cliente.get("/api/v1/reportes/forecast", headers=dueno)
    assert forecast.status_code == 200
    assert forecast.json()["cobros_fiado_proyectados_centavos"] == 0
    assert forecast.json()["dias"] == 30


def test_el_periodo_invalido_es_422(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 11")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d11")

    assert cliente.get("/api/v1/reportes/pyl?periodo=trimestre", headers=cabeceras).status_code == 422
    assert cliente.get("/api/v1/reportes/pyl?fecha=28-07-2026", headers=cabeceras).status_code == 422
    assert cliente.get("/api/v1/reportes/pyl?periodo=semana&fecha=2026-07-28", headers=cabeceras).status_code == 200


def test_sin_sesion_abierta_la_actual_es_404(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Caja 12")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d12")

    respuesta = cliente.get("/api/v1/caja/sesiones/actual", headers=cabeceras)
    assert respuesta.status_code == 404 and respuesta.json()["code"] == "caja_sin_sesion_abierta"


def test_sin_token_es_401(app_con_base):
    cliente, _, _ = app_con_base
    assert cliente.get("/api/v1/caja/sesiones/actual").status_code == 401
    assert cliente.post("/api/v1/caja/movimientos", json={}).status_code == 401
    assert cliente.get("/api/v1/reportes/pyl").status_code == 401
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/api/test_caja_api.py -q
# Esperado: 13 fallos con 404 (las rutas no existen)
```

- [ ] **Paso 2: enseñar la limpieza al conftest de API.** En `backend/tests/api/conftest.py`, en la tupla de tablas de `limpiar_tenants_de_prueba`, añadir `"caja_movimientos"` como PRIMERA entrada (antes de `movimientos_inventario`): referencia `caja_sesiones` con FK `RESTRICT`, y sin ella la segunda corrida revienta al borrar sesiones.

- [ ] **Paso 3: escribir las dependencias.** Crear `backend/services/api/app/modules/caja/dependencies.py`:

```python
"""Dependencias del módulo `caja`.

El guard de permisos vive en `app.dependencies.exigir_permiso` (su casa desde
el módulo ventas). El reparto (ADR-023 y decisión 4 del plan): el cajero
abre, lee y mueve caja; cerrar y el historial de arqueos exigen
`caja:cerrar`; los reportes exigen `reporte:leer`. El 403 del cajero al
cerrar es la respuesta correcta y esperada, no un error a ocultar.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import exigir_permiso, sesion_de_tenant
from app.modules.caja.reportes import ReportesService
from app.modules.caja.service import CajaService
from app.modules.tenants.dependencies import exigir_negocio_activo
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.auth.policies import (
    PERM_CAJA_ABRIR,
    PERM_CAJA_CERRAR,
    PERM_CAJA_LEER,
    PERM_CAJA_MOVIMIENTO,
    PERM_REPORTE_LEER,
    has_permission,
)
from vendi_core.tenant.context import TenantContext

exigir_caja_leer = exigir_permiso(PERM_CAJA_LEER)
exigir_caja_abrir = exigir_permiso(PERM_CAJA_ABRIR)
exigir_caja_cerrar = exigir_permiso(PERM_CAJA_CERRAR)
exigir_caja_movimiento = exigir_permiso(PERM_CAJA_MOVIMIENTO)
exigir_reporte_leer = exigir_permiso(PERM_REPORTE_LEER)


async def servicio_de_caja(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
    user: UserContext = Depends(get_current_user),
) -> CajaService:
    """El servicio del negocio del token, con la sesión que la RLS acota.

    `exigir_negocio_activo` va primero: un negocio suspendido no opera caja
    (403 `tenant_suspendido`). El veredicto sobre cerrar se deriva AQUÍ del
    token y viaja al servicio como flag — el servicio no lee claims
    (ADR-015/ADR-023) — y condiciona el esperado vivo (decisión 4). El
    `actor_id` queda en cada sesión y movimiento: la auditoría del gesto
    con dinero."""
    return CajaService(
        session=session,
        tenant_id=tenant.tenant_id,
        actor_id=user.user_id,
        puede_cerrar=has_permission(user, PERM_CAJA_CERRAR),
    )


async def servicio_de_reportes(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
) -> ReportesService:
    return ReportesService(session=session, tenant_id=tenant.tenant_id)


__all__ = [
    "exigir_caja_abrir",
    "exigir_caja_cerrar",
    "exigir_caja_leer",
    "exigir_caja_movimiento",
    "exigir_reporte_leer",
    "servicio_de_caja",
    "servicio_de_reportes",
]
```

- [ ] **Paso 4: escribir el router.** Crear `backend/services/api/app/modules/caja/router.py`:

```python
"""Caja y reportes: `/api/v1/caja/*` y `/api/v1/reportes/*`.

Endpoints REST ONLINE puros (patrón inventario): NADA de este módulo viaja
por el lote del sync — la apertura implícita del sync sigue igual (ADR-018,
decisión 10 del plan). Todo trabaja con la sesión de TENANT (rol
`vendi_app`, RLS activo): ningún handler recibe `tenant_id` por URL, cuerpo
o cabecera. Los permisos (ADR-023): abrir `caja:abrir`, leer `caja:leer`,
movimientos `caja:movimiento`, cerrar e historial `caja:cerrar`, reportes
`reporte:leer`. El 403 por rol es la respuesta correcta y esperada.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from app.modules.caja.dependencies import (
    exigir_caja_abrir,
    exigir_caja_cerrar,
    exigir_caja_leer,
    exigir_caja_movimiento,
    exigir_reporte_leer,
    servicio_de_caja,
    servicio_de_reportes,
)
from app.modules.caja.reportes import ReportesService
from app.modules.caja.schemas import (
    ArqueoConDesglose,
    ArqueoSalida,
    ForecastSalida,
    MovimientoCrear,
    MovimientoSalida,
    PyLSalida,
    SesionAbrir,
    SesionActualSalida,
    SesionCerrar,
    SesionSalida,
)
from app.modules.caja.service import CajaService
from vendi_core.auth.context import UserContext
from vendi_core.models.pagination import PagedList
from vendi_core.models.responses import ErrorResponse

router = APIRouter(tags=["caja"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    422: {"model": ErrorResponse, "description": "Request malformado (validación de estructura o de dominio)"},
}


@router.post(
    "/caja/sesiones",
    response_model=SesionSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Abrir la caja del día",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "Ya hay una caja abierta (o el id de sesión está en uso)"},
    },
)
async def abrir_caja(
    datos: SesionAbrir,
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_abrir),
) -> SesionSalida:
    """UNA sesión abierta por tienda (ADR-021): la regla la hace cumplir el
    índice único parcial, no el código. Acepta el `id` del cliente
    (ADR-017): reenviar la misma apertura devuelve la sesión existente."""
    return SesionSalida.model_validate(await servicio.abrir_sesion(datos))


@router.get(
    "/caja/sesiones/actual",
    response_model=SesionActualSalida,
    summary="La sesión abierta, con el esperado vivo solo para quien cierra",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "No hay caja abierta"}},
)
async def sesion_actual(
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_leer),
) -> SesionActualSalida:
    """`efectivo_esperado` viaja en `null` sin `caja:cerrar` (decisión 4):
    el esperado vivo es la cifra con la que se cuadra un faltante, y el
    cajero no cierra ni ve reportes (ADR-023)."""
    return await servicio.sesion_actual()


@router.get(
    "/caja/sesiones",
    response_model=PagedList[ArqueoSalida],
    summary="Historial de sesiones con su arqueo congelado",
    responses=_RESPUESTAS_COMUNES,
)
async def listar_sesiones(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_cerrar),
) -> PagedList[ArqueoSalida]:
    """Faltantes y sobrantes históricos son un reporte: exige `caja:cerrar`
    (decisión 4). Las columnas congeladas son la única fuente: jamás se
    recalculan."""
    filas, total = await servicio.listar_sesiones(skip=skip, limit=limit)
    return PagedList[ArqueoSalida](
        items=[ArqueoSalida.model_validate(f) for f in filas], total=total, skip=skip, limit=limit
    )


@router.post(
    "/caja/sesiones/{sesion_id}/cerrar",
    response_model=ArqueoConDesglose,
    summary="Cerrar la caja con arqueo (conteo físico)",
    responses={
        **_RESPUESTAS_COMUNES,
        404: {"model": ErrorResponse, "description": "La sesión no existe"},
        409: {"model": ErrorResponse, "description": "La sesión ya fue cerrada con otro conteo"},
    },
)
async def cerrar_caja(
    sesion_id: uuid.UUID,
    datos: SesionCerrar,
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_cerrar),
) -> ArqueoConDesglose:
    """El arqueo (ADR-021): el servidor calcula `esperado = base + ventas en
    efectivo + abonos (0 hasta el módulo 5) + ingresos − egresos −
    devoluciones` sumando desde las tablas de origen, y lo CONGELA con el
    `contado` y la `diferencia` en la sesión. Desde entonces nada lo reabre:
    ni una venta que sincroniza tarde, ni una anulación posterior. El
    reintento con el mismo conteo devuelve el arqueo firmado."""
    return await servicio.cerrar_sesion(sesion_id, datos)


@router.post(
    "/caja/movimientos",
    response_model=MovimientoSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un ingreso o egreso manual de caja",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "No hay caja abierta, o el id del movimiento ya existe con datos distintos"},
    },
)
async def registrar_movimiento(
    datos: MovimientoCrear,
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_movimiento),
) -> MovimientoSalida:
    """Con `motivo` obligatorio e `id` del cliente requerido (es dinero: la
    ancla hace seguro el reintento). Las ventas en efectivo y los abonos NO
    son movimientos: el arqueo los suma desde su tabla de origen (ADR-021)."""
    return MovimientoSalida.model_validate(await servicio.registrar_movimiento(datos))


@router.get(
    "/caja/movimientos",
    response_model=PagedList[MovimientoSalida],
    summary="Movimientos de una sesión (la abierta, por defecto)",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "La sesión no existe (o no hay abierta)"}},
)
async def listar_movimientos(
    sesion_id: uuid.UUID | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: CajaService = Depends(servicio_de_caja),
    _actor: UserContext = Depends(exigir_caja_leer),
) -> PagedList[MovimientoSalida]:
    filas, total = await servicio.listar_movimientos(sesion_id, skip=skip, limit=limit)
    return PagedList[MovimientoSalida](
        items=[MovimientoSalida.model_validate(f) for f in filas], total=total, skip=skip, limit=limit
    )


@router.get(
    "/reportes/pyl",
    response_model=PyLSalida,
    summary="P&L simple del período (día/semana/mes en America/Bogota)",
    responses=_RESPUESTAS_COMUNES,
)
async def pyl(
    periodo: Literal["dia", "semana", "mes"] = Query(default="dia"),
    fecha: date | None = Query(default=None, description="Ancla Bogotá (YYYY-MM-DD); por defecto, hoy"),
    servicio: ReportesService = Depends(servicio_de_reportes),
    _actor: UserContext = Depends(exigir_reporte_leer),
) -> PyLSalida:
    """Se calcula de lo que ya se registra (ADR-006): ventas por
    `recibida_en`, costo con el `ultimo_costo` actual (declarado), compras
    por fecha de factura y movimientos de caja. Cada número declara su
    fuente en `fuentes`."""
    return await servicio.pyl(periodo, fecha)


@router.get(
    "/reportes/forecast",
    response_model=ForecastSalida,
    summary="Forecast de flujo de caja a 30 días",
    responses=_RESPUESTAS_COMUNES,
)
async def forecast(
    servicio: ReportesService = Depends(servicio_de_reportes),
    _actor: UserContext = Depends(exigir_reporte_leer),
) -> ForecastSalida:
    """Proyección explicada, no promesa (ADR-006): saldo vivo + promedio de
    ventas en efectivo 30d + cobros de fiado (0 hasta el módulo 5,
    declarado) − promedio de egresos de caja 30d. Cada número declara su
    fuente."""
    return await servicio.forecast()
```

- [ ] **Paso 5: montar el router.** En `backend/services/api/app/factory.py`, añadir el import tras el de inventario:

```python
from app.modules.caja.router import router as router_caja
```

y tras `app.include_router(router_inventario, prefix="/api/v1")`:

```python
    app.include_router(router_caja, prefix="/api/v1")
```

- [ ] **Paso 6: verificar.**

```bash
cd backend && uv run pytest tests/api/test_caja_api.py -q
# Esperado: 13 passed — 0 SKIPPED
uv run pytest tests/api -q
# Esperado: toda la carpeta verde (los tests de catálogo, ventas, inventario y tenants siguen pasando)
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 7: commit**

```bash
git add backend/services/api/app/modules/caja/dependencies.py backend/services/api/app/modules/caja/router.py backend/services/api/app/factory.py backend/tests/api/test_caja_api.py backend/tests/api/conftest.py
git commit -m "Endpoints REST de caja y reportes: sesiones, arqueo, movimientos, P&L y forecast"
```

**Criterios de aceptación:** los 13 tests de API pasan contra el stack real, 0 SKIPPED; el cajero abre y mueve caja pero recibe 403 `permiso_ausente` al cerrar, en el historial y en los dos reportes, y el esperado vivo le llega en `null` con la misma forma; el almacenista recibe 403 en todo lo de caja; la segunda apertura es 409 con la sesión vigente; el reintento del cierre no recalcula ni reabre; la sesión del vecino es 404/invisible; las cotas son 422 y nunca 500; el sobre de error es el estándar; `tests/api` completo verde (con la limpieza cubriendo `caja_movimientos`); `ruff` limpio.

---

## Tarea 9: Cerrar D-15 (`exigir_venta_anular` se borra) y extender el check 23

**Files:**
- Modify: `backend/services/api/app/modules/ventas/dependencies.py` (la definición y el `__all__`)
- Modify: `scripts/verify-setup.sh` (bloque del check 23)

**Interfaces:**
- Consume: el generador de tokens de ejemplo de la Admin API que el check 23 ya usa para inspeccionar `realm_access.roles` del token del dueño demo.
- Produce: D-15 lista para cerrarse en la Tarea 11; el check 23 falla si el token del dueño no trae los cinco permisos nuevos.

Contexto (D-15 de `docs/deuda-tecnica.md`): `exigir_venta_anular` está definido y exportado sin endpoint que lo use — la anulación del piloto viaja como operación del lote y su chequeo es por operación dentro del servicio (decisión 12 del plan de ventas). Su vencimiento dice «Fase 1 (módulo 4); si nada lo usa, se borra». Este módulo es caja y finanzas: ningún endpoint nuevo la usa, y la decisión 11 de este plan firma el borrado.

- [ ] **Paso 1: borrar el guard huérfano.** En `backend/services/api/app/modules/ventas/dependencies.py`:

- Eliminar la línea `exigir_venta_anular = exigir_permiso(PERM_VENTA_ANULAR)`.
- Eliminar `"exigir_venta_anular",` de `__all__`.
- CONSERVAR el import de `PERM_VENTA_ANULAR`: lo usa `servicio_de_ventas` para derivar `puede_anular` (la anulación se sigue chequeando por operación dentro del servicio — eso no cambia).
- Actualizar el docstring de cabecera si menciona el guard.

- [ ] **Paso 2: verificar que nada lo usaba y que todo sigue verde.**

```bash
cd backend && grep -rn "exigir_venta_anular" . --include="*.py"
# Esperado: sin resultados (ni definición, ni usos, ni imports en tests)
uv run pytest -q -m integration
# Esperado: verde, 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 3: extender el bucle de permisos del check 23.** En `scripts/verify-setup.sh`, dentro del heredoc `python3 - <<'PY'` del check 23, reemplazar la línea del bucle por:

```python
for permiso in ("producto:leer", "producto:editar", "venta:crear", "venta:anular", "inventario:ajustar", "compra:crear", "caja:leer", "caja:abrir", "caja:cerrar", "caja:movimiento", "reporte:leer"):
```

y el mensaje del `ok` por:

```bash
        ok "aud=${KEYCLOAK_AUDIENCE:-vendi-backend}, rol de negocio y permisos de catálogo, ventas, inventario y caja en el token del dueño"
```

- [ ] **Paso 4: verificar contra el stack.**

```bash
bash scripts/seed.sh && bash scripts/verify-setup.sh 2>&1 | grep -E "^\[(OK|FALLO|OMITIDO)\].*23"
# Esperado: [OK] 23 ... permisos de catálogo, ventas, inventario y caja en el token del dueño
```

Prueba negativa (obligatoria): quitar temporalmente `caja:cerrar` del mapeo del grupo `dueno` en la consola de Keycloak (`https://accounts.vendi.co`, con `--resolve accounts.vendi.co:443:127.0.0.1`), re-ejecutar el check y verlo fallar con el mensaje de siembra; restaurar con `bash scripts/seed.sh` y ver el OK.

- [ ] **Paso 5: commit**

```bash
git add backend/services/api/app/modules/ventas/dependencies.py scripts/verify-setup.sh
git commit -m "Borrado el guard exigir_venta_anular sin consumidor (D-15) y check 23 con los permisos de caja"
```

**Criterios de aceptación:** ninguna referencia a `exigir_venta_anular` queda en el código; la suite de integración sigue verde (la anulación por operación conserva su chequeo y sus tests); el check 23 pasa con la siembra al día y falla —con mensaje accionable— si falta cualquiera de los once permisos.

---

## Tarea 10: Congelar el OpenAPI y regenerar el cliente TypeScript

**Files:**
- Modify: `docs/api/openapi-fase0.json` (regenerado, mismo archivo — decisión 13 del plan)
- Modify: `docs/api/README.md` (tabla de rutas, códigos, notas)
- Modify: `frontend/projects/libs/data-access/src/lib/api-client/openapi.json` e `index.ts` (salida del codegen)

**Interfaces:**
- Consume: la API viva con `DOCS_PUBLICOS=true` y `scripts/codegen-api-client.sh` en modo congelado.
- Produce: el contrato con las 8 rutas nuevas; el cliente TS regenerado sin deriva (`codegen + git diff --exit-code` en 0).

- [ ] **Paso 1: regenerar el contrato congelado desde la API viva.** Con el stack levantado y la migración aplicada:

```bash
curl -sS --resolve api.vendi.co:443:127.0.0.1 https://api.vendi.co/openapi.json \
  | python3 -c 'import json,sys; json.dump(json.load(sys.stdin), open("docs/api/openapi-fase0.json","w"), indent=2, ensure_ascii=False, sort_keys=True)'
python3 -c 'import json; d=json.load(open("docs/api/openapi-fase0.json")); print(sorted(p for p in d["paths"] if "caja" in p or "reportes" in p))'
# Esperado: ['/api/v1/caja/movimientos', '/api/v1/caja/sesiones', '/api/v1/caja/sesiones/actual',
#            '/api/v1/caja/sesiones/{sesion_id}/cerrar', '/api/v1/reportes/forecast', '/api/v1/reportes/pyl']
```

`sort_keys=True` e `indent=2` no son cosméticos: sin orden estable, cada regeneración produce un diff ilegible.

- [ ] **Paso 2: actualizar `docs/api/README.md`.** Añadir a la tabla de rutas:

```markdown
| `POST /api/v1/caja/sesiones` | `caja:abrir` | abre la caja del día con `base_inicial`; UNA abierta por tienda (índice único parcial, ADR-021); acepta `id` del cliente (idempotente); 409 `caja_ya_abierta` si ya hay |
| `GET /api/v1/caja/sesiones/actual` | `caja:leer` | la sesión abierta; `efectivo_esperado` viaja en `null` sin `caja:cerrar` (mismo patrón que `ultimo_costo`); 404 `caja_sin_sesion_abierta` |
| `GET /api/v1/caja/sesiones` | `caja:cerrar` | historial paginado con el arqueo congelado (faltantes/sobrantes son del dueño) |
| `POST /api/v1/caja/sesiones/{id}/cerrar` | `caja:cerrar` | el arqueo: calcula `esperado = base + ventas efectivo completadas + abonos (0 hasta el módulo 5) + ingresos − egresos − devoluciones` desde las tablas de origen y lo CONGELA; reintento con el mismo `contado` devuelve lo firmado, con otro es 409 `caja_ya_cerrada` |
| `POST /api/v1/caja/movimientos` | `caja:movimiento` | ingreso/egreso manual con `categoria` cerrada y `motivo` obligatorio; `id` del cliente requerido; reintento idéntico = no-op, divergente = 409; 409 `caja_sin_sesion_abierta` |
| `GET /api/v1/caja/movimientos` | `caja:leer` | listado paginado de una sesión (la abierta por defecto) |
| `GET /api/v1/reportes/pyl` | `reporte:leer` | P&L simple del período (`dia`/`semana`/`mes` en America/Bogota, `fecha` opcional); cada número declara su fuente en `fuentes`; el costo es `ultimo_costo` ACTUAL (declarado) |
| `GET /api/v1/reportes/forecast` | `reporte:leer` | forecast a 30 días: saldo vivo + promedio ventas efectivo 30d + cobros fiado (0, declarado) − promedio egresos 30d |
```

A la lista de `code` estables: `caja_ya_abierta`, `caja_sin_sesion_abierta`, `caja_sesion_no_encontrada`, `caja_ya_cerrada`, `sesion_id_duplicado`, `movimiento_id_divergente`. Y a las notas finales:

```markdown
En `GET /api/v1/caja/sesiones/actual`, `efectivo_esperado` viaja en `null`
para quien no tiene `caja:cerrar` (el cajero): el esperado vivo es la cifra
con la que se cuadra un faltante antes del arqueo, y ADR-023 firma que el
cajero no cierra ni ve reportes. El campo sigue presente en el esquema
(anulable); lo que cambia con el permiso es su valor, no la forma.

El arqueo cerrado no se recalcula jamás: las columnas congeladas de la
sesión son la única fuente. Las ventas en efectivo y los abonos de fiado NO
se duplican como movimientos (ADR-021): el arqueo los suma desde su tabla de
origen — los abonos son 0 hasta el módulo 5 (ADR-022), declarado en el
desglose y en el forecast. La devolución de una venta anulada tras el cierre
cae en la sesión abierta en ese momento (vía `ventas.anulada_en`).

Eventos nuevos del outbox en este contrato: `caja.sesion_abierta`,
`caja.movimiento_registrado` y `caja.sesion_cerrada` — esta última con el
resumen completo del arqueo (desglose, esperado, contado, diferencia), que
es el insumo del briefing matutino de IA y de la telemetría.
```

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
git commit -m "Contrato OpenAPI con las rutas de caja y reportes, y cliente TypeScript regenerado"
```

**Criterios de aceptación:** el OpenAPI congelado contiene las 6 rutas nuevas (8 endpoints) con sus schemas (`SesionAbrir`, `SesionActualSalida`, `SesionCerrar`, `ArqueoSalida`, `ArqueoConDesglose`, `MovimientoCrear`, `MovimientoSalida`, `PyLSalida`, `ForecastSalida`); el job `frontend-contratos` del CI (codegen contra el congelado + `git diff --exit-code`) queda en verde; `vendi-admin` compila contra el cliente regenerado.

---

## Tarea 11: Cierre del módulo — gate de la Etapa 1.2, `docs/estado.md` y cierre de D-11/D-15

**Files:**
- Modify: `docs/estado.md` (sección nueva del módulo caja y finanzas, con fecha de corte y evidencia comando+salida)
- Modify: `docs/deuda-tecnica.md` (D-11 y D-15 pasan a «Cerradas en Fase 1» con su evidencia)

- [ ] **Paso 1: ejecutar el gate completo del módulo** (idéntico al de cualquier módulo de la Etapa 1.2):

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
bash scripts/verify-setup.sh 2>&1 | grep -E "^\[(OK|FALLO)\]" | tail -3
# Esperado: todo [OK], con el check 23 exigiendo los once permisos
```

Gate por módulo (del plan maestro de Fase 1), a verificar ítem a ítem:
- [ ] Migración con RLS + índice + grants, revisada por el agente de seguridad.
- [ ] Tests de integración con aislamiento cross-tenant nuevo por tabla (`test_aislamiento_caja.py`: `caja_movimientos` con su policy y el `WITH CHECK`), 0 SKIPPED.
- [ ] Los candados firmados de ADR-021: el arqueo cuadra al peso con ventas, movimientos y devoluciones sembradas (`test_el_arqueo_suma_desde_las_tablas_de_origen_y_cuadra_al_peso`); el segundo INSERT de sesión abierta revienta contra el índice único y la carrera de aperturas deja una sola sesión (`test_dos_aperturas_concurrentes_dejan_una_sola_sesion`); el arqueo se congela y nada lo reabre (`test_el_arqueo_se_congela_y_nada_lo_reabre`).
- [ ] El candado firmado de ADR-023: cajero que cierra caja → 403, mismo gesto con dueño → 200 (`test_el_cajero_abre_y_mueve_caja_pero_no_cierra`), y `PERMISOS_POR_ROL ⊆ PERMISSION_CATALOG` verde.
- [ ] OpenAPI congelado actualizado + codegen + `contrato.ts` sigue compilando.
- [ ] Eventos de outbox emitidos según ADR-021 (`caja.sesion_abierta`, `caja.movimiento_registrado`, `caja.sesion_cerrada` con el resumen del arqueo, clave `<tenant_id>.<evento>`); `pytest -m integration` verde; `ruff` verde.

- [ ] **Paso 2: actualizar `docs/estado.md`.** Añadir una sección «Módulo caja y finanzas (Fase 1, Etapa 1.2)» con: fecha de corte, qué se entregó (`caja_movimientos` y los CHECK del cierre, `ventas.anulada_en`, la apertura/movimientos/cierre online, el arqueo que suma desde el origen y se congela, el esperado vivo condicionado por permiso, el cambio de `FOR UPDATE` en el sync, el P&L por período en Bogotá con fuentes declaradas, el forecast 30d con su alcance honesto, los cinco permisos y su reparto, las 8 rutas, D-11 y D-15 cerradas), y **al lado de cada afirmación el comando que la demuestra** con su salida pegada (regla del documento: no promete nada que un comando no demuestre).

- [ ] **Paso 3: cerrar D-11 y D-15 en `docs/deuda-tecnica.md`.** Mover ambas entradas a la sección «Cerradas en Fase 1», cada una con qué era, cómo se cerró y la evidencia comando+salida:

- **D-11** (`caja_sesiones` existe y se puebla sin endpoints propios): se cerró con los endpoints del módulo (apertura, sesión actual, historial, cierre con arqueo, movimientos). Evidencia: `uv run pytest tests/api/test_caja_api.py -q` → 13 passed, y las rutas `/api/v1/caja/*` en el OpenAPI congelado.
- **D-15** (`exigir_venta_anular` definido sin consumidor): se cerró BORRÁNDOLO (decisión 11 del plan: este módulo no le da uso y su vencimiento lo mandaba). Evidencia: `grep -rn "exigir_venta_anular" backend/ --include="*.py"` sin resultados y `uv run pytest -q -m integration` verde (la anulación conserva su chequeo por operación).

No tocar D-10 (vence en el módulo 5), D-13, D-16, D-17, D-18, D-19, D-20, D-21, D-22, D-23, D-24, D-25: viven sus propios vencimientos. Si el ejecutor registra deuda nueva (p. ej. lo que el QA encuentre en la superficie de abajo), que sea con el formato del registro (qué es, por qué se aceptó, riesgo, vencimiento, candados mientras tanto).

- [ ] **Paso 4: commit de cierre**

```bash
git add docs/estado.md docs/deuda-tecnica.md
git commit -m "Módulo caja y finanzas cerrado: gate de la Etapa 1.2 verificado, estado actualizado y D-11/D-15 cerradas"
```

---

## Superficie de ataque para QA — módulo caja y finanzas (sesiones, arqueo, P&L, forecast)

Para el agente de QA adversarial de la Etapa 1.4 (agente distinto del implementador; su KPI son hallazgos). Los escenarios marcados (firmado) ya tienen test que los fija: verificarlos, no «redescubrirlos»; el hallazgo sería que el test miente.

- **El arqueo (el corazón):** cuadre al peso con ventas efectivo/fiado, movimientos y devoluciones (firmado); sesión sin ventas ni movimientos (esperado == base); egresos MAYORES que base + ventas + ingresos (esperado negativo: legítimo y viaja con signo — verificar que ninguna cota lo corta y que la `diferencia = contado − esperado` resulta positiva); contado 0 con esperado positivo (faltante total: 200, diferencia negativa); una venta anulada de la PROPIA sesión abierta (efecto neto cero: no suma en completadas y NO se resta como devolución — firmado que las ajenas sí; verificar que las propias no se restan dos veces); devolución de venta FIADA anulada tras el cierre (no toca el esperado: no hubo efectivo — verificar); devolución cuya `anulada_en` cae FUERA de la ventana de la sesión abierta (antes de abrirla: no descuenta — verificar el borde exacto `>= abierta_en`); dos sesiones cerradas el mismo día Bogotá y una anulación entre ambas (cae solo en la ventana que la contiene).
- **Congelamiento y carreras:** venta insertada por SQL contra la sesión ya cerrada (columnas intactas — firmado); anulación posterior a la cerrada (ídem — firmado); **la carrera real cierre vs sync**: lote de ventas concurrente con el cierre de la misma sesión (con los dos `FOR UPDATE` se serializan: la venta cae en la sesión vieja ANTES del arqueo o en la implícita nueva, jamás en la cerrada después — intentar provocar el caso y medir; es el escenario que justifica la decisión 5); dos cierres concurrentes de la misma sesión (el perdedor ve `cerrada`: mismo conteo → lo congelado, otro conteo → 409 — nunca doble evento `caja.sesion_cerrada`); cierre concurrente con un movimiento manual (el movimiento confirma antes o revienta después con `caja_sin_sesion_abierta`... o queda insertado contra la sesión cerrada si resolvió antes: ¿es alcanzable? `registrar_movimiento` lee la sesión abierta SIN bloqueo — si lo es, registrar deuda con vencimiento piloto, NO arreglar en este módulo).
- **Apertura:** dos aperturas concurrentes (una 201, otra 409 — firmado); apertura con el `id` de una sesión CERRADA propia (409 `sesion_id_duplicado`... ¿o la devuelve? verificar el comportamiento y fijarlo: el `id` ya existe, no es reintento de apertura); apertura con `id` de sesión de OTRO negocio (409 tipado, sin fuga — mismo criterio que D-24); apertura explícita sobre una sesión IMPLÍCITA del sync (409 `caja_ya_abierta` con la sesión vigente — firmado como decisión 10: no hay camino para «poner la base»; documentar que el arqueo cuadra con base 0 y el conteo lo explica).
- **El sync y la sesión:** venta que sincroniza tras el cierre (cae en implícita nueva, base 0 — firmado); lote de 200 ventas con el `FOR UPDATE` nuevo (¿regresión de latencia? medir, no adivinar); dos dispositivos sincronizando concurrentemente tras el cierre (UNA implícita nueva, no dos — el índice decide).
- **Aislamiento:** movimiento/sesión/reporte del vecino (404, listas vacías, SUM en 0 — firmado para sesiones y P&L; verificar forecast); `tenant_id` inyectado en las tres entradas (422 por `extra="forbid"` — firmado); un `caja.sesion_cerrada` de T1 nunca sale con routing key de T2 (verificar con el payload).
- **Validación y bordes:** `base_inicial`/`contado`/`monto` en 2^31 (422 — firmado); `contado` negativo (422 — firmado); `monto` 0 y negativo (422 — firmado); motivo de puros espacios, de 2 letras, de 301 caracteres (422 — firmado el primero); categoría inventada (422 — firmado); movimiento con HTML/emoji en el motivo (viaja como texto en JSON — el XSS es asunto del render del frontend); `fecha` del P&L en formato inválido (422 — firmado) y en 1970/2100 (200 con todo en 0: es una ventana vacía, no un error).
- **Permisos:** cajero en las 8 rutas (201 en abrir/movimientos/actual/movimientos-lista; 403 en cerrar, historial, P&L, forecast — firmado); almacenista (403 en todo — firmado); el esperado vivo en `null` para el cajero y en número para el dueño (firmado); un token con `caja:leer` pero sin `caja:abrir` (rol editado a mano en Keycloak) lee pero no abre — los guards son por permiso, no por rol; negocio suspendido a media sesión (403 `tenant_suspendido` en el siguiente request).
- **P&L y forecast:** venta a las 8:30pm Colombia (cuenta en su día Bogotá — firmado); semana que cruza de mes (ventana [lunes, lunes) sin importar el mes — verificar); mes de febrero (la aritmética `replace(day=28) + 7 días → día 1` no se desborda — verificar febrero y diciembre); producto sin compras (`ultimo_costo` NULL → costo 0 declarado por el `coalesce` — verificar que no revienta y que el margen sale del 100%: es D-25 aplicada al P&L, comportamiento ya registrado); producto dado de baja tras venderse (sigue en el JOIN: el costo usa su fila — verificar); forecast sin sesión abierta (saldo 0 declarado — firmado); tienda con 1 día de datos (la proyección usa el total, no lo multiplica por 30 — firmado con `dias_con_datos`); P&L de un período con ventas pero sin ítems (venta sembrada sin líneas: el JOIN la deja fuera del costo, no del total — las ventas reales siempre traen ítems; documentar).
- **Eventos:** `caja.sesion_cerrada` lleva el resumen completo del arqueo (firmado); rollback a mitad de cierre (provocar fallo tras el UPDATE: ni sesión cerrada, ni evento — la garantía outbox); el reintento del cierre NO re-emite (firmado implícito: la sesión ya está cerrada — verificar contando mensajes); `caja.movimiento_registrado` sin PII (payload: ids, tipo, categoría, monto — el motivo NO viaja: verificar y fijar).
- **Overflow del arqueo:** esperado o diferencia por encima de 2^31−1 (422 `total_fuera_de_rango` tipado, nunca el 500 del `DataError` — inalcanzable con montos reales de tienda; si se quiere el camino, sembrar `base_inicial` en el tope y sumar ventas al tope).

---

## Self-Review

- **Cobertura del spec:** ADR-021 (una sesión abierta por tienda por índice único parcial —ya existente—, `caja_movimientos` con tipo/categoría/motivo/sesión, arqueo que suma desde las tablas de origen sin duplicar, congelamiento al cierre, anulaciones que caen en la sesión abierta, centavos enteros, día en `America/Bogota`, eventos `caja.sesion_abierta`/`caja.movimiento_registrado`/`caja.sesion_cerrada` con resumen, candados de cross-tenant/arqueo-al-peso/índice único) → Tareas 1, 2, 5, 6, 8 + decisiones 1-7. ADR-006 (P&L simple de lo que ya se registra, forecast 30d, pantalla que declara sus fuentes) → Tarea 7 + decisiones 8-9. ADR-023 (los cuatro permisos de caja + `reporte:leer`, reparto exacto cajero/almacenista/dueño, candado de autorización por gesto con dinero, extensión del check 23) → Tareas 4, 8, 9 + decisión 12. ADR-018 (sesión implícita intacta, `recibida_en` como verdad temporal del P&L) → Tareas 6, 7 + decisión 10. ADR-020 (`ultimo_costo` como fuente del costo) → Tarea 7 + decisión 8. ADR-022 (abonos y cobros como 0 declarado con punto de cambio único) → Tareas 5, 7 + decisión 3. Deuda D-11 → Tarea 8 + cierre en Tarea 11; D-15 → Tarea 9 + cierre en Tarea 11. Lecciones de los módulos 1-3 (cotas `le=`, overflow tipado `total_fuera_de_rango`, validadores sin asunción de `str`, FOR UPDATE en read-modify-write, traducción de IntegrityError, salidas condicionadas por permiso, idempotencia no ciega a la divergencia) → Global Constraints, Tareas 1, 3, 5, 6. Items del encargo 1-6 → Tareas 1-11.
- **Placeholders:** ninguno. Todo paso lleva código completo, comando exacto y salida esperada. Los conteos de tests son los escritos (9 aislamiento, 6 modelos, 10 schemas, 17 servicio de caja tras la Tarea 6, 7 reportes, 13 API); si el ejecutor añade casos, ajusta el número (los comandos de gate son de suite, no de conteo).
- **Consistencia de tipos/contratos:** nombres de tablas, columnas, índices y CHECK coinciden entre migración (Tarea 1), modelos (Tarea 2), tests de metadata y schemas (Tarea 3); los `code` de error coinciden entre servicio, tests de servicio, tests de API y la tabla de `docs/api/README.md` (`caja_ya_abierta`, `caja_sin_sesion_abierta`, `caja_sesion_no_encontrada`, `caja_ya_cerrada`, `sesion_id_duplicado`, `movimiento_id_divergente`, `total_fuera_de_rango`); el esperado lo calcula una sola función (`calcular_desglose`) usada por cierre, sesión actual y forecast; las listas cerradas (`ingreso`/`egreso`, cuatro categorías) tienen una sola definición (modelo) reusada por schema y migración; los eventos usan la firma real de `DomainEventService.emit`; los schemas reusan `TOPE_PRECIO`/`_limpiar_texto` del catálogo; el refactor de ventas conserva las firmas de `_resolver_sesion_caja` y `_anular_venta`.
- **Riesgos conocidos y declarados:** (1) `registrar_movimiento` lee la sesión abierta SIN `FOR UPDATE`: una carrera cierre-vs-movimiento podría insertar el movimiento contra la sesión ya cerrada (se sumó antes del cierre en la cuenta pero confirma después) — ventana estrecha, queda en la superficie de QA para medir y, de ser alcanzable, en deuda con vencimiento piloto; (2) el `FOR UPDATE` nuevo del sync serializa los lotes concurrentes del tenant en la fila de la sesión: despreciable a la escala de una tienda, medido en QA; (3) las anulaciones pre-módulo quedan con `anulada_en NULL` y fuera de toda devolución — no existe operación real pre-piloto, declarado en la migración; (4) `venta.anulada_en` usa `datetime.now(UTC)` de la app y no `now()` de Postgres (precedente: `dispositivo.ultima_sync`): dos nodos con reloj desviado moverían el borde de la ventana de devoluciones — un solo nodo de API en el MVP; (5) el P&L costea con el `ultimo_costo` actual (decisión 8): una compra posterior cambia retroactivamente el costo de ventas anteriores — aproximación honesta y declarada, la alternativa es un libro de costos que el MVP no tiene; (6) un `IntegrityError` de FK (`caja_movimientos_sesion_caja_id_fkey`, carrera con un borrado físico que hoy no existe) saldría como 500: inalcanzable con RESTRICT y sin borrado de sesiones, mismo criterio que ventas; (7) ponerle base a una sesión implícita ya abierta no tiene camino en el MVP (decisión 10): el arqueo cuadra con base 0 y el conteo lo explica — si el piloto lo pide, vendrá con su decisión.
