# Módulo inventario: alertas de stock, compras y ajustes (Fase 1, Etapa 1.2, módulo 3) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar el tercer módulo de negocio del MVP —el inventario de ADR-020 completo— con: la migración `0007_inventario` (tablas `compras`, `compra_items` y `ajustes_inventario`, todas con RLS + índices + grants; `movimientos_inventario` NO se toca porque su CHECK ya admite `compra`/`ajuste`/`merma` desde la 0005), los permisos `inventario:ajustar` y `compra:crear` repartidos según ADR-023 (dueño todo, almacenista ambos, cajero NADA), las alertas de tres niveles (agotado/crítico/bajo derivados de `stock_minimo`) con el evento `inventario.alerta_stock` emitido SOLO al cruzar un nivel hacia abajo, evaluado en el punto único por el que TODO movimiento se aplica (`inventario/stock.py`, usado también por el servicio de ventas refactorizado), las compras simples (`proveedor_nombre` texto libre, sin tabla proveedores) que en una sola transacción insertan movimientos tipo `compra`, actualizan la proyección `stock_actual` y `ultimo_costo` y emiten `compra.registrada`, los ajustes ONLINE (única operación de inventario que exige conexión, ADR-020) por conteo y las mermas, con motivo obligatorio e idempotencia por UUID de cliente, los endpoints REST puros (NADA entra al lote del sync), el estado de stock con su nivel derivado para lectura, el cierre de la deuda D-14 (`OperacionSync.datos` requerido) y D-12 (alertas), el contrato OpenAPI regenerado con su cliente TS, y el gate de módulo de la Etapa 1.2.

**Architecture:** Se mantiene la arquitectura firmada: monolito modular FastAPI (`backend/services/api`) sobre `vendi-core`, RLS en schema único con los roles `vendi_app` (sin `BYPASSRLS`) y `vendi_platform` (con `BYPASSRLS`, owner, corre las migraciones). El módulo nuevo vive en `app/modules/inventario/`. Todo corre sobre la **sesión de tenant** (`sesion_de_tenant`, GUC `vendi.tenant_id`): ningún handler recibe `tenant_id` por URL, cuerpo o cabecera, y la policy `tenant_isolation` con su `WITH CHECK` hace el aislamiento. El inventario es un libro inmutable (`movimientos_inventario`, ya creada en la 0005) más una proyección (`stock_actual` en `productos`), actualizados en la misma transacción con la fila del producto bloqueada `FOR UPDATE`; el stock negativo es legítimo. Compras y ajustes son endpoints REST online clásicos (decisión 3): NO son tipos de operación del lote de sync. Las alertas se derivan comparando el nivel antes/después dentro del bloqueo de fila (decisión 2): no hay columna de nivel que mantener.

**Tech Stack:** Python 3.12 · FastAPI 0.139 · SQLAlchemy 2.0 async (asyncpg) · Alembic · PostgreSQL 17 RLS · Pydantic v2 · pytest + pytest-asyncio · ruff · uv · openapi-typescript (codegen).

**Spec fuente:**
- `docs/adr/adr-020-inventario-y-compras.md` (EL diseño firmado: libro inmutable, proyección, idempotencia por constraint, stock negativo, ajustes online, alertas de 3 niveles con evento solo al cruzar, compras simples sin proveedores)
- `docs/adr/adr-023-multi-empleado-permisos.md` (`inventario:ajustar`, `compra:crear`; reparto dueño/almacenista/cajero; catálogo de 14 permisos cerrado; extensión del check 23)
- `docs/adr/adr-017-sincronizacion-offline-first.md` (qué viaja por el sync y qué no; ids de cliente; eventos una sola vez por operación aceptada)
- `docs/adr/adr-018-modelo-de-ventas-offline.md` (referencia: centavos enteros; los movimientos de venta ya existen)
- `docs/adr/adr-006-finanzas-simples.md` (referencia: el P&L costea con `ultimo_costo` y consume `compra.registrada`)
- `docs/deuda-tecnica.md` (D-12 se cierra aquí; D-14 se cierra aquí; D-10/D-11/D-15/D-16/D-17/D-18 NO son de este módulo)
- Plantillas a imitar: `backend/services/api/alembic/versions/20260728_0005_ventas.py` y `20260727_0006_movimientos_tipo_anulacion.py` (cómo se recrea —o no— un CHECK), `backend/services/api/app/modules/ventas/` (service con `_mover_stock` y su FOR UPDATE, router, dependencies, schemas) y `backend/services/api/app/modules/catalogo/` (idempotencia REST por UUID de cliente, `_flush_traduciendo_integridad`), `backend/tests/test_aislamiento_ventas.py`, `backend/tests/test_ventas_servicio.py`, `backend/tests/api/test_ventas_sync.py`.

## Global Constraints

- Todo artefacto en español riguroso (código, docstrings, commits, mensajes de error). Sin tildes ni eñes en identificadores técnicos que viajen en tokens, URLs o JSON.
- Toda tabla nueva de dominio lleva `tenant_id` + policy RLS vía `enable_rls(op, ...)` + índice que empieza por `tenant_id`, verificada por test de aislamiento cross-tenant contra PostgreSQL real. Los tests de integración **fallan, no se omiten**, si falta el servicio (0 SKIPPED).
- El candado invertido `backend/tests/test_privilegios_de_vendi_app.py` exige EXACTAMENTE `{SELECT, INSERT, UPDATE, DELETE}` para toda tabla de negocio: las tres tablas nuevas heredan los grants por defecto y el candado pasa sin edición (mismo criterio que las cinco de ventas, decisión 11 de ese plan).
- TDD en cada tarea: primero el test que falla (con la salida del fallo esperada), luego la implementación completa, luego el test en verde, luego el commit. Prohibido «similar a», «agregar validación», TODO o código elidido.
- Los errores de la API usan el sobre `{"success": false, "message": "...", "code": "..."}` (`vendi_core.errors.domain` + `ErrorHandlerMiddleware`). Nada de `HTTPException` con `{"detail": ...}` ni de 500 no tipados: TODO `IntegrityError` esperable se traduce a un error de dominio.
- **Lecciones de los QA adversariales de catálogo y ventas, aplicadas desde el diseño:** (1) cota `le=` contra el tipo de columna en TODO número de entrada — un overflow de `Integer`/`Numeric(14,3)` es un `DataError` → 500, no un 422; (2) las cantidades se CUANTIZAN a los 3 decimales de la columna con `ROUND_HALF_UP` al validar, porque Postgres redondea en silencio lo que no cabe (BUG-2 del QA de ventas); (3) ningún validador `mode="before"` asume `str` — lo que no es `str` pasa intacto para que pydantic lo rechace; (4) todo read-modify-write de `stock_actual` va con `SELECT ... FOR UPDATE` sobre la fila del producto (el lost update multi-caja que el fix `49553da` cerró en ventas); (5) la idempotencia NO es ciega a la divergencia de payload donde hay stock de por medio.
- Dinero SIEMPRE en centavos enteros (`costo_unitario_centavos`, `total_centavos`); cantidades en `Decimal` (`Numeric(14,3)`), nunca flotante.
- El libro `movimientos_inventario` es inmutable: un error se corrige con OTRO movimiento (un ajuste), nunca editando ni borrando filas. No hay UPDATE ni DELETE de compras en el MVP: la corrección de una compra mal registrada es un ajuste.
- El reloj del cliente es dato, no árbitro: `fecha` de la compra es el dato de la factura; el orden temporal real lo dan las marcas del servidor (`created_at`).
- Los commits son por tarea, mensajes en español estilo oración. Nunca `git push` sin confirmación humana.
- Un ADR no se edita para cambiar de opinión: lo que este plan decide más allá de los ADRs queda listado en la sección siguiente, con su justificación.

## Decisiones de diseño tomadas en este plan (más allá de los ADRs)

1. **La lógica de aplicar movimientos y evaluar alertas vive en UN solo sitio: `app/modules/inventario/stock.py`, y el servicio de ventas se refactoriza para usarlo.** Hoy hay dos caminos que mutan `stock_actual` (`_registrar_venta` y `_anular_venta`, ambos vía `VentasService._mover_stock`); este módulo añade tres más (compra, ajuste, merma). ADR-020 firma «al aplicar un movimiento se compara el nivel antes y después»: con cinco puntos de aplicación, la evaluación del cruce en cada uno serían cinco copias del mismo `if` esperando a que alguien olvide una. El punto único —`aplicar_movimiento(session, ...)`: inserta la fila del libro, actualiza la proyección y emite `inventario.alerta_stock` si el nivel empeoró— hace estructuralmente imposible mover stock sin evaluar la alerta. `VentasService._mover_stock` conserva su firma y delega. La dirección del import es `ventas.service → inventario.stock → ventas.models` (el modelo `MovimientoInventario` se queda en `ventas/models.py`, donde nació en el módulo 2; moverlo sería churn sin beneficio, y `ventas.models` no importa nada de inventario: no hay ciclo).
2. **El nivel anterior NO se persiste: se deriva dentro del bloqueo `FOR UPDATE`.** La emisión «solo al cruzar hacia abajo» exige conocer el nivel antes del movimiento, y la tentación es una columna `nivel_anterior` en `productos`. Se descarta por tres razones: (a) la fila del producto ya está bloqueada `FOR UPDATE` en el momento de aplicar el movimiento, así que `stock_actual` antes del delta ES el estado exacto post-commit del anterior — la comparación es una función pura de dos columnas de la misma fila, y persistir su resultado es estado redundante que puede derivar; (b) una columna de nivel quedaría stale cuando el tendero EDITA `stock_minimo` (el nivel cambia sin movimiento de por medio): con la derivación, el siguiente movimiento compara contra el mínimo vigente y `GET /inventario/stock` muestra el nivel correcto siempre; (c) el anti-spam es una invariante transaccional (quien aplica, compara bajo llave), no un dato histórico que consultar. Caso borde declarado: subir `stock_minimo` de 0 a 10 con stock 5 NO emite alerta por sí solo (las alertas se emiten al aplicar movimientos, ADR-020 literal); el nivel `bajo` es visible de inmediato en el endpoint de estado de stock, que es donde la app lo muestra.
3. **Compras y ajustes son endpoints REST clásicos del módulo `api`; el contrato del sync queda CERRADO (no se añaden tipos de operación al lote).** Cuatro razones: (a) el ajuste es online-obligatorio por ADR-020 firmado — su delta se calcula contra el stock del servidor en el momento del conteo, y un ajuste offline corrompería el contador de forma no conmutativa; declararlo tipo de sync sería declarar algo que el propio diseño prohíbe; (b) el guard de entrada del lote es `venta:crear` (el permiso del CAJERO): abrir el lote a compras y ajustes obligaría a chequeos de permiso por operación para operaciones que el cajero jamás debe poder encolar — superficie de ataque creada por gusto; (c) la semántica de respuesta del lote (`aceptada`/`duplicada`/`rechazada` por operación) existe para una cola de dispositivo que drena tarde; una compra o un ajuste son gestos síncronos del usuario, donde un 201/409/422 HTTP es más rico y más simple; (d) el cliente POS nunca encola estas operaciones: si llega un lote con `tipo: "inventario.ajustar"` es `rechazada` con `tipo_desconocido` — hay test que lo fija. La compra tampoco necesita offline: registrar una factura es un gesto de una vez, con red, del dueño o el almacenista (su suma al stock es conmutativa, pero su actor y su momento no son los del cobro).
4. **La idempotencia REST es por UUID de cliente, como el catálogo — con una asimetría deliberada: el `id` del ajuste es REQUERIDO y el de la compra opcional.** La compra sigue el patrón `ProductoCrear`/`DispositivoRegistrar` (id del cliente aceptado como PK; reenvío idéntico devuelve la existente). El ajuste exige `id` porque la MERMA es un delta RELATIVO: un reintento sin ancla la descontaría dos veces y corrompería el stock sin que ninguna constraint lo impida (dos movimientos con `referencia_id` distinta son legítimos). Con el `id` como PK de `ajustes_inventario`, la fila es la prueba (ADR-017) y el reintento es un no-op. El ajuste por conteo es idempotente «de gratis» (delta 0 la segunda vez) solo si el stock no se movió entre medias — y como sí puede moverse (ventas sincronizando), la ancla es obligatoria para los dos tipos por simetría y seguridad. El frontend ya genera UUIDs para todo (ventas, productos, dispositivos): el coste es cero.
5. **Hay tabla `ajustes_inventario` (el ADR no la lista) y NO hay columna `nota` en `movimientos_inventario`.** ADR-020 lista como tablas nuevas `movimientos_inventario`, `compras` y `compra_items`, y describe el ajuste como un movimiento más. La desviación se justifica por un agujero concreto que la opción «columna nota + movimiento» no puede cerrar: un ajuste por conteo cuyo delta es CERO no puede escribir movimiento (`ck_movimientos_cantidad_no_cero`), así que no deja rastro de su `referencia_id` — y un reintento tardío del mismo `id` (con el stock ya movido por ventas) se aplicaría como ajuste NUEVO con el conteo viejo: corrupción silenciosa. Con la tabla, la fila del ajuste ES la prueba de idempotencia aunque no haya movimiento, guarda el `motivo` (justificación obligatoria) sin ensuciar el libro con una columna que el 95% de las filas (ventas, compras, anulaciones) dejaría NULL, almacena `stock_resultante` para responder al reintento exactamente lo que se respondió la primera vez, y hace el listado de ajustes una consulta directa en vez de un barrido del libro. El movimiento (cuando delta ≠ 0) referencia `ajustes_inventario.id`, así que la auditoría «¿por qué cambió el stock?» va del libro al ajuste y de ahí al motivo. Es la misma filosofía «la fila es la prueba» de ADR-017, y la desviación queda registrada aquí porque los ADRs no se editan.
6. **`movimientos_inventario` NO se migra: ni CHECK nuevo, ni índice nuevo, ni columna.** La 0005 creó `ck_movimientos_tipo` ya con `('venta', 'compra', 'ajuste', 'merma')` (decisión 1 del plan de ventas: «para que el módulo 3 no migre nada») y la 0006 solo añadió `'anulacion'`. El índice único `(tenant_id, tipo, referencia_id, producto_id)` ya deduplica los movimientos de compra (referencia = `compra.id`) y de ajuste/merma (referencia = `ajuste.id`). Hay test que lo demuestra insertando los tres tipos contra la base migrada (Tarea 1), para que «ya lo admite» sea un hecho verificado y no una creencia.
7. **El total de la compra lo calcula el servidor, por línea, en centavos enteros.** `total_centavos = Σ cuantizar_a_entero(cantidad × costo_unitario_centavos)` con `ROUND_HALF_UP` por línea. El cliente NO envía total: no hay divergencia que detectar, y el P&L (ADR-006) suma la verdad del servidor. El redondeo por línea (no sobre la suma) hace que el total sea exactamente la suma de lo que cada línea costó, que es lo que cuadra contra la factura de papel. Las cantidades de granel con costo entero casi siempre dan entero exacto (`0.350 kg × $2.500 = 875`); cuando no (`0.333 × 100 = 33.3`), la línea redondea a 33 y el total es la suma de las líneas redondeadas — documentado, no silencioso.
8. **Un producto repetido en dos líneas de la misma compra es 422, no consolidación silenciosa.** `ux_movimientos_origen` es por `(tipo, referencia_id=compra.id, producto_id)`: dos líneas del mismo producto chocarían entre sí (el BUG-1 del QA de ventas). En ventas se consolidó porque el ticket offline es un hecho que hay que aceptar tal cual; una compra es un formulario síncrono — la UI puede sumar las líneas antes de enviar, y si no lo hace, el 422 con mensaje claro («súmalas en una sola») es mejor que elegir en silencio qué `costo_unitario` gana para `ultimo_costo`. Lo valida un `model_validator` del schema.
9. **Los ítems de la compra se bloquean en orden de `producto_id` (anti-deadlock).** Cada ítem hace `SELECT ... FOR UPDATE` de su producto; dos compras concurrentes con productos solapados en orden distinto se interbloquearían (deadlock → 500 no tipado). Ordenar los ítems por `producto_id` antes de bloquear serializa el orden de adquisición y lo hace imposible. Es gratis y es la misma disciplina que exige el FOR UPDATE. (La venta del sync hereda el riesgo teórico en el orden del ticket del cliente; queda anotado en la superficie de QA para que se mida, no se arregla aquí — no es de este módulo.)
10. **No se inventan permisos de lectura: el catálogo de ADR-023 es cerrado.** Los 14 permisos firmados no incluyen `inventario:leer` ni `compra:leer`, y ADR-023 dice que el catálogo «se amplía solo con ADR nuevo». Reparto de las lecturas con lo que existe: `GET /inventario/stock` (niveles de stock) con `producto:leer` — los tres roles lo tienen y el cajero ya ve el stock en el POS vía delta; `GET /compras*` con `compra:crear` — los costos son el margen del negocio y el cajero NO debe verlos; dueño y almacenista, que son quienes compran, son quienes consultan; `GET /inventario/ajustes` con `inventario:ajustar` — quien ajusta audita sus ajustes. El cajero recibe 403 `permiso_ausente` en todo lo de compras y ajustes, que es la respuesta correcta y esperada (ADR-023).
11. **D-14 se cierra aquí: `OperacionSync.datos` pasa de `Field(default_factory=dict)` a requerido.** La deuda vence «Fase 1 (módulo 3)» y su propia nota dice «cuando el sync gane tipos de operación nuevos y el contrato se revise». Este módulo NO añade tipos al sync (decisión 3), pero sí revisa el contrato (se regenera el OpenAPI de todas formas) y el arreglo es de una línea con beneficio inmediato: una operación sin `datos` deja de llegar al servicio como `{}` para salir `rechazada`, y pasa a ser un 422 de pydantic — la señal más temprana posible, que es exactamente lo que la deuda pedía. El comportamiento para `datos` presentes pero inválidos no cambia (sigue siendo `rechazada` por operación, con su candado). Se verificó que ningún test vigente construye operaciones sin `datos` (la construcción de pruebas pasa siempre `datos` con contenido); el plan añade el test del 422.
12. **La alerta se emite también desde las ventas, y los tests de ventas que lo notan se actualizan — no se esquiva.** Con el punto único (decisión 1), una venta que cruza un umbral emite `inventario.alerta_stock` además de `venta.creada`. Los conteos de eventos de la suite de ventas filtran por routing key (`%.venta.creada`), así que no se contaminan; lo que SÍ hay que tocar: (a) las tuplas `BORRADO` de `test_ventas_servicio.py` y `test_sync_idempotente.py`, que limpian el outbox con `LIKE '%.venta.%'` y dejarían escapar filas `%.inventario.%` entre tests (suite no re-entrante: la siguiente corrida encontraría alertas viejas); (b) `test_el_stock_puede_quedar_negativo_y_la_venta_se_acepta`, que ahora además DEMUESTRA la alerta de agotado — se refuerza el assert en vez de dejarlo pasar de lado. Es el pago natural de D-12: el negativo ya no solo es visible, notifica.
13. **El evento `inventario.alerta_stock` lleva el mínimo payload y `resource_type="producto"`.** `data = {producto_id, nivel, stock_actual, stock_minimo}` — nada de PII, como pide el checklist de seguridad que ADR-020 cita. El recurso es el producto (no el movimiento ni la venta): el consumidor es el módulo de notificaciones (ADR-025), que lo traduce a push, y lo que necesita es «qué producto, qué tan grave». Los movimientos de venta siguen sin evento propio (ADR-020 lo firma: duplicarlo inflaría el outbox) — la alerta no es el evento del movimiento, es el evento del cruce de umbral, y solo existe cuando hay cruce.
14. **Anti-duplicado de la alerta por construcción, en tres capas.** (a) La emisión vive dentro de `aplicar_movimiento`, después de insertar el movimiento: los caminos `duplicada`/`rechazada` del sync y los retornos idempotentes de REST NUNCA llegan a aplicar un movimiento, así que nunca llegan a la emisión. (b) La comparación antes/después bajo `FOR UPDATE` hace que N movimientos por debajo del mismo umbral emitan exactamente UN evento por cruce (el segundo movimiento lee el nivel ya empeorado como su «antes»). (c) El evento viaja en la misma transacción que el movimiento: un rollback se lleva los dos. Un reintento de compra (mismo `id`) devuelve la existente sin tocar stock; un reintento de ajuste igual; una venta re-sincronizada es `duplicada` antes de mover nada. No hace falta deduplicar el evento por separado: no hay camino que lo emita dos veces sin aplicar dos veces, y aplicar dos veces es lo que las constraints ya hacen imposible.
15. **Se regenera `docs/api/openapi-fase0.json`; NO se crea un congelado nuevo** (misma decisión de los módulos 1 y 2: fuente única del codegen y del job `frontend-contratos`). Se actualiza `docs/api/README.md` con las 6 rutas y los `code` nuevos.

---

## Tarea 1: Migración `0007_inventario` — `compras`, `compra_items`, `ajustes_inventario`

**Files:**
- Create: `backend/tests/test_aislamiento_inventario.py` (primero: el test que falla)
- Create: `backend/services/api/alembic/versions/20260728_0007_inventario.py`

**Interfaces:**
- Consume: `vendi_core.db.rls.enable_rls` / `disable_rls`, fixtures `pg_app_url` / `pg_platform_url` y datos `T1`/`T2` de `backend/tests/datos_de_prueba.py`.
- Produce: las tres tablas migradas, cada una con policy `tenant_isolation` e índice que empieza por `tenant_id`, checks, FKs con `RESTRICT`, y grants por defecto (los cuatro) para `vendi_app` — el candado invertido pasa sin edición. `movimientos_inventario` queda intacta (decisión 6) y hay test que lo demuestra.

- [ ] **Paso 1: escribir el test de aislamiento que falla.** Crear `backend/tests/test_aislamiento_inventario.py`:

```python
"""Aislamiento cross-tenant y reglas duras de las tablas del módulo inventario.

Hermano de `test_aislamiento_ventas.py`, mismo criterio: SQL crudo con el rol
`vendi_app` y nada de ORM, para que ningún `WHERE` amable del ORM dé un falso
verde sobre una policy que no filtra. Las tablas las crea la migración
`0007_inventario`; hasta que existe, TODOS estos tests fallan — que es el
punto del paso TDD.

Además del aislamiento, este archivo fija la decisión 6 del plan: el CHECK
de tipos de `movimientos_inventario` YA admite `compra`, `ajuste` y `merma`
desde la migración 0005 (la 0006 añadió `anulacion`), así que la 0007 no la
toca — y aquí se demuestra insertando los tres tipos de verdad.
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
    "DELETE FROM compra_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compras WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ajustes_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
)


@pytest_asyncio.fixture
async def semilla_de_los_dos_tenants(pg_platform_url: str):
    """Un producto, una compra con su ítem y un ajuste POR NEGOCIO, más tres
    movimientos del libro (compra, ajuste, merma) en T1 — la prueba de que el
    CHECK de tipos ya los admite. Limpia antes y después: la suite es
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
            compra = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO compras (id, tenant_id, proveedor_nombre, total_centavos) "
                     "VALUES (:c, :t, 'Distribuidora La 33', 25000)"),
                {"c": compra, "t": tenant},
            )
            await conn.execute(
                text("INSERT INTO compra_items (tenant_id, compra_id, producto_id, cantidad, "
                     "costo_unitario_centavos) VALUES (:t, :c, :p, 10, 2500)"),
                {"t": tenant, "c": compra, "p": producto},
            )
            ajuste = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO ajustes_inventario (id, tenant_id, producto_id, tipo, "
                    "stock_contado, delta, motivo, aplicado_por, stock_resultante) "
                    "VALUES (:a, :t, :p, 'ajuste', 8, -2, 'Conteo de cierre', 'dueno', 8)"
                ),
                {"a": ajuste, "t": tenant, "p": producto},
            )
            ids[nombre] = {"producto": producto, "compra": compra, "ajuste": ajuste}
        # Los tres tipos del libro que este módulo estrena (decisión 6: el
        # CHECK ya los admite; si no, estos INSERT revientan aquí).
        await conn.execute(
            text("INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                 "producto_id) VALUES (:t, 'compra', 10, :r, :p)"),
            {"t": T1, "r": ids["T1"]["compra"], "p": ids["T1"]["producto"]},
        )
        await conn.execute(
            text("INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                 "producto_id) VALUES (:t, 'ajuste', -2, :r, :p)"),
            {"t": T1, "r": ids["T1"]["ajuste"], "p": ids["T1"]["producto"]},
        )
        await conn.execute(
            text("INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                 "producto_id) VALUES (:t, 'merma', -1, :r, :p)"),
            {"t": T1, "r": uuid.uuid4(), "p": ids["T1"]["producto"]},
        )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def sesion_t1(pg_app_url: str, semilla_de_los_dos_tenants):
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
@pytest.mark.parametrize("tabla", ["compras", "compra_items", "ajustes_inventario"])
async def test_select_solo_ve_las_filas_del_propio_tenant(sesion_t1, tabla):
    filas = (await sesion_t1.execute(text(f"SELECT tenant_id FROM {tabla}"))).all()
    assert len(filas) == 1
    assert filas[0][0] == T1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sentencia",
    [
        "INSERT INTO compras (tenant_id, proveedor_nombre, total_centavos) "
        "VALUES (:t, 'Proveedor X', 100)",
        "INSERT INTO ajustes_inventario (tenant_id, producto_id, tipo, stock_contado, delta, "
        "motivo, aplicado_por, stock_resultante) "
        "VALUES (:t, :p, 'ajuste', 1, 1, 'x', 'dueno', 1)",
    ],
)
async def test_insert_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1, semilla_de_los_dos_tenants, sentencia):
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(text(sentencia), {"t": T2, "p": semilla_de_los_dos_tenants["T1"]["producto"]})
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_movimiento_de_una_compra_no_se_puede_aplicar_dos_veces(sesion_t1, semilla_de_los_dos_tenants):
    """La red de idempotencia de ADR-020 también cubre las compras: el
    reintento del mismo movimiento de entrada choca contra
    `ux_movimientos_origen` — la base lo hace imposible, no el código."""
    ids = semilla_de_los_dos_tenants["T1"]
    with pytest.raises(IntegrityError, match="ux_movimientos_origen"):
        await sesion_t1.execute(
            text("INSERT INTO movimientos_inventario (tenant_id, tipo, cantidad, referencia_id, "
                 "producto_id) VALUES (:t, 'compra', 10, :r, :p)"),
            {"t": T1, "r": ids["compra"], "p": ids["producto"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_check_de_tipos_ya_admite_compra_ajuste_y_merma_sin_migrarla(sesion_t1):
    """Decisión 6: la 0005 dejó el CHECK con los cinco tipos y la 0007 no lo
    recrea. El fixture ya insertó los tres tipos nuevos en T1; si la
    constraint no los admitiera, este test ni siquiera arrancaría."""
    tipos = (
        await sesion_t1.execute(
            text("SELECT DISTINCT tipo FROM movimientos_inventario WHERE tipo IN ('compra', 'ajuste', 'merma')")
        )
    ).scalars().all()
    assert sorted(tipos) == ["ajuste", "compra", "merma"]


@pytest.mark.asyncio
async def test_un_ajuste_con_la_forma_equivocada_no_cabe(sesion_t1, semilla_de_los_dos_tenants):
    """`ck_ajustes_forma`: tipo 'ajuste' exige `stock_contado` y prohíbe
    `cantidad`; tipo 'merma', al revés. La forma la hace cumplir la base."""
    ids = semilla_de_los_dos_tenants["T1"]
    with pytest.raises(IntegrityError, match="ck_ajustes_forma"):
        await sesion_t1.execute(
            text(
                "INSERT INTO ajustes_inventario (tenant_id, producto_id, tipo, cantidad, delta, "
                "motivo, aplicado_por, stock_resultante) "
                "VALUES (:t, :p, 'ajuste', 2, -2, 'forma rota', 'dueno', 8)"
            ),
            {"t": T1, "p": ids["producto"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_una_merma_de_cantidad_cero_no_cabe(sesion_t1, semilla_de_los_dos_tenants):
    ids = semilla_de_los_dos_tenants["T1"]
    with pytest.raises(IntegrityError, match="ck_ajustes_cantidad_positiva"):
        await sesion_t1.execute(
            text(
                "INSERT INTO ajustes_inventario (tenant_id, producto_id, tipo, cantidad, delta, "
                "motivo, aplicado_por, stock_resultante) "
                "VALUES (:t, :p, 'merma', 0, 0, 'nada se dañó', 'dueno', 10)"
            ),
            {"t": T1, "p": ids["producto"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_un_ajuste_de_delta_cero_si_cabe(sesion_t1, semilla_de_los_dos_tenants):
    """El conteo que CUADRA es legítimo y frecuente: `delta` admite 0 (la
    fila del ajuste es la prueba de idempotencia aunque no haya movimiento,
    decisión 5). Lo que no admite cero es el libro (`ck_movimientos_cantidad_no_cero`)."""
    ids = semilla_de_los_dos_tenants["T1"]
    await sesion_t1.execute(
        text(
            "INSERT INTO ajustes_inventario (tenant_id, producto_id, tipo, stock_contado, delta, "
            "motivo, aplicado_por, stock_resultante) "
            "VALUES (:t, :p, 'ajuste', 10, 0, 'Cuadró el conteo', 'dueno', 10)"
        ),
        {"t": T1, "p": ids["producto"]},
    )
    await sesion_t1.rollback()
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_aislamiento_inventario.py -q
```

Esperado: 10 errores/fallos con `relation "compras" does not exist` (o `ajustes_inventario`, según el orden de resolución de fixtures).

- [ ] **Paso 2: escribir la migración.** Crear `backend/services/api/alembic/versions/20260728_0007_inventario.py`:

```python
"""Inventario y compras: `compras`, `compra_items` y `ajustes_inventario` (ADR-020/023).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-28

## Las tres tablas y su porqué

- `compras` (ADR-020): el registro simple de una compra a proveedor.
  `proveedor_nombre` es TEXTO LIBRE — la factura es un papel, a veces
  manuscrito, y NO hay tabla de proveedores (YAGNI firmado: sin consumidor
  del historial en el MVP, sería la entidad imaginada que ADR-016 prohíbe).
  `fecha` es el dato de la factura (puede ser de ayer; el orden temporal
  real lo da `created_at`, del servidor). `total_centavos` lo calcula el
  servidor por línea (decisión 7 del plan).
- `compra_items` (ADR-020): las líneas con el costo de ESTA compra. FK a
  `compras` y a `productos` con RESTRICT. Postgres NO aplica RLS al verificar
  llaves foráneas: que el producto sea del propio tenant lo garantiza el
  servicio, que lo lee con FOR UPDATE por la sesión de tenant antes de
  insertar. El índice `(tenant_id, producto_id)` es el insumo de las futuras
  sugerencias de reabastecimiento (ADR-020: se calculan de `compra_items`).
- `ajustes_inventario` (decisión 5 del plan; el ADR no la lista y la
  desviación queda justificada allí): el ajuste de conteo o la merma como
  HECHO, con su `motivo` obligatorio. Su PK es el UUID del cliente: la fila
  es la prueba de idempotencia INCLUSO cuando el delta es cero y no hay
  movimiento que escribir — el agujero que una columna `nota` en el libro no
  podía cerrar. `delta` guarda lo aplicado (0 permitido) y
  `stock_resultante`, el stock tras aplicar, para responder al reintento lo
  mismo que la primera vez. El movimiento del libro (cuando delta ≠ 0)
  lleva `referencia_id = ajustes_inventario.id`, así que la auditoría va del
  libro al ajuste y de ahí al motivo.

## Lo que esta migración NO hace (decisión 6)

No toca `movimientos_inventario`: la 0005 creó `ck_movimientos_tipo` con los
cinco tipos (`venta`, `compra`, `ajuste`, `merma`, y `anulacion` vía 0006) y
el índice único `(tenant_id, tipo, referencia_id, producto_id)` ya deduplica
los movimientos de compra y de ajuste. `test_aislamiento_inventario.py` lo
demuestra insertando los tres tipos nuevos contra la base migrada.

## Grants

Los privilegios por defecto de 01-roles.sh conceden los cuatro a `vendi_app`
sobre toda tabla creada por `vendi_platform`, que es lo que el candado
invertido exige para tablas de negocio (mismo criterio que `productos`,
`ventas` y `files`). No se toca nada aquí a propósito.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        "compras",
        *_columnas_base(),
        # Texto libre, no tabla de proveedores (ADR-020, YAGNI firmado). La
        # cota de largo la pone el schema (160), no la columna: es de
        # negocio, no de tipo.
        sa.Column("proveedor_nombre", sa.Text(), nullable=False),
        # El dato de la factura de papel. Sin cota: una factura de ayer se
        # registra hoy. La verdad temporal es `created_at` (servidor).
        sa.Column("fecha", sa.Date(), server_default=sa.func.current_date(), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        # Lo calcula el servidor por línea (decisión 7): nunca viene del cliente.
        sa.Column("total_centavos", sa.Integer(), nullable=False),
        sa.CheckConstraint("total_centavos >= 0", name="ck_compras_total_no_negativo"),
    )
    # Empieza por tenant_id (predicado RLS como Index Cond) y ordena el
    # listado por la fecha de la factura.
    op.create_index("ix_compras_tenant_fecha", "compras", ["tenant_id", "fecha"])
    enable_rls(op, "compras", crear_indice=False)

    op.create_table(
        "compra_items",
        *_columnas_base(),
        sa.Column(
            "compra_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("compras.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "producto_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("productos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("cantidad", sa.Numeric(14, 3), nullable=False),
        # Dinero en centavos enteros, jamás flotante (criterio unificado ADR-018).
        sa.Column("costo_unitario_centavos", sa.Integer(), nullable=False),
        sa.CheckConstraint("cantidad > 0", name="ck_compra_items_cantidad_positiva"),
        sa.CheckConstraint("costo_unitario_centavos >= 0", name="ck_compra_items_costo_no_negativo"),
    )
    op.create_index("ix_compra_items_tenant_compra", "compra_items", ["tenant_id", "compra_id"])
    # El historial de costos por producto: insumo de las sugerencias de
    # reabastecimiento (ADR-020).
    op.create_index("ix_compra_items_tenant_producto", "compra_items", ["tenant_id", "producto_id"])
    enable_rls(op, "compra_items", crear_indice=False)

    op.create_table(
        "ajustes_inventario",
        *_columnas_base(),
        sa.Column(
            "producto_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("productos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tipo", sa.String(8), nullable=False),
        # Forma por tipo (la hace cumplir ck_ajustes_forma): el ajuste es un
        # conteo absoluto (`stock_contado`); la merma, una cantidad que se
        # dañó (`cantidad`).
        sa.Column("stock_contado", sa.Numeric(14, 3), nullable=True),
        sa.Column("cantidad", sa.Numeric(14, 3), nullable=True),
        # Lo aplicado contra el stock del servidor en el momento (ADR-020:
        # el ajuste es online porque su delta se calcula contra ESTE dato).
        # Admite 0: el conteo que cuadra no escribe movimiento, pero la fila
        # queda como prueba de idempotencia (decisión 5).
        sa.Column("delta", sa.Numeric(14, 3), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("aplicado_por", sa.String(120), nullable=False),
        # El stock tras aplicar: es lo que se responde al reintento.
        sa.Column("stock_resultante", sa.Numeric(14, 3), nullable=False),
        sa.CheckConstraint("tipo IN ('ajuste', 'merma')", name="ck_ajustes_tipo"),
        sa.CheckConstraint(
            "(tipo = 'ajuste' AND stock_contado IS NOT NULL AND cantidad IS NULL) OR "
            "(tipo = 'merma' AND cantidad IS NOT NULL AND stock_contado IS NULL)",
            name="ck_ajustes_forma",
        ),
        sa.CheckConstraint("cantidad IS NULL OR cantidad > 0", name="ck_ajustes_cantidad_positiva"),
        sa.CheckConstraint("stock_contado IS NULL OR stock_contado >= 0", name="ck_ajustes_conteo_no_negativo"),
    )
    # El libro de ajustes por producto (auditoría «¿quién movió el arroz?»),
    # empezando por tenant_id para el predicado RLS.
    op.create_index("ix_ajustes_tenant_producto", "ajustes_inventario", ["tenant_id", "producto_id"])
    enable_rls(op, "ajustes_inventario", crear_indice=False)


def downgrade() -> None:
    disable_rls(op, "ajustes_inventario", borrar_indice=False)
    op.drop_index("ix_ajustes_tenant_producto", table_name="ajustes_inventario")
    op.drop_table("ajustes_inventario")
    disable_rls(op, "compra_items", borrar_indice=False)
    op.drop_index("ix_compra_items_tenant_producto", table_name="compra_items")
    op.drop_index("ix_compra_items_tenant_compra", table_name="compra_items")
    op.drop_table("compra_items")
    disable_rls(op, "compras", borrar_indice=False)
    op.drop_index("ix_compras_tenant_fecha", table_name="compras")
    op.drop_table("compras")
```

- [ ] **Paso 3: migrar y verificar.**

```bash
bash scripts/migrate.sh
# Esperado: Running upgrade 0006 -> 0007, Inventario y compras: `compras`, `compra_items` y `ajustes_inventario` … 0007 (head)
cd backend && uv run pytest tests/test_aislamiento_inventario.py -q
# Esperado: 10 passed
uv run pytest tests/test_rls_coverage.py tests/test_privilegios_de_vendi_app.py -q
# Esperado: verdes — las tres tablas entran en la cobertura de nivel 2 (base migrada) y heredan los cuatro grants;
# el nivel 1 (metadata) las cubre cuando los modelos se registren en la Tarea 2
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/alembic/versions/20260728_0007_inventario.py backend/tests/test_aislamiento_inventario.py
git commit -m "Migración 0007: compras, compra_items y ajustes_inventario con RLS, índices y checks"
```

**Criterios de aceptación:** las tres tablas existen con policy `tenant_isolation` forzada, índices que empiezan por `tenant_id`, FKs `RESTRICT` y los checks de forma; el CHECK de tipos de `movimientos_inventario` admite `compra`/`ajuste`/`merma` sin haberse tocado (test que lo demuestra); el índice único del libro deduplica el movimiento de una compra; los 10 tests de aislamiento pasan contra PostgreSQL real, 0 SKIPPED.

---

## Tarea 2: Modelos SQLAlchemy del módulo inventario

**Files:**
- Create: `backend/tests/test_inventario_modelo.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/inventario/__init__.py` (vacío, como los otros módulos)
- Create: `backend/services/api/app/modules/inventario/models.py`
- Modify: `backend/tests/test_rls_coverage.py` (registrar los tres modelos en los imports del candado)

**Interfaces:**
- Consume: `vendi_core.db.base.Base`, `TenantModel`; la metadata fiel a la migración 0007.
- Produce: `Compra`, `CompraItem`, `AjusteInventario` y `TIPOS_DE_AJUSTE`; el candado de cobertura RLS de nivel 1 vuelve a verde con los tres modelos registrados.

- [ ] **Paso 1: escribir el test del modelo que falla.** Crear `backend/tests/test_inventario_modelo.py`:

```python
"""El metadata de los modelos de inventario es fiel a la migración 0007.

Sin base de datos (no lleva marcador `integration`): compara nombres de
tabla, índices, checks y FKs contra lo que la migración creó. Si las dos
definiciones se separan, este test es el primero en gritar (D-17 registra
que `alembic check` aún no corre en CI; mientras tanto, ESTE es el candado).
"""

from __future__ import annotations

from app.modules.inventario.models import TIPOS_DE_AJUSTE, AjusteInventario, Compra, CompraItem


def test_las_tablas_son_las_de_la_migracion():
    assert Compra.__tablename__ == "compras"
    assert CompraItem.__tablename__ == "compra_items"
    assert AjusteInventario.__tablename__ == "ajustes_inventario"


def test_cada_tabla_tiene_indice_que_empieza_por_tenant():
    for modelo in (Compra, CompraItem, AjusteInventario):
        for indice in modelo.__table__.indexes:
            if list(indice.columns)[0].name == "tenant_id":
                break
        else:
            raise AssertionError(f"{modelo.__tablename__} no tiene índice que empiece por tenant_id")


def test_los_indices_son_los_de_la_migracion():
    assert {i.name for i in Compra.__table__.indexes} == {"ix_compras_tenant_fecha"}
    assert {i.name for i in CompraItem.__table__.indexes} == {
        "ix_compra_items_tenant_compra",
        "ix_compra_items_tenant_producto",
    }
    assert {i.name for i in AjusteInventario.__table__.indexes} == {"ix_ajustes_tenant_producto"}


def test_los_checks_son_los_de_la_migracion():
    nombres = {c.name for t in (Compra.__table__, CompraItem.__table__, AjusteInventario.__table__) for c in t.constraints}
    assert {
        "ck_compras_total_no_negativo",
        "ck_compra_items_cantidad_positiva",
        "ck_compra_items_costo_no_negativo",
        "ck_ajustes_tipo",
        "ck_ajustes_forma",
        "ck_ajustes_cantidad_positiva",
        "ck_ajustes_conteo_no_negativo",
    } <= nombres


def test_las_fk_son_restrict():
    compra_fks = {f.column.table.name: f.ondelete for f in CompraItem.__table__.foreign_keys}
    assert compra_fks == {"compras": "RESTRICT", "productos": "RESTRICT"}
    ajuste_fks = {f.column.table.name: f.ondelete for f in AjusteInventario.__table__.foreign_keys}
    assert ajuste_fks == {"productos": "RESTRICT"}


def test_los_tipos_de_ajuste_son_los_del_check():
    assert TIPOS_DE_AJUSTE == ("ajuste", "merma")
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_inventario_modelo.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.inventario'
```

- [ ] **Paso 2: escribir los modelos.** Crear `backend/services/api/app/modules/inventario/__init__.py` vacío y `backend/services/api/app/modules/inventario/models.py`:

```python
"""Modelos del módulo inventario: compras y ajustes (ADR-020, decisiones 5-7 del plan).

Tres tablas, todas de negocio (policy `tenant_isolation` puesta por la
migración 0007):

- `Compra`: el registro simple de una compra a proveedor. `proveedor_nombre`
  es texto libre (la factura es un papel; NO hay tabla de proveedores —
  YAGNI firmado en ADR-020). `total_centavos` lo calcula el servidor por
  línea: nunca viene del cliente. Sin `SoftDeleteMixin`: una compra
  equivocada no se borra ni se edita, se corrige con un ajuste — el libro
  es inmutable.
- `CompraItem`: las líneas con el costo de ESTA compra. El índice por
  producto es el insumo de las futuras sugerencias de reabastecimiento.
- `AjusteInventario`: el ajuste de conteo o la merma como hecho, con su
  `motivo` obligatorio. Su PK es el UUID del cliente (la fila es la prueba
  de idempotencia incluso con delta cero, decisión 5); el movimiento del
  libro —cuando lo hay— la referencia.

El libro `movimientos_inventario` NO se mueve a este módulo: nació en
`ventas/models.py` (módulo 2) y allí se queda; `inventario/stock.py` lo
importa. Moverlo sería churn sin beneficio.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import UUID, CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, TenantModel

#: Las dos operaciones online del inventario (ADR-020). El ajuste es un
#: conteo absoluto; la merma, una cantidad que se dañó. La forma de cada una
#: la hace cumplir `ck_ajustes_forma`.
TIPOS_DE_AJUSTE: tuple[str, ...] = ("ajuste", "merma")


class Compra(Base, TenantModel):
    """Una compra a proveedor. Append-only como el resto del inventario: la
    corrección es un ajuste, nunca un UPDATE."""

    __tablename__ = "compras"
    __table_args__ = (
        Index("ix_compras_tenant_fecha", "tenant_id", "fecha"),
        CheckConstraint("total_centavos >= 0", name="ck_compras_total_no_negativo"),
    )

    #: Texto libre (ADR-020): «Distribuidora La 33», «el de las gaseosas».
    proveedor_nombre: Mapped[str] = mapped_column(Text, nullable=False)
    #: El dato de la factura de papel; el defecto es la fecha del servidor.
    fecha: Mapped[date] = mapped_column(Date, server_default=func.current_date(), nullable=False)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Σ por línea, calculado en el servidor (decisión 7). Centavos enteros.
    total_centavos: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Compra {self.id} {self.proveedor_nombre!r} {self.total_centavos}>"


class CompraItem(Base, TenantModel):
    """Una línea de compra. El costo se congela aquí: es lo que ESTA compra
    costó, y al confirmarse actualiza `ultimo_costo` del producto (ADR-020)."""

    __tablename__ = "compra_items"
    __table_args__ = (
        Index("ix_compra_items_tenant_compra", "tenant_id", "compra_id"),
        Index("ix_compra_items_tenant_producto", "tenant_id", "producto_id"),
        CheckConstraint("cantidad > 0", name="ck_compra_items_cantidad_positiva"),
        CheckConstraint("costo_unitario_centavos >= 0", name="ck_compra_items_costo_no_negativo"),
    )

    compra_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compras.id", ondelete="RESTRICT"), nullable=False
    )
    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False
    )
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    costo_unitario_centavos: Mapped[int] = mapped_column(Integer, nullable=False)


class AjusteInventario(Base, TenantModel):
    """Un ajuste por conteo («conté 14, el sistema dice 16») o una merma
    («se dañaron 3 kg»). ONLINE obligatorio (ADR-020): su delta se calcula
    contra el stock del servidor en el momento, con la fila bloqueada.

    La PK es el UUID del cliente (decisión 4: REQUERIDO, porque la merma es
    un delta relativo y solo la ancla la hace segura ante reintentos). La
    fila se crea SIEMPRE, incluso cuando `delta` es 0 y no hay movimiento
    que escribir: es la prueba de idempotencia (decisión 5)."""

    __tablename__ = "ajustes_inventario"
    __table_args__ = (
        Index("ix_ajustes_tenant_producto", "tenant_id", "producto_id"),
        CheckConstraint("tipo IN ('ajuste', 'merma')", name="ck_ajustes_tipo"),
        CheckConstraint(
            "(tipo = 'ajuste' AND stock_contado IS NOT NULL AND cantidad IS NULL) OR "
            "(tipo = 'merma' AND cantidad IS NOT NULL AND stock_contado IS NULL)",
            name="ck_ajustes_forma",
        ),
        CheckConstraint("cantidad IS NULL OR cantidad > 0", name="ck_ajustes_cantidad_positiva"),
        CheckConstraint("stock_contado IS NULL OR stock_contado >= 0", name="ck_ajustes_conteo_no_negativo"),
    )

    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(8), nullable=False)
    #: El conteo físico (solo ajustes). NULL en mermas.
    stock_contado: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    #: Lo que se dañó (solo mermas). NULL en ajustes.
    cantidad: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    #: Lo aplicado contra el stock del servidor: `stock_contado - stock_actual`
    #: en el ajuste; `-cantidad` en la merma. Admite 0 (conteo que cuadra).
    delta: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    #: La justificación obligatoria: un ajuste sin motivo es un desfalco con
    #: buenos modales.
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    aplicado_por: Mapped[str] = mapped_column(String(120), nullable=False)
    #: El stock tras aplicar: lo que se responde también al reintento.
    stock_resultante: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
```

- [ ] **Paso 3: registrar los modelos en el candado de cobertura RLS.** En `backend/tests/test_rls_coverage.py`, añadir tras el import de los modelos de ventas:

```python
from app.modules.inventario.models import AjusteInventario, Compra, CompraItem  # noqa: F401
```

- [ ] **Paso 4: verificar.**

```bash
cd backend && uv run pytest tests/test_inventario_modelo.py tests/test_rls_coverage.py -q
# Esperado: 6 passed del modelo + el candado de nivel 1 verde
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 5: commit**

```bash
git add backend/services/api/app/modules/inventario/__init__.py backend/services/api/app/modules/inventario/models.py backend/tests/test_inventario_modelo.py backend/tests/test_rls_coverage.py
git commit -m "Modelos del módulo inventario: Compra, CompraItem y AjusteInventario"
```

**Criterios de aceptación:** los 6 tests del modelo pasan; el candado de cobertura RLS de nivel 1 ve las tres tablas con índice que empieza por `tenant_id`; el metadata coincide con la migración 0007; `ruff` limpio.

---

## Tarea 3: Schemas Pydantic del módulo inventario

**Files:**
- Create: `backend/tests/test_inventario_schemas.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/inventario/schemas.py`

**Interfaces:**
- Consume: `TOPE_PRECIO`, `TOPE_STOCK` de `app.modules.catalogo.schemas` (misma reutilización que ventas); `TIPOS_DE_AJUSTE` del modelo.
- Produce: `CompraCrear`, `CompraItemEntrada`, `CompraSalida`, `CompraItemSalida`, `CompraDetalleSalida`, `AjusteCrear`, `AjusteSalida`, `AjusteCreado`, `StockSalida`.

Reglas duras (Global Constraints): cotas `le=` contra la columna en todo número; cuantización `ROUND_HALF_UP` a 3 decimales en las cantidades (lección BUG-2 del QA de ventas); `extra="forbid"` en las entradas; validadores `mode="before"` que no asumen `str`.

- [ ] **Paso 1: escribir los tests de schema que fallan.** Crear `backend/tests/test_inventario_schemas.py`:

```python
"""Las reglas duras de la entrada del módulo inventario (sin base de datos).

Cotas contra la columna (un overflow es un DataError → 500, no un 422),
cuantización a los 3 decimales de la columna, forma por tipo de ajuste,
motivo obligatorio y `extra="forbid"`. Las lecciones de los dos QA
adversariales, fijadas antes de escribir el schema.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.inventario.schemas import AjusteCrear, CompraCrear, CompraItemEntrada


def _item(**cambios) -> dict:
    cuerpo = {"producto_id": str(uuid.uuid4()), "cantidad": "2", "costo_unitario_centavos": 2500}
    cuerpo.update(cambios)
    return cuerpo


def _compra(**cambios) -> dict:
    cuerpo = {"proveedor_nombre": "Distribuidora La 33", "items": [_item()]}
    cuerpo.update(cambios)
    return cuerpo


def _ajuste(**cambios) -> dict:
    cuerpo = {
        "id": str(uuid.uuid4()),
        "tipo": "ajuste",
        "producto_id": str(uuid.uuid4()),
        "stock_contado": "14",
        "motivo": "Conteo de cierre",
    }
    cuerpo.update(cambios)
    return cuerpo


# --- Compra ---------------------------------------------------------------------


def test_la_compra_feliz_cuantiza_la_cantidad_y_acepta_fecha():
    compra = CompraCrear.model_validate(_compra(fecha=str(date(2026, 7, 20)), items=[_item(cantidad="0.3334")]))
    assert compra.items[0].cantidad == Decimal("0.333")
    assert compra.fecha == date(2026, 7, 20)


def test_la_cantidad_que_cuantiza_a_cero_se_rechaza():
    # BUG-2 del QA de ventas: 0.0004 cabría redondeado a 0.000 por Postgres y
    # reventaba el CHECK como 500. El schema lo corta como dato inválido.
    with pytest.raises(ValidationError):
        CompraItemEntrada.model_validate(_item(cantidad="0.0004"))


def test_la_cantidad_de_cuatro_decimales_se_cuantiza_como_postgres():
    item = CompraItemEntrada.model_validate(_item(cantidad="0.3335"))
    assert item.cantidad == Decimal("0.334")  # ROUND_HALF_UP, el mismo redondeo de la columna


def test_el_costo_no_puede_desbordar_el_integer():
    with pytest.raises(ValidationError):
        CompraItemEntrada.model_validate(_item(costo_unitario_centavos=2**31))
    assert CompraItemEntrada.model_validate(_item(costo_unitario_centavos=2**31 - 1))


def test_la_cantidad_no_puede_desbordar_el_numeric():
    with pytest.raises(ValidationError):
        CompraItemEntrada.model_validate(_item(cantidad="100000000000"))  # 12 dígitos enteros: no cabe en (14,3)


def test_el_proveedor_se_limpia_antes_de_medir():
    compra = CompraCrear.model_validate(_compra(proveedor_nombre="  Distribuidora   La 33  "))
    assert compra.proveedor_nombre == "Distribuidora La 33"
    with pytest.raises(ValidationError):
        CompraCrear.model_validate(_compra(proveedor_nombre="   "))  # limpia a "" y choca con min_length


def test_el_limpiador_no_asume_str():
    with pytest.raises(ValidationError):
        CompraCrear.model_validate(_compra(proveedor_nombre=123))  # 422 de pydantic, no AttributeError


def test_un_producto_repetido_en_dos_lineas_es_422():
    with pytest.raises(ValidationError, match="mismo producto"):
        CompraCrear.model_validate(_compra(items=[_item(), _item()]))  # el helper usa el MISMO producto_id


def test_la_compra_no_acepta_campos_desconocidos():
    with pytest.raises(ValidationError):
        CompraCrear.model_validate(_compra(tenant_id=str(uuid.uuid4()), total_centavos=5))


def test_la_compra_exige_al_menos_un_item():
    with pytest.raises(ValidationError):
        CompraCrear.model_validate(_compra(items=[]))


# --- Ajuste y merma ---------------------------------------------------------------


def test_el_ajuste_exige_id_tipo_conteo_y_motivo():
    ajuste = AjusteCrear.model_validate(_ajuste())
    assert ajuste.stock_contado == Decimal("14")
    for falta in ("id", "stock_contado", "motivo"):
        cuerpo = _ajuste()
        del cuerpo[falta]
        with pytest.raises(ValidationError):
            AjusteCrear.model_validate(cuerpo)


def test_el_ajuste_rechaza_la_cantidad_que_es_de_merma():
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(cantidad="2"))


def test_la_merma_exige_cantidad_y_rechaza_conteo():
    merma = AjusteCrear.model_validate(_ajuste(tipo="merma", cantidad="3", stock_contado=None, motivo="Se dañó"))
    assert merma.cantidad == Decimal("3")
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(tipo="merma", stock_contado=None, motivo="Se dañó"))  # sin cantidad
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(tipo="merma", cantidad="3", motivo="Se dañó"))  # con conteo


def test_el_conteo_cero_es_valido_y_se_cuantiza():
    ajuste = AjusteCrear.model_validate(_ajuste(stock_contado="0.0004"))
    assert ajuste.stock_contado == Decimal("0")  # el conteo cero es legítimo; se guarda cuantizado


def test_el_motivo_se_limpia_y_exige_tres_letras():
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(motivo="  ok "))  # limpia a "ok": menos de 3
    assert AjusteCrear.model_validate(_ajuste(motivo="  Conteo   de cierre  ")).motivo == "Conteo de cierre"


def test_el_ajuste_no_acepta_campos_desconocidos():
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(tenant_id=str(uuid.uuid4())))


def test_el_tipo_solo_admite_ajuste_o_merma():
    with pytest.raises(ValidationError):
        AjusteCrear.model_validate(_ajuste(tipo="correccion"))
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_inventario_schemas.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.inventario.schemas'
```

- [ ] **Paso 2: escribir los schemas.** Crear `backend/services/api/app/modules/inventario/schemas.py`:

```python
"""Esquemas de entrada y salida del módulo inventario.

El contrato que consume el frontend sale de aquí vía `openapi.json`: cada
cambio es un cambio de contrato y se regenera `docs/api/openapi-fase0.json`
con su cliente TypeScript.

Reglas duras heredadas de los QA adversariales de catálogo y ventas:

- Cotas `le=` contra el tipo de columna en TODO número de entrada: un
  overflow de `Integer` o `Numeric(14,3)` es un `DataError` → 500, no un 422.
- Las cantidades se CUANTIZAN a los 3 decimales de la columna con
  `ROUND_HALF_UP` al validar (BUG-2 del QA de ventas: Postgres redondea en
  silencio; cliente y servidor deben comparar siempre la misma cantidad).
- Dinero en centavos enteros (`costo_unitario_centavos`), jamás flotante.
- `extra="forbid"` en las entradas: un `tenant_id` inyectado se rechaza.
- Los validadores `mode="before"` no asumen `str` (BUG-1 del QA de catálogo).

El `total_centavos` de la compra NO está aquí a propósito: lo calcula el
servidor por línea (decisión 7 del plan) — el cliente no puede declararlo.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.catalogo.schemas import TOPE_PRECIO, TOPE_STOCK

#: Tope de líneas por compra: acota la transacción que retiene los bloqueos
#: de fila de los productos (mismo criterio que el tope del lote del sync).
TOPE_ITEMS_POR_COMPRA = 200


def _limpiar_texto(valor: object) -> object:
    # Corre ANTES de la validación de tipo (mode="before"): lo que no sea str
    # pasa intacto para que pydantic lo rechace como 422. Intentar limpiarlo
    # reventaría con AttributeError dentro del validador y saldría como 500.
    if not isinstance(valor, str):
        return valor
    return " ".join(valor.split())


def _cuantizar_cantidad(valor: Decimal) -> Decimal:
    """La columna es NUMERIC(14,3): Postgres REDONDEA lo que no cabe
    (BUG-2 del QA de ventas). El schema aplica el MISMO redondeo al validar
    y rechaza lo que cuantiza a cero, que reventaría `ck_..._cantidad_positiva`
    como 500. Misma regla que `ventas/schemas.py`; se duplica a propósito:
    el mensaje de error nombra el contexto (una línea de compra)."""
    cuantizada = valor.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if cuantizada == 0:
        raise ValueError("La cantidad es menor que 0.001: no cabe en una línea de compra.")
    return cuantizada


def _cuantizar_conteo(valor: Decimal) -> Decimal:
    """El conteo físico también se guarda en NUMERIC(14,3), pero el cero es
    un conteo VÁLIDO («no queda ninguna»): se cuantiza sin rechazarlo."""
    return valor.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# --- Compra ---------------------------------------------------------------------


class CompraItemEntrada(BaseModel):
    """Una línea de factura. El costo es el de ESTA compra: al confirmarse
    actualiza `ultimo_costo` del producto (ADR-020)."""

    model_config = ConfigDict(extra="forbid")

    producto_id: uuid.UUID
    cantidad: Decimal = Field(gt=0, le=TOPE_STOCK)
    costo_unitario_centavos: int = Field(ge=0, le=TOPE_PRECIO)

    _cantidad_cuantizada = field_validator("cantidad")(_cuantizar_cantidad)


class CompraCrear(BaseModel):
    """Una compra a proveedor. `proveedor_nombre` es texto libre (ADR-020:
    la factura es un papel; no hay tabla de proveedores). El `id` del
    cliente se acepta como PK (ADR-017): reenviar la misma compra es un
    no-op. El total NO viaja: lo calcula el servidor (decisión 7)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    proveedor_nombre: str = Field(min_length=1, max_length=160)
    #: El dato de la factura de papel; sin cota de rango (una factura de
    #: ayer se registra hoy). Si falta, el servidor pone su fecha.
    fecha: date | None = None
    observaciones: str | None = Field(default=None, max_length=500)
    items: list[CompraItemEntrada] = Field(min_length=1, max_length=TOPE_ITEMS_POR_COMPRA)

    _proveedor_limpio = field_validator("proveedor_nombre", mode="before")(_limpiar_texto)
    _observaciones_limpias = field_validator("observaciones", mode="before")(
        lambda v: None if v is None else _limpiar_texto(v)
    )

    @model_validator(mode="after")
    def _un_producto_por_linea(self) -> CompraCrear:
        """Decisión 8: dos líneas del mismo producto chocarían en
        `ux_movimientos_origen` (referencia = compra.id) y habría que elegir
        en silencio qué costo gana para `ultimo_costo`. La compra es un
        formulario síncrono: la UI suma las líneas, y si no, 422."""
        ids = [item.producto_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("La compra tiene el mismo producto en dos líneas: súmalas en una sola.")
        return self


class CompraItemSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    producto_id: uuid.UUID
    cantidad: Decimal
    costo_unitario_centavos: int


class CompraSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    proveedor_nombre: str
    fecha: date
    observaciones: str | None = None
    total_centavos: int
    created_at: datetime | None = None


class CompraDetalleSalida(CompraSalida):
    items: list[CompraItemSalida]


# --- Ajuste y merma ---------------------------------------------------------------


class AjusteCrear(BaseModel):
    """Un ajuste por conteo o una merma. ONLINE obligatorio (ADR-020): el
    delta se calcula contra el stock del servidor en el momento.

    `id` es REQUERIDO (decisión 4): es la PK de `ajustes_inventario` y la
    única ancla que hace seguro el reintento de una merma, que es un delta
    relativo. El `motivo` es obligatorio: un ajuste sin justificación es un
    desfalco con buenos modales.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    tipo: Literal["ajuste", "merma"]
    producto_id: uuid.UUID
    #: El conteo físico (solo `tipo="ajuste"`).
    stock_contado: Decimal | None = Field(default=None, ge=0, le=TOPE_STOCK)
    #: Lo que se dañó (solo `tipo="merma"`).
    cantidad: Decimal | None = Field(default=None, gt=0, le=TOPE_STOCK)
    motivo: str = Field(min_length=3, max_length=300)

    _conteo_cuantizado = field_validator("stock_contado")(
        lambda v: None if v is None else _cuantizar_conteo(v)
    )
    _cantidad_cuantizada = field_validator("cantidad")(
        lambda v: None if v is None else _cuantizar_cantidad(v)
    )
    # La limpieza va ANTES de min_length: un motivo de puros espacios choca
    # con la cota, no se cuela como "".
    _motivo_limpio = field_validator("motivo", mode="before")(_limpiar_texto)

    @model_validator(mode="after")
    def _la_forma_es_la_del_tipo(self) -> AjusteCrear:
        """Espejo en la aplicación de `ck_ajustes_forma`: el 422 lo da
        pydantic, no la constraint (que saldría como 500)."""
        if self.tipo == "ajuste":
            if self.stock_contado is None:
                raise ValueError("Un ajuste por conteo necesita `stock_contado` (lo que contaste).")
            if self.cantidad is not None:
                raise ValueError("`cantidad` es solo para mermas; el ajuste lleva `stock_contado`.")
        else:
            if self.cantidad is None:
                raise ValueError("Una merma necesita `cantidad` (lo que se dañó).")
            if self.stock_contado is not None:
                raise ValueError("`stock_contado` es solo para ajustes por conteo; la merma lleva `cantidad`.")
        return self


class AjusteSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tipo: str
    producto_id: uuid.UUID
    stock_contado: Decimal | None = None
    cantidad: Decimal | None = None
    #: Lo aplicado contra el stock del servidor (0 = el conteo cuadraba y no
    #: hubo movimiento en el libro).
    delta: Decimal
    motivo: str
    aplicado_por: str
    stock_resultante: Decimal
    created_at: datetime | None = None


class AjusteCreado(AjusteSalida):
    """La respuesta del alta: lo mismo que la fila, más el nivel de alerta en
    que quedó el producto (lo deriva el servidor, que es la única autoridad
    del umbral — decisión 2)."""

    nivel: str


# --- Estado de stock ---------------------------------------------------------------


class StockSalida(BaseModel):
    """El stock de un producto con su nivel derivado (agotado/crítico/bajo/ok).

    El nivel lo calcula el servidor con la misma función que dispara las
    alertas: una sola definición del umbral, ninguna reimplementación en el
    frontend. El stock negativo es un dato legítimo (ADR-020) y viaja tal
    cual con nivel `agotado`."""

    producto_id: uuid.UUID
    nombre: str
    stock_actual: Decimal
    stock_minimo: Decimal
    nivel: str


__all__ = [
    "TOPE_ITEMS_POR_COMPRA",
    "AjusteCreado",
    "AjusteCrear",
    "AjusteSalida",
    "CompraCrear",
    "CompraDetalleSalida",
    "CompraItemEntrada",
    "CompraItemSalida",
    "CompraSalida",
    "StockSalida",
]
```

- [ ] **Paso 3: verificar.**

```bash
cd backend && uv run pytest tests/test_inventario_schemas.py -q
# Esperado: 17 passed
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/inventario/schemas.py backend/tests/test_inventario_schemas.py
git commit -m "Schemas del módulo inventario: compras, ajustes con forma por tipo y estado de stock"
```

**Criterios de aceptación:** los 17 tests pasan; las cantidades se cuantizan como la columna (y lo que cuantiza a cero se rechaza); ningún número de entrada puede desbordar su columna; el producto duplicado en una compra es 422; la forma por tipo de ajuste la exige pydantic (espejo del CHECK); `extra="forbid"` en todas las entradas; `ruff` limpio.

---

## Tarea 4: Permisos `inventario:ajustar` / `compra:crear` en `vendi-core` (ADR-023)

**Files:**
- Modify: `backend/libs/vendi-core/src/vendi_core/auth/policies.py`
- Modify: `backend/tests/test_auth_policies.py`

**Interfaces:**
- Consume: el patrón vigente (constantes `PERM_*`, `PERMISSION_CATALOG`, `_PERMISOS_DUENO/_CAJERO/_ALMACENISTA`, `PERMISOS_POR_ROL` como semilla).
- Produce: los dos permisos en el catálogo; el dueño los tiene los dos; el almacenista los tiene los dos (ADR-023 literal); el cajero NINGUNO. `roles_de_realm_del_grupo` los siembra solo.

- [ ] **Paso 1: escribir los tests que fallan.** En `backend/tests/test_auth_policies.py`, reemplazar `test_el_reparto_de_permisos_es_el_de_adr_023` por:

```python
def test_el_reparto_de_permisos_es_el_de_adr_023():
    """El cajero VENDE pero no anula, no ajusta inventario ni compra: anular,
    arquear y ajustar son los gestos con los que se desfalca una tienda y
    quedan fuera de sus manos en el MVP (ADR-023). El almacenista no vende:
    su trabajo es que el estante y el sistema digan lo mismo."""
    assert PERMISOS_POR_ROL[ROL_CAJERO] == frozenset({PERM_PRODUCTO_LEER, PERM_VENTA_CREAR})
    assert PERM_VENTA_ANULAR not in PERMISOS_POR_ROL[ROL_CAJERO]
    assert PERM_INVENTARIO_AJUSTAR not in PERMISOS_POR_ROL[ROL_CAJERO]
    assert PERM_COMPRA_CREAR not in PERMISOS_POR_ROL[ROL_CAJERO]
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
    } <= PERMISOS_POR_ROL[ROL_DUENO]
```

y añadir los dos nombres al import de `vendi_core.auth.policies` del archivo (`PERM_COMPRA_CREAR`, `PERM_INVENTARIO_AJUSTAR`).

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_auth_policies.py -q
# Esperado: ImportError: cannot import name 'PERM_INVENTARIO_AJUSTAR' from 'vendi_core.auth.policies'
```

- [ ] **Paso 2: añadir los permisos al catálogo y al reparto.** En `backend/libs/vendi-core/src/vendi_core/auth/policies.py`, tras el bloque de ventas:

```python
# Inventario y compras (ADR-020/ADR-023). El almacenista ajusta y compra; el
# cajero NO toca inventario ni compras — ajustar stock es el tercer gesto
# con el que se desfalca una tienda, junto a anular y arquear.
PERM_INVENTARIO_AJUSTAR = "inventario:ajustar"
PERM_COMPRA_CREAR = "compra:crear"
```

En `PERMISSION_CATALOG`, tras `(PERM_VENTA_ANULAR, "venta")`:

```python
    (PERM_INVENTARIO_AJUSTAR, "inventario"),
    (PERM_COMPRA_CREAR, "compra"),
```

En `_PERMISOS_DUENO`, añadir los dos nombres al set. Y reemplazar la línea del almacenista (con su comentario actualizado):

```python
# ADR-023: el cajero consulta el catálogo y vende, pero NO edita el catálogo,
# NO anula ventas, NO ajusta inventario y NO registra compras (anular, arquear
# y ajustar son los gestos con los que se desfalca una tienda; son del dueño
# en el MVP). El almacenista mantiene el catálogo, ajusta el inventario y
# registra las compras; no vende ni toca caja ni fiado. El resto de permisos
# de cada rol llega con su módulo.
_PERMISOS_CAJERO: frozenset[str] = frozenset({PERM_PRODUCTO_LEER, PERM_VENTA_CREAR})
_PERMISOS_ALMACENISTA: frozenset[str] = frozenset(
    {PERM_PRODUCTO_LEER, PERM_PRODUCTO_EDITAR, PERM_INVENTARIO_AJUSTAR, PERM_COMPRA_CREAR}
)
```

- [ ] **Paso 3: verificar y resembrar el realm local.**

```bash
cd backend && uv run pytest tests/test_auth_policies.py -q
# Esperado: todos passed (el candado «todo permiso asignado está en el catálogo» pasa solo)
bash scripts/seed.sh
# Esperado: [OK] Siembra completa. — los grupos dueno y almacenista quedan con los dos roles nuevos mapeados
```

- [ ] **Paso 4: commit**

```bash
git add backend/libs/vendi-core/src/vendi_core/auth/policies.py backend/tests/test_auth_policies.py
git commit -m "Permisos inventario:ajustar y compra:crear en el catálogo y el reparto (ADR-023)"
```

**Criterios de aceptación:** el catálogo tiene los 12 permisos (10 + 2); el reparto es exactamente el de ADR-023 (almacenista con ambos, cajero con ninguno, dueño con todo lo de su negocio); el candado «PERMISOS_POR_ROL ⊆ PERMISSION_CATALOG» pasa; la siembra aplica el diff en el realm local.

---

## Tarea 5: `inventario/stock.py` — el punto único de movimientos y alertas (y el refactor de ventas)

**Files:**
- Create: `backend/tests/test_inventario_alertas.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/inventario/stock.py`
- Modify: `backend/services/api/app/modules/ventas/service.py` (`_mover_stock` delega; decisión 1)
- Modify: `backend/tests/test_ventas_servicio.py` (BORRADO cubre el outbox de inventario; el test del negativo demuestra la alerta — decisión 12)
- Modify: `backend/tests/test_sync_idempotente.py` (BORRADO cubre el outbox de inventario)

**Interfaces:**
- Consume: `MovimientoInventario` de `app.modules.ventas.models`, `Producto` de `app.modules.catalogo.models`, `DomainEventService.emit`.
- Produce: `nivel_de_stock(stock, stock_minimo) -> str` (función pura), `NIVELES_DE_STOCK`, `aplicar_movimiento(session, ...) -> None` (libro + proyección + alerta al cruzar hacia abajo). `VentasService._mover_stock` conserva su firma y delega.

- [ ] **Paso 1: escribir los tests de alerta que fallan.** Crear `backend/tests/test_inventario_alertas.py`:

```python
"""Las alertas de umbral de ADR-020, contra el PostgreSQL real.

Los niveles se derivan de `stock_minimo`: agotado (`stock <= 0`), crítico
(`< stock_minimo / 2`), bajo (`< stock_minimo`), ok el resto. El evento
`inventario.alerta_stock` se emite SOLO cuando el nivel empeora al aplicar
un movimiento — nunca por movimiento, nunca al recuperarse, nunca dos veces
por el mismo cruce.

Semilla del producto de estos tests: stock 10, `stock_minimo` 4. El mapa:

    stock >-= 4   ok
    2 <= stock < 4  bajo
    0 < stock < 2   crítico
    stock <= 0    agotado
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.catalogo.models import Producto
from app.modules.inventario.stock import aplicar_movimiento, nivel_de_stock
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
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.inventario.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Un producto con stock 10 y mínimo 4 en T1, y un dispositivo para las
    ventas por sync."""
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
            text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual, stock_minimo) "
                 "VALUES (:p, :t, 'Arroz 500g', 2500, 10, 4)"),
            {"p": ids["producto"], "t": T1},
        )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def sesion(pg_app_url: str, semilla):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield s
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def _alertas(pg_platform_url: str) -> list[str]:
    """Los niveles de las alertas emitidas por T1, en orden de emisión."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            filas = (
                await conn.execute(
                    text(
                        "SELECT payload->'data'->>'nivel' FROM outbox_messages "
                        "WHERE routing_key = :k ORDER BY created_at, id"
                    ),
                    {"k": f"{T1}.inventario.alerta_stock"},
                )
            ).scalars().all()
            return list(filas)
    finally:
        await engine.dispose()


async def _aplicar(sesion, semilla, delta: str, tipo: str = "venta") -> None:
    producto = await sesion.get(Producto, semilla["producto"], with_for_update=True)
    await aplicar_movimiento(
        sesion,
        tenant_id=T1,
        producto=producto,
        delta=Decimal(delta),
        tipo=tipo,
        referencia_id=uuid.uuid4(),
    )
    await sesion.commit()


# --- La función pura -----------------------------------------------------------------


@pytest.mark.parametrize(
    "stock,minimo,esperado",
    [
        ("10", "4", "ok"),
        ("4", "4", "ok"),       # el mínimo exacto NO es bajo: bajo es estricto
        ("3.999", "4", "bajo"),
        ("2", "4", "bajo"),     # la mitad exacta NO es crítico: crítico es estricto
        ("1.999", "4", "critico"),
        ("0.001", "4", "critico"),
        ("0", "4", "agotado"),
        ("-3", "4", "agotado"),  # el negativo es legítimo y es agotado (ADR-020)
        ("0", "0", "agotado"),   # sin mínimo configurado, el cero ya es agotado
        ("5", "0", "ok"),        # sin mínimo, no hay bajo ni crítico
    ],
)
def test_nivel_de_stock_en_los_bordes(stock, minimo, esperado):
    assert nivel_de_stock(Decimal(stock), Decimal(minimo)) == esperado


# --- El cruce hacia abajo emite; lo demás, no ----------------------------------------


async def test_cruzar_hacia_abajo_emite_un_evento_por_cruce_y_no_por_movimiento(sesion, semilla, pg_platform_url):
    await _aplicar(sesion, semilla, "-7")   # 10 → 3: ok → bajo. EMITE.
    await _aplicar(sesion, semilla, "-1")   # 3 → 2: bajo → bajo. NO emite.
    await _aplicar(sesion, semilla, "-1")   # 2 → 1: bajo → crítico. EMITE.
    await _aplicar(sesion, semilla, "-0.5")  # 1 → 0.5: crítico → crítico. NO emite.
    await _aplicar(sesion, semilla, "-1")   # 0.5 → -0.5: crítico → agotado. EMITE.
    await _aplicar(sesion, semilla, "-1")   # -0.5 → -1.5: agotado → agotado. NO emite.
    assert await _alertas(pg_platform_url) == ["bajo", "critico", "agotado"]


async def test_recuperarse_no_emite_y_volver_a_cruzar_si(sesion, semilla, pg_platform_url):
    """El candado de ADR-020: N movimientos que cruzan el MISMO umbral emiten
    UN evento por cruce — y una recuperación «re-arma» el umbral."""
    await _aplicar(sesion, semilla, "-7")                # ok → bajo. EMITE (1).
    await _aplicar(sesion, semilla, "20", tipo="compra")  # 3 → 23: bajo → ok. NO emite.
    await _aplicar(sesion, semilla, "-20")               # 23 → 3: ok → bajo. EMITE (2).
    assert await _alertas(pg_platform_url) == ["bajo", "bajo"]


async def test_dos_ventas_seguidas_por_debajo_del_minimo_emiten_una_sola_alerta(
    sesion, semilla, pg_platform_url
):
    """El escenario anti-spam firmado: la cola de sync con varias ventas del
    mismo producto NO manda una notificación por venta. Aquí por el camino
    real del sync (VentasService), no por el helper."""
    def venta(consecutivo: int, cantidad: str, total: int) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "tipo": "venta.crear",
            "secuencia": consecutivo,
            "datos": {
                "consecutivo_local": consecutivo,
                "medio_pago": "efectivo",
                "total_centavos": total,
                "creada_en_cliente": "2026-07-28T10:00:00+00:00",
                "items": [{"producto_id": str(semilla["producto"]), "cantidad": cantidad, "precio_unitario_centavos": 2500}],
            },
        }

    servicio = VentasService(session=sesion, tenant_id=T1, actor_id="cajero-prueba", puede_anular=False)
    # Primera venta: 10 → 3 (ok → bajo, EMITE). Segunda, ya por debajo del
    # mínimo: 3 → 2.5 (bajo → bajo, NO emite). El umbral se cruzó UNA vez.
    lote = LoteSync.model_validate(
        {"dispositivo_id": str(semilla["dispositivo"]), "operaciones": [venta(1, "7", 17500), venta(2, "0.5", 1250)]}
    )
    resultados = await servicio.procesar_lote(lote)
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada"]
    await sesion.commit()
    assert await _alertas(pg_platform_url) == ["bajo"]


async def test_la_operacion_duplicada_no_reemite_la_alerta(sesion, semilla, pg_platform_url):
    """Anti-duplicado por construcción (decisión 14): el reintento del mismo
    lote es `duplicada` antes de mover stock, así que jamás llega a la
    emisión."""
    operacion = {
        "id": str(uuid.uuid4()),
        "tipo": "venta.crear",
        "secuencia": 1,
        "datos": {
            "consecutivo_local": 1,
            "medio_pago": "efectivo",
            "total_centavos": 17500,
            "creada_en_cliente": "2026-07-28T10:00:00+00:00",
            "items": [{"producto_id": str(semilla["producto"]), "cantidad": "7", "precio_unitario_centavos": 2500}],
        },
    }
    servicio = VentasService(session=sesion, tenant_id=T1, actor_id="cajero-prueba", puede_anular=False)
    lote = LoteSync.model_validate({"dispositivo_id": str(semilla["dispositivo"]), "operaciones": [operacion]})
    await servicio.procesar_lote(lote)
    await sesion.commit()
    reintento = await servicio.procesar_lote(lote)
    assert reintento[0].resultado == "duplicada"
    await sesion.commit()
    assert await _alertas(pg_platform_url) == ["bajo"]  # 10 → 3: una sola, no dos
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_inventario_alertas.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.inventario.stock'
```

- [ ] **Paso 2: escribir el punto único.** Crear `backend/services/api/app/modules/inventario/stock.py`:

```python
"""El punto ÚNICO por el que se aplica un movimiento de stock (decisión 1).

Todo cambio de inventario —venta, anulación, compra, ajuste, merma— pasa por
`aplicar_movimiento`: inserta la fila del libro, actualiza la proyección
`stock_actual` y evalúa el cruce de umbral. Si la evaluación viviera en cada
punto de aplicación serían cinco copias del mismo `if` esperando a que
alguien olvide una; aquí es estructuralmente imposible mover stock sin
evaluar la alerta.

## El nivel se DERIVA, no se persiste (decisión 2)

Quien llama tiene la fila del producto bloqueada `FOR UPDATE`, así que
`stock_actual` antes del delta ES el estado exacto post-commit del movimiento
anterior: comparar `nivel(antes)` con `nivel(después)` con la función pura
basta. Una columna `nivel_anterior` sería estado redundante capaz de derivar
(quedaría stale al editar `stock_minimo`, que cambia el nivel sin movimiento).

## El evento solo al cruzar hacia abajo (ADR-020)

`inventario.alerta_stock` se emite cuando el nivel EMPEORA. Nunca por
movimiento (una cola de 40 ventas del mismo producto mandaría 40 push
idénticas), nunca al recuperarse (la compra que repone no alerta: re-arma el
umbral), nunca dos veces por el mismo cruce (el siguiente movimiento lee el
nivel ya empeorado como su «antes»). Payload mínimo, sin PII (decisión 13).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalogo.models import Producto
from app.modules.ventas.models import MovimientoInventario
from vendi_core.events.service import DomainEventService

logger = structlog.get_logger()

#: Los cuatro niveles derivados de `stock_minimo` (ADR-020). El orden de
#: `_SEVERIDAD` es el criterio de «empeora»: agotado > crítico > bajo > ok.
NIVELES_DE_STOCK: tuple[str, ...] = ("ok", "bajo", "critico", "agotado")

_SEVERIDAD: dict[str, int] = {"ok": 0, "bajo": 1, "critico": 2, "agotado": 3}


def nivel_de_stock(stock: Decimal, stock_minimo: Decimal) -> str:
    """El nivel de un stock dado su mínimo. Función pura: la misma que usa el
    endpoint de estado de stock, para que lo que la app muestra y lo que
    dispara la alerta sea una sola definición.

    ADR-020 literal: agotado (`<= 0`), crítico (`< stock_minimo / 2`), bajo
    (`< stock_minimo`). Los bordes son estrictos: el mínimo exacto es `ok` y
    la mitad exacta es `bajo`. Con `stock_minimo = 0` no hay bajo ni crítico:
    el primer nivel alcanzable es el agotado del cero."""
    if stock <= 0:
        return "agotado"
    if stock < stock_minimo / 2:
        return "critico"
    if stock < stock_minimo:
        return "bajo"
    return "ok"


async def aplicar_movimiento(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    producto: Producto,
    delta: Decimal,
    tipo: str,
    referencia_id: uuid.UUID,
) -> None:
    """Un movimiento en el libro + la proyección + la alerta si cruza, todo
    en la transacción del llamante (ADR-020).

    El signo lo pone quien llama (la venta descuenta, la compra suma). El
    stock puede quedar negativo y es legítimo. Quien llama cargó el producto
    con `with_for_update=True`: el read-modify-write de `stock_actual` —y la
    comparación antes/después del nivel— solo son seguros con la fila
    bloqueada hasta el commit. El evento viaja en la misma transacción: un
    rollback se lleva el movimiento Y la alerta (decisión 14).
    """
    antes = nivel_de_stock(producto.stock_actual, producto.stock_minimo)
    session.add(
        MovimientoInventario(
            tenant_id=tenant_id,
            tipo=tipo,
            cantidad=delta,
            referencia_id=referencia_id,
            producto_id=producto.id,
        )
    )
    producto.stock_actual += delta
    despues = nivel_de_stock(producto.stock_actual, producto.stock_minimo)
    if _SEVERIDAD[despues] > _SEVERIDAD[antes]:
        await DomainEventService.emit(
            session,
            tenant_id=tenant_id,
            event_name="inventario.alerta_stock",
            resource_type="producto",
            resource_id=str(producto.id),
            data={
                "producto_id": str(producto.id),
                "nivel": despues,
                "stock_actual": str(producto.stock_actual),
                "stock_minimo": str(producto.stock_minimo),
            },
        )
        logger.info(
            "alerta_stock_emitida",
            producto_id=str(producto.id),
            nivel_antes=antes,
            nivel_despues=despues,
        )
```

- [ ] **Paso 3: refactorizar `VentasService._mover_stock` para delegar.** En `backend/services/api/app/modules/ventas/service.py`, reemplazar el método `_mover_stock` completo por:

```python
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
```

y añadir el import en la cabecera del archivo, tras el import de los modelos de ventas:

```python
from app.modules.inventario.stock import aplicar_movimiento
```

(El cuerpo viejo —el `session.add(MovimientoInventario(...))` y el `producto.stock_actual += delta`— desaparece: ahora lo hace el helper. El import de `MovimientoInventario` en `ventas/service.py` queda sin uso; quitarlo del import de modelos.)

- [ ] **Paso 4: actualizar los tests de ventas que lo notan (decisión 12).**

En `backend/tests/test_ventas_servicio.py`, en la tupla `BORRADO`, reemplazar la línea del outbox por las dos claves:

```python
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.inventario.%'",
```

y reforzar `test_el_stock_puede_quedar_negativo_y_la_venta_se_acepta` añadiendo al final (tras el assert del stock negativo):

```python
    # Desde el módulo 3 (cierre de D-12), el negativo además NOTIFICA: cruzar
    # a agotado emitió exactamente una alerta con el payload mínimo.
    alertas = await _uno(
        pg_platform_url,
        "SELECT payload->'data'->>'nivel' AS nivel FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.inventario.alerta_stock",
    )
    assert alertas.nivel == "agotado"
```

En `backend/tests/test_sync_idempotente.py`, misma adición a su `BORRADO` (la línea `%.inventario.%` tras la de `%.venta.%`).

- [ ] **Paso 5: verificar.**

```bash
cd backend && uv run pytest tests/test_inventario_alertas.py -q
# Esperado: 14 passed (10 de la función pura parametrizada + 4 de cruce)
uv run pytest tests/test_ventas_servicio.py tests/test_sync_idempotente.py tests/test_ventas_fixes_qa.py -q
# Esperado: toda la suite de ventas verde, con el test del negativo reforzado
uv run pytest -q -m integration
# Esperado: verde, 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 6: commit**

```bash
git add backend/services/api/app/modules/inventario/stock.py backend/services/api/app/modules/ventas/service.py backend/tests/test_inventario_alertas.py backend/tests/test_ventas_servicio.py backend/tests/test_sync_idempotente.py
git commit -m "Alertas de umbral en el punto único de movimientos de stock; ventas delega en él"
```

**Criterios de aceptación:** el nivel se deriva con los bordes exactos de ADR-020 (mínimo exacto = ok, mitad exacta = bajo, cero y negativo = agotado); cruzar hacia abajo emite un evento por cruce y nunca por movimiento; recuperarse no emite y re-arma el umbral (segundo cruce = segundo evento); dos ventas seguidas por debajo del mínimo por el sync emiten UNA alerta; la operación `duplicada` no re-emite; la suite de ventas completa sigue verde con el stock negativo ahora notificando; 0 SKIPPED.

---

## Tarea 6: Servicio de inventario (`InventarioService`)

**Files:**
- Create: `backend/tests/test_inventario_servicio.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/inventario/service.py`

**Interfaces:**
- Consume: `aplicar_movimiento` / `nivel_de_stock` de `inventario.stock`, los modelos y schemas de las Tareas 2-3, `DomainEventService.emit`, los errores de `vendi_core.errors.domain`.
- Produce: `InventarioService(session, tenant_id, actor_id)` con `registrar_compra`, `obtener_compra`, `listar_compras`, `registrar_ajuste`, `listar_ajustes`, `estado_stock`.

- [ ] **Paso 1: escribir los tests de servicio que fallan.** Crear `backend/tests/test_inventario_servicio.py`:

```python
"""`InventarioService` contra el PostgreSQL real, con el rol `vendi_app`.

Misma regla que `test_ventas_servicio.py`: la base no se dobla. Aquí se fijan
los comportamientos firmados del módulo: la compra que mueve stock, costo y
evento en una transacción; el ajuste online cuyo delta se calcula contra el
stock del servidor; la idempotencia por UUID de cliente; la invariante del
libro de ADR-020.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.inventario.schemas import AjusteCrear, CompraCrear
from app.modules.inventario.service import InventarioService
from app.modules.inventario.stock import aplicar_movimiento
from app.modules.catalogo.models import Producto
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import ConflictError, NotFoundError, ValidationError
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

BORRADO = (
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compra_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM compras WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ajustes_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.inventario.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.compra.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """T1: producto stock 10 mínimo 4, y producto2 stock 3 mínimo 0.
    T2: un producto propio (para las pruebas de aislamiento)."""
    ids = {"producto": uuid.uuid4(), "producto2": uuid.uuid4(), "ajeno": uuid.uuid4()}
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual, stock_minimo) "
                 "VALUES (:p, :t, 'Arroz 500g', 2500, 10, 4)"),
            {"p": ids["producto"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                 "VALUES (:p, :t, 'Huevo und', 600, 3)"),
            {"p": ids["producto2"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                 "VALUES (:p, :t, 'Panela', 1800, 7)"),
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
            yield InventarioService(session=s, tenant_id=T1, actor_id="almacenista-prueba")
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


def _compra(semilla: dict, compra_id: uuid.UUID | None = None, cantidad: str = "10", costo: int = 2000, **cambios) -> CompraCrear:
    cuerpo = {
        "proveedor_nombre": "Distribuidora La 33",
        "items": [{"producto_id": str(semilla["producto"]), "cantidad": cantidad, "costo_unitario_centavos": costo}],
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


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


# --- Compras ---------------------------------------------------------------------


async def test_registrar_compra_mueve_stock_actualiza_ultimo_costo_y_emite_evento(servicio, semilla, pg_platform_url):
    compra = await servicio.registrar_compra(_compra(semilla, uuid.uuid4()))
    await servicio._session.commit()

    producto = await _uno(
        pg_platform_url,
        "SELECT stock_actual, ultimo_costo FROM productos WHERE id = :p",
        p=semilla["producto"],
    )
    assert producto.stock_actual == 20  # 10 + 10
    assert producto.ultimo_costo == 2000  # lo que costó ESTA compra (ADR-020: lo costea el P&L)
    movimiento = await _uno(
        pg_platform_url,
        "SELECT tipo, cantidad, referencia_id FROM movimientos_inventario WHERE tenant_id = :t",
        t=T1,
    )
    assert (movimiento.tipo, movimiento.cantidad, movimiento.referencia_id) == ("compra", 10, compra.id)
    evento = await _uno(
        pg_platform_url,
        "SELECT payload->'data'->>'total_centavos' AS total FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.compra.registrada",
    )
    assert evento.total == "20000"


async def test_el_total_de_la_compra_lo_calcula_el_servidor_por_linea(servicio, semilla):
    """Granel: 0.333 kg × $1.00 = 33.3 centavos → la línea redondea a 33
    (ROUND_HALF_UP, decisión 7) y el total es la suma de las líneas."""
    compra = await servicio.registrar_compra(
        _compra(
            semilla,
            uuid.uuid4(),
            cantidad="0.333",
            costo=100,
            items=[
                {"producto_id": str(semilla["producto"]), "cantidad": "0.333", "costo_unitario_centavos": 100},
                {"producto_id": str(semilla["producto2"]), "cantidad": "2", "costo_unitario_centavos": 550},
            ],
        )
    )
    assert compra.total_centavos == 33 + 1100


async def test_registrar_compra_es_idempotente_por_el_id_del_cliente(servicio, semilla, pg_platform_url):
    el_id = uuid.uuid4()
    primera = await servicio.registrar_compra(_compra(semilla, el_id))
    await servicio._session.commit()
    segunda = await servicio.registrar_compra(_compra(semilla, el_id))
    await servicio._session.commit()

    assert segunda.id == primera.id == el_id
    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM movimientos_inventario WHERE tenant_id = :t) AS movimientos, "
        "(SELECT count(*) FROM outbox_messages WHERE routing_key = :k) AS eventos, "
        "(SELECT stock_actual FROM productos WHERE id = :p) AS stock",
        t=T1, k=f"{T1}.compra.registrada", p=semilla["producto"],
    )
    assert (fila.movimientos, fila.eventos, fila.stock) == (1, 1, 20)  # ni doble stock ni doble evento


async def test_compra_con_producto_de_otro_negocio_es_422_sin_fuga(servicio, semilla):
    """La RLS hace invisible el producto de T2: mismo veredicto que uno
    inexistente (criterio `padre_no_encontrado` del catálogo)."""
    with pytest.raises(ValidationError) as exc:
        await servicio.registrar_compra(
            _compra(semilla, uuid.uuid4(), items=[{"producto_id": str(semilla["ajeno"]), "cantidad": "1", "costo_unitario_centavos": 100}])
        )
    assert exc.value.code == "producto_no_encontrado"


async def test_compra_sobre_producto_dado_de_baja_es_422(servicio, semilla, pg_platform_url):
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE productos SET deleted_at = now() WHERE id = :p"), {"p": semilla["producto"]})
    await engine.dispose()
    with pytest.raises(ValidationError) as exc:
        await servicio.registrar_compra(_compra(semilla, uuid.uuid4()))
    assert exc.value.code == "producto_no_encontrado"


async def test_dos_compras_concurrentes_del_mismo_producto_dejan_el_stock_exacto(pg_app_url, semilla, pg_platform_url):
    """La carrera de la proyección: sin FOR UPDATE, las dos sesiones leerían el
    MISMO stock y el segundo commit pisaría al primero. Con el bloqueo, el
    perdedor espera y re-lee (fix `49553da` de ventas, misma disciplina)."""
    async def compra_con_sesion_propia(cantidad: str) -> None:
        engine = create_engine(pg_app_url)
        factory = create_session_factory(engine)
        marca = current_tenant_id.set(T1)
        try:
            async with factory() as s:
                servicio = InventarioService(session=s, tenant_id=T1, actor_id="almacenista-prueba")
                await servicio.registrar_compra(_compra(semilla, uuid.uuid4(), cantidad=cantidad))
                await s.commit()
        finally:
            current_tenant_id.reset(marca)
            await engine.dispose()

    await asyncio.gather(compra_con_sesion_propia("5"), compra_con_sesion_propia("7"))
    fila = await _uno(
        pg_platform_url,
        "SELECT stock_actual FROM productos WHERE id = :p",
        p=semilla["producto"],
    )
    assert fila.stock_actual == 22  # 10 + 5 + 7, ni una unidad perdida


async def test_comprar_no_emite_alerta_aunque_salga_del_rojo(servicio, semilla, pg_platform_url):
    """La compra que repone el stock MEJORA el nivel: no alerta (ADR-020: el
    evento es solo al cruzar hacia abajo); lo que hace es re-armar el umbral."""
    # Primero, una venta deja el producto en bajo (y emite su alerta).
    producto = await servicio._session.get(Producto, semilla["producto"], with_for_update=True)
    await aplicar_movimiento(
        servicio._session, tenant_id=T1, producto=producto, delta=Decimal("-7"), tipo="venta", referencia_id=uuid.uuid4()
    )
    await servicio._session.commit()
    await servicio.registrar_compra(_compra(semilla, uuid.uuid4()))
    await servicio._session.commit()
    fila = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n FROM outbox_messages WHERE routing_key = :k",
        k=f"{T1}.inventario.alerta_stock",
    )
    assert fila.n == 1  # solo la del cruce hacia abajo; la compra no sumó


# --- Ajustes y mermas ---------------------------------------------------------------


async def test_el_ajuste_calcula_el_delta_contra_el_stock_del_servidor(servicio, semilla, pg_platform_url):
    """ADR-020: «conté 8, el sistema dice 10» → delta -2 calculado AQUÍ, no
    en el cliente. Por eso el ajuste es online: contra un stock viejo, el
    delta sería mentira."""
    creado = await servicio.registrar_ajuste(_ajuste(semilla, uuid.uuid4()))
    await servicio._session.commit()

    assert creado.delta == -2
    assert creado.stock_resultante == 8
    assert creado.nivel == "ok"  # 8 >= mínimo 4
    fila = await _uno(
        pg_platform_url,
        "SELECT tipo, cantidad, referencia_id FROM movimientos_inventario WHERE tenant_id = :t",
        t=T1,
    )
    assert (fila.tipo, fila.cantidad, fila.referencia_id) == ("ajuste", -2, creado.id)


async def test_el_ajuste_al_alza_es_un_movimiento_positivo(servicio, semilla, pg_platform_url):
    creado = await servicio.registrar_ajuste(_ajuste(semilla, uuid.uuid4(), stock_contado="14", motivo="Sobrante del conteo"))
    await servicio._session.commit()
    assert creado.delta == 4
    fila = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert fila.stock_actual == 14


async def test_el_conteo_que_cuadra_no_escribe_movimiento_pero_si_fila(servicio, semilla, pg_platform_url):
    """El caso que justifica la tabla (decisión 5): sin fila, el reintento de
    este ajuste sería inanclable. `ck_movimientos_cantidad_no_cero` prohíbe el
    movimiento de cero; la fila del ajuste queda como prueba."""
    creado = await servicio.registrar_ajuste(_ajuste(semilla, uuid.uuid4(), stock_contado="10", motivo="Cuadró el conteo"))
    await servicio._session.commit()
    assert creado.delta == 0
    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT count(*) FROM movimientos_inventario WHERE tenant_id = :t) AS movimientos, "
        "(SELECT count(*) FROM ajustes_inventario WHERE tenant_id = :t) AS ajustes",
        t=T1,
    )
    assert (fila.movimientos, fila.ajustes) == (0, 1)


async def test_el_reintento_del_ajuste_devuelve_lo_mismo_sin_mover_stock(servicio, semilla, pg_platform_url):
    el_id = uuid.uuid4()
    primero = await servicio.registrar_ajuste(_ajuste(semilla, el_id))
    await servicio._session.commit()
    segundo = await servicio.registrar_ajuste(_ajuste(semilla, el_id))
    await servicio._session.commit()
    assert segundo.id == primero.id
    assert segundo.delta == -2 and segundo.stock_resultante == 8
    fila = await _uno(
        pg_platform_url,
        "SELECT count(*) AS n, (SELECT stock_actual FROM productos WHERE id = :p) AS stock "
        "FROM movimientos_inventario WHERE tenant_id = :t",
        t=T1, p=semilla["producto"],
    )
    assert (fila.n, fila.stock) == (1, 8)  # el delta se aplicó UNA vez


async def test_el_mismo_id_de_ajuste_con_otro_payload_es_409(servicio, semilla):
    """La idempotencia NO es ciega a la divergencia (lección del QA): mismo id
    con otro conteo no es un reintento, es otro ajuste que alguien debe mirar."""
    el_id = uuid.uuid4()
    await servicio.registrar_ajuste(_ajuste(semilla, el_id))
    await servicio._session.commit()
    with pytest.raises(ConflictError) as exc:
        await servicio.registrar_ajuste(_ajuste(semilla, el_id, stock_contado="5"))
    assert exc.value.code == "ajuste_id_divergente"
    assert "stock_contado" in exc.value.details["campos"]


async def test_la_merma_descuenta_y_su_reintento_no_descuenta_dos_veces(servicio, semilla, pg_platform_url):
    """La merma es el caso que hace el `id` REQUERIDO (decisión 4): es un
    delta relativo, y sin ancla el reintento la aplicaría dos veces."""
    el_id = uuid.uuid4()
    datos = _ajuste(semilla, el_id, tipo="merma", cantidad="3", stock_contado=None, motivo="Se dañó con la nevera apagada")
    creado = await servicio.registrar_ajuste(datos)
    await servicio._session.commit()
    assert creado.delta == -3 and creado.nivel == "ok"  # 10 → 7, con mínimo 4: sigue ok
    await servicio.registrar_ajuste(datos)  # reintento byte-idéntico
    await servicio._session.commit()
    fila = await _uno(
        pg_platform_url,
        "SELECT cantidad, tipo FROM movimientos_inventario WHERE tenant_id = :t",
        t=T1,
    )
    assert (fila.tipo, fila.cantidad) == ("merma", -3)
    stock = await _uno(pg_platform_url, "SELECT stock_actual FROM productos WHERE id = :p", p=semilla["producto"])
    assert stock.stock_actual == 7


async def test_la_invariante_del_libro_tras_una_secuencia_mezclada(servicio, semilla, pg_platform_url):
    """El candado de ADR-020: tras ventas, una compra, una merma y un ajuste,
    `stock_actual = SUM(cantidad de los movimientos)`."""
    producto_id = semilla["producto"]
    # Venta -3 (por el punto único, como la aplicaría el sync).
    producto = await servicio._session.get(Producto, producto_id, with_for_update=True)
    await aplicar_movimiento(
        servicio._session, tenant_id=T1, producto=producto, delta=Decimal("-3"), tipo="venta", referencia_id=uuid.uuid4()
    )
    await servicio.registrar_compra(_compra(semilla, uuid.uuid4(), cantidad="10"))   # +10
    await servicio.registrar_ajuste(
        _ajuste(semilla, uuid.uuid4(), tipo="merma", cantidad="2", stock_contado=None, motivo="Roto en transporte")
    )  # -2
    await servicio.registrar_ajuste(_ajuste(semilla, uuid.uuid4(), stock_contado="20", motivo="Reconteo general"))  # → 20
    await servicio._session.commit()

    fila = await _uno(
        pg_platform_url,
        "SELECT (SELECT stock_actual FROM productos WHERE id = :p) AS proyeccion, "
        "(SELECT COALESCE(SUM(cantidad), 0) FROM movimientos_inventario WHERE tenant_id = :t AND producto_id = :p) AS libro",
        t=T1, p=producto_id,
    )
    # 10 (inicial) - 3 + 10 - 2 = 15; el ajuste a 20 aplica +5 → 20 = SUM.
    assert fila.proyeccion == 20 == fila.libro


# --- Estado de stock ------------------------------------------------------------------


async def test_el_estado_de_stock_deriva_el_nivel_y_filtra_las_alertas(servicio, semilla):
    # Arroz: 10 con mínimo 4 → ok. Huevo: 3 con mínimo 0 → ok. Un ajuste deja
    # el huevo en 0 → agotado.
    await servicio.registrar_ajuste(
        _ajuste(semilla, uuid.uuid4(), producto_id=str(semilla["producto2"]), stock_contado="0", motivo="No queda ninguno")
    )
    todo, total = await servicio.estado_stock()
    assert total == 2
    niveles = {s.nombre: s.nivel for s in todo}
    assert niveles == {"Arroz 500g": "ok", "Huevo und": "agotado"}
    alertas, total_alertas = await servicio.estado_stock(solo_alertas=True)
    assert total_alertas == 1
    assert alertas[0].nombre == "Huevo und" and alertas[0].stock_actual == 0


async def test_obtener_compra_devuelve_sus_items_y_la_desconocida_es_404(servicio, semilla):
    compra = await servicio.registrar_compra(_compra(semilla, uuid.uuid4()))
    await servicio._session.commit()
    hallada, items = await servicio.obtener_compra(compra.id)
    assert hallada.id == compra.id
    assert [(i.producto_id, i.cantidad, i.costo_unitario_centavos) for i in items] == [
        (semilla["producto"], Decimal("10.000"), 2000)
    ]
    with pytest.raises(NotFoundError) as exc:
        await servicio.obtener_compra(uuid.uuid4())
    assert exc.value.code == "compra_no_encontrada"
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_inventario_servicio.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.inventario.service'
```

- [ ] **Paso 2: escribir el servicio.** Crear `backend/services/api/app/modules/inventario/service.py`:

```python
"""Servicio de inventario: compras, ajustes y estado de stock (ADR-020).

## RLS hace el aislamiento; el servicio NO filtra por `tenant_id` a mano

Todo corre en la sesión de tenant (`vendi_app` + GUC `vendi.tenant_id`): la
policy `tenant_isolation` acota lecturas y escrituras, y el `WITH CHECK`
rechaza un `tenant_id` inyectado. Los schemas llevan `extra="forbid"`, así
que el payload ni siquiera acepta el campo.

## ONLINE, no sync (decisión 3)

Compras y ajustes son gestos síncronos del usuario con respuesta HTTP
(201/404/409/422), no operaciones de la cola del dispositivo. El ajuste es
online-obligatorio por ADR-020: su delta se calcula contra el `stock_actual`
del servidor EN ESTE MOMENTO, con la fila del producto bloqueada FOR UPDATE.
Un ajuste offline llegaría con un delta calculado contra un stock viejo y
corrompería el contador de forma no conmutativa.

## Idempotencia: la fila es la prueba (ADR-017)

La compra acepta el UUID del cliente como PK (opcional, como el catálogo); el
ajuste lo EXIGE (decisión 4: la merma es un delta relativo y solo la ancla
hace seguro su reintento). El ajuste se graba SIEMPRE, incluso con delta
cero (decisión 5): es la prueba de idempotencia del conteo que cuadró. La
red final la ponen las constraints (`compras`/`ajustes_inventario` pkey,
`ux_movimientos_origen`).

## Los eventos viajan en la transacción del llamante

El servicio hace `flush` pero NUNCA `commit`: confirma la dependencia
`sesion_de_tenant` al final del request (o el test), y con ella la compra,
los movimientos, el stock y los eventos del outbox — la garantía del patrón.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

import structlog
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalogo.models import Producto
from app.modules.inventario.models import AjusteInventario, Compra, CompraItem
from app.modules.inventario.schemas import AjusteCreado, AjusteCrear, CompraCrear, StockSalida
from app.modules.inventario.stock import aplicar_movimiento, nivel_de_stock
from vendi_core.errors.domain import ConflictError, NotFoundError, ValidationError
from vendi_core.events.service import DomainEventService

logger = structlog.get_logger()

#: Campos cuya divergencia convierte un reintento de ajuste en 409 (mismo
#: criterio que `_CAMPOS_DEL_HECHO` de ventas): si alguno difiere, NO es un
#: reintento — es otro ajuste con el mismo id, y alguien tiene que mirarlo.
_CAMPOS_DEL_AJUSTE = ("tipo", "producto_id", "stock_contado", "cantidad", "motivo")


class InventarioService:
    """Operaciones de inventario de UN negocio: el del GUC de la sesión."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: str):
        self._session = session
        self._tenant_id = tenant_id
        self._actor_id = actor_id

    # --- Compras ----------------------------------------------------------------

    async def registrar_compra(self, datos: CompraCrear) -> Compra:
        """Registra la compra y, en la MISMA transacción: sus ítems, un
        movimiento `compra` por línea, la proyección `stock_actual` y
        `ultimo_costo` de cada producto, y el evento `compra.registrada`
        (ADR-020). Idempotente por el UUID del cliente: reenviar la misma
        compra devuelve la existente sin duplicar fila, stock ni evento."""
        if datos.id is not None:
            existente = await self._session.get(Compra, datos.id)
            if existente is not None:
                logger.info("compra_registrada_idempotente", compra_id=str(existente.id))
                return existente

        # El total lo calcula el servidor por línea (decisión 7): la línea se
        # cuantiza a centavos enteros y el total es la suma de las líneas.
        total = 0
        for item in datos.items:
            linea = (item.cantidad * item.costo_unitario_centavos).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            total += int(linea)

        compra = Compra(
            tenant_id=self._tenant_id,
            proveedor_nombre=datos.proveedor_nombre,
            fecha=datos.fecha or datetime.now(UTC).date(),
            observaciones=datos.observaciones,
            total_centavos=total,
        )
        if datos.id is not None:
            compra.id = datos.id
        self._session.add(compra)
        await self._flush_traduciendo_integridad()

        for item in sorted(datos.items, key=lambda i: i.producto_id):
            # Ordenados por producto_id (decisión 9): dos compras concurrentes
            # con productos solapados adquieren los bloqueos en el MISMO orden
            # y no se interbloquean.
            self._session.add(
                CompraItem(
                    tenant_id=self._tenant_id,
                    compra_id=compra.id,
                    producto_id=item.producto_id,
                    cantidad=item.cantidad,
                    costo_unitario_centavos=item.costo_unitario_centavos,
                )
            )
            producto = await self._producto_bloqueado(item.producto_id)
            await aplicar_movimiento(
                self._session,
                tenant_id=self._tenant_id,
                producto=producto,
                delta=item.cantidad,
                tipo="compra",
                referencia_id=compra.id,
            )
            # Lo que el P&L costea (ADR-006/020): el costo de la ÚLTIMA compra.
            producto.ultimo_costo = item.costo_unitario_centavos

        await DomainEventService.emit(
            self._session,
            tenant_id=self._tenant_id,
            event_name="compra.registrada",
            resource_type="compra",
            resource_id=str(compra.id),
            data={
                "compra_id": str(compra.id),
                "proveedor_nombre": compra.proveedor_nombre,
                "fecha": compra.fecha.isoformat(),
                "total_centavos": compra.total_centavos,
                "items": [
                    {
                        "producto_id": str(i.producto_id),
                        "cantidad": str(i.cantidad),
                        "costo_unitario_centavos": i.costo_unitario_centavos,
                    }
                    for i in datos.items
                ],
            },
        )
        logger.info("compra_registrada", compra_id=str(compra.id), total_centavos=compra.total_centavos)
        return compra

    async def obtener_compra(self, compra_id: uuid.UUID) -> tuple[Compra, list[CompraItem]]:
        compra = await self._session.get(Compra, compra_id)
        if compra is None:
            # Un id de otro negocio da el mismo 404 que uno inexistente: la
            # RLS lo hace invisible y no hay nada que filtrar.
            raise NotFoundError("La compra no existe.", code="compra_no_encontrada")
        items = (
            (await self._session.execute(select(CompraItem).where(CompraItem.compra_id == compra.id)))
            .scalars()
            .all()
        )
        return compra, list(items)

    async def listar_compras(self, *, skip: int = 0, limit: int = 25) -> tuple[list[Compra], int]:
        total = (await self._session.execute(select(func.count()).select_from(Compra))).scalar_one()
        filas = (
            (
                await self._session.execute(
                    select(Compra).order_by(Compra.created_at.desc(), Compra.id).offset(skip).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(filas), int(total)

    # --- Ajustes y mermas ----------------------------------------------------------

    async def registrar_ajuste(self, datos: AjusteCrear) -> AjusteCreado:
        """Ajuste por conteo o merma, ONLINE (ADR-020). El delta se calcula
        contra el stock del servidor con la fila bloqueada FOR UPDATE:
        `stock_contado - stock_actual` en el ajuste; `-cantidad` en la merma.

        La fila del ajuste se graba SIEMPRE (incluso con delta cero: es la
        prueba de idempotencia, decisión 5). El movimiento del libro solo se
        escribe si delta ≠ 0 (`ck_movimientos_cantidad_no_cero`), con
        `referencia_id = ajuste.id`. Si el delta cruza un umbral hacia abajo,
        `aplicar_movimiento` emite la alerta en esta misma transacción."""
        producto = await self._producto_bloqueado(datos.producto_id)

        existente = await self._session.get(AjusteInventario, datos.id)
        if existente is not None:
            return self._reintento_de_ajuste(existente, datos, producto)

        if datos.tipo == "ajuste":
            assert datos.stock_contado is not None  # lo garantiza el schema
            delta = datos.stock_contado - producto.stock_actual
        else:
            assert datos.cantidad is not None
            delta = -datos.cantidad

        ajuste = AjusteInventario(
            id=datos.id,
            tenant_id=self._tenant_id,
            producto_id=datos.producto_id,
            tipo=datos.tipo,
            stock_contado=datos.stock_contado,
            cantidad=datos.cantidad,
            delta=delta,
            motivo=datos.motivo,
            aplicado_por=self._actor_id,
            stock_resultante=producto.stock_actual + delta,
        )
        self._session.add(ajuste)
        if delta != 0:
            await aplicar_movimiento(
                self._session,
                tenant_id=self._tenant_id,
                producto=producto,
                delta=delta,
                tipo=datos.tipo,
                referencia_id=ajuste.id,
            )
        await self._flush_traduciendo_integridad()
        logger.info("ajuste_registrado", ajuste_id=str(ajuste.id), tipo=ajuste.tipo, delta=str(delta))
        return self._salida(ajuste, producto)

    async def listar_ajustes(self, *, skip: int = 0, limit: int = 25) -> tuple[list[AjusteInventario], int]:
        total = (await self._session.execute(select(func.count()).select_from(AjusteInventario))).scalar_one()
        filas = (
            (
                await self._session.execute(
                    select(AjusteInventario)
                    .order_by(AjusteInventario.created_at.desc(), AjusteInventario.id)
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(filas), int(total)

    # --- Estado de stock ------------------------------------------------------------

    async def estado_stock(self, *, skip: int = 0, limit: int = 50, solo_alertas: bool = False) -> tuple[list[StockSalida], int]:
        """El stock de cada producto con su nivel derivado (decisión 2: una
        sola función define el umbral — la misma que dispara la alerta).

        `solo_alertas=True` filtra en SQL lo que la app muestra como lista de
        pendientes: agotados (`stock <= 0`) o por debajo del mínimo. El orden
        es el de urgencia: agotados primero, luego por déficit."""
        base = select(Producto).where(Producto.deleted_at.is_(None))
        conteo = select(func.count()).select_from(Producto).where(Producto.deleted_at.is_(None))
        if solo_alertas:
            en_alerta = or_(
                Producto.stock_actual <= 0,
                and_(Producto.stock_minimo > 0, Producto.stock_actual < Producto.stock_minimo),
            )
            base = base.where(en_alerta)
            conteo = conteo.where(en_alerta)
        total = (await self._session.execute(conteo)).scalar_one()
        filas = (
            (
                await self._session.execute(
                    base.order_by(
                        (Producto.stock_actual <= 0).desc(),
                        (Producto.stock_actual - Producto.stock_minimo).asc(),
                        Producto.nombre,
                    )
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return (
            [
                StockSalida(
                    producto_id=f.id,
                    nombre=f.nombre,
                    stock_actual=f.stock_actual,
                    stock_minimo=f.stock_minimo,
                    nivel=nivel_de_stock(f.stock_actual, f.stock_minimo),
                )
                for f in filas
            ],
            int(total),
        )

    # --- Internas ----------------------------------------------------------------

    async def _producto_bloqueado(self, producto_id: uuid.UUID) -> Producto:
        """SELECT ... FOR UPDATE sobre la fila del producto: el read-modify-write
        de `stock_actual` y la comparación de nivel antes/después solo son
        seguros con la fila bloqueada hasta el commit (el lost update que el
        fix `49553da` cerró en ventas). Un producto de otro negocio es
        invisible por RLS y un dado de baja no se reabastece: mismo 422."""
        producto = await self._session.get(Producto, producto_id, with_for_update=True)
        if producto is None or producto.deleted_at is not None:
            raise ValidationError(
                "Uno de los productos no existe en tu negocio.",
                code="producto_no_encontrado",
                details={"producto_id": str(producto_id)},
            )
        return producto

    def _reintento_de_ajuste(self, existente: AjusteInventario, datos: AjusteCrear, producto: Producto) -> AjusteCreado:
        """El id ya existe: ¿es el MISMO ajuste? Payload idéntico → se
        devuelve lo que se respondió la primera vez (el reintento legítimo,
        sin mover stock otra vez). Cualquier campo distinto → 409 con los
        campos que difieren (lección de divergencia del QA): jamás un no-op
        silencioso cuando hay stock de por medio."""
        divergentes: list[str] = []
        for campo in _CAMPOS_DEL_AJUSTE:
            guardado = getattr(existente, campo)
            enviado = getattr(datos, campo)
            if str(guardado) != str(enviado) and not (
                isinstance(guardado, Decimal) and isinstance(enviado, Decimal) and guardado == enviado
            ):
                divergentes.append(campo)
        if divergentes:
            raise ConflictError(
                "Ese id de ajuste ya existe con datos distintos. El servidor conserva la primera versión.",
                code="ajuste_id_divergente",
                details={"campos": divergentes},
            )
        logger.info("ajuste_registrado_idempotente", ajuste_id=str(existente.id))
        return self._salida(existente, producto)

    @staticmethod
    def _salida(ajuste: AjusteInventario, producto: Producto) -> AjusteCreado:
        return AjusteCreado(
            id=ajuste.id,
            tipo=ajuste.tipo,
            producto_id=ajuste.producto_id,
            stock_contado=ajuste.stock_contado,
            cantidad=ajuste.cantidad,
            delta=ajuste.delta,
            motivo=ajuste.motivo,
            aplicado_por=ajuste.aplicado_por,
            stock_resultante=ajuste.stock_resultante,
            created_at=ajuste.created_at,
            nivel=nivel_de_stock(ajuste.stock_resultante, producto.stock_minimo),
        )

    async def _flush_traduciendo_integridad(self) -> None:
        """Las constraints son las de verdad; el servicio traduce su violación
        al sobre de errores de la API. Tras un `IntegrityError` la transacción
        queda abortada: quien llama (la dependencia o el test) hace rollback
        al propagar."""
        try:
            await self._session.flush()
        except IntegrityError as exc:
            detalle = str(exc)
            if "compras_pkey" in detalle:
                # El id venía del cliente y choca con una fila que la RLS no
                # le deja ver (de otro negocio) o con una carrera de dos altas.
                raise ConflictError("Ese id de compra ya existe.", code="compra_id_duplicado") from exc
            if "ajustes_inventario_pkey" in detalle:
                # Carrera de dos PRIMEROS intentos con el mismo id de cliente
                # (el reintento normal lo resuelve `_reintento_de_ajuste`
                # antes de llegar aquí). El perdedor recibe un 409 tipado, no
                # el 500 del IntegrityError.
                raise ConflictError("Ese id de ajuste ya existe.", code="ajuste_id_divergente") from exc
            raise
```

- [ ] **Paso 3: verificar.**

```bash
cd backend && uv run pytest tests/test_inventario_servicio.py -q
# Esperado: 16 passed
uv run pytest -q -m integration
# Esperado: verde, 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/inventario/service.py backend/tests/test_inventario_servicio.py
git commit -m "Servicio de inventario: compras que mueven stock y costo, ajustes online idempotentes y estado de stock"
```

**Criterios de aceptación:** los 16 tests de servicio pasan contra PostgreSQL real, 0 SKIPPED; la compra mueve stock + `ultimo_costo` + evento en una transacción y es idempotente por id de cliente; el ajuste calcula su delta contra el stock del servidor, graba fila aunque el delta sea cero, y su reintento idéntico es no-op y el divergente 409; la merma no se aplica dos veces; la invariante del libro se cumple tras la secuencia mezclada; la carrera de dos compras deja el stock exacto; un producto ajeno o dado de baja es 422 sin fuga; `ruff` limpio.

---

## Tarea 7: Dependencias, router y montaje en la app

**Files:**
- Create: `backend/tests/api/test_inventario_api.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/inventario/dependencies.py`
- Create: `backend/services/api/app/modules/inventario/router.py`
- Modify: `backend/services/api/app/factory.py` (importar y montar el router)
- Modify: `backend/tests/api/conftest.py` (la limpieza borra también las tablas nuevas — sin esto, la segunda corrida revienta contra las FK `RESTRICT` al borrar `productos`)

**Interfaces:**
- Consume: `exigir_permiso`, `sesion_de_tenant` de `app.dependencies`; `exigir_negocio_activo` de `app.modules.tenants.dependencies`; los permisos de la Tarea 4; `PagedList` de `vendi_core.models.pagination`; `ErrorResponse`.
- Produce: 6 rutas — `POST/GET /api/v1/compras`, `GET /api/v1/compras/{id}`, `POST/GET /api/v1/inventario/ajustes`, `GET /api/v1/inventario/stock` — con guards por permiso y sobre de error estándar.

- [ ] **Paso 1: escribir los tests de API que fallan.** Crear `backend/tests/api/test_inventario_api.py`:

```python
"""Los endpoints de inventario y compras contra el PostgreSQL real.

Misma regla que `test_ventas_sync.py`: la base no se dobla, y cada test crea
su negocio por el camino real y opera con tokens de roles distintos, porque
lo que se mide aquí es quién puede hacer qué (ADR-023): el cajero NO ajusta
ni compra ni ve costos; el almacenista y el dueño sí.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_con_rol, usuario_de_plataforma

from vendi_core.auth.policies import ROL_ALMACENISTA, ROL_CAJERO, ROL_DUENO

pytestmark = pytest.mark.integration


def _dec(valor) -> Decimal:
    """Las cantidades viajan como número JSON (`1.0`, no `"1.000"`): se
    comparan como Decimal, que es lo que son (mismo helper que
    `test_catalogo_productos.py`)."""
    return Decimal(str(valor))


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


def _alta_producto(cliente, cabeceras, stock_minimo: str = "0") -> str:
    respuesta = cliente.post(
        "/api/v1/productos",
        json={"nombre": "Arroz 500g", "precio_venta": 2500, "stock_minimo": stock_minimo},
        headers=cabeceras,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _compra(producto_id: str, **cambios) -> dict:
    cuerpo = {
        "proveedor_nombre": "Distribuidora La 33",
        "items": [{"producto_id": producto_id, "cantidad": "10", "costo_unitario_centavos": 2000}],
        **cambios,
    }
    return cuerpo


def _ajuste(producto_id: str, **cambios) -> dict:
    cuerpo = {
        "id": str(uuid.uuid4()),
        "tipo": "ajuste",
        "producto_id": producto_id,
        "stock_contado": "8",
        "motivo": "Conteo de cierre",
        **cambios,
    }
    return cuerpo


# --- Compras ---------------------------------------------------------------------


def test_registrar_compra_devuelve_201_con_total_calculado(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 1")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d1")
    producto = _alta_producto(cliente, cabeceras)

    respuesta = cliente.post("/api/v1/compras", json=_compra(producto), headers=cabeceras)

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["proveedor_nombre"] == "Distribuidora La 33"
    assert cuerpo["total_centavos"] == 20000  # lo calculó el servidor: el cliente no lo envió
    assert cuerpo["items"][0]["costo_unitario_centavos"] == 2000


def test_la_compra_es_idempotente_por_el_id_del_cliente(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 2")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d2")
    producto = _alta_producto(cliente, cabeceras)
    el_id = str(uuid.uuid4())

    primero = cliente.post("/api/v1/compras", json=_compra(producto, id=el_id), headers=cabeceras)
    segundo = cliente.post("/api/v1/compras", json=_compra(producto, id=el_id), headers=cabeceras)

    assert primero.status_code == 201 and segundo.status_code == 201
    assert segundo.json()["id"] == el_id
    detalle = cliente.get(f"/api/v1/compras/{el_id}", headers=cabeceras)
    assert detalle.status_code == 200 and detalle.json()["total_centavos"] == 20000


def test_el_cajero_no_compra_ni_ve_compras(app_con_base):
    """ADR-023: el cajero no tiene `compra:crear`, y como los costos son el
    margen del negocio, la consulta usa el MISMO permiso (decisión 10)."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 3")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c3")

    alta = cliente.post("/api/v1/compras", json=_compra(str(uuid.uuid4())), headers=cajero)
    assert alta.status_code == 403 and alta.json()["code"] == "permiso_ausente"
    lista = cliente.get("/api/v1/compras", headers=cajero)
    assert lista.status_code == 403 and lista.json()["code"] == "permiso_ausente"
    detalle = cliente.get(f"/api/v1/compras/{uuid.uuid4()}", headers=cajero)
    assert detalle.status_code == 403


def test_el_almacenista_compra_y_consulta(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 4")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a4")
    producto = _alta_producto(cliente, almacenista)

    alta = cliente.post("/api/v1/compras", json=_compra(producto), headers=almacenista)
    assert alta.status_code == 201
    lista = cliente.get("/api/v1/compras", headers=almacenista)
    assert lista.status_code == 200 and lista.json()["total"] == 1


def test_la_compra_de_otro_negocio_es_404_sin_fuga(app_con_base):
    cliente, validador, _ = app_con_base
    negocio_a = _crear_negocio(cliente, validador, "Inv 5A")
    negocio_b = _crear_negocio(cliente, validador, "Inv 5B")
    cab_a = _cabeceras_de(validador, ROL_DUENO, negocio_a, "tok-d5a")
    cab_b = _cabeceras_de(validador, ROL_DUENO, negocio_b, "tok-d5b")
    producto = _alta_producto(cliente, cab_a)
    compra_id = cliente.post("/api/v1/compras", json=_compra(producto), headers=cab_a).json()["id"]

    assert cliente.get(f"/api/v1/compras/{compra_id}", headers=cab_b).status_code == 404
    assert cliente.get("/api/v1/compras", headers=cab_b).json()["total"] == 0


def test_la_compra_valida_cotas_y_forma(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 6")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d6")
    producto = _alta_producto(cliente, cabeceras)

    # Costo que desborda Integer → 422, nunca 500 (lección BUG-2).
    assert cliente.post(
        "/api/v1/compras", json=_compra(producto, items=[{"producto_id": producto, "cantidad": "1", "costo_unitario_centavos": 2**31}]), headers=cabeceras
    ).status_code == 422
    # El mismo producto en dos líneas → 422 (decisión 8).
    assert cliente.post(
        "/api/v1/compras", json=_compra(producto, items=[{"producto_id": producto, "cantidad": "1", "costo_unitario_centavos": 100}, {"producto_id": producto, "cantidad": "2", "costo_unitario_centavos": 100}]), headers=cabeceras
    ).status_code == 422
    # Un tenant_id inyectado → 422 por extra="forbid".
    assert cliente.post("/api/v1/compras", json=_compra(producto, tenant_id=str(uuid.uuid4())), headers=cabeceras).status_code == 422


# --- Ajustes ---------------------------------------------------------------------


def test_registrar_ajuste_devuelve_201_con_delta_y_nivel(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 7")
    cabeceras = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a7")
    producto = _alta_producto(cliente, cabeceras, stock_minimo="4")
    cliente.post("/api/v1/compras", json=_compra(producto), headers=cabeceras)  # stock 10, mínimo 4

    respuesta = cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto, stock_contado="3"), headers=cabeceras)

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert _dec(cuerpo["delta"]) == Decimal("-7") and _dec(cuerpo["stock_resultante"]) == Decimal("3")
    assert cuerpo["nivel"] == "bajo"


def test_el_cajero_no_ajusta_ni_ve_ajustes(app_con_base):
    """ADR-023: ajustar stock es un gesto con el que se desfalca una tienda."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 8")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d8")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c8")
    producto = _alta_producto(cliente, dueno)

    assert cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto), headers=cajero).status_code == 403
    assert cliente.get("/api/v1/inventario/ajustes", headers=cajero).status_code == 403
    # Y el dueño sí ajusta (distingue «deniega porque no lo tiene» de «deniega siempre»).
    assert cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto), headers=dueno).status_code == 201


def test_el_ajuste_exige_motivo_y_la_forma_de_su_tipo(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 9")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d9")
    producto = _alta_producto(cliente, cabeceras)

    assert cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto, motivo="  "), headers=cabeceras).status_code == 422
    assert cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto, cantidad="2"), headers=cabeceras).status_code == 422
    merma = _ajuste(producto, tipo="merma", cantidad="2", stock_contado=None, motivo="Se dañó")
    assert cliente.post("/api/v1/inventario/ajustes", json=merma, headers=cabeceras).status_code == 201


def test_el_ajuste_de_un_producto_desconocido_es_422(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 10")
    cabeceras = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d10")

    respuesta = cliente.post("/api/v1/inventario/ajustes", json=_ajuste(str(uuid.uuid4())), headers=cabeceras)
    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "producto_no_encontrado"


# --- Estado de stock ------------------------------------------------------------------


def test_el_estado_de_stock_lo_lee_cualquier_rol_con_nivel_derivado(app_con_base):
    """`producto:leer` (decisión 10): el cajero también ve los niveles — ya los
    ve en el POS vía delta. El nivel lo deriva el servidor."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Inv 11")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d11")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c11")
    producto = _alta_producto(cliente, dueno, stock_minimo="4")
    cliente.post("/api/v1/compras", json=_compra(producto), headers=dueno)  # stock 10
    cliente.post("/api/v1/inventario/ajustes", json=_ajuste(producto, stock_contado="1"), headers=dueno)  # → 1: crítico

    respuesta = cliente.get("/api/v1/inventario/stock", headers=cajero)
    assert respuesta.status_code == 200
    (item,) = respuesta.json()["items"]
    assert item["nivel"] == "critico" and _dec(item["stock_actual"]) == Decimal("1")

    solo = cliente.get("/api/v1/inventario/stock?solo_alertas=true", headers=cajero)
    assert solo.status_code == 200 and solo.json()["total"] == 1


def test_sin_token_es_401(app_con_base):
    cliente, _, _ = app_con_base
    assert cliente.get("/api/v1/inventario/stock").status_code == 401
    assert cliente.post("/api/v1/compras", json={}).status_code == 401
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/api/test_inventario_api.py -q
# Esperado: 12 fallos con 404 (las rutas no existen)
```

- [ ] **Paso 2: enseñar la limpieza al conftest de API.** En `backend/tests/api/conftest.py`, en `limpiar_tenants_de_prueba`, reemplazar la tupla de tablas por:

```python
                for tabla in (
                    "movimientos_inventario",
                    "ventas_items",
                    "ventas",
                    "caja_sesiones",
                    "dispositivos",
                    "compra_items",
                    "compras",
                    "ajustes_inventario",
                ):
```

El orden importa: `compra_items` antes de `compras` (FK `RESTRICT`), y todas antes del `DELETE FROM productos` de más abajo — sin estas tres tablas en la lista, las filas que dejen los tests de inventario harían fallar la limpieza de la siguiente corrida contra la FK de productos.

- [ ] **Paso 3: escribir las dependencias.** Crear `backend/services/api/app/modules/inventario/dependencies.py`:

```python
"""Dependencias del módulo `inventario`.

El guard de permisos vive en `app.dependencies.exigir_permiso` (su casa desde
el módulo ventas, por el mismo motivo que `exigir_admin_de_plataforma`).

Los permisos (ADR-023 y decisión 10 del plan): compras y ajustes exigen
`compra:crear` e `inventario:ajustar` también para LEER — el catálogo de
permisos es cerrado y los costos/ajustes no son para el cajero—; el estado
de stock exige `producto:leer` (los tres roles: el cajero ya ve el stock en
el POS).
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import exigir_permiso, sesion_de_tenant
from app.modules.inventario.service import InventarioService
from app.modules.tenants.dependencies import exigir_negocio_activo
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.auth.policies import PERM_COMPRA_CREAR, PERM_INVENTARIO_AJUSTAR, PERM_PRODUCTO_LEER
from vendi_core.tenant.context import TenantContext

exigir_compra_crear = exigir_permiso(PERM_COMPRA_CREAR)
exigir_inventario_ajustar = exigir_permiso(PERM_INVENTARIO_AJUSTAR)
exigir_producto_leer = exigir_permiso(PERM_PRODUCTO_LEER)


async def servicio_de_inventario(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
    user: UserContext = Depends(get_current_user),
) -> InventarioService:
    """El servicio del negocio del token, con la sesión que la RLS acota.

    `exigir_negocio_activo` va primero: un negocio suspendido no compra ni
    ajusta (403 `tenant_suspendido`). El `actor_id` queda grabado en cada
    ajuste (`aplicado_por`): la auditoría del gesto con stock.
    """
    return InventarioService(session=session, tenant_id=tenant.tenant_id, actor_id=user.user_id)


__all__ = [
    "exigir_compra_crear",
    "exigir_inventario_ajustar",
    "exigir_producto_leer",
    "servicio_de_inventario",
]
```

- [ ] **Paso 4: escribir el router.** Crear `backend/services/api/app/modules/inventario/router.py`:

```python
"""Inventario y compras: `/api/v1/compras*` y `/api/v1/inventario/*`.

Endpoints REST ONLINE clásicos (decisión 3 del plan): NADA de este módulo
viaja por el lote del sync. El ajuste es la única operación de inventario que
exige conexión (ADR-020: su delta se calcula contra el stock del servidor en
el momento del conteo) y la compra es un gesto síncrono del dueño o el
almacenista; un lote con `tipo: "inventario.ajustar"` sale `rechazada` con
`tipo_desconocido` — el contrato del sync queda cerrado.

Todo trabaja con la sesión de TENANT (rol `vendi_app`, RLS activo): ningún
handler recibe `tenant_id` por URL, cuerpo o cabecera. Los permisos
(ADR-023/ADR-010 del plan): escribir Y leer compras exige `compra:crear`;
escribir Y leer ajustes exige `inventario:ajustar`; el estado de stock, con
su nivel derivado, exige `producto:leer`. El 403 del cajero es la respuesta
correcta y esperada.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.modules.inventario.dependencies import (
    exigir_compra_crear,
    exigir_inventario_ajustar,
    exigir_producto_leer,
    servicio_de_inventario,
)
from app.modules.inventario.schemas import (
    AjusteCreado,
    AjusteCrear,
    AjusteSalida,
    CompraCrear,
    CompraDetalleSalida,
    CompraItemSalida,
    CompraSalida,
    StockSalida,
)
from app.modules.inventario.service import InventarioService
from vendi_core.auth.context import UserContext
from vendi_core.models.pagination import PagedList
from vendi_core.models.responses import ErrorResponse

router = APIRouter(tags=["inventario"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    422: {"model": ErrorResponse, "description": "Request malformado (validación de estructura o de dominio)"},
}


@router.post(
    "/compras",
    response_model=CompraDetalleSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una compra a proveedor",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "El id de la compra ya existe (en este u otro negocio)"},
    },
)
async def registrar_compra(
    datos: CompraCrear,
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_compra_crear),
) -> CompraDetalleSalida:
    """En la MISMA transacción: la compra, sus ítems, un movimiento `compra`
    por línea, `stock_actual` y `ultimo_costo` de cada producto, y el evento
    `compra.registrada` (ADR-020). Acepta el `id` que traiga el cliente
    (ADR-017): reenviar la misma compra devuelve la existente, sin duplicar
    fila, stock ni evento. El total lo calcula el servidor por línea; el
    `proveedor_nombre` es texto libre (la factura es un papel: no hay tabla
    de proveedores)."""
    compra, items = await servicio.obtener_compra((await servicio.registrar_compra(datos)).id)
    return _detalle(compra, items)


@router.get(
    "/compras",
    response_model=PagedList[CompraSalida],
    summary="Listar compras",
    responses=_RESPUESTAS_COMUNES,
)
async def listar_compras(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_compra_crear),
) -> PagedList[CompraSalida]:
    filas, total = await servicio.listar_compras(skip=skip, limit=limit)
    return PagedList[CompraSalida](
        items=[CompraSalida.model_validate(f) for f in filas], total=total, skip=skip, limit=limit
    )


@router.get(
    "/compras/{compra_id}",
    response_model=CompraDetalleSalida,
    summary="Ver una compra con sus ítems",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "La compra no existe"}},
)
async def ver_compra(
    compra_id: uuid.UUID,
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_compra_crear),
) -> CompraDetalleSalida:
    compra, items = await servicio.obtener_compra(compra_id)
    return _detalle(compra, items)


@router.post(
    "/inventario/ajustes",
    response_model=AjusteCreado,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un ajuste por conteo o una merma (ONLINE)",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "El id del ajuste ya existe con datos distintos"},
    },
)
async def registrar_ajuste(
    datos: AjusteCrear,
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_inventario_ajustar),
) -> AjusteCreado:
    """La única operación de inventario que EXIGE conexión (ADR-020): el
    delta se calcula contra el stock del servidor en el momento del conteo —
    un ajuste offline corrompería el contador de forma no conmutativa. El
    `motivo` es obligatorio. El `id` del cliente es requerido y ancla la
    idempotencia: el reintento idéntico devuelve lo ya respondido sin mover
    stock; el divergente es 409 `ajuste_id_divergente`. Un conteo que cuadra
    (delta 0) graba la fila pero no escribe movimiento en el libro."""
    return await servicio.registrar_ajuste(datos)


@router.get(
    "/inventario/ajustes",
    response_model=PagedList[AjusteSalida],
    summary="Listar ajustes y mermas",
    responses=_RESPUESTAS_COMUNES,
)
async def listar_ajustes(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_inventario_ajustar),
) -> PagedList[AjusteSalida]:
    """La auditoría del «¿quién movió el arroz?»: cada fila lleva su motivo
    y quién la aplicó."""
    filas, total = await servicio.listar_ajustes(skip=skip, limit=limit)
    return PagedList[AjusteSalida](
        items=[AjusteSalida.model_validate(f) for f in filas], total=total, skip=skip, limit=limit
    )


@router.get(
    "/inventario/stock",
    response_model=PagedList[StockSalida],
    summary="Estado de stock con su nivel (agotado/crítico/bajo/ok)",
    responses=_RESPUESTAS_COMUNES,
)
async def estado_de_stock(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    solo_alertas: bool = Query(default=False, description="Solo productos agotados o por debajo del mínimo"),
    servicio: InventarioService = Depends(servicio_de_inventario),
    _actor: UserContext = Depends(exigir_producto_leer),
) -> PagedList[StockSalida]:
    """El nivel lo deriva el servidor con la misma función que dispara
    `inventario.alerta_stock`: una sola definición del umbral. El stock
    negativo es un dato legítimo (ADR-020) y viaja como `agotado`."""
    items, total = await servicio.estado_stock(skip=skip, limit=limit, solo_alertas=solo_alertas)
    return PagedList[StockSalida](items=items, total=total, skip=skip, limit=limit)


def _detalle(compra, items) -> CompraDetalleSalida:
    salida = CompraSalida.model_validate(compra)
    return CompraDetalleSalida(
        **salida.model_dump(),
        items=[CompraItemSalida.model_validate(i) for i in items],
    )
```

- [ ] **Paso 5: montar el router.** En `backend/services/api/app/factory.py`, añadir el import tras el de ventas:

```python
from app.modules.inventario.router import router as router_inventario
```

y tras `app.include_router(router_ventas, prefix="/api/v1")`:

```python
    app.include_router(router_inventario, prefix="/api/v1")
```

- [ ] **Paso 6: verificar.**

```bash
cd backend && uv run pytest tests/api/test_inventario_api.py -q
# Esperado: 12 passed
uv run pytest tests/api -q
# Esperado: toda la carpeta verde (los tests de catálogo, ventas y tenants no se tocan y siguen pasando)
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 7: commit**

```bash
git add backend/services/api/app/modules/inventario/dependencies.py backend/services/api/app/modules/inventario/router.py backend/services/api/app/factory.py backend/tests/api/test_inventario_api.py backend/tests/api/conftest.py
git commit -m "Endpoints REST de inventario: compras, ajustes online y estado de stock con nivel"
```

**Criterios de aceptación:** los 12 tests de API pasan contra el stack real, 0 SKIPPED; el cajero recibe 403 `permiso_ausente` en compras y ajustes (lectura incluida) y 200 en el estado de stock; el almacenista y el dueño operan; la compra de otro negocio es 404 sin fuga; las cotas son 422 y nunca 500; el sobre de error es el estándar; `tests/api` completo verde (con la limpieza cubriendo las tablas nuevas); `ruff` limpio.

---

## Tarea 8: Cerrar D-14 — `OperacionSync.datos` requerido en el contrato

**Files:**
- Modify: `backend/services/api/app/modules/ventas/schemas.py` (`OperacionSync.datos` pierde el `default_factory`)
- Modify: `backend/tests/test_ventas_schemas.py` (el test del 422 de schema)
- Modify: `backend/tests/api/test_ventas_sync.py` (el test del 422 de request)

**Interfaces:**
- Consume: nada nuevo; es un endurecimiento del contrato existente.
- Produce: una operación sin `datos` es 422 de pydantic (la señal más temprana posible), no `rechazada` con `datos_invalidos`. D-14 queda lista para cerrarse en la Tarea 11.

Contexto (D-14 de `docs/deuda-tecnica.md`): `datos` tiene `Field(default_factory=dict)`, así que una operación sin `datos` no es 422 de request: llega al servicio con `{}` y sale `rechazada`. La deuda vence «Fase 1 (módulo 3)» y pide hacerlo requerido al revisar el contrato. Este módulo no añade tipos de operación al sync (decisión 3) pero SÍ regenera el contrato, y el arreglo es de una línea. El comportamiento para `datos` presentes pero con contenido inválido NO cambia: sigue siendo `rechazada` por operación (la unidad de fallo del lote), con su candado vigente.

- [ ] **Paso 1: escribir los tests que fallan.** En `backend/tests/test_ventas_schemas.py`, añadir:

```python
def test_una_operacion_sin_datos_es_422_de_schema():
    """D-14 cerrada: `datos` es requerido en el contrato. La operación sin
    `datos` ya no llega al servicio disfrazada de `{}` para salir `rechazada`:
    pydantic la corta en la frontera, que es la señal más temprana posible.
    (El contenido inválido CON campo sigue siendo `rechazada` por operación:
    eso no cambia — la unidad de fallo del lote es la operación.)"""
    with pytest.raises(ValidationError):
        OperacionSync.model_validate({"id": str(uuid.uuid4()), "tipo": "venta.crear", "secuencia": 1})
```

En `backend/tests/api/test_ventas_sync.py`, añadir:

```python
def test_una_operacion_sin_datos_es_422_del_lote(app_con_base):
    """El 422 es del request entero (estructura malformada), no un rechazo por
    operación: el cliente que omite `datos` tiene un bug y nada se aplicó."""
    cliente, validador, _ = app_con_base
    cabeceras, _, dispositivo = _montar(cliente, validador, "Sync datos")
    lote = {
        "dispositivo_id": dispositivo,
        "operaciones": [{"id": str(uuid.uuid4()), "tipo": "venta.crear", "secuencia": 1}],
    }
    respuesta = cliente.post("/api/v1/sync/lotes", json=lote, headers=cabeceras)
    assert respuesta.status_code == 422
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_ventas_schemas.py -q -k sin_datos
# Esperado: FAILED — la operación sin datos valida (default_factory=dict)
```

- [ ] **Paso 2: hacer `datos` requerido.** En `backend/services/api/app/modules/ventas/schemas.py`, en `OperacionSync`, reemplazar:

```python
    datos: dict[str, Any] = Field(default_factory=dict)
```

por:

```python
    #: Requerido (cierre de D-14): la operación sin `datos` es un 422 de
    #: request, no una `rechazada` del lote. El CONTENIDO se valida por
    #: operación en el servicio (decisión 6 del plan de ventas): `datos`
    #: presentes pero inválidos siguen siendo `rechazada` sin arrastrar el lote.
    datos: dict[str, Any]
```

y ajustar el docstring de `OperacionSync` para que diga que `datos` es requerido (el párrafo actual describe el viaje como dict que valida el servicio; añadir esa frase).

- [ ] **Paso 3: comprobar que nada más dependía de la opcionalidad.**

```bash
cd backend && grep -rn '"tipo":' tests/test_ventas_servicio.py tests/api/test_ventas_sync.py tests/test_sync_idempotente.py tests/test_ventas_fixes_qa.py tests/test_ventas_adversarial.py | grep -v datos | head
# Esperado: ninguna construcción de operación sin la clave "datos" (todas la pasan con contenido)
uv run pytest tests/test_ventas_schemas.py tests/api/test_ventas_sync.py -q -k "sin_datos"
# Esperado: 2 passed
uv run pytest -q -m integration
# Esperado: toda la suite verde, 0 SKIPPED (el rechazo por contenido inválido sigue siendo rechazada)
```

Si el grep encuentra alguna construcción sin `datos`, actualizarla para pasar `datos` con contenido (el comportamiento que prueba no cambia).

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/ventas/schemas.py backend/tests/test_ventas_schemas.py backend/tests/api/test_ventas_sync.py
git commit -m "OperacionSync.datos es requerido en el contrato (cierre de D-14)"
```

**Criterios de aceptación:** la operación sin `datos` es 422 de schema y de request; el contenido inválido con `datos` presente sigue siendo `rechazada` por operación (su candado vigente pasa); toda la suite de integración verde, 0 SKIPPED.

---

## Tarea 9: Extender el check 23 de `verify-setup.sh` (candado de ADR-023)

**Files:**
- Modify: `scripts/verify-setup.sh` (bloque del check 23, ~líneas 736-746)

**Interfaces:**
- Consume: el generador de tokens de ejemplo de la Admin API que el check 23 ya usa para inspeccionar `realm_access.roles` del token del dueño demo.
- Produce: el check falla si el token del dueño no trae `inventario:ajustar` y `compra:crear` — «un permiso que nadie tiene en el token del dueño es un bug de siembra, no de autorización» (ADR-023).

- [ ] **Paso 1: extender el bucle de permisos del check 23.** En `scripts/verify-setup.sh`, dentro del heredoc `python3 - <<'PY'` del check 23, reemplazar la línea del bucle por:

```python
for permiso in ("producto:leer", "producto:editar", "venta:crear", "venta:anular", "inventario:ajustar", "compra:crear"):
```

y el mensaje del `ok` por:

```bash
        ok "aud=${KEYCLOAK_AUDIENCE:-vendi-backend}, rol de negocio y permisos de catálogo, ventas e inventario en el token del dueño"
```

- [ ] **Paso 2: verificar contra el stack.**

```bash
bash scripts/seed.sh && bash scripts/verify-setup.sh 2>&1 | grep -E "^\[(OK|FALLO|OMITIDO)\].*23"
# Esperado: [OK] 23 ... permisos de catálogo, ventas e inventario en el token del dueño
```

Prueba negativa (obligatoria): quitar temporalmente `compra:crear` del mapeo del grupo `dueno` en la consola de Keycloak (`https://accounts.vendi.co`, con `--resolve accounts.vendi.co:443:127.0.0.1`), re-ejecutar el check y verlo fallar con el mensaje de siembra; restaurar con `bash scripts/seed.sh` y ver el OK.

- [ ] **Paso 3: commit**

```bash
git add scripts/verify-setup.sh
git commit -m "El check 23 exige los permisos de inventario y compras en el token del dueño (ADR-023)"
```

**Criterios de aceptación:** el check 23 pasa con la siembra al día y falla —con mensaje accionable— si falta cualquiera de los seis permisos.

---

## Tarea 10: Congelar el OpenAPI y regenerar el cliente TypeScript

**Files:**
- Modify: `docs/api/openapi-fase0.json` (regenerado, mismo archivo — decisión 15 del plan)
- Modify: `docs/api/README.md` (tabla de rutas y códigos)
- Modify: `frontend/projects/libs/data-access/src/lib/api-client/openapi.json` e `index.ts` (salida del codegen)

**Interfaces:**
- Consume: la API viva con `DOCS_PUBLICOS=true` y `scripts/codegen-api-client.sh` en modo congelado.
- Produce: el contrato con las 6 rutas nuevas y `OperacionSync.datos` requerido; el cliente TS regenerado sin deriva (`codegen + git diff --exit-code` en 0).

- [ ] **Paso 1: regenerar el contrato congelado desde la API viva.** Con el stack levantado y la migración aplicada:

```bash
curl -sS --resolve api.vendi.co:443:127.0.0.1 https://api.vendi.co/openapi.json \
  | python3 -c 'import json,sys; json.dump(json.load(sys.stdin), open("docs/api/openapi-fase0.json","w"), indent=2, ensure_ascii=False, sort_keys=True)'
python3 -c 'import json; d=json.load(open("docs/api/openapi-fase0.json")); print(sorted(p for p in d["paths"] if "compra" in p or "inventario" in p))'
# Esperado: ['/api/v1/compras', '/api/v1/compras/{compra_id}', '/api/v1/inventario/ajustes', '/api/v1/inventario/stock']
python3 -c 'import json; d=json.load(open("docs/api/openapi-fase0.json")); print("datos" in d["components"]["schemas"]["OperacionSync"].get("required", []))'
# Esperado: True (D-14)
```

`sort_keys=True` e `indent=2` no son cosméticos: sin orden estable, cada regeneración produce un diff ilegible.

- [ ] **Paso 2: actualizar `docs/api/README.md`.** Añadir a la tabla de rutas:

```markdown
| `POST /api/v1/compras` | `compra:crear` | compra a proveedor (texto libre, sin tabla de proveedores); mueve stock y `ultimo_costo` en la misma transacción; idempotente por `id` del cliente; total calculado en el servidor |
| `GET /api/v1/compras` | `compra:crear` | listado paginado (`PagedList`) |
| `GET /api/v1/compras/{id}` | `compra:crear` | detalle con ítems; 404 si es de otro negocio |
| `POST /api/v1/inventario/ajustes` | `inventario:ajustar` | ajuste por conteo o merma; ONLINE (no viaja por el sync, ADR-020); `motivo` e `id` obligatorios; reintento idéntico = no-op, divergente = 409 |
| `GET /api/v1/inventario/ajustes` | `inventario:ajustar` | listado paginado con motivo y `aplicado_por` |
| `GET /api/v1/inventario/stock` | `producto:leer` | stock con nivel derivado (`agotado`/`critico`/`bajo`/`ok`); `solo_alertas=true` filtra |
```

y a la lista de `code` estables: `compra_no_encontrada`, `compra_id_duplicado`, `ajuste_id_divergente`. Añadir a la nota final una línea de eventos nuevos del outbox: `compra.registrada` e `inventario.alerta_stock` (este último solo al cruzar un umbral hacia abajo; payload `{producto_id, nivel, stock_actual, stock_minimo}`, sin PII).

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
git commit -m "Contrato OpenAPI con las rutas de inventario y compras, datos requerido y cliente TypeScript regenerado"
```

**Criterios de aceptación:** el OpenAPI congelado contiene las 4 rutas nuevas (6 endpoints) con sus schemas (`CompraCrear`, `CompraDetalleSalida`, `AjusteCrear`, `AjusteCreado`, `StockSalida`) y `datos` requerido en `OperacionSync`; el job `frontend-contratos` del CI (codegen contra el congelado + `git diff --exit-code`) queda en verde; `vendi-admin` compila contra el cliente regenerado.

---

## Tarea 11: Cierre del módulo — gate de la Etapa 1.2, `docs/estado.md` y cierre de D-12/D-14

**Files:**
- Modify: `docs/estado.md` (sección nueva del módulo inventario, con fecha de corte y evidencia comando+salida)
- Modify: `docs/deuda-tecnica.md` (D-12 y D-14 pasan a «Cerradas en Fase 1» con su evidencia)

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
# Esperado: todo [OK], con el check 23 exigiendo los seis permisos
```

Gate por módulo (del plan maestro de Fase 1), verificado ítem a ítem:
- [ ] Migración con RLS + índice + grants, revisada por el agente de seguridad.
- [ ] Tests de integración con aislamiento cross-tenant nuevo por tabla (`test_aislamiento_inventario.py`: las tres tablas), 0 SKIPPED.
- [ ] Los candados firmados de ADR-020: alerta única por cruce (N movimientos bajo el mismo umbral = 1 evento; recuperación + nuevo cruce = 2) e invariante del libro (`stock_actual = SUM(movimientos)` tras secuencia mezclada de venta, compra, merma y ajuste).
- [ ] El gatillo de D-14 ejecutado: `OperacionSync.datos` requerido, con su test de 422 y el contrato regenerado.
- [ ] OpenAPI congelado actualizado + codegen + `contrato.ts` sigue compilando.
- [ ] Eventos de outbox emitidos según ADR-020 (`compra.registrada`, `inventario.alerta_stock` solo al cruzar hacia abajo, clave `<tenant_id>.<evento>`); `pytest -m integration` verde; `ruff` verde.

- [ ] **Paso 2: actualizar `docs/estado.md`.** Añadir una sección «Módulo inventario (Fase 1, Etapa 1.2)» con: fecha de corte, qué se entregó (las tres tablas, el punto único de movimientos y alertas, las compras con `ultimo_costo`, los ajustes online idempotentes, los permisos y su reparto, las 6 rutas, D-12 y D-14 cerradas), y **al lado de cada afirmación el comando que la demuestra** con su salida pegada (regla del documento: no promete nada que un comando no demuestre).

- [ ] **Paso 3: cerrar D-12 y D-14 en `docs/deuda-tecnica.md`.** Mover ambas entradas a la sección «Cerradas en Fase 1», cada una con qué era, cómo se cerró y la evidencia comando+salida:

- **D-12** (el stock no tiene alertas de umbral): se cerró con `inventario/stock.py` (nivel derivado en el punto único de aplicación de movimientos; evento `inventario.alerta_stock` solo al cruzar hacia abajo). Evidencia: `uv run pytest tests/test_inventario_alertas.py -q` → 14 passed (cruce único, anti-spam de la cola de sync, recuperación y nuevo cruce, bordes exactos); el test reforzado del stock negativo que ahora demuestra la alerta de agotado.
- **D-14** (`OperacionSync.datos` opcional): se cerró haciendo el campo requerido (Tarea 8). Evidencia: `uv run pytest tests/test_ventas_schemas.py -q -k sin_datos` → 1 passed, y `"datos" in required` en el `OperacionSync` del OpenAPI congelado.

No tocar D-10, D-11, D-13, D-15, D-16, D-17, D-18: viven sus propios vencimientos. Si el ejecutor registra deuda nueva (p. ej. lo que el QA encuentre en la superficie de abajo), que sea con el formato del registro (qué es, por qué se aceptó, riesgo, vencimiento, candados mientras tanto).

- [ ] **Paso 4: commit de cierre**

```bash
git add docs/estado.md docs/deuda-tecnica.md
git commit -m "Módulo inventario cerrado: gate de la Etapa 1.2 verificado, estado actualizado y D-12/D-14 cerradas"
```

---

## Superficie de ataque para QA — módulo inventario (alertas, compras, ajustes)

Para el agente de QA adversarial de la Etapa 1.4 (agente distinto del implementador; su KPI son hallazgos). Los escenarios marcados (firmado) ya tienen test que los fija: verificarlos, no «redescubrirlos»; el hallazgo sería que el test miente.

- **Alertas (el corazón):** los bordes estrictos (stock == mínimo es `ok`; stock == mínimo/2 es `bajo`, no `critico` — firmado); cruzar DOS niveles en un movimiento (venta de 10 → −1 con mínimo 4: `ok → agotado` directo, UN evento `agotado`, no `bajo`+`agotado` — verificar que el evento lleva el nivel FINAL); recuperación parcial (de `agotado` a `critico` sin pasar por `ok`: no emite; y el siguiente cruce a `agotado` ¿emite? Sí, porque `critico → agotado` es empeorar — verificar y fijar); edición de `stock_minimo` con el stock quieto (no emite nada, decisión 2 — y el endpoint de stock muestra el nivel nuevo de inmediato); producto con `stock_minimo` gigante (10^11: `stock_minimo / 2` no desborda el Numeric — verificar); una venta que cruza el umbral de un producto cuyo `stock_minimo` se editó ENTRE la venta física y el sync (el nivel se calcula contra el mínimo VIGENTE al aplicar — documentar el comportamiento).
- **Anti-duplicado:** el mismo lote de ventas 3 veces (una alerta — firmado); compra reenviada con el mismo `id` (sin re-emisión de nada — firmado); ajuste reenviado tras timeout con el stock ya movido por ventas (devuelve lo grabado la primera vez, NO re-aplica el conteo viejo — firmado para el reintento idéntico; ¿y si la app reintenta con el MISMO id pero el usuario cambió el conteo? 409 `ajuste_id_divergente` — firmado); carrera de dos PRIMEROS envíos del mismo ajuste concurrentes (una gana, la otra 409 tipado — nunca 500, nunca doble movimiento).
- **Carreras:** dos compras concurrentes del mismo producto (stock exacto — firmado); compra y venta concurrentes del mismo producto (serializadas por el FOR UPDATE; el nivel de la alerta se calcula contra el estado real post-commit); dos compras concurrentes con DOS productos en orden inverso (el orden de bloqueo por `producto_id`, decisión 9, hace el deadlock imposible — intentar provocarlo); una venta del sync cuyo ticket trae dos productos en orden inverso al de otra venta concurrente (el sync hereda el riesgo teórico de deadlock del orden del ticket: ¿es alcanzable? Si lo es, registrar deuda con vencimiento — NO arreglar en este módulo).
- **Aislamiento:** compra/ajuste con `producto_id` del vecino (422 sin fuga — firmado); `GET /compras/{id}` del vecino (404 — firmado); listados del vecino (vacíos — firmado); `tenant_id` inyectado en compra y en ajuste (422 por `extra="forbid"` — firmado); una alerta de T1 nunca sale con routing key de T2 (el outbox deriva la clave de la columna `tenant_id`, D-05 cerrada — verificar con el payload).
- **Validación y bordes:** `costo_unitario_centavos` en 2^31 (422 — firmado); `cantidad` que desborda `Numeric(14,3)` (422 — firmado); `cantidad` de 4 decimales (cuantiza como Postgres — firmado); `cantidad` que cuantiza a cero (422 — firmado); `stock_contado` negativo (422); `stock_contado` de 4 decimales (cuantiza permitiendo cero — firmado); motivo de puros espacios, de 2 letras, de 301 caracteres (422 — firmado el primero); `proveedor_nombre` con HTML/emoji/saltos (se limpia y se guarda como texto — el XSS es asunto del render del frontend, verificar que viaja escapado en JSON); `fecha` de la factura en 1970 y en 2100 (se acepta: es dato del papel); observaciones de 501 caracteres (422).
- **El ajuste online:** un lote del sync con `tipo: "inventario.ajustar"` (`rechazada` `tipo_desconocido` — el contrato del sync quedó cerrado, verificar); ajuste sobre producto dado de baja lógica (422 — firmado); ajuste con delta cero (fila sin movimiento — firmado) seguido de un REINTENTO del mismo ajuste tras una venta (devuelve lo grabado: el conteo viejo NO se re-aplica — el agujero que justifica la tabla, verificar que está cerrado).
- **Permisos:** cajero en las 5 rutas de compras/ajustes (403 — firmado) y 200 en `/inventario/stock` (firmado); almacenista sin `venta:crear` intentando sincronizar un lote (403, sigue firmado del módulo 2); negocio suspendido a media sesión (403 `tenant_suspendido` en el siguiente request); un token con `inventario:ajustar` pero sin `compra:crear` (rol editado a mano en Keycloak) ajusta pero no compra — los guards son por permiso, no por rol.
- **Eventos:** payload de `inventario.alerta_stock` exactamente `{producto_id, nivel, stock_actual, stock_minimo}` (sin PII, sin nombre de producto — firmado); `compra.registrada` con el total del servidor y los ítems; rollback a mitad de compra (provocar fallo tras el primer movimiento: ni compra, ni movimientos, ni stock, ni eventos — la garantía outbox); una compra de 50 líneas deja 50 movimientos y UN `compra.registrada`.
- **Invariante del libro:** tras la secuencia mezclada venta+compra+merma+ajuste (firmado) y tras anular una venta DESPUÉS de una compra del mismo producto (la reposición y la entrada coexisten en el libro; `stock_actual = SUM`).

---

## Self-Review

- **Cobertura del spec:** ADR-020 (libro inmutable ya creado, proyección con FOR UPDATE, idempotencia por constraint, stock negativo legítimo, ajustes online-obligatorios, alertas de 3 niveles con evento solo al cruzar hacia abajo, compras simples con `proveedor_nombre` texto y sin tabla proveedores, `ultimo_costo` en la misma transacción, eventos `compra.registrada` e `inventario.alerta_stock`, candados de doble sincronización/invariante/alerta única/cross-tenant) → Tareas 1, 5, 6, 7 + decisiones 1-6, 13, 14. ADR-023 (`inventario:ajustar`, `compra:crear`, reparto dueño/almacenista/cajero, catálogo cerrado, candados, check 23) → Tareas 4, 7, 9 + decisión 10. ADR-017 (ids de cliente, la fila es la prueba, eventos una sola vez, qué viaja por el sync) → Tareas 6, 7, 8 + decisiones 3, 4. ADR-006 (el P&L costea `ultimo_costo` y consume `compra.registrada`) → Tarea 6. Deuda D-12 → Tarea 5 + cierre en Tarea 11; D-14 → Tarea 8 + cierre en Tarea 11. Lecciones de los QA de catálogo y ventas (cotas `le=`, cuantización, validadores sin asunción de `str`, traducción de IntegrityError, FOR UPDATE en read-modify-write, divergencia explícita, nada de 500 no tipados) → Global Constraints, Tareas 3, 6, decisiones 7-9. Items del encargo 1-7 → Tareas 1-11.
- **Placeholders:** ninguno. Todo paso lleva código completo, comando exacto y salida esperada. Los conteos de tests son los escritos (10 aislamiento, 6 modelo, 17 schemas, 14 alertas, 16 servicio, 12 API); si el ejecutor añade casos, ajusta el número (los comandos de gate son de suite, no de conteo).
- **Consistencia de tipos/contratos:** nombres de tablas, columnas, índices y checks coinciden entre migración (Tarea 1), modelos (Tarea 2), tests de metadata y schemas (Tarea 3); los `code` de error coinciden entre servicio, tests de servicio, tests de API y la tabla de `docs/api/README.md`; los niveles (`ok`/`bajo`/`critico`/`agotado`) tienen una sola definición (`nivel_de_stock`) usada por la alerta y por el endpoint; los eventos usan la firma real de `DomainEventService.emit`; los schemas reusan `TOPE_PRECIO`/`TOPE_STOCK` del catálogo; el refactor de ventas conserva la firma de `_mover_stock`.
- **Riesgos conocidos y declarados:** (1) hay tabla `ajustes_inventario` que ADR-020 no lista — desviación deliberada y justificada por el agujero de idempotencia del ajuste con delta cero (decisión 5); (2) la compra acepta `id` opcional del cliente: sin él, un reenvío tras timeout duplica la compra (mismo riesgo aceptado del catálogo; la app genera UUIDs para todo — si el QA lo considera insuficiente, va a deuda con vencimiento piloto); (3) una carrera de dos primeros envíos del mismo ajuste resuelve al perdedor con 409 en vez de devolverle la fila ganadora (ventana estrecha, documentada en `_flush_traduciendo_integridad`); (4) el sync hereda el riesgo teórico de deadlock por orden de ítems del ticket — queda en la superficie de QA para medir, no se arregla aquí; (5) un `IntegrityError` de FK (`compra_items_producto_id_fkey`, carrera con un borrado físico que hoy no existe) saldría como 500: inalcanzable con borrado lógico y RESTRICT, mismo criterio que ventas; (6) `total_centavos` de una compra de 200 líneas a 2^31−1 por línea desbordaría el Integer de la columna `total_centavos` — inalcanzable con ítems reales de tienda de barrio (el tope práctico es 200 × el costo de UNA línea); si el QA lo quiere cerrado, la cota es `le=TOPE_PRECIO // TOPE_ITEMS_POR_COMPRA` por línea, a deuda.
