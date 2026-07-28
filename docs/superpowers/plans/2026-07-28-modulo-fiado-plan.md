# Módulo fiado y clientes: el cuaderno — créditos con saldo vivo, abonos, recordatorios y clientes mínimos (Fase 1, Etapa 1.2, módulo 5) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar el quinto módulo de negocio del MVP —el fiado de ADR-009/ADR-022, «el cuaderno»— con: la migración `0009_fiado` (tres tablas con RLS + índices + checks: `clientes`, `fiado_creditos` con `saldo_pendiente` materializado y `CHECK (saldo_pendiente >= 0)`, y `fiado_abonos` con la sesión de caja que cobró el efectivo), los tres permisos que faltan del catálogo de 14 de ADR-023 (`cliente:gestionar`, `fiado:crear`, `fiado:abonar` — el cajero fía y cobra; el almacenista no toca fiado), el nacimiento del crédito EN EL SYNC (la venta fiada se convierte en crédito en la misma transacción del lote, con el cupo evaluado pero nunca rechazado — ADR-018 — y el exceso visible en el resultado de la operación), la operación nueva del lote `cliente.crear` (el cliente del fiado pudo nacer offline en el mismo dispositivo; su id del dispositivo ES la PK — cierre de D-10 por adopción), la anulación de la venta fiada que anula el crédito (`anulado`, cuarto estado; los abonos son historia intocable y la devolución del dinero es gesto manual de caja), los endpoints REST online de clientes (CRUD mínimo con saldo y cupo calculados) y del cuaderno (créditos, detalle con historial de abonos y `whatsapp_url` prearmada, reprogramación de vencimiento, registro de abonos con `id` de cliente requerido, descuento del saldo en la misma transacción y eventos `fiado.abono_registrado`/`fiado.credito_saldado`), el trabajo diario del worker `fiado.vencimientos` (marca `vencido` y emite `fiado.credito_vencido` UNA vez por crédito — la transición de estado ES el anti-duplicado), la activación de los dos puntos de cambio declarados por el módulo 4 (`_abonos_en_efectivo_de_la_sesion` real — el abono en efectivo suma al arqueo de la sesión abierta — y el forecast con cobros de fiado reales), la extensión del check 23 a los 14 permisos, el contrato OpenAPI regenerado con su cliente TS, el cierre de D-10 con evidencia real y el gate de módulo de la Etapa 1.2.

**Architecture:** Se mantiene la arquitectura firmada: monolito modular FastAPI (`backend/services/api`) sobre `vendi-core`, RLS en schema único con los roles `vendi_app` (sin `BYPASSRLS`) y `vendi_platform` (con `BYPASSRLS`, owner, corre las migraciones y el worker). El módulo nuevo vive en `app/modules/fiado/` (modelos, schemas, servicio, puente del sync, dependencias, un router). La API opera sobre la **sesión de tenant** (`sesion_de_tenant`, GUC `vendi.tenant_id`): ningún handler recibe `tenant_id` por URL, cuerpo o cabecera. El crédito nace dentro del lote del sync (misma transacción, SAVEPOINT de la operación — decisión 1): `ventas/service.py` llama al puente `fiado/sync.py`, igual que ya llama a `inventario.stock`. El saldo por cliente NO se guarda: es `SUM(saldo_pendiente)` de sus créditos `vigente`/`vencido` (ADR-022), calculado en cada lectura. Los abonos NO se duplican como movimientos de caja (ADR-021): el arqueo los suma desde `fiado_abonos` por la `sesion_caja_id` que guarda el abono en efectivo al registrarse. El recordatorio lo emite el worker (scope `tenant`, sesión de plataforma — el filtro por `tenant_id` es explícito porque el rol salta RLS, al revés de la API) y el módulo de notificaciones (módulo 7) consumirá `fiado.credito_vencido` y lo traducirá a `notificacion.enviar` (ADR-025): este módulo emite el evento de dominio y ahí termina su alcance. Los montos son enteros en centavos (criterio unificado ADR-018); las fechas de vencimiento son `Date` y «vencido» se juzga en el calendario de `America/Bogota`.

**Tech Stack:** Python 3.12 · FastAPI 0.139 · SQLAlchemy 2.0 async (asyncpg) · Alembic · PostgreSQL 17 RLS · Pydantic v2 · `zoneinfo` (stdlib) · pytest + pytest-asyncio · ruff · uv · openapi-typescript (codegen).

**Spec fuente:**
- `docs/adr/adr-022-fiado-y-clientes-tecnico.md` (el corazón: tres tablas, `saldo_pendiente` materializado con `CHECK >= 0`, saldo por cliente como SUM nunca guardado, abono contra el crédito que el usuario toca, recordatorio push al tendero vía trabajo diario + `wa.me` manual, ids de abonos del cliente, eventos del outbox, candados)
- `docs/adr/adr-009-fiado-y-clientes.md` (el fiado ES el cuaderno; historial de pagos y base mínima de clientes)
- `docs/adr/adr-018-modelo-de-ventas-offline.md` (la venta fiada ya existe: `medio_pago='fiado'` + `cliente_id` sin FK; fiado sin red permitido; el servidor NO rechaza aunque se supere el cupo — registra el exceso y lo muestra)
- `docs/adr/adr-017` vía el plan de ventas (ids del cliente como ancla de idempotencia; decisión 8 del plan de ventas: la creación del `fiado_creditos` es íntegramente de este módulo, que «tiene todo lo que necesita en la venta y en el evento `venta.creada`»)
- `docs/adr/adr-023-multi-empleado-permisos.md` (`cliente:gestionar`, `fiado:crear`, `fiado:abonar`; el cajero fía y cobra abonos; candado de autorización; extensión del check 23)
- `docs/adr/adr-025-push-fcm.md` (`fiado.credito_vencido` lo consume el módulo de notificaciones — módulo 7 — y lo traduce a `notificacion.enviar`; sin PII en el payload)
- `docs/adr/adr-021-caja-y-arqueo.md` (los abonos en efectivo los suma el arqueo de la sesión abierta; no se duplican como movimiento de caja)
- `docs/deuda-tecnica.md` (D-10: `ventas.cliente_id` sin FK — vence en este módulo)
- Plantillas a imitar: `backend/services/api/alembic/versions/20260728_0008_caja.py`, `backend/services/api/app/modules/caja/` (service con flush-sin-commit, `_flush_traduciendo_integridad`, guards en `dependencies.py`, router con `PagedList`), `backend/services/api/app/modules/ventas/service.py` (SAVEPOINT por operación, `_traducir_integridad`, `puede_anular` como flag), `backend/services/worker/worker/jobs.py` (registro de trabajos), `backend/tests/test_aislamiento_caja.py`, `backend/tests/test_caja_servicio.py`, `backend/tests/api/test_caja_api.py`.

## Global Constraints

- Todo artefacto en español riguroso (código, docstrings, commits, mensajes de error). Sin tildes ni eñes en identificadores técnicos que viajen en tokens, URLs o JSON (`dueno`, `anulado`, no `dueño`/`anulado` con tilde).
- Toda tabla nueva de dominio lleva `tenant_id` + policy RLS vía `enable_rls(op, ...)` + índice que empieza por `tenant_id`, verificada por test de aislamiento cross-tenant contra PostgreSQL real. Los tests de integración **fallan, no se omiten**, si falta el servicio. 0 SKIPPED en cualquier gate.
- El candado invertido `backend/tests/test_privilegios_de_vendi_app.py` exige EXACTAMENTE `{SELECT, INSERT, UPDATE, DELETE}` para toda tabla de negocio: las tres tablas nuevas reciben los cuatro por defecto y el candado pasa sin edición (misma decisión que las tablas append-only de ventas, inventario y caja — aunque `fiado_creditos` sí se actualiza: el saldo se descuenta y el estado cambia).
- TDD en cada tarea: primero el test que falla (con la salida del fallo esperada), luego la implementación completa, luego el test en verde, luego el commit. Prohibido «similar a», «agregar validación», TODO o código elidido.
- Los errores de la API usan el sobre `{"success": false, "message": "...", "code": "..."}` (`vendi_core.errors.domain` + `ErrorHandlerMiddleware`). NO se usa `require_permission` de `vendi-core`: el guard es `exigir_permiso` de `app.dependencies`.
- **Lecciones de los módulos anteriores, aplicadas desde el diseño:** (1) toda entrada entera lleva cota `le=TOPE_PRECIO` contra su columna `Integer` — un overflow sale como `DataError` → 500, no como 422 (BUG-2 del catálogo); (2) ningún validador `mode="before"` asume `str` (BUG-1 del catálogo); (3) la idempotencia NO es ciega a la divergencia: mismo `id` con datos distintos es 409/rechazada con los campos que difieren, nunca un no-op silencioso; (4) read-modify-write siempre con la fila bloqueada `FOR UPDATE` hasta el commit (el abono bloquea el crédito; el abono en efectivo bloquea además la sesión de caja — mismo patrón que `registrar_movimiento`); (5) todo `IntegrityError` esperable se traduce a un error tipado del sobre o a una `rechazada` del lote — nada de 500 mudos; (6) las salidas con datos sensibles se condicionan por permiso cuando aplica y el campo sensible viaja en `null`, no desaparece del esquema (la fuga de `ultimo_costo`); (7) la limpieza de texto va ANTES de las cotas de largo.
- Dinero SIEMPRE en centavos enteros (ADR-018/ADR-022). El `saldo_pendiente` se descuenta en la misma transacción del abono con el `CHECK (saldo_pendiente >= 0)` como red final: el desfase es un error tipado, no un dato malo (ADR-022).
- El reloj del cliente es dato, no árbitro (ADR-017): el vencimiento lo juzga el servidor con el calendario de `America/Bogota` (`zoneinfo`), nunca con la fecha del request.
- El historial de pagos NO se reescribe (ADR-022): los abonos son append-only; un crédito `saldado` nunca vuelve a `vigente` y uno `anulado` tampoco — la devolución de dinero es un gesto de caja manual, no una edición del cuaderno.
- En la API el servicio NO filtra por `tenant_id` a mano (lo hace la policy). En el WORKER es al revés: la sesión es de plataforma (`BYPASSRLS`, sin GUC) y el filtro `tenant_id = :tenant_id` es OBLIGATORIO y explícito en cada sentencia — un trabajo de tenant que no filtra toca las filas de todos.
- Los commits son por tarea, mensajes en español estilo oración. Nunca `git push` sin confirmación humana.
- Un ADR no se edita para cambiar de opinión: lo que este plan decide más allá de los ADRs queda listado en la sección siguiente, con su justificación.

## Decisiones de diseño tomadas en este plan (más allá de los ADRs)

1. **El crédito nace EN EL SYNC, en la misma transacción (SAVEPOINT) de la `venta.crear` — no en un consumidor del evento `venta.creada`.** La opción (b) —un consumidor— no existe hoy: el outbox es fan-out a RabbitMQ y el primer consumidor de eventos de dominio será el módulo 7 (notificaciones); inventar un consumidor dentro de la API para esto sería pagar infraestructura que el MVP no tiene. Y aunque existiera, sería peor: la anulación puede llegar EN EL MISMO LOTE que el alta (o segundos después, antes de que el consumidor corriera) y tendría que revertir un crédito que quizá aún no nace; con la creación en la misma transacción, venta y crédito confirman o revientan juntos, que es exactamente la garantía del patrón outbox, y el `saldo_pendiente` materializado jamás se desfasa de la venta que lo originó. ADR-022 (decisión 8 del plan de ventas) lo permite expresamente: este módulo «tiene todo lo que necesita en la venta». `ventas/service.py` llama al puente `app/modules/fiado/sync.py` (precedente: ya llama a `inventario.stock.aplicar_movimiento`). El evento `fiado.credito_creado` se emite en la misma transacción, una sola vez por venta aceptada.
2. **El cliente del fiado sube por el lote: operación nueva `cliente.crear`, con el id del dispositivo como PK (D-10 se cierra por adopción).** La venta fiada sin red (firmada en ADR-018) referencia un cliente que pudo nacer offline en el mismo dispositivo; si los clientes solo se crearan online, la referencia llegaría sin fila y el crédito no podría crearse — y la venta NO se rechaza jamás. El orden FIFO de la cola del dispositivo garantiza que `cliente.crear` precede a la venta en el lote, así que la dependencia es estructural, no una convención de la app (la lección de D-20: las convenciones no enforced son deuda). **Red de seguridad:** si aun así la venta fiada llega sin cliente (su `cliente.crear` fue rechazada por datos inválidos), el puente hace auto-alta mínima con nombre placeholder `(sin nombre)` — editable después — en vez de perder el fiado: el cuaderno nunca pierde una deuda, y un cliente sin nombre se ve y se corrige; un fiado sin crédito, no. La edición y el CRUD online viven en REST (`POST/PATCH/GET /clientes`); el lote solo crea.
3. **Anular una venta fiada SIEMPRE se permite; el crédito pasa a `anulado` (cuarto estado) con `saldo_pendiente = 0`, en el mismo SAVEPOINT de la `venta.anular`; los abonos NO se tocan y la devolución del dinero es un gesto de caja MANUAL.** ADR-022 firmó tres estados; el cuarto es la única salida coherente con el append-only: el crédito no se borra (la deuda existió y su historia importa) y no puede quedar `vigente` (la venta que lo respaldaba ya no existe). El caso duro —anulación con abonos ya registrados— se resuelve con la regla del mismo ADR: «el historial de pagos es la verdad y no se reescribe». Los abonos quedan; el evento `fiado.credito_anulado` lleva `total_abonado`; y si hay plata que devolver, el tendero la devuelve y lo registra como egreso de caja con su motivo — porque «déjelo ahí a favor para la próxima» es tan legítimo como devolverla, y automatizar la devolución decidiría por él (mismo criterio con el que ADR-022 descartó aplicar abonos al crédito más antiguo automáticamente). El arqueo no se descuadra: los abonos en efectivo SÍ entraron a la gaveta y siguen ahí hasta que el tendero decida. Un crédito `saldado` cuya venta se anula también pasa a `anulado` (no «vuelve a vigente»: esa prohibición del ADR se conserva).
4. **`fiado_creditos.cliente_id` SÍ lleva FK RESTRICT; `ventas.cliente_id` se queda SIN FK a propósito.** El crédito lo crea el servidor, que garantiza la fila del cliente antes (incluida la auto-alta placeholder): la FK no estorba y protege. La venta es distinta: su INSERT no puede depender de nada que falle — la venta NO se rechaza (ADR-018) — y Postgres NO aplica RLS al verificar llaves foráneas, así que la FK no añadiría aislamiento, solo fragilidad (un `cliente_id` de otro tenant pasaría la FK sin ser visible). D-10 se cierra como manda su vencimiento: adoptando el `cliente_id` del dispositivo como PK de `clientes` (mismo patrón que `ventas` y `productos`), no con una FK.
5. **El id del crédito lo genera el SERVIDOR; la idempotencia la ancla la venta.** ADR-022 dice «los ids de créditos y abonos se generan en el cliente». Para abonos se cumple literal (el `id` es requerido en el POST). Para créditos no hace falta: hay exactamente un crédito por venta, la venta ya es idempotente por su PK de cliente, y `ux_fiado_creditos_venta` (`UNIQUE(venta_id)`) hace imposible el doble crédito aunque algo se cuele — la re-aplicación de la venta sale como `duplicada` ANTES de tocar el crédito. Pedirle al cliente un `credito_id` sería un campo más del contrato para una garantía que ya existe por estructura. Desviación deliberada y acotada del literal del ADR.
6. **Los abonos son REST ONLINE en este módulo; el abono offline NO viaja por el lote todavía.** ADR-022 contempla «un abono registrado sin señal tiene que sincronizar sin duplicarse»: el mecanismo que lo hace seguro (el `id` del cliente como ancla) queda puesto desde ya — el POST exige `id` — pero la operación `fiado.abonar` del lote NO entra en este módulo (alcance firmado del encargo: endpoint REST online). Se registra como deuda D-27 con vencimiento antes del piloto: cuando el abono offline entre, entrará como operación del lote reusando el mismo ancla, sin romper nada de lo entregado aquí. Tensión declarada con ADR-022, no escondida.
7. **El recordatorio NO lleva bandera: la transición `vigente → vencido` EN UN SOLO `UPDATE ... RETURNING` ES el anti-duplicado.** El trabajo diario corre `UPDATE fiado_creditos SET estado = 'vencido' WHERE estado = 'vigente' AND fecha_vencimiento < :hoy ... RETURNING ...` y emite UN `fiado.credito_vencido` por fila devuelta. Re-correr el job es no-op (ya no son `vigente`); dos corridas concurrentes se serializan en los bloqueos de fila del UPDATE (la segunda actualiza 0 filas). Una bandera `recordatorio_emitido_en` duplicaría información que el estado ya tiene y habría que resetearla a mano cuando el tendero reprograme: con la transición pura, ampliar la fecha de un `vencido` a futuro lo devuelve a `vigente` (endpoint de reprogramación, Tarea 6) y podrá volver a vencer con su recordatorio — semánticamente correcto y gratis. Crédito sin `fecha_vencimiento` = sin recordatorio, declarado en pantalla (ADR-022).
8. **El cupo nunca rechaza; el exceso se registra, se muestra y es consultable — calculado, nunca materializado.** ADR-018 firma que el servidor no rechaza la venta fiada aunque supere el cupo. Al crear el crédito en el sync se evalúa `saldo resultante > limite_credito` (SUM de `vigente`/`vencido` tras el alta): si excede, log estructurado `fiado_cupo_excedido` y el `ResultadoOperacion` aceptada viaja con `detalles = {"cupo_excedido": true}` — la app lo muestra al confirmar el sync («registra el exceso y lo muestra», ADR-018). Y es consultable en todo momento: `GET /clientes` y `GET /clientes/{id}` devuelven `saldo_pendiente_total`, `limite_credito` y `cupo_excedido` CALCULADOS en cada lectura — una bandera guardada se desactualizaría con cada abono, anulación o edición del límite; el cálculo nunca miente.
9. **El abono en efectivo exige sesión de caja abierta y guarda su `sesion_caja_id`; los demás métodos no tocan caja.** Es la activación del punto de cambio declarado por el módulo 4: `_abonos_en_efectivo_de_la_sesion` suma por `sesion_caja_id` (misma regla que ventas y movimientos: el efectivo cae en la sesión abierta en ese momento, ADR-021). Sin sesión abierta, un abono en efectivo sería plata que entra a una gaveta que ningún arqueo mira: 409 `caja_sin_sesion_abierta` (mismo code que los movimientos). `transferencia`/`otro` no entran a la gaveta: se registran con `sesion_caja_id NULL` y sin exigir sesión. La lista cerrada de métodos es `("efectivo", "transferencia", "otro")` con CHECK en base y `Literal` en el schema; ampliarla exige migración, a propósito (el arqueo distingue por ella).
10. **Permisos: se siembran los tres que faltan del catálogo de 14; el reparto es ADR-023 literal; el cajero VE saldos y cupo.** `_PERMISOS_DUENO` y `_PERMISOS_CAJERO` ganan `cliente:gestionar`, `fiado:crear`, `fiado:abonar`; `_PERMISOS_ALMACENISTA` no gana ninguno. El cajero necesita el saldo del cliente para fiar (¿le fío más a Don Carlos?) y para cobrar (¿cuánto me debe?): ocultárselo sería la fuga de `ultimo_costo` al revés — romper el POS por pudor. Guards: clientes CRUD → `cliente:gestionar`; cuaderno (listar/detallar créditos, reprogramar) → `fiado:crear`; abonos → `fiado:abonar`. En el sync, la venta fiada exige `fiado:crear` POR OPERACIÓN y `cliente.crear` exige `cliente:gestionar` (patrón `puede_anular`: el veredicto se deriva del token en la dependencia y viaja al servicio como flags `puede_fiar`/`puede_gestionar_clientes`; la operación sin permiso es `rechazada` `permiso_ausente`, no un 403 del lote). El 403 por rol en REST es la respuesta correcta y esperada (ADR-023: «almacenista que cobra fiado → 403»). El check 23 se extiende a los 14 permisos.
11. **El forecast cobra fiado de verdad: `SUM(saldo_pendiente)` de créditos `vigente`/`vencido` con `fecha_vencimiento <= hoy + 30 días` (Bogotá).** Es la fuente declarada del punto de cambio del módulo 4: proyecta lo que debería entrar si cada fiado se paga a tiempo — y los ya vencidos cuentan (su fecha también es <= hoy+30), porque el cuaderno espera cobrarlos. Los créditos sin fecha NO entran (sin fecha no hay promesa de pago; ADR-022 los declara «sin recordatorio»): la respuesta lo dice en `fuentes`. El `fuentes.cobros_fiado` y el docstring de `ForecastSalida` dejan de decir «0 hasta el módulo 5».
12. **WhatsApp es `wa.me` prearmado en el detalle del crédito; el push es del módulo 7 (alcance honesto).** ADR-022 firma push automático + WhatsApp manual. Este módulo: (a) emite `fiado.credito_vencido` desde el trabajo diario — sin PII en el payload (sin nombre de cliente, ADR-025) — y ahí termina: el módulo de notificaciones (módulo 7) lo consumirá y lo traducirá a `notificacion.enviar`; (b) el detalle del crédito trae `whatsapp_url` (`https://wa.me/<telefono>?text=<mensaje>` con el saldo; si el teléfono tiene 10 dígitos se antepone `57`; `null` si el cliente no tiene teléfono). El payload del evento lleva `credito_id`/`cliente_id`/montos/fecha: el módulo 7 arma «Tienes N fiados vencidos» sin nombres.
13. **Los clientes no se borran en el MVP y no hay delta de clientes hacia dispositivos.** No hay DELETE: el cuaderno referencia clientes y un borrado rompería la historia (la edición basta para corregir; un cliente obsoleto simplemente queda sin créditos nuevos — si el piloto pide borrado, vendrá con su decisión). Y los clientes creados en un dispositivo llegan al OTRO solo vía API online (GET /clientes): no hay delta offline de clientes (el delta de ADR-017 cubre productos). El caso real —dos cajas, una crea el cliente offline y la otra le fía sin red antes de sincronizar— no es alcanzable sin que el segundo dispositivo conozca el id del cliente. Se registra como D-28 con vencimiento piloto.

---

## Tarea 1: Migración `0009_fiado` — `clientes`, `fiado_creditos` y `fiado_abonos`

**Files:**
- Create: `backend/tests/test_aislamiento_fiado.py` (primero: el test que falla)
- Create: `backend/services/api/alembic/versions/20260728_0009_fiado.py`

**Interfaces:**
- Consume: `vendi_core.db.rls.enable_rls` / `disable_rls`, fixtures `pg_app_url` / `pg_platform_url` y datos `T1`/`T2` de `backend/tests/datos_de_prueba.py`. Las tablas `ventas` y `caja_sesiones` existentes (FKs RESTRICT).
- Produce: las tres tablas migradas con policy `tenant_isolation`, índices que empiezan por `tenant_id`, sus CHECK, `ux_fiado_creditos_venta` (UN crédito por venta) y grants por defecto.

- [ ] **Paso 1: escribir el test de aislamiento que falla.** Crear `backend/tests/test_aislamiento_fiado.py`:

```python
"""Aislamiento cross-tenant y reglas duras del fiado (módulo fiado y clientes).

Hermano de `test_aislamiento_caja.py`, mismo criterio: SQL crudo con el rol
`vendi_app` y nada de ORM, para que ningún `WHERE` amable dé un falso verde
sobre una policy que no filtra. Las tablas las crea la migración `0009_fiado`;
hasta que existen, TODOS estos tests fallan — que es el punto del paso TDD.
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
    "DELETE FROM fiado_abonos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM fiado_creditos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM clientes WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    """Un cliente por negocio, un crédito de 100.000 en T1 (con su venta y su
    sesión) y un abono de 30.000. Limpia antes y después: la suite es re-entrante."""
    engine = create_async_engine(pg_platform_url)
    ids = {
        "cliente_t1": uuid.uuid4(),
        "cliente_t2": uuid.uuid4(),
        "dispositivo": uuid.uuid4(),
        "sesion": uuid.uuid4(),
        "venta": uuid.uuid4(),
        "credito": uuid.uuid4(),
        "abono": uuid.uuid4(),
    }
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        for nombre, tenant in (("cliente_t1", T1), ("cliente_t2", T2)):
            await conn.execute(
                text("INSERT INTO clientes (id, tenant_id, nombre) VALUES (:c, :t, 'Don Carlos')"),
                {"c": ids[nombre], "t": tenant},
            )
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) "
                 "VALUES (:s, :t, 'dueno', 0)"),
            {"s": ids["sesion"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                 "medio_pago, total_centavos, cliente_id, creada_en_cliente, secuencia_dispositivo) "
                 "VALUES (:v, :t, :d, :s, 1, 'fiado', 100000, :c, now(), 1)"),
            {"v": ids["venta"], "t": T1, "d": ids["dispositivo"], "s": ids["sesion"], "c": ids["cliente_t1"]},
        )
        await conn.execute(
            text("INSERT INTO fiado_creditos (id, tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, "
                 "fecha_vencimiento, estado) "
                 "VALUES (:cr, :t, :c, :v, 100000, 70000, CURRENT_DATE + 10, 'vigente')"),
            {"cr": ids["credito"], "t": T1, "c": ids["cliente_t1"], "v": ids["venta"]},
        )
        await conn.execute(
            text("INSERT INTO fiado_abonos (id, tenant_id, credito_id, sesion_caja_id, monto, metodo_pago, registrado_por) "
                 "VALUES (:a, :t, :cr, :s, 30000, 'efectivo', 'dueno')"),
            {"a": ids["abono"], "t": T1, "cr": ids["credito"], "s": ids["sesion"]},
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
async def test_select_solo_ve_las_tres_tablas_del_propio_tenant(sesion_t1):
    for tabla, esperado in (("clientes", 1), ("fiado_creditos", 1), ("fiado_abonos", 1)):
        filas = (await sesion_t1.execute(text(f"SELECT tenant_id FROM {tabla}"))).all()
        assert len(filas) == esperado, tabla
        assert all(f[0] == T1 for f in filas), tabla


@pytest.mark.asyncio
@pytest.mark.parametrize("tabla, sentencia", [
    ("clientes", "INSERT INTO clientes (tenant_id, nombre) VALUES (:t, 'inyectado')"),
    ("fiado_creditos", "INSERT INTO fiado_creditos (tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, estado) "
                       "VALUES (:t, :c, :v, 100, 100, 'vigente')"),
    ("fiado_abonos", "INSERT INTO fiado_abonos (tenant_id, credito_id, monto, metodo_pago, registrado_por) "
                     "VALUES (:t, :cr, 100, 'efectivo', 'dueno')"),
])
async def test_insert_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1, semilla, tabla, sentencia):
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(
            text(sentencia),
            {"t": T2, "c": semilla["cliente_t2"], "v": semilla["venta"], "cr": semilla["credito"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_saldo_pendiente_no_puede_quedar_negativo(sesion_t1, semilla):
    """`ck_fiado_creditos_saldo_no_negativo`: el desfase es un error, no un
    dato malo (ADR-022). Es la red final del descuento del abono."""
    with pytest.raises(IntegrityError, match="ck_fiado_creditos_saldo_no_negativo"):
        await sesion_t1.execute(
            text("UPDATE fiado_creditos SET saldo_pendiente = -1 WHERE id = :cr"),
            {"cr": semilla["credito"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_saldo_no_puede_superar_el_monto_total(sesion_t1, semilla):
    with pytest.raises(IntegrityError, match="ck_fiado_creditos_saldo_acotado"):
        await sesion_t1.execute(
            text("UPDATE fiado_creditos SET saldo_pendiente = 100001 WHERE id = :cr"),
            {"cr": semilla["credito"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "estado",
    ["moroso", "pagado", "VIGENTE"],
)
async def test_el_estado_es_de_la_lista_cerrada(sesion_t1, semilla, estado):
    with pytest.raises(IntegrityError, match="ck_fiado_creditos_estado"):
        await sesion_t1.execute(
            text("UPDATE fiado_creditos SET estado = :e WHERE id = :cr"),
            {"e": estado, "cr": semilla["credito"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_una_venta_tiene_un_solo_credito(sesion_t1, semilla):
    """`ux_fiado_creditos_venta`: la red del doble crédito (decisión 5)."""
    with pytest.raises(IntegrityError, match="ux_fiado_creditos_venta"):
        await sesion_t1.execute(
            text("INSERT INTO fiado_creditos (tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, estado) "
                 "VALUES (:t, :c, :v, 100, 100, 'vigente')"),
            {"t": T1, "c": semilla["cliente_t1"], "v": semilla["venta"]},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "monto,metodo",
    [
        (0, "efectivo"),          # un abono de cero no es abono
        (-5000, "efectivo"),      # el movimiento inverso NO es un abono negativo
        (1000, "nequi"),          # método fuera de la lista cerrada
    ],
)
async def test_los_checks_del_abono_rechazan_monto_y_metodo_invalidos(sesion_t1, semilla, monto, metodo):
    with pytest.raises(IntegrityError):
        await sesion_t1.execute(
            text("INSERT INTO fiado_abonos (tenant_id, credito_id, monto, metodo_pago, registrado_por) "
                 "VALUES (:t, :cr, :m, :mp, 'dueno')"),
            {"t": T1, "cr": semilla["credito"], "m": monto, "mp": metodo},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_abono_exige_credito_existente(sesion_t1):
    """FK RESTRICT: ningún abono huérfano de crédito (ni siquiera contra un
    UUID al azar: Postgres no aplica RLS al verificar llaves foráneas)."""
    with pytest.raises(IntegrityError, match="fiado_abonos_credito_id_fkey"):
        await sesion_t1.execute(
            text("INSERT INTO fiado_abonos (tenant_id, credito_id, monto, metodo_pago, registrado_por) "
                 "VALUES (:t, :cr, 100, 'efectivo', 'dueno')"),
            {"t": T1, "cr": uuid.uuid4()},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_limite_de_credito_no_es_negativo(sesion_t1, semilla):
    with pytest.raises(IntegrityError, match="ck_clientes_limite_no_negativo"):
        await sesion_t1.execute(
            text("UPDATE clientes SET limite_credito = -1 WHERE id = :c"),
            {"c": semilla["cliente_t1"]},
        )
    await sesion_t1.rollback()
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_aislamiento_fiado.py -q
# Esperado: todos fallan — relation "clientes" does not exist (y las demás tablas)
```

- [ ] **Paso 2: escribir la migración.** Crear `backend/services/api/alembic/versions/20260728_0009_fiado.py`:

```python
"""Fiado y clientes: `clientes`, `fiado_creditos` y `fiado_abonos`
(ADR-022, decisiones 1-5 y 9 del plan del módulo).

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-28

## Qué crea

- `clientes` (ADR-009/ADR-022): la entidad mínima — `nombre`, `telefono`
  (formato WhatsApp colombiano, sin validación internacional en MVP), `nota`
  y `limite_credito` opcional. La PK la pone el cliente cuando nace offline
  (mismo patrón que `ventas` y `productos`: es el cierre de D-10 por
  adopción — `ventas.cliente_id` se queda SIN FK a propósito, decisión 4).
- `fiado_creditos` (ADR-022): una fila por venta fiada (`ux_fiado_creditos_venta`:
  UN crédito por venta — la red del doble crédito, decisión 5). `monto_total`
  y `saldo_pendiente` en centavos enteros; el saldo SÍ se materializa y se
  descuenta en la misma transacción de cada abono, con
  `CHECK (saldo_pendiente >= 0)` como red: el desfase es un error, no un dato
  malo. `estado` es de lista cerrada: las tres firmadas (`vigente`,
  `vencido`, `saldado`) más `anulado` (decisión 3: la anulación de la venta
  fiada anula el crédito; append-only, nunca se borra). `fecha_vencimiento`
  nullable: sin fecha no hay recordatorio (ADR-022).
- `fiado_abonos` (ADR-022): cada pago parcial o total. `monto` estrictamente
  positivo (el movimiento inverso NO es un abono negativo: es un egreso de
  caja manual, decisión 3), `metodo_pago` de lista cerrada (`efectivo`,
  `transferencia`, `otro` — ampliarla exige migración: el arqueo distingue
  por ella, decisión 9) y `sesion_caja_id` NULLABLE: la sesión que cobró el
  efectivo (los demás métodos no tocan la gaveta). Los abonos NO se duplican
  como movimientos de caja: el arqueo los suma desde aquí (ADR-021).

## Grants

Los privilegios por defecto conceden los cuatro a `vendi_app` sobre toda
tabla creada por `vendi_platform` — incluidas estas; `fiado_creditos` de
hecho se actualiza (el saldo y el estado). El candado invertido pasa sin
edición, misma decisión que los módulos anteriores.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Las tres firmadas en ADR-022 más `anulado` (decisión 3 del plan).
ESTADOS_DE_CREDITO = ("vigente", "vencido", "saldado", "anulado")
METODOS_DE_PAGO_ABONO = ("efectivo", "transferencia", "otro")


def upgrade() -> None:
    op.create_table(
        "clientes",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("telefono", sa.String(15), nullable=True),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.Column("limite_credito", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "limite_credito IS NULL OR limite_credito >= 0",
            name="ck_clientes_limite_no_negativo",
        ),
    )
    # La lista y la búsqueda del POS filtran por nombre dentro del tenant.
    op.create_index("ix_clientes_tenant_nombre", "clientes", ["tenant_id", "nombre"])
    enable_rls(op, "clientes", crear_indice=False)

    op.create_table(
        "fiado_creditos",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cliente_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clientes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "venta_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("ventas.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("monto_total", sa.Integer(), nullable=False),
        sa.Column("saldo_pendiente", sa.Integer(), nullable=False),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=True),
        sa.Column("estado", sa.String(12), nullable=False),
        sa.CheckConstraint("monto_total > 0", name="ck_fiado_creditos_monto_positivo"),
        sa.CheckConstraint("saldo_pendiente >= 0", name="ck_fiado_creditos_saldo_no_negativo"),
        sa.CheckConstraint(
            "saldo_pendiente <= monto_total",
            name="ck_fiado_creditos_saldo_acotado",
        ),
        sa.CheckConstraint(
            "estado IN (" + ", ".join(f"'{e}'" for e in ESTADOS_DE_CREDITO) + ")",
            name="ck_fiado_creditos_estado",
        ),
        sa.UniqueConstraint("venta_id", name="ux_fiado_creditos_venta"),
    )
    # El saldo por cliente es un SUM acotado por la policy (Index Cond).
    op.create_index("ix_fiado_creditos_tenant_cliente", "fiado_creditos", ["tenant_id", "cliente_id"])
    # El cuaderno (pendientes por vencimiento) y el trabajo diario de vencidos.
    op.create_index(
        "ix_fiado_creditos_tenant_estado", "fiado_creditos", ["tenant_id", "estado", "fecha_vencimiento"]
    )
    enable_rls(op, "fiado_creditos", crear_indice=False)

    op.create_table(
        "fiado_abonos",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "credito_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("fiado_creditos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # La sesión que cobró el efectivo (decisión 9): NULL en los métodos
        # que no tocan la gaveta. RESTRICT como todo lo de caja.
        sa.Column(
            "sesion_caja_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("caja_sesiones.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("monto", sa.Integer(), nullable=False),
        sa.Column("metodo_pago", sa.String(16), nullable=False),
        sa.Column("registrado_por", sa.String(120), nullable=False),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.CheckConstraint("monto > 0", name="ck_fiado_abonos_monto_positivo"),
        sa.CheckConstraint(
            "metodo_pago IN (" + ", ".join(f"'{m}'" for m in METODOS_DE_PAGO_ABONO) + ")",
            name="ck_fiado_abonos_metodo",
        ),
    )
    # El historial de pagos del crédito (ADR-009) y el SUM del arqueo por
    # sesión (decisión 9).
    op.create_index("ix_fiado_abonos_tenant_credito", "fiado_abonos", ["tenant_id", "credito_id"])
    op.create_index("ix_fiado_abonos_tenant_sesion", "fiado_abonos", ["tenant_id", "sesion_caja_id"])
    enable_rls(op, "fiado_abonos", crear_indice=False)


def downgrade() -> None:
    disable_rls(op, "fiado_abonos", borrar_indice=False)
    op.drop_index("ix_fiado_abonos_tenant_sesion", table_name="fiado_abonos")
    op.drop_index("ix_fiado_abonos_tenant_credito", table_name="fiado_abonos")
    op.drop_table("fiado_abonos")
    disable_rls(op, "fiado_creditos", borrar_indice=False)
    op.drop_index("ix_fiado_creditos_tenant_estado", table_name="fiado_creditos")
    op.drop_index("ix_fiado_creditos_tenant_cliente", table_name="fiado_creditos")
    op.drop_table("fiado_creditos")
    disable_rls(op, "clientes", borrar_indice=False)
    op.drop_index("ix_clientes_tenant_nombre", table_name="clientes")
    op.drop_table("clientes")
```

- [ ] **Paso 3: aplicar la migración y verificar en verde.**

```bash
bash scripts/migrate.sh
# Esperado: ...  -> 0009
cd backend && uv run pytest tests/test_aislamiento_fiado.py -q
# Esperado: 10 passed — 0 SKIPPED
uv run pytest tests/test_rls_coverage.py tests/test_privilegios_de_vendi_app.py -q
# Esperado: verde (las tres tablas con policy; los cuatro privilegios por defecto)
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/alembic/versions/20260728_0009_fiado.py backend/tests/test_aislamiento_fiado.py
git commit -m "Migración 0009: clientes, fiado_creditos con saldo materializado y fiado_abonos, con RLS y checks"
```

**Criterios de aceptación:** la migración aplica y revierte limpio (`alembic downgrade -1` y de vuelta); los 10 tests de aislamiento pasan contra PostgreSQL real con el rol `vendi_app` (0 SKIPPED); el `WITH CHECK` rechaza el `tenant_id` inyectado en las tres tablas; el saldo no puede quedar negativo ni superar el total; una venta no puede tener dos créditos; `test_rls_coverage.py` y `test_privilegios_de_vendi_app.py` siguen verdes sin edición.

---

## Tarea 2: Modelos del módulo fiado

**Files:**
- Create: `backend/tests/test_fiado_modelos.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/fiado/__init__.py` (vacío)
- Create: `backend/services/api/app/modules/fiado/models.py`

**Interfaces:**
- Consume: `vendi_core.db.base.Base` / `TenantModel` (id, tenant_id, created_at, updated_at), las listas cerradas de la migración `0009`.
- Produce: `Cliente`, `FiadoCredito`, `FiadoAbono` y las constantes `ESTADOS_DE_CREDITO` / `METODOS_DE_PAGO_ABONO`, con metadata idéntica a la migración.

- [ ] **Paso 1: escribir el test de metadata que falla.** Crear `backend/tests/test_fiado_modelos.py`:

```python
"""La metadata de los modelos del fiado contra el contrato de la 0009."""

from __future__ import annotations

from app.modules.fiado.models import ESTADOS_DE_CREDITO, METODOS_DE_PAGO_ABONO, Cliente, FiadoAbono, FiadoCredito


def test_las_tres_tablas_tienen_su_nombre_y_tenant():
    assert Cliente.__tablename__ == "clientes"
    assert FiadoCredito.__tablename__ == "fiado_creditos"
    assert FiadoAbono.__tablename__ == "fiado_abonos"
    for modelo in (Cliente, FiadoCredito, FiadoAbono):
        assert "tenant_id" in modelo.__table__.columns


def test_las_listas_cerradas_son_las_de_la_migracion():
    assert ESTADOS_DE_CREDITO == ("vigente", "vencido", "saldado", "anulado")
    assert METODOS_DE_PAGO_ABONO == ("efectivo", "transferencia", "otro")


def test_el_credito_lleva_los_checks_del_saldo_y_la_unicidad_por_venta():
    tabla = FiadoCredito.__table__
    checks = {c.name for c in tabla.check_constraints}
    assert {
        "ck_fiado_creditos_monto_positivo",
        "ck_fiado_creditos_saldo_no_negativo",
        "ck_fiado_creditos_saldo_acotado",
        "ck_fiado_creditos_estado",
    } <= checks
    unicos = {u.name for c in tabla.constraints for u in [c] if c.__class__.__name__ == "UniqueConstraint"}
    assert "ux_fiado_creditos_venta" in unicos
    columnas = tabla.columns
    assert columnas["saldo_pendiente"].nullable is False
    assert columnas["fecha_vencimiento"].nullable is True  # sin fecha = sin recordatorio (ADR-022)
    fks = {fk.target_fullname for fk in tabla.foreign_keys}
    assert fks == {"clientes.id", "ventas.id"}


def test_el_abono_referencia_credito_y_opcionalmente_sesion():
    tabla = FiadoAbono.__table__
    checks = {c.name for c in tabla.check_constraints}
    assert {"ck_fiado_abonos_monto_positivo", "ck_fiado_abonos_metodo"} <= checks
    assert tabla.columns["sesion_caja_id"].nullable is True  # NULL fuera del efectivo (decisión 9)
    fks = {fk.target_fullname for fk in tabla.foreign_keys}
    assert fks == {"fiado_creditos.id", "caja_sesiones.id"}


def test_los_indices_empiezan_por_tenant_id():
    esperados = {
        "clientes": {"ix_clientes_tenant_nombre"},
        "fiado_creditos": {"ix_fiado_creditos_tenant_cliente", "ix_fiado_creditos_tenant_estado"},
        "fiado_abonos": {"ix_fiado_abonos_tenant_credito", "ix_fiado_abonos_tenant_sesion"},
    }
    for modelo in (Cliente, FiadoCredito, FiadoAbono):
        indices = {i.name: i for i in modelo.__table__.indexes}
        assert esperados[modelo.__tablename__] <= set(indices)
        for nombre in esperados[modelo.__tablename__]:
            assert indices[nombre].columns.values()[0].name == "tenant_id"
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_fiado_modelos.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.fiado'
```

- [ ] **Paso 2: crear el paquete y los modelos.** `backend/services/api/app/modules/fiado/__init__.py` vacío. Crear `backend/services/api/app/modules/fiado/models.py`:

```python
"""Modelos del módulo fiado y clientes: el cuaderno (ADR-009/ADR-022).

Una fila de `fiado_creditos` por venta fiada (UN crédito por venta:
`ux_fiado_creditos_venta`). El `saldo_pendiente` SÍ se materializa y se
descuenta en la misma transacción de cada abono; el `CHECK (>= 0)` convierte
el desfase en error, no en dato malo. El saldo por CLIENTE no se guarda: es
`SUM(saldo_pendiente)` de sus créditos `vigente`/`vencido`, calculado en
cada lectura (ADR-022).

`ventas.cliente_id` se queda SIN FK (decisión 4 del plan): la venta no se
rechaza jamás y Postgres no aplica RLS al verificar llaves. Aquí la FK SÍ
existe: el crédito lo crea el servidor, que garantiza la fila del cliente.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import UUID, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, TenantModel

#: Las tres firmadas en ADR-022 más `anulado` (decisión 3: la anulación de
#: la venta fiada anula el crédito; append-only, nunca se borra).
ESTADOS_DE_CREDITO: tuple[str, ...] = ("vigente", "vencido", "saldado", "anulado")

#: Cómo pagó el cliente. El arqueo solo suma `efectivo` (decisión 9);
#: ampliar la lista exige migración, a propósito.
METODOS_DE_PAGO_ABONO: tuple[str, ...] = ("efectivo", "transferencia", "otro")

#: Estados con deuda viva: el saldo por cliente suma solo estos (ADR-022).
ESTADOS_CON_DEUDA: tuple[str, ...] = ("vigente", "vencido")


class Cliente(Base, TenantModel):
    """El vecino del cuaderno (ADR-009): nombre, teléfono para el `wa.me`,
    nota y límite de crédito opcional. Sin más: el CRM avanzado es Fase 3.

    La PK la pone el cliente cuando nace offline (patrón ADR-017, cierre de
    D-10 por adopción). No se borra (decisión 13): el cuaderno lo referencia
    y la historia no se reescribe."""

    __tablename__ = "clientes"
    __table_args__ = (
        Index("ix_clientes_tenant_nombre", "tenant_id", "nombre"),
        CheckConstraint("limite_credito IS NULL OR limite_credito >= 0", name="ck_clientes_limite_no_negativo"),
    )

    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    #: Formato WhatsApp colombiano, solo dígitos (la limpieza es del schema).
    telefono: Mapped[str | None] = mapped_column(String(15), nullable=True)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: NULL = sin cupo declarado: se fía sin tope (el cuaderno nunca dijo que no).
    limite_credito: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FiadoCredito(Base, TenantModel):
    """Un fiado: «Don Carlos me debe 43.000 del martes». Una fila por venta
    fiada; el crédito no duplica las líneas de la venta (ADR-022).

    `saldo_pendiente` se materializa y se descuenta en la misma transacción
    del abono, con el CHECK como red. `fecha_vencimiento` NULL = sin
    recordatorio (ADR-022). `anulado` es el cuarto estado (decisión 3): la
    anulación de la venta fiada lo pone en 0 y lo cierra; un `saldado` o
    `anulado` nunca vuelve a `vigente`."""

    __tablename__ = "fiado_creditos"
    __table_args__ = (
        Index("ix_fiado_creditos_tenant_cliente", "tenant_id", "cliente_id"),
        Index("ix_fiado_creditos_tenant_estado", "tenant_id", "estado", "fecha_vencimiento"),
        UniqueConstraint("venta_id", name="ux_fiado_creditos_venta"),
        CheckConstraint("monto_total > 0", name="ck_fiado_creditos_monto_positivo"),
        CheckConstraint("saldo_pendiente >= 0", name="ck_fiado_creditos_saldo_no_negativo"),
        CheckConstraint("saldo_pendiente <= monto_total", name="ck_fiado_creditos_saldo_acotado"),
        CheckConstraint(
            "estado IN (" + ", ".join(f"'{e}'" for e in ESTADOS_DE_CREDITO) + ")",
            name="ck_fiado_creditos_estado",
        ),
    )

    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False
    )
    venta_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ventas.id", ondelete="RESTRICT"), nullable=False
    )
    #: Centavos enteros (criterio unificado ADR-018).
    monto_total: Mapped[int] = mapped_column(Integer, nullable=False)
    saldo_pendiente: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_vencimiento: Mapped[date | None] = mapped_column(nullable=True)
    estado: Mapped[str] = mapped_column(String(12), nullable=False, default="vigente")


class FiadoAbono(Base, TenantModel):
    """Un pago parcial o total contra el crédito que el usuario tocó
    (ADR-022: nada de aplicarlo al más antiguo automáticamente).

    Append-only: el historial de pagos de ADR-009 es la verdad y no se
    reescribe. La PK es el UUID del cliente (REQUERIDO en el schema: es
    dinero — solo la ancla hace seguro el reintento tras un timeout, y deja
    lista la vía del abono offline, decisión 6). `sesion_caja_id` es la
    sesión que cobró el efectivo (NULL en los demás métodos, decisión 9):
    el arqueo la suma desde aquí, sin duplicar movimientos (ADR-021)."""

    __tablename__ = "fiado_abonos"
    __table_args__ = (
        Index("ix_fiado_abonos_tenant_credito", "tenant_id", "credito_id"),
        Index("ix_fiado_abonos_tenant_sesion", "tenant_id", "sesion_caja_id"),
        CheckConstraint("monto > 0", name="ck_fiado_abonos_monto_positivo"),
        CheckConstraint(
            "metodo_pago IN (" + ", ".join(f"'{m}'" for m in METODOS_DE_PAGO_ABONO) + ")",
            name="ck_fiado_abonos_metodo",
        ),
    )

    credito_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fiado_creditos.id", ondelete="RESTRICT"), nullable=False
    )
    sesion_caja_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caja_sesiones.id", ondelete="RESTRICT"), nullable=True
    )
    monto: Mapped[int] = mapped_column(Integer, nullable=False)
    metodo_pago: Mapped[str] = mapped_column(String(16), nullable=False)
    registrado_por: Mapped[str] = mapped_column(String(120), nullable=False)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Paso 3: verificar en verde.**

```bash
cd backend && uv run pytest tests/test_fiado_modelos.py -q
# Esperado: 5 passed
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/fiado/__init__.py backend/services/api/app/modules/fiado/models.py backend/tests/test_fiado_modelos.py
git commit -m "Modelos del fiado: clientes, créditos con saldo materializado y abonos"
```

**Criterios de aceptación:** la metadata de los modelos coincide con la migración `0009` (tablas, checks, unique, índices que empiezan por `tenant_id`, FKs); `alembic check` no reporta deriva si se corre a mano (D-17 sigue abierta: no corre en CI); `ruff` limpio.

---

## Tarea 3: Schemas del módulo fiado

**Files:**
- Create: `backend/tests/test_fiado_schemas.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/fiado/schemas.py`

**Interfaces:**
- Consume: `TOPE_PRECIO` y `_limpiar_texto` de `app.modules.catalogo.schemas`; las listas cerradas de `fiado/models.py`.
- Produce: entradas (`ClienteCrear`, `ClienteEditar`, `ClienteCrearSync`, `AbonoCrear`, `CreditoReprogramar`) y salidas (`ClienteSalida`, `ClienteConSaldo`, `ClienteDetalleSalida`, `CreditoResumenSalida`, `CreditoDetalleSalida`, `AbonoSalida`).

- [ ] **Paso 1: escribir el test que falla.** Crear `backend/tests/test_fiado_schemas.py`:

```python
"""Las reglas de los schemas del fiado (cotas, limpieza, teléfono, listas)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.catalogo.schemas import TOPE_PRECIO
from app.modules.fiado.schemas import AbonoCrear, ClienteCrear, ClienteCrearSync, ClienteEditar, CreditoReprogramar


def _cliente(**cambios) -> dict:
    return {"nombre": "Don Carlos", "telefono": "300 123 4567", **cambios}


def test_cliente_crear_valido_y_limpieza():
    c = ClienteCrear.model_validate(_cliente(nombre="  Don   Carlos  "))
    assert c.nombre == "Don Carlos"
    assert c.telefono == "3001234567"  # espacios fuera; solo dígitos
    assert c.id is None and c.limite_credito is None and c.nota is None


def test_el_telefono_admite_indicativo_y_rechaza_lo_que_no_es_whatsapp():
    assert ClienteCrear.model_validate(_cliente(telefono="+57 3001234567")).telefono == "573001234567"
    for malo in ("12345", "3001234567890123456", "trescientos", "300-123-45-67x"):
        with pytest.raises(ValidationError):
            ClienteCrear.model_validate(_cliente(telefono=malo))


def test_el_telefono_es_opcional():
    assert ClienteCrear.model_validate({"nombre": "La vecina"}).telefono is None


def test_el_limite_lleva_cota_y_no_es_negativo():
    with pytest.raises(ValidationError):
        ClienteCrear.model_validate(_cliente(limite_credito=-1))
    with pytest.raises(ValidationError):
        ClienteCrear.model_validate(_cliente(limite_credito=TOPE_PRECIO + 1))
    assert ClienteCrear.model_validate(_cliente(limite_credito=0)).limite_credito == 0  # cero: no fiarle más


def test_los_campos_desconocidos_se_rechazan():
    with pytest.raises(ValidationError):
        ClienteCrear.model_validate(_cliente(tenant_id=str(uuid.uuid4())))
    with pytest.raises(ValidationError):
        AbonoCrear.model_validate(
            {"id": str(uuid.uuid4()), "monto": 100, "metodo_pago": "efectivo", "tenant_id": str(uuid.uuid4())}
        )


def test_el_nombre_no_son_puros_espacios():
    with pytest.raises(ValidationError):
        ClienteCrear.model_validate({"nombre": "    "})


def test_cliente_editar_todo_opcional_y_limite_borrable():
    assert ClienteEditar.model_validate({}).model_dump(exclude_unset=True) == {}
    # null explícito: quitar el cupo (vuelve a «sin tope»).
    assert ClienteEditar.model_validate({"limite_credito": None}).limite_credito is None
    with pytest.raises(ValidationError):
        ClienteEditar.model_validate({"nombre": "x"})


def test_abono_exige_id_monto_positivo_y_metodo_de_la_lista():
    with pytest.raises(ValidationError):
        AbonoCrear.model_validate({"monto": 100, "metodo_pago": "efectivo"})  # sin id (la ancla)
    for malo in (0, -100, TOPE_PRECIO + 1):
        with pytest.raises(ValidationError):
            AbonoCrear.model_validate({"id": str(uuid.uuid4()), "monto": malo, "metodo_pago": "efectivo"})
    with pytest.raises(ValidationError):
        AbonoCrear.model_validate({"id": str(uuid.uuid4()), "monto": 100, "metodo_pago": "nequi"})
    ok = AbonoCrear.model_validate({"id": str(uuid.uuid4()), "monto": 100, "metodo_pago": "transferencia"})
    assert ok.nota is None


def test_la_nota_se_limpia_y_es_opcional():
    ok = AbonoCrear.model_validate(
        {"id": str(uuid.uuid4()), "monto": 100, "metodo_pago": "otro", "nota": "  dejó   el  destajo  "}
    )
    assert ok.nota == "dejó el destajo"


def test_reprogramar_admite_fecha_o_null():
    assert CreditoReprogramar.model_validate({"fecha_vencimiento": "2026-08-15"}).fecha_vencimiento is not None
    assert CreditoReprogramar.model_validate({"fecha_vencimiento": None}).fecha_vencimiento is None


def test_cliente_sync_es_el_contrato_del_lote():
    ok = ClienteCrearSync.model_validate({"nombre": "Don Carlos", "telefono": "3001234567"})
    assert ok.limite_credito is None
    with pytest.raises(ValidationError):
        ClienteCrearSync.model_validate({"nombre": "X"})
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_fiado_schemas.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.fiado.schemas'
```

- [ ] **Paso 2: escribir los schemas.** Crear `backend/services/api/app/modules/fiado/schemas.py`:

```python
"""Schemas del módulo fiado y clientes (ADR-022).

El contrato que consume el frontend sale de aquí vía `openapi.json`: cada
cambio es un cambio de contrato (se regenera el congelado y el cliente TS).

Dinero SIEMPRE en centavos enteros, con cota `le=TOPE_PRECIO` contra la
columna `Integer` (un overflow saldría como `DataError` → 500, no como 422:
BUG-2 del QA del catálogo). La limpieza de texto va ANTES de las cotas de
largo y ningún validador `mode="before"` asume `str` (BUG-1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.catalogo.schemas import TOPE_PRECIO, _limpiar_texto
from app.modules.fiado.models import METODOS_DE_PAGO_ABONO


def _telefono_limpio(valor: object) -> object:
    """Formato WhatsApp colombiano, sin validación internacional (ADR-022):
    solo dígitos, 10 a 15 (10 = celular local sin indicativo). Corre ANTES
    de la validación de tipo (mode="before"): lo que no sea str pasa intacto
    para que pydantic lo rechace como 422 (BUG-1)."""
    if valor is None or not isinstance(valor, str):
        return valor
    limpio = valor.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if limpio.startswith("+"):
        limpio = limpio[1:]
    if not limpio.isdigit() or not 10 <= len(limpio) <= 15:
        raise ValueError("El teléfono debe ser de WhatsApp: solo dígitos, entre 10 y 15 (con indicativo).")
    return limpio


# --- Entradas ------------------------------------------------------------


class ClienteCrear(BaseModel):
    """Alta online de un cliente. `id` es el UUID del cliente (ADR-017):
    reenviar el mismo alta devuelve el existente; con otro contenido, 409."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    nombre: str = Field(min_length=2, max_length=160)
    telefono: str | None = None
    nota: str | None = Field(default=None, max_length=300)
    #: NULL = sin cupo: se fía sin tope (el cuaderno nunca le dijo que no a
    #: nadie). 0 = no fiarle más. El servidor nunca rechaza por cupo
    #: (ADR-018): lo registra y lo muestra (decisión 8).
    limite_credito: int | None = Field(default=None, ge=0, le=TOPE_PRECIO)

    _nombre_limpio = field_validator("nombre", mode="before")(_limpiar_texto)
    _nota_limpia = field_validator("nota", mode="before")(_limpiar_texto)
    _telefono_valido = field_validator("telefono", mode="before")(_telefono_limpio)


class ClienteEditar(BaseModel):
    """Edición parcial. `null` explícito en `limite_credito`/`telefono`/`nota`
    BORRA el valor (vuelve a «sin cupo»/«sin teléfono»)."""

    model_config = ConfigDict(extra="forbid")

    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    telefono: str | None = None
    nota: str | None = Field(default=None, max_length=300)
    limite_credito: int | None = Field(default=None, ge=0, le=TOPE_PRECIO)

    _nombre_limpio = field_validator("nombre", mode="before")(_limpiar_texto)
    _nota_limpia = field_validator("nota", mode="before")(_limpiar_texto)
    _telefono_valido = field_validator("telefono", mode="before")(_telefono_limpio)


class ClienteCrearSync(BaseModel):
    """Los datos de una operación `cliente.crear` del lote (decisión 2). El
    id del cliente ES el id de la operación (`OperacionSync.id`): la PK que
    puso el dispositivo, adoptada como PK (cierre de D-10)."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=2, max_length=160)
    telefono: str | None = None
    nota: str | None = Field(default=None, max_length=300)
    limite_credito: int | None = Field(default=None, ge=0, le=TOPE_PRECIO)

    _nombre_limpio = field_validator("nombre", mode="before")(_limpiar_texto)
    _nota_limpia = field_validator("nota", mode="before")(_limpiar_texto)
    _telefono_valido = field_validator("telefono", mode="before")(_telefono_limpio)


class AbonoCrear(BaseModel):
    """Un pago contra el crédito que el usuario tocó (ADR-022).

    `id` es REQUERIDO (es dinero: solo la ancla hace seguro el reintento
    tras un timeout — y deja lista la vía del abono offline por el lote,
    decisión 6). El servidor descuenta el saldo en la misma transacción; un
    abono mayor que el saldo es 422 `abono_excede_saldo` (el CHECK es la
    red, no la regla)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    monto: int = Field(gt=0, le=TOPE_PRECIO)
    metodo_pago: Literal[*METODOS_DE_PAGO_ABONO]
    nota: str | None = Field(default=None, max_length=300)

    _nota_limpia = field_validator("nota", mode="before")(_limpiar_texto)


class CreditoReprogramar(BaseModel):
    """«Deme hasta el otro viernes»: nueva fecha de vencimiento (o null para
    dejarlo sin recordatorio). Un `vencido` reprogramado a futuro vuelve a
    `vigente` (decisión 7)."""

    model_config = ConfigDict(extra="forbid")

    fecha_vencimiento: date | None = None


# --- Salidas -------------------------------------------------------------


class ClienteSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    telefono: str | None = None
    nota: str | None = None
    limite_credito: int | None = None
    created_at: datetime | None = None


class CreditoResumenSalida(BaseModel):
    """Un fiado del cuaderno. `monto_total` y `saldo_pendiente` en centavos."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cliente_id: uuid.UUID
    venta_id: uuid.UUID
    monto_total: int
    saldo_pendiente: int
    fecha_vencimiento: date | None = None
    estado: str
    created_at: datetime | None = None
    #: El nombre viaja para que el cuaderno diga «Don Carlos me debe...» sin
    #: un segundo viaje por crédito.
    cliente_nombre: str | None = None


class ClienteConSaldo(ClienteSalida):
    """El cliente con su deuda viva: `SUM(saldo_pendiente)` de sus créditos
    `vigente`/`vencido` — calculado en cada lectura, nunca guardado
    (ADR-022) — y el cupo evaluado (decisión 8)."""

    saldo_pendiente_total: int
    cupo_excedido: bool


class ClienteDetalleSalida(ClienteConSaldo):
    """La ficha del cliente: sus datos, su saldo y sus fiados con deuda."""

    creditos: list[CreditoResumenSalida] = []


class AbonoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    credito_id: uuid.UUID
    sesion_caja_id: uuid.UUID | None = None
    monto: int
    metodo_pago: str
    registrado_por: str
    nota: str | None = None
    created_at: datetime | None = None


class CreditoDetalleSalida(CreditoResumenSalida):
    """La pantalla del fiado: su historial de pagos (ADR-009) y el enlace
    `wa.me` prearmado para cobrarle (ADR-022: WhatsApp manual). `null` si el
    cliente no tiene teléfono."""

    abonos: list[AbonoSalida] = []
    whatsapp_url: str | None = None


__all__ = [
    "AbonoCrear",
    "AbonoSalida",
    "ClienteConSaldo",
    "ClienteCrear",
    "ClienteCrearSync",
    "ClienteDetalleSalida",
    "ClienteEditar",
    "ClienteSalida",
    "CreditoDetalleSalida",
    "CreditoReprogramar",
    "CreditoResumenSalida",
]
```

- [ ] **Paso 3: verificar en verde.**

```bash
cd backend && uv run pytest tests/test_fiado_schemas.py -q
# Esperado: 11 passed
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/fiado/schemas.py backend/tests/test_fiado_schemas.py
git commit -m "Schemas del fiado: clientes, abonos con ancla obligatoria y salidas con saldo y cupo"
```

**Criterios de aceptación:** las cotas `le=TOPE_PRECIO` están en todo entero de entrada; el teléfono se limpia y valida sin asumir `str`; `extra="forbid"` en todas las entradas; la nota y el nombre se limpian antes de las cotas; los 11 tests pasan; `ruff` limpio.

---

## Tarea 4: Los tres permisos que faltan del catálogo de 14 (ADR-023)

**Files:**
- Modify: `backend/tests/test_auth_policies.py` (primero: el test que falla)
- Modify: `backend/libs/vendi-core/src/vendi_core/auth/policies.py`

**Interfaces:**
- Consume: `PERMISSION_CATALOG`, `PERMISOS_POR_ROL`, `roles_de_realm_del_grupo`, `ROL_CAJERO`, `ROL_ALMACENISTA`, `ROL_DUENO`.
- Produce: `PERM_CLIENTE_GESTIONAR`, `PERM_FIADO_CREAR`, `PERM_FIADO_ABONAR` en el catálogo; el reparto exacto de ADR-023.

- [ ] **Paso 1: añadir el test que falla.** Al final de `backend/tests/test_auth_policies.py`:

```python
def test_el_catalogo_de_14_se_completa_con_fiado_y_clientes():
    """ADR-023: `cliente:gestionar`, `fiado:crear` y `fiado:abonar` son los
    tres últimos del catálogo cerrado de 14. Ampliarlo exige ADR nuevo."""
    from vendi_core.auth.policies import PERM_CLIENTE_GESTIONAR, PERM_FIADO_ABONAR, PERM_FIADO_CREAR

    catalogo = {nombre for nombre, _modulo in PERMISSION_CATALOG}
    assert {PERM_CLIENTE_GESTIONAR, PERM_FIADO_CREAR, PERM_FIADO_ABONAR} <= catalogo
    dominio = {n for n, m in PERMISSION_CATALOG if m not in ("tenant", "platform", "audit")}
    assert len(dominio) == 14  # el catálogo de dominio de ADR-023, completo


def test_el_reparto_de_fiado_es_el_de_adr_023():
    """El cajero fía y cobra abonos (y gestiona clientes: los necesita para
    fiar); el almacenista no toca fiado; el dueño lo tiene todo."""
    from vendi_core.auth.policies import (
        PERM_CLIENTE_GESTIONAR,
        PERM_FIADO_ABONAR,
        PERM_FIADO_CREAR,
        ROL_ALMACENISTA,
        ROL_CAJERO,
        ROL_DUENO,
    )

    los_tres = {PERM_CLIENTE_GESTIONAR, PERM_FIADO_CREAR, PERM_FIADO_ABONAR}
    assert los_tres <= PERMISOS_POR_ROL[ROL_DUENO]
    assert los_tres <= PERMISOS_POR_ROL[ROL_CAJERO]
    assert not (los_tres & PERMISOS_POR_ROL[ROL_ALMACENISTA])
```

y añadir los nombres nuevos al import de `vendi_core.auth.policies` del archivo (`PERM_CLIENTE_GESTIONAR`, `PERM_FIADO_ABONAR`, `PERM_FIADO_CREAR` — si el import ya es amplio, dejar solo los que falten).

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_auth_policies.py -q
# Esperado: ImportError: cannot import name 'PERM_CLIENTE_GESTIONAR' from 'vendi_core.auth.policies'
```

- [ ] **Paso 2: añadir los permisos al catálogo y al reparto.** En `backend/libs/vendi-core/src/vendi_core/auth/policies.py`, tras el bloque de caja y reportes:

```python
# Fiado y clientes (ADR-022/ADR-023): el cuaderno. El cajero fía y cobra
# abonos — el fiado es el modo normal de vender y cobrar en la tienda — y
# gestiona los clientes (necesita el saldo para fiar y para cobrar). El
# almacenista no toca fiado: su trabajo es el estante.
PERM_CLIENTE_GESTIONAR = "cliente:gestionar"
PERM_FIADO_CREAR = "fiado:crear"
PERM_FIADO_ABONAR = "fiado:abonar"
```

En `PERMISSION_CATALOG`, tras `(PERM_REPORTE_LEER, "reporte")`:

```python
    (PERM_CLIENTE_GESTIONAR, "cliente"),
    (PERM_FIADO_CREAR, "fiado"),
    (PERM_FIADO_ABONAR, "fiado"),
```

En `_PERMISOS_DUENO`, añadir los tres nombres al set. Y reemplazar el bloque del cajero (con su comentario actualizado):

```python
# ADR-023: el cajero consulta el catálogo, vende, fía, cobra abonos, gestiona
# los clientes, abre su caja y registra movimientos, pero NO edita el
# catálogo, NO anula ventas, NO ajusta inventario, NO registra compras, NO
# cierra la caja y NO ve reportes (anular y arquear son los gestos con los
# que se desfalca una tienda; son del dueño en el MVP). El almacenista
# mantiene el catálogo, ajusta el inventario y registra las compras; no
# vende ni toca caja ni fiado.
_PERMISOS_CAJERO: frozenset[str] = frozenset(
    {
        PERM_PRODUCTO_LEER,
        PERM_VENTA_CREAR,
        PERM_CAJA_LEER,
        PERM_CAJA_ABRIR,
        PERM_CAJA_MOVIMIENTO,
        PERM_CLIENTE_GESTIONAR,
        PERM_FIADO_CREAR,
        PERM_FIADO_ABONAR,
    }
)
```

- [ ] **Paso 3: verificar en verde y re-sembrar.**

```bash
cd backend && uv run pytest tests/test_auth_policies.py -q
# Esperado: verde, con los 2 tests nuevos
bash scripts/seed.sh
# Esperado: los grupos dueno/cajero mapean los tres roles de realm nuevos en Keycloak
```

- [ ] **Paso 4: commit**

```bash
git add backend/libs/vendi-core/src/vendi_core/auth/policies.py backend/tests/test_auth_policies.py
git commit -m "Catálogo de permisos completo: cliente:gestionar, fiado:crear y fiado:abonar con el reparto de ADR-023"
```

**Criterios de aceptación:** el catálogo de dominio tiene exactamente los 14 permisos de ADR-023; `PERMISOS_POR_ROL ⊆ PERMISSION_CATALOG` sigue verde; el cajero hereda los tres en el token tras la siembra (lo verifica el check 23 en la Tarea 11); el almacenista no gana ninguno.

---

## Tarea 5: Servicio — clientes con saldo y cupo calculados

**Files:**
- Create: `backend/tests/test_fiado_servicio.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/fiado/service.py`

**Interfaces:**
- Consume: los modelos y schemas de las Tareas 2-3; `ZONA_LOCAL` de `app.modules.caja.reportes`; `CajaSesion` de `app.modules.ventas.models` (la usa la Tarea 6); `DomainEventService` (Tarea 6).
- Produce: `FiadoService` con el CRUD de clientes y las lecturas con saldo/cupo; la Tarea 6 añade cuaderno, detalle, reprogramación y abonos sobre el mismo archivo.

- [ ] **Paso 1: escribir el test que falla.** Crear `backend/tests/test_fiado_servicio.py`:

```python
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

from app.modules.fiado.schemas import AbonoCrear, ClienteCrear, ClienteEditar, CreditoReprogramar
from app.modules.fiado.service import FiadoService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import ConflictError, NotFoundError, ValidationError
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
            text("INSERT INTO clientes (id, tenant_id, nombre, telefono, limite_credito) "
                 "VALUES (:c, :t, 'Don Carlos', '3001234567', 100000)"),
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
            consecutivo = (await conn.execute(text("SELECT count(*) FROM ventas WHERE tenant_id = :t"), {"t": T1})).scalar_one() + 1
            await conn.execute(
                text("INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                     "medio_pago, total_centavos, cliente_id, creada_en_cliente, secuencia_dispositivo) "
                     f"VALUES (:v, :t, :d, :s, {consecutivo}, 'fiado', :m, :c, now(), 1)"),
                {"v": venta_id, "t": T1, "d": semilla["dispositivo"], "s": semilla["sesion"],
                 "m": monto, "c": cliente_id or semilla["cliente"]},
            )
            await conn.execute(
                text(f"INSERT INTO fiado_creditos (id, tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, "
                     f"fecha_vencimiento, estado) VALUES (:cr, :t, :c, :v, :m, :s, {vencimiento}, :e)"),
                {"cr": credito_id, "t": T1, "c": cliente_id or semilla["cliente"], "v": venta_id, "m": monto,
                 "s": saldo, "e": estado},
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
        semilla["cliente"], ClienteEditar.model_validate({"nombre": "Don Carlos (el de la esquina)", "limite_credito": None})
    )
    assert editado.nombre == "Don Carlos (el de la esquina)" and editado.limite_credito is None


@pytest.mark.asyncio
async def test_buscar_por_nombre(servicio, semilla):
    filas, total = await servicio.listar_clientes("carlos")
    assert total == 1 and filas[0].nombre == "Don Carlos"
    filas, total = await servicio.listar_clientes("nadie-se-llama-así")
    assert total == 0 and filas == []
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_fiado_servicio.py -q
# Esperado: ModuleNotFoundError: No module named 'app.modules.fiado.service'
```

- [ ] **Paso 2: escribir el servicio (parte de clientes).** Crear `backend/services/api/app/modules/fiado/service.py`:

```python
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
            raise ConflictError("Ese id de cliente ya está en uso. Genera uno nuevo.", code="cliente_id_en_conflicto") from exc
        logger.info("cliente_creado", cliente_id=str(cliente.id))
        return ClienteSalida.model_validate(cliente)

    async def listar_clientes(self, q: str | None, *, skip: int = 0, limit: int = 25) -> tuple[list[ClienteConSaldo], int]:
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
            (
                await self._session.execute(
                    select(Cliente, func.coalesce(saldos.c.saldo, 0))
                    .outerjoin(saldos, saldos.c.cliente_id == Cliente.id)
                    .where(*filtro)
                    .order_by(Cliente.nombre, Cliente.id)
                    .offset(skip)
                    .limit(limit)
                )
            )
            .all()
        )
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
```

- [ ] **Paso 3: verificar en verde.**

```bash
cd backend && uv run pytest tests/test_fiado_servicio.py -q
# Esperado: 7 passed — 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/fiado/service.py backend/tests/test_fiado_servicio.py
git commit -m "Servicio del fiado: clientes con saldo calculado por lectura y cupo nunca materializado"
```

**Criterios de aceptación:** el saldo por cliente es un `SUM` calculado (vigente + vencido; el saldado no cuenta); el cupo se evalúa en cada lectura; el alta es idempotente por `id` con divergencia explícita; el cliente del vecino es 404/invisible; la búsqueda filtra por nombre; los 7 tests pasan (0 SKIPPED); `ruff` limpio.

---

## Tarea 6: Servicio — abonos al peso, cuaderno, detalle y reprogramación

**Files:**
- Modify: `backend/tests/test_fiado_servicio.py` (los tests nuevos, primero: fallan)
- Modify: `backend/services/api/app/modules/fiado/service.py`

**Interfaces:**
- Consume: el servicio de la Tarea 5; `CajaSesion` (ya importada); `DomainEventService`; los eventos firmados de ADR-022.
- Produce: `registrar_abono` (el candado del saldo), `listar_creditos`, `obtener_credito` (con historial y `whatsapp_url`), `reprogramar_vencimiento`.

- [ ] **Paso 1: añadir los tests que fallan.** Al final de `backend/tests/test_fiado_servicio.py`:

```python
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
            text("UPDATE caja_sesiones SET estado = 'cerrada', cerrada_por = 'dueno', cerrada_en = now(), "
                 "efectivo_esperado = 0, efectivo_contado = 0, diferencia = 0 WHERE id = :s"),
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
        await servicio.registrar_abono(credito_id, AbonoCrear.model_validate(
            {"id": str(datos.id), "monto": 25000, "metodo_pago": "efectivo"}))
    assert exc2.value.code == "abono_id_divergente"


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
                await servicio_t2.registrar_abono(credito_de_t1, _abono(1000))
            assert exc.value.code == "credito_no_encontrado"
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


@pytest.mark.asyncio
async def test_reprogramar_un_vencido_a_futuro_lo_devuelve_a_vigente(servicio, pg_platform_url, semilla):
    """«Deme hasta el otro viernes» (decisión 7): el `vencido` reprogramado
    vuelve a `vigente` y podrá volver a vencer con su recordatorio."""
    credito_id = await _credito(pg_platform_url, semilla, 50000, 50000, estado="vencido", vencimiento="CURRENT_DATE - 1")
    reprogramado = await servicio.reprogramar_vencimiento(
        credito_id, CreditoReprogramar.model_validate({"fecha_vencimiento": "2099-01-15"})
    )
    assert reprogramado.estado == "vigente" and str(reprogramado.fecha_vencimiento) == "2099-01-15"
    saldado = await _credito(pg_platform_url, semilla, 50000, 0, estado="saldado")
    with pytest.raises(ConflictError) as exc:
        await servicio.reprogramar_vencimiento(saldado, CreditoReprogramar.model_validate({"fecha_vencimiento": "2099-01-15"}))
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
    credito_id = await _credito(pg_platform_url, semilla, 43000, 43000)
    detalle = await servicio.obtener_credito(credito_id)
    assert detalle.whatsapp_url is not None
    assert detalle.whatsapp_url.startswith("https://wa.me/573001234567?text=")
    assert "%2443.000" in detalle.whatsapp_url  # «$43.000» codificado
    sin_telefono = await servicio.crear_cliente(ClienteCrear.model_validate({"nombre": "Sin número"}))
    credito_sin = await _credito(pg_platform_url, semilla, 10000, 10000, cliente_id=sin_telefono.id)
    assert (await servicio.obtener_credito(credito_sin)).whatsapp_url is None
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_fiado_servicio.py -q
# Esperado: los 7 de la Tarea 5 pasan; los 10 nuevos fallan — AttributeError: 'FiadoService' object has no attribute 'registrar_abono'
```

- [ ] **Paso 2: añadir al servicio.** En `backend/services/api/app/modules/fiado/service.py`, tras `editar_cliente` y antes de `# --- Internas`:

```python
    # --- El cuaderno (créditos) ---------------------------------------------------

    async def listar_creditos(
        self, estado: str | None, *, skip: int = 0, limit: int = 25
    ) -> tuple[list[CreditoResumenSalida], int]:
        """El cuaderno: por defecto solo lo que se debe (`vigente` + `vencido`),
        lo que vence primero arriba. `estado="todos"` incluye la historia."""
        filtro = []
        if estado is None:
            filtro.append(FiadoCredito.estado.in_(ESTADOS_CON_DEUDA))
        elif estado != "todos":
            filtro.append(FiadoCredito.estado == estado)
        total = (
            await self._session.execute(select(func.count()).select_from(FiadoCredito).where(*filtro))
        ).scalar_one()
        filas = (
            (
                await self._session.execute(
                    select(FiadoCredito, Cliente.nombre)
                    .join(Cliente, FiadoCredito.cliente_id == Cliente.id)
                    .where(*filtro)
                    .order_by(FiadoCredito.fecha_vencimiento.asc().nulls_last(), FiadoCredito.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .all()
        )
        return [self._resumen(credito, nombre) for credito, nombre in filas], int(total)

    async def obtener_credito(self, credito_id: uuid.UUID) -> CreditoDetalleSalida:
        """La pantalla del fiado: su historial de pagos (ADR-009: es la
        verdad y no se reescribe) y el `wa.me` prearmado para cobrarle."""
        credito = await self._session.get(FiadoCredito, credito_id)
        if credito is None:
            raise NotFoundError("El crédito no existe.", code="credito_no_encontrado")
        cliente = await self._session.get(Cliente, credito.cliente_id)
        abonos = (
            (
                await self._session.execute(
                    select(FiadoAbono).where(FiadoAbono.credito_id == credito.id).order_by(FiadoAbono.created_at, FiadoAbono.id)
                )
            )
            .scalars()
            .all()
        )
        salida = CreditoDetalleSalida.model_validate(credito)
        salida.cliente_nombre = cliente.nombre if cliente is not None else None
        salida.abonos = [AbonoSalida.model_validate(a) for a in abonos]
        salida.whatsapp_url = construir_whatsapp_url(cliente, credito) if cliente is not None else None
        return salida

    async def reprogramar_vencimiento(self, credito_id: uuid.UUID, datos: CreditoReprogramar) -> CreditoResumenSalida:
        """«Deme hasta el otro viernes». Un `vencido` reprogramado a futuro
        (o dejado sin fecha) vuelve a `vigente` — la transición ES el
        anti-duplicado del recordatorio, así que esto no rompe nada
        (decisión 7) —; un `saldado`/`anulado` ya no se toca."""
        credito = await self._session.get(FiadoCredito, credito_id, with_for_update=True)
        if credito is None:
            raise NotFoundError("El crédito no existe.", code="credito_no_encontrado")
        if credito.estado in ("saldado", "anulado"):
            raise ConflictError(
                f"Este crédito está {credito.estado}: ya no se reprograma.",
                code="credito_no_editable",
                details={"estado": credito.estado},
            )
        credito.fecha_vencimiento = datos.fecha_vencimiento
        if credito.estado == "vencido" and (
            datos.fecha_vencimiento is None or datos.fecha_vencimiento >= datetime.now(ZONA_LOCAL).date()
        ):
            credito.estado = "vigente"
        credito.updated_at = datetime.now(UTC)
        await self._session.flush()
        logger.info("fiado_credito_reprogramado", credito_id=str(credito.id), fecha=str(datos.fecha_vencimiento))
        return self._resumen(credito, None)

    # --- Abonos -------------------------------------------------------------------

    async def registrar_abono(self, credito_id: uuid.UUID, datos: AbonoCrear) -> AbonoSalida:
        """Un pago contra el crédito que el usuario tocó (ADR-022).

        - Idempotente por el `id` REQUERIDO del cliente (es dinero: la ancla
          hace seguro el reintento tras un timeout). Reintento idéntico → el
          abono existente, sin descontar dos veces ni re-emitir; divergente →
          409 `abono_id_divergente`.
        - El crédito se bloquea `FOR UPDATE` hasta el commit: dos abonos
          concurrentes se serializan y el CHECK `saldo_pendiente >= 0` es la
          red final (ADR-022).
        - Abono mayor que el saldo → 422 `abono_excede_saldo` (pre-chequeo;
          la carrera la cierra el CHECK, traducido al mismo 422).
        - `efectivo` exige sesión abierta y guarda su `sesion_caja_id`
          (decisión 9: su plata entra al arqueo de esa sesión; los demás
          métodos no tocan la gaveta).
        - Al llegar a 0: `saldado` y evento `fiado.credito_saldado`. Un
          `saldado` nunca vuelve a `vigente` (ADR-022).
        """
        existente = await self._session.get(FiadoAbono, datos.id)
        if existente is not None:
            divergentes = [c for c in _CAMPOS_DEL_ABONO if str(getattr(existente, c)) != str(getattr(datos, c))]
            if existente.credito_id != credito_id:
                divergentes.append("credito_id")
            if divergentes:
                raise ConflictError(
                    "Ese id de abono ya existe con datos distintos. El servidor conserva la primera versión.",
                    code="abono_id_divergente",
                    details={"campos": divergentes},
                )
            logger.info("fiado_abono_idempotente", abono_id=str(existente.id))
            return AbonoSalida.model_validate(existente)

        credito = await self._session.get(FiadoCredito, credito_id, with_for_update=True)
        if credito is None:
            raise NotFoundError("El crédito no existe.", code="credito_no_encontrado")
        if credito.estado in ("saldado", "anulado"):
            raise ConflictError(
                f"Este crédito está {credito.estado}: no admite abonos.",
                code="credito_no_abonable",
                details={"estado": credito.estado},
            )
        if datos.monto > credito.saldo_pendiente:
            raise ValidationError(
                "El abono es mayor que lo que debe: ajusta el monto al saldo.",
                code="abono_excede_saldo",
                details={"saldo_pendiente": credito.saldo_pendiente},
            )
        sesion_caja_id: uuid.UUID | None = None
        if datos.metodo_pago == "efectivo":
            # FOR UPDATE como en `registrar_movimiento` de caja: el abono se
            # serializa con el cierre y jamás cae en una sesión ya cerrada.
            sesion = (
                await self._session.execute(select(CajaSesion).where(CajaSesion.estado == "abierta").with_for_update())
            ).scalar_one_or_none()
            if sesion is None:
                raise ConflictError(
                    "No hay una caja abierta: el abono en efectivo entra a la gaveta y necesita su sesión.",
                    code="caja_sin_sesion_abierta",
                )
            sesion_caja_id = sesion.id

        abono = FiadoAbono(
            id=datos.id,
            tenant_id=self._tenant_id,
            credito_id=credito.id,
            sesion_caja_id=sesion_caja_id,
            monto=datos.monto,
            metodo_pago=datos.metodo_pago,
            registrado_por=self._actor_id,
            nota=datos.nota,
        )
        self._session.add(abono)
        credito.saldo_pendiente -= datos.monto
        if credito.saldo_pendiente == 0:
            credito.estado = "saldado"
        credito.updated_at = datetime.now(UTC)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            detalle = str(exc)
            if "ck_fiado_creditos_saldo_no_negativo" in detalle or "ck_fiado_creditos_saldo_acotado" in detalle:
                # La red de ADR-022 atrapando una carrera que el FOR UPDATE
                # hace casi imposible: mismo 422 tipado, nunca un 500 mudo.
                raise ValidationError(
                    "El abono es mayor que lo que debe: ajusta el monto al saldo.",
                    code="abono_excede_saldo",
                ) from exc
            if "fiado_abonos_pkey" in detalle:
                # Dos PRIMEROS envíos concurrentes con el mismo id, o el id
                # de una fila que la RLS no deja ver (criterio D-24).
                raise ConflictError("Ese id de abono ya existe.", code="abono_id_divergente") from exc
            raise
        await DomainEventService.emit(
            self._session,
            tenant_id=self._tenant_id,
            event_name="fiado.abono_registrado",
            resource_type="fiado_abono",
            resource_id=str(abono.id),
            data={
                "abono_id": str(abono.id),
                "credito_id": str(credito.id),
                "cliente_id": str(credito.cliente_id),
                "monto": abono.monto,
                "metodo_pago": abono.metodo_pago,
                "saldo_restante": credito.saldo_pendiente,
            },
        )
        if credito.estado == "saldado":
            await DomainEventService.emit(
                self._session,
                tenant_id=self._tenant_id,
                event_name="fiado.credito_saldado",
                resource_type="fiado_credito",
                resource_id=str(credito.id),
                data={
                    "credito_id": str(credito.id),
                    "cliente_id": str(credito.cliente_id),
                    "venta_id": str(credito.venta_id),
                    "monto_total": credito.monto_total,
                },
            )
        logger.info("fiado_abono_registrado", abono_id=str(abono.id), saldo_restante=credito.saldo_pendiente)
        return AbonoSalida.model_validate(abono)
```

- [ ] **Paso 3: verificar en verde.**

```bash
cd backend && uv run pytest tests/test_fiado_servicio.py -q
# Esperado: 17 passed — 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/fiado/service.py backend/tests/test_fiado_servicio.py
git commit -m "Abonos al peso con el CHECK como red, cuaderno, historial con wa.me y reprogramación de vencimiento"
```

**Criterios de aceptación:** el candado de ADR-022 pasa literal (crédito de 100, abonos de 30+30 → saldo 40; el de 41 es 422 tipado, nunca 500); el saldo se descuenta en la misma transacción con el crédito bloqueado; el abono en efectivo exige sesión abierta y queda atado a ella; los eventos `fiado.abono_registrado` y `fiado.credito_saldado` salen una sola vez y en la transacción; ni un `saldado` ni un `anulado` admiten abonos ni reprogramación; el `wa.me` va prearmado con el saldo; los 17 tests pasan (0 SKIPPED); `ruff` limpio.

---

## Tarea 7: El sync — `cliente.crear`, la venta fiada se convierte en crédito y la anulación lo anula

**Files:**
- Create: `backend/tests/test_fiado_sync.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/fiado/sync.py`
- Modify: `backend/services/api/app/modules/ventas/schemas.py` (`VentaCrearSync.fecha_vencimiento`)
- Modify: `backend/services/api/app/modules/ventas/service.py` (dispatch, flags, crédito, anulación, integridad)
- Modify: `backend/services/api/app/modules/ventas/dependencies.py` (los dos veredictos nuevos)

**Interfaces:**
- Consume: el patrón SAVEPOINT/`rechazada` de `ventas/service.py` (decisión 5 del plan de ventas), `ResultadoOperacion`, los permisos de la Tarea 4.
- Produce: la conversión venta fiada → crédito (decisión 1), la operación `cliente.crear` (decisión 2), la anulación del crédito (decisión 3), el cupo visible en `detalles` (decisión 8).

- [ ] **Paso 1: escribir el test que falla.** Crear `backend/tests/test_fiado_sync.py`:

```python
"""El fiado dentro del lote del sync (decisiones 1-3 del plan del módulo).

Mismo criterio que `test_ventas_servicio.py`: el lote se procesa con la
sesión de tenant real y las filas se verifican por SQL con el rol de
plataforma. Aquí se fija lo firmado: la venta fiada se convierte en crédito
en la misma transacción (incluida la que llega tarde por el sync), el
servidor NO rechaza por cupo (registra y lo muestra), y la anulación anula
el crédito sin tocar el historial de abonos.
"""

from __future__ import annotations

import uuid

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
    "DELETE FROM fiado_abonos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM fiado_creditos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM clientes WHERE tenant_id = ANY(:ids)",
    "DELETE FROM movimientos_inventario WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas_items WHERE tenant_id = ANY(:ids)",
    "DELETE FROM ventas WHERE tenant_id = ANY(:ids)",
    "DELETE FROM caja_sesiones WHERE tenant_id = ANY(:ids)",
    "DELETE FROM dispositivos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM productos WHERE tenant_id = ANY(:ids)",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.fiado.%'",
    "DELETE FROM outbox_messages WHERE routing_key LIKE '%.venta.%'",
)


@pytest_asyncio.fixture
async def semilla(pg_platform_url: str):
    engine = create_async_engine(pg_platform_url)
    ids = {"dispositivo": uuid.uuid4(), "producto": uuid.uuid4()}
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await conn.execute(
            text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (:d, :t, 'Caja 1')"),
            {"d": ids["dispositivo"], "t": T1},
        )
        await conn.execute(
            text("INSERT INTO productos (id, tenant_id, nombre, precio_venta, stock_actual) "
                 "VALUES (:p, :t, 'Arroz 500g', 2500, 100)"),
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
async def servicio(pg_app_url: str, semilla):
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield VentasService(
                session=s,
                tenant_id=T1,
                actor_id="cajero-prueba",
                puede_anular=True,
                puede_fiar=True,
                puede_gestionar_clientes=True,
            )
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


def _lote(semilla: dict, operaciones: list[dict]) -> LoteSync:
    return LoteSync.model_validate({"dispositivo_id": str(semilla["dispositivo"]), "operaciones": operaciones})


def _op_cliente(cliente_id: uuid.UUID, secuencia: int, **datos) -> dict:
    base: dict = {"nombre": "Don Carlos", "telefono": "3001234567"}
    base.update(datos)
    return {"id": str(cliente_id), "tipo": "cliente.crear", "secuencia": secuencia, "datos": base}


def _op_venta_fiada(
    venta_id: uuid.UUID,
    semilla: dict,
    cliente_id: uuid.UUID,
    total: int,
    secuencia: int,
    consecutivo: int = 1,
    vencimiento: str | None = "2026-08-15",
    estado: str = "completada",
) -> dict:
    datos: dict = {
        "consecutivo_local": consecutivo,
        "estado": estado,
        "medio_pago": "fiado",
        "total_centavos": total,
        "cliente_id": str(cliente_id),
        "creada_en_cliente": "2026-07-28T10:00:00+00:00",
        "items": [{"producto_id": str(semilla["producto"]), "cantidad": "1", "precio_unitario_centavos": total}],
    }
    if vencimiento is not None:
        datos["fecha_vencimiento"] = vencimiento
    return {"id": str(venta_id), "tipo": "venta.crear", "secuencia": secuencia, "datos": datos}


def _op_anular(operacion_id: uuid.UUID, venta_id: uuid.UUID, secuencia: int) -> dict:
    return {"id": str(operacion_id), "tipo": "venta.anular", "secuencia": secuencia, "datos": {"venta_id": str(venta_id)}}


async def _uno(pg_platform_url: str, sql: str, **params):
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await engine.dispose()


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


@pytest.mark.asyncio
async def test_cliente_crear_del_lote_crea_la_fila(servicio, semilla, pg_platform_url):
    cliente_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(_lote(semilla, [_op_cliente(cliente_id, 1)]))
    assert [r.resultado for r in resultados] == ["aceptada"]
    fila = await _uno(pg_platform_url, "SELECT nombre, telefono FROM clientes WHERE id = :c", c=cliente_id)
    assert fila == ("Don Carlos", "3001234567")


@pytest.mark.asyncio
async def test_cliente_crear_es_idempotente_y_la_divergencia_es_rechazo(servicio, semilla):
    cliente_id = uuid.uuid4()
    await servicio.procesar_lote(_lote(semilla, [_op_cliente(cliente_id, 1)]))
    de_nuevo = await servicio.procesar_lote(_lote(semilla, [_op_cliente(cliente_id, 2)]))
    assert de_nuevo[0].resultado == "duplicada"
    divergente = await servicio.procesar_lote(_lote(semilla, [_op_cliente(cliente_id, 3, nombre="Otro nombre")]))
    assert divergente[0].resultado == "rechazada" and divergente[0].motivo == "cliente_id_divergente"


@pytest.mark.asyncio
async def test_cliente_crear_sin_permiso_es_rechazada(servicio, semilla):
    """El veredicto viaja del token como flag (patrón `puede_anular`): sin
    `cliente:gestionar` la operación es `rechazada`, no un 403 del lote."""
    servicio._puede_gestionar_clientes = False
    resultados = await servicio.procesar_lote(_lote(semilla, [_op_cliente(uuid.uuid4(), 1)]))
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "permiso_ausente"


@pytest.mark.asyncio
async def test_la_venta_fiada_se_convierte_en_credito_en_la_misma_transaccion(servicio, semilla, pg_platform_url):
    """Decisión 1: cliente y venta en el MISMO lote (el orden FIFO del
    dispositivo garantiza la dependencia); al confirmar, el crédito ya
    existe con su saldo igual al total — no hay consumidor que esperar."""
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(semilla, [_op_cliente(cliente_id, 1), _op_venta_fiada(venta_id, semilla, cliente_id, 43000, 2)])
    )
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada"]
    fila = await _uno(
        pg_platform_url,
        "SELECT cliente_id, monto_total, saldo_pendiente, estado, fecha_vencimiento FROM fiado_creditos WHERE venta_id = :v",
        v=venta_id,
    )
    assert fila is not None
    assert fila[0] == cliente_id and fila[1] == 43000 and fila[2] == 43000 and fila[3] == "vigente"
    assert str(fila[4]) == "2026-08-15"
    creados = await _eventos(pg_platform_url, "fiado.credito_creado")
    assert len(creados) == 1 and creados[0]["data"]["monto_total"] == 43000


@pytest.mark.asyncio
async def test_la_venta_fiada_sin_cliente_conocido_no_se_rechaza(servicio, semilla, pg_platform_url):
    """La red de seguridad de la decisión 2: la venta se acepta SIEMPRE
    (ADR-018); el cliente queda con placeholder editable y el fiado existe."""
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    resultados = await servicio.procesar_lote(_lote(semilla, [_op_venta_fiada(venta_id, semilla, cliente_id, 12000, 1)]))
    assert resultados[0].resultado == "aceptada"
    cliente = await _uno(pg_platform_url, "SELECT nombre FROM clientes WHERE id = :c", c=cliente_id)
    assert cliente == ("(sin nombre)",)
    credito = await _uno(pg_platform_url, "SELECT saldo_pendiente FROM fiado_creditos WHERE venta_id = :v", v=venta_id)
    assert credito == (12000,)


@pytest.mark.asyncio
async def test_la_venta_fiada_sin_permiso_es_rechazada_y_no_deja_credito(servicio, semilla, pg_platform_url):
    servicio._puede_fiar = False
    venta_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(_lote(semilla, [_op_venta_fiada(venta_id, semilla, uuid.uuid4(), 5000, 1)]))
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "permiso_ausente"
    assert await _uno(pg_platform_url, "SELECT id FROM ventas WHERE id = :v", v=venta_id) is None
    assert await _uno(pg_platform_url, "SELECT id FROM fiado_creditos WHERE venta_id = :v", v=venta_id) is None


@pytest.mark.asyncio
async def test_el_cupo_no_rechaza_pero_el_exceso_viaja_en_el_resultado(servicio, semilla, pg_platform_url):
    """ADR-018: la mercancía ya salió; el servidor registra el exceso y lo
    muestra (decisión 8): `detalles.cupo_excedido` en la aceptada."""
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(semilla, [
            _op_cliente(cliente_id, 1, limite_credito=50000),
            _op_venta_fiada(venta_id, semilla, cliente_id, 80000, 2),
        ])
    )
    assert [r.resultado for r in resultados] == ["aceptada", "aceptada"]
    assert resultados[1].detalles == {"cupo_excedido": True}
    # Y una venta dentro del cupo viaja sin la señal.
    dentro = await servicio.procesar_lote(
        _lote(semilla, [_op_venta_fiada(uuid.uuid4(), semilla, cliente_id, 1000, 3, consecutivo=2)])
    )
    assert dentro[0].detalles == {"cupo_excedido": True}  # 81.000 > 50.000: sigue excedido


@pytest.mark.asyncio
async def test_la_anulacion_anula_el_credito_sin_tocar_los_abonos(servicio, semilla, pg_platform_url):
    """Decisión 3 (el caso duro): fiado de 100 con 30 abonados; la anulación
    pone el crédito `anulado` con saldo 0, el abono queda como historia y el
    evento lleva `total_abonado` para que el tendero decida la devolución."""
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    await servicio.procesar_lote(
        _lote(semilla, [_op_cliente(cliente_id, 1), _op_venta_fiada(venta_id, semilla, cliente_id, 100000, 2)])
    )
    credito = await _uno(pg_platform_url, "SELECT id FROM fiado_creditos WHERE venta_id = :v", v=venta_id)
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO fiado_abonos (id, tenant_id, credito_id, monto, metodo_pago, registrado_por) "
                 "VALUES (:a, :t, :cr, 30000, 'efectivo', 'dueno')"),
            {"a": uuid.uuid4(), "t": T1, "cr": credito[0]},
        )
        await conn.execute(
            text("UPDATE fiado_creditos SET saldo_pendiente = 70000 WHERE id = :cr"), {"cr": credito[0]}
        )
    await engine.dispose()

    anulacion = await servicio.procesar_lote(_lote(semilla, [_op_anular(uuid.uuid4(), venta_id, 3)]))
    assert anulacion[0].resultado == "aceptada"
    estado = await _uno(pg_platform_url, "SELECT estado, saldo_pendiente FROM fiado_creditos WHERE id = :c", c=credito[0])
    assert estado == ("anulado", 0)
    abono = await _uno(pg_platform_url, "SELECT monto FROM fiado_abonos WHERE credito_id = :c", c=credito[0])
    assert abono == (30000,)  # el historial es la verdad y no se reescribe (ADR-022)
    anulados = await _eventos(pg_platform_url, "fiado.credito_anulado")
    assert len(anulados) == 1 and anulados[0]["data"]["total_abonado"] == 30000


@pytest.mark.asyncio
async def test_la_venta_que_sube_ya_anulada_no_genera_credito(servicio, semilla, pg_platform_url):
    """Como no mueve stock (decisión 9 del plan de ventas), tampoco genera
    deuda: su efecto neto es cero."""
    venta_id = uuid.uuid4()
    resultados = await servicio.procesar_lote(
        _lote(semilla, [_op_venta_fiada(venta_id, semilla, uuid.uuid4(), 8000, 1, estado="anulada")])
    )
    assert resultados[0].resultado == "aceptada"
    assert await _uno(pg_platform_url, "SELECT id FROM fiado_creditos WHERE venta_id = :v", v=venta_id) is None


@pytest.mark.asyncio
async def test_la_fecha_de_vencimiento_es_solo_del_fiado(servicio, semilla):
    datos = _op_venta_fiada(uuid.uuid4(), semilla, uuid.uuid4(), 5000, 1)
    datos["datos"]["medio_pago"] = "efectivo"
    datos["datos"]["cliente_id"] = None
    resultados = await servicio.procesar_lote(_lote(semilla, [datos]))
    assert resultados[0].resultado == "rechazada" and resultados[0].motivo == "fecha_vencimiento_solo_en_fiado"


@pytest.mark.asyncio
async def test_el_lote_reenviado_no_duplica_cliente_credito_ni_eventos(servicio, semilla, pg_platform_url):
    cliente_id, venta_id = uuid.uuid4(), uuid.uuid4()
    lote = _lote(semilla, [_op_cliente(cliente_id, 1), _op_venta_fiada(venta_id, semilla, cliente_id, 9000, 2)])
    await servicio.procesar_lote(lote)
    de_nuevo = await servicio.procesar_lote(lote)
    assert [r.resultado for r in de_nuevo] == ["duplicada", "duplicada"]
    filas = await _uno(pg_platform_url, "SELECT count(*) FROM fiado_creditos WHERE venta_id = :v", v=venta_id)
    assert filas == (1,)
    assert len(await _eventos(pg_platform_url, "fiado.credito_creado")) == 1
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_fiado_sync.py -q
# Esperado: TypeError: VentasService.__init__() got an unexpected keyword argument 'puede_fiar'
```

- [ ] **Paso 2: crear el puente `fiado/sync.py`.** Crear `backend/services/api/app/modules/fiado/sync.py`:

```python
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


def _rechazada(operacion: OperacionSync, motivo: str, mensaje: str, detalles: dict | None = None) -> ResultadoOperacion:
    logger.info("operacion_rechazada", operacion_id=str(operacion.id), motivo=motivo, mensaje=mensaje)
    return ResultadoOperacion(
        id=operacion.id, tipo=operacion.tipo, resultado="rechazada", motivo=motivo,
        detalles={"mensaje": mensaje, **(detalles or {})},
    )


def _duplicada(operacion: OperacionSync) -> ResultadoOperacion:
    return ResultadoOperacion(id=operacion.id, tipo=operacion.tipo, resultado="duplicada")


async def comparar_cliente_con_la_aceptada(operacion: OperacionSync, existente: Cliente) -> ResultadoOperacion:
    """La fila ya existe con la PK del cliente: ¿es el MISMO cliente?

    Payload idéntico → `duplicada` (el reintento legítimo). Cualquier campo
    distinto → `rechazada` `cliente_id_divergente` con los campos que
    difieren: jamás un no-op silencioso (lección del catálogo)."""
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
    `_traducir_integridad` del servicio de ventas, que es quien la llama."""
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


async def crear_credito_de_venta(
    session: AsyncSession, tenant_id: uuid.UUID, venta: Venta, fecha_vencimiento
) -> bool:
    """La venta fiada se convierte en crédito (ADR-022). Devuelve True si el
    cupo del cliente quedó excedido — para que la operación aceptada lo
    muestre (decisión 8). El cupo NUNCA rechaza (ADR-018).

    Si el cliente no existe en el servidor (su `cliente.crear` fue
    rechazada, o la venta se fió a un id que nunca subió), se hace el alta
    mínima con placeholder `(sin nombre)` — editable después — en vez de
    perder el fiado (decisión 2): el cuaderno nunca pierde una deuda."""
    cliente = await session.get(Cliente, venta.cliente_id)
    if cliente is None:
        cliente = Cliente(id=venta.cliente_id, tenant_id=tenant_id, nombre="(sin nombre)")
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
```

- [ ] **Paso 3: cambiar el contrato del sync (`VentaCrearSync.fecha_vencimiento`).** En `backend/services/api/app/modules/ventas/schemas.py`, añadir `date` al import de `datetime` y, en `VentaCrearSync`, tras `cliente_id`:

```python
    #: Solo fiado (ADR-022): la pone el tendero por fiado (la app propone el
    #: default, p. ej. 15 días). NULL = crédito sin recordatorio, declarado
    #: en pantalla. En una venta que no es fiada es `rechazada`
    #: `fecha_vencimiento_solo_en_fiado` (regla de negocio por operación).
    fecha_vencimiento: date | None = None
```

- [ ] **Paso 4: cambiar `ventas/service.py`.** Cuatro cambios quirúrgicos:

**4a. Imports y constructor.** Añadir a los imports:

```python
from app.modules.fiado.models import Cliente
from app.modules.fiado.sync import (
    anular_credito_de_venta,
    comparar_cliente_con_la_aceptada,
    crear_credito_de_venta,
    registrar_cliente_sync,
)
```

y reemplazar el constructor por:

```python
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        actor_id: str,
        puede_anular: bool,
        puede_fiar: bool = False,
        puede_gestionar_clientes: bool = False,
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
        #: El dispositivo del lote en curso (lo fija `procesar_lote` tras
        #: verificar que existe y es del tenant — vía RLS).
        self._dispositivo_id: uuid.UUID | None = None
```

(Los flags nuevos llevan default `False` a propósito: los 23 call sites de tests existentes no cambian — ninguno acepta una venta fiada por el servicio, verificado por grep — y el olvido deja de fugar: sin veredicto, no se fía.)

**4b. El dispatch.** En `_aplicar_operacion`, tras la rama de `venta.anular`:

```python
                if operacion.tipo == "cliente.crear":
                    return await self._registrar_cliente(operacion)
```

y el método nuevo tras `_aplicar_operacion`:

```python
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
```

**4c. La conversión y el permiso.** En `_registrar_venta`, tras el bloque de `error = self._reglas_de_negocio(...)`:

```python
        if datos.medio_pago == "fiado" and not self._puede_fiar:
            return self._rechazada(
                operacion,
                "permiso_ausente",
                "Fiar requiere el permiso fiado:crear.",
                {"permiso": "fiado:crear"},
            )
```

y, tras el bloque de movimientos de stock (antes de `await self._emitir("venta.creada", ...)`):

```python
        cupo_excedido = False
        if datos.estado == "completada" and datos.medio_pago == "fiado" and venta.total_centavos > 0:
            # La venta fiada se convierte en crédito EN LA MISMA TRANSACCIÓN
            # (módulo 5, decisión 1): confirman o revientan juntas. Un fiado
            # de total 0 no genera crédito (no hay nada que deber). El cupo
            # se evalúa pero NUNCA se rechaza (ADR-018): el exceso viaja en
            # `detalles` para que la app lo muestre al confirmar el sync.
            cupo_excedido = await crear_credito_de_venta(
                self._session, self._tenant_id, venta, datos.fecha_vencimiento
            )
```

y reemplazar el `return` final de `_registrar_venta` por:

```python
        return ResultadoOperacion(
            id=operacion.id,
            tipo=operacion.tipo,
            resultado="aceptada",
            detalles={"cupo_excedido": True} if cupo_excedido else None,
        )
```

**4d. La fecha solo en fiado y la anulación del crédito.** En `_reglas_de_negocio`, tras la regla `cliente_solo_en_fiado`:

```python
        if datos.medio_pago != "fiado" and datos.fecha_vencimiento is not None:
            return self._rechazada(
                operacion,
                "fecha_vencimiento_solo_en_fiado",
                "Solo una venta fiada lleva fecha de vencimiento.",
            )
```

y en `_anular_venta`, tras `venta.anulada_en = datetime.now(UTC)`:

```python
        if venta.medio_pago == "fiado":
            # La anulación de la venta fiada anula el crédito en la misma
            # transacción (módulo 5, decisión 3): los abonos son historia
            # intocable (ADR-022) y la devolución del dinero es un gesto de
            # caja MANUAL del tendero — «déjelo ahí a favor» es tan legítimo
            # como devolverla, y automatizarla decidiría por él.
            await anular_credito_de_venta(self._session, self._tenant_id, venta.id)
```

**4e. La integridad de clientes y del crédito único.** En `_traducir_integridad`, tras la rama de `ventas_pkey`:

```python
        if "clientes_pkey" in detalle:
            # El id choca con una fila ya insertada (misma lógica que
            # `ventas_pkey`): si es visible, es el MISMO cliente (duplicada o
            # divergente); si no, es de otro negocio → rechazada tipada.
            if operacion.tipo == "cliente.crear":
                existente = await self._session.get(Cliente, operacion.id)
                if existente is not None:
                    return await comparar_cliente_con_la_aceptada(operacion, existente)
            return self._rechazada(operacion, "cliente_id_divergente", "Ese id de cliente ya existe.")
        if "ux_fiado_creditos_venta" in detalle:
            # El crédito de esta venta ya existe: la operación se aplicó
            # antes (carrera de reintentos). Es duplicada, no error — mismo
            # criterio que `ux_movimientos_origen` (ADR-020).
            return self._duplicada(operacion)
```

- [ ] **Paso 5: los veredictos en la dependencia.** En `backend/services/api/app/modules/ventas/dependencies.py`, añadir al import de policies `PERM_CLIENTE_GESTIONAR` y `PERM_FIADO_CREAR`, y al constructor del servicio:

```python
    return VentasService(
        session=session,
        tenant_id=tenant.tenant_id,
        actor_id=user.user_id,
        puede_anular=has_permission(user, PERM_VENTA_ANULAR),
        puede_fiar=has_permission(user, PERM_FIADO_CREAR),
        puede_gestionar_clientes=has_permission(user, PERM_CLIENTE_GESTIONAR),
    )
```

- [ ] **Paso 6: verificar en verde.**

```bash
cd backend && uv run pytest tests/test_fiado_sync.py -q
# Esperado: 11 passed — 0 SKIPPED
uv run pytest tests/test_ventas_servicio.py tests/test_sync_idempotente.py tests/test_ventas_schemas.py -q
# Esperado: verde (los flags nuevos tienen default fail-closed y ningún test viejo acepta fiado por el servicio)
uv run pytest -q -m integration
# Esperado: toda la suite verde, 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 7: commit**

```bash
git add backend/services/api/app/modules/fiado/sync.py backend/services/api/app/modules/ventas/ backend/tests/test_fiado_sync.py
git commit -m "La venta fiada se convierte en crédito en el sync, cliente.crear entra al lote y la anulación anula el crédito"
```

**Criterios de aceptación:** la venta fiada crea su crédito en la misma transacción (incluida la tardía del sync y la del mismo lote que su `cliente.crear`); el servidor no rechaza por cupo y el exceso viaja en `detalles.cupo_excedido`; la venta fiada sin cliente crea el placeholder y el crédito; la anulación deja el crédito `anulado` con saldo 0, el abono intacto y el evento con `total_abonado`; la que sube ya anulada no genera crédito; el reenvío del lote no duplica nada; los 11 tests nuevos y toda la suite de integración pasan (0 SKIPPED); `ruff` limpio.

---

## Tarea 8: El trabajo diario de vencidos (`fiado.vencimientos`) en el worker

**Files:**
- Create: `backend/tests/test_fiado_vencimientos.py` (primero: el test que falla)
- Modify: `backend/services/worker/worker/jobs.py`

**Interfaces:**
- Consume: `JobContext`/`ScheduledJob` de `vendi_core.jobs.types` (scope `tenant`: el planificador itera los negocios activos), `DomainEventService`, la sesión de plataforma del worker.
- Produce: el trabajo diario que marca `vencido` y encola `fiado.credito_vencido` UNA vez por crédito (decisión 7). El módulo de notificaciones (módulo 7) consumirá el evento y lo traducirá a `notificacion.enviar` (ADR-025) — aquí termina el alcance.

- [ ] **Paso 1: escribir el test que falla.** Crear `backend/tests/test_fiado_vencimientos.py`:

```python
"""El trabajo diario de vencidos contra el PostgreSQL real (ADR-022).

El candado firmado: un crédito con vencimiento de ayer pasa a `vencido` y
encola EXACTAMENTE un `fiado.credito_vencido`, idempotente al re-correr.
La sesión es de plataforma (como la del worker real): el filtro por tenant
es explícito y se prueba que T2 no se toca cuando corre la pasada de T1.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.db.session import create_platform_session_factory
from vendi_core.jobs.types import JobContext
from worker.jobs import construir_jobs, marcar_vencimientos_fiado

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
    """En T1: crédito vencido de ayer, uno a futuro, uno sin fecha y uno
    saldado. En T2: otro vencido de ayer (la pasada de T1 NO debe tocarlo)."""
    engine = create_async_engine(pg_platform_url)
    ids = {"vencido": uuid.uuid4(), "futuro": uuid.uuid4(), "sin_fecha": uuid.uuid4(), "saldado": uuid.uuid4(), "de_t2": uuid.uuid4()}
    async with engine.begin() as conn:
        for sentencia in BORRADO:
            await conn.execute(text(sentencia), {"ids": [T1, T2]})
        for tenant in (T1, T2):
            await conn.execute(
                text("INSERT INTO clientes (id, tenant_id, nombre) VALUES (gen_random_uuid(), :t, 'Don Carlos')"),
                {"t": tenant},
            )
            await conn.execute(
                text("INSERT INTO dispositivos (id, tenant_id, nombre) VALUES (gen_random_uuid(), :t, 'Caja 1')"),
                {"t": tenant},
            )
            await conn.execute(
                text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial) "
                     "VALUES (gen_random_uuid(), :t, 'dueno', 0)"),
                {"t": tenant},
            )
        for tenant, filas in (
            (T1, (("vencido", "CURRENT_DATE - 1", "vigente", 43000, 43000),
                  ("futuro", "CURRENT_DATE + 10", "vigente", 10000, 10000),
                  ("sin_fecha", "NULL", "vigente", 5000, 5000),
                  ("saldado", "CURRENT_DATE - 3", "saldado", 8000, 0))),
            (T2, (("de_t2", "CURRENT_DATE - 1", "vigente", 7000, 7000),)),
        ):
            cliente = (await conn.execute(text("SELECT id FROM clientes WHERE tenant_id = :t"), {"t": tenant})).scalar_one()
            dispositivo = (await conn.execute(text("SELECT id FROM dispositivos WHERE tenant_id = :t"), {"t": tenant})).scalar_one()
            sesion = (await conn.execute(text("SELECT id FROM caja_sesiones WHERE tenant_id = :t"), {"t": tenant})).scalar_one()
            for clave, vencimiento, estado, monto, saldo in filas:
                venta = uuid.uuid4()
                await conn.execute(
                    text("INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                         "medio_pago, total_centavos, cliente_id, creada_en_cliente, secuencia_dispositivo) "
                         "VALUES (:v, :t, :d, :s, 1, 'fiado', :m, :c, now(), 1)"),
                    {"v": venta, "t": tenant, "d": dispositivo, "s": sesion, "m": monto, "c": cliente},
                )
                await conn.execute(
                    text(f"INSERT INTO fiado_creditos (id, tenant_id, cliente_id, venta_id, monto_total, "
                         f"saldo_pendiente, fecha_vencimiento, estado) "
                         f"VALUES (:cr, :t, :c, :v, :m, :s, {vencimiento}, :e)"),
                    {"cr": ids[clave], "t": tenant, "c": cliente, "v": venta, "m": monto, "s": saldo, "e": estado},
                )
    try:
        yield ids
    finally:
        async with engine.begin() as conn:
            for sentencia in BORRADO:
                await conn.execute(text(sentencia), {"ids": [T1, T2]})
        await engine.dispose()


def _ctx(pg_platform_url: str, tenant_id: uuid.UUID) -> JobContext:
    from vendi_core.db.engine import create_engine as _crear

    engine = _crear(pg_platform_url)
    return JobContext(session_factory=create_platform_session_factory(engine), engine=engine, tenant_id=tenant_id)


async def _estado(pg_platform_url: str, credito_id: uuid.UUID) -> str:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text("SELECT estado FROM fiado_creditos WHERE id = :c"), {"c": credito_id})).scalar_one()
    finally:
        await engine.dispose()


async def _conteo_eventos(pg_platform_url: str) -> int:
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT count(*) FROM outbox_messages WHERE routing_key LIKE '%.fiado.credito_vencido'")
                )
            ).scalar_one()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_marca_vencido_y_encola_exactamente_un_evento(pg_platform_url, semilla):
    """El candado de ADR-022, literal: el crédito con vencimiento de ayer pasa
    a `vencido` y encola exactamente un `fiado.credito_vencido`."""
    cambios = await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    assert cambios == {"creditos_vencidos": 1}
    assert await _estado(pg_platform_url, semilla["vencido"]) == "vencido"
    assert await _conteo_eventos(pg_platform_url) == 1


@pytest.mark.asyncio
async def test_recorrer_la_pasada_es_noop(pg_platform_url, semilla):
    """La transición ES el anti-duplicado (decisión 7): el UPDATE solo toca
    `vigente`, así que la segunda corrida marca 0 y no re-emite."""
    await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    cambios = await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    assert cambios == {"creditos_vencidos": 0}
    assert await _conteo_eventos(pg_platform_url) == 1


@pytest.mark.asyncio
async def test_no_toca_el_futuro_el_sin_fecha_el_saldado_ni_el_vecino(pg_platform_url, semilla):
    await marcar_vencimientos_fiado(_ctx(pg_platform_url, T1))
    assert await _estado(pg_platform_url, semilla["futuro"]) == "vigente"
    assert await _estado(pg_platform_url, semilla["sin_fecha"]) == "vigente"  # sin fecha = sin recordatorio
    assert await _estado(pg_platform_url, semilla["saldado"]) == "saldado"
    assert await _estado(pg_platform_url, semilla["de_t2"]) == "vigente"  # el filtro explícito por tenant
    # Y cuando corre la pasada de T2, el suyo sí vence.
    await marcar_vencimientos_fiado(_ctx(pg_platform_url, T2))
    assert await _estado(pg_platform_url, semilla["de_t2"]) == "vencido"
    assert await _conteo_eventos(pg_platform_url) == 2


@pytest.mark.asyncio
async def test_el_trabajo_esta_registrado_con_scope_de_tenant(pg_platform_url):
    """El planificador itera los negocios activos (scope `tenant`): una fila
    de auditoría por negocio y el ContextVar sembrado por iteración."""
    runner = None
    jobs = {j.name: j for j in construir_jobs(runner)}
    assert "fiado.vencimientos" in jobs
    assert jobs["fiado.vencimientos"].scope == "tenant"
    assert jobs["fiado.vencimientos"].cron == "30 11 * * *"
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_fiado_vencimientos.py -q
# Esperado: ImportError: cannot import name 'marcar_vencimientos_fiado' from 'worker.jobs'
```

- [ ] **Paso 2: registrar el trabajo.** En `backend/services/worker/worker/jobs.py`, añadir a los imports:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from vendi_core.events.service import DomainEventService
```

y, tras los imports, la sentencia y el handler a nivel de módulo:

```python
#: La pasada de vencidos de UN negocio. La sesión del worker es de
#: PLATAFORMA (BYPASSRLS, sin GUC): el `tenant_id` del filtro es obligatorio
#: y explícito — al revés de la API, donde la policy acota. El UPDATE solo
#: toca filas `vigente` y bloquea las que devuelve hasta el commit: una
#: segunda corrida (reintento, concurrencia) actualiza 0 filas y emite 0
#: eventos. La transición de estado ES el anti-duplicado (decisión 7 del
#: plan del módulo): no hay bandera que olvidar resetear cuando el tendero
#: reprograme la fecha.
SQL_MARCAR_VENCIDOS = text(
    """
    UPDATE fiado_creditos
       SET estado = 'vencido', updated_at = now()
     WHERE tenant_id = :tenant_id
       AND estado = 'vigente'
       AND fecha_vencimiento IS NOT NULL
       AND fecha_vencimiento < :hoy
    RETURNING id, cliente_id, monto_total, saldo_pendiente, fecha_vencimiento
    """
)


async def marcar_vencimientos_fiado(ctx: JobContext) -> Mapping[str, Any]:
    """Marca `vencido` los créditos cuya fecha ya pasó — en el calendario de
    America/Bogota, no en el UTC crudo del servidor — y encola UN
    `fiado.credito_vencido` por crédito (ADR-022: lo consume el módulo de
    notificaciones, módulo 7, que lo traduce a `notificacion.enviar`).

    SQL crudo a propósito: los modelos viven en la API (`app.modules.fiado`)
    y el worker no la importa; la sentencia es pequeña y su contrato lo
    fijan los tests contra la base real."""
    hoy = datetime.now(ZoneInfo("America/Bogota")).date()
    async with ctx.session_factory() as session:
        filas = (await session.execute(SQL_MARCAR_VENCIDOS, {"tenant_id": ctx.tenant_id, "hoy": hoy})).all()
        for fila in filas:
            # Sin PII en el payload (ADR-025): el nombre del cliente NO
            # viaja; el módulo 7 arma «Tienes N fiados vencidos».
            await DomainEventService.emit(
                session,
                tenant_id=ctx.tenant_id,
                event_name="fiado.credito_vencido",
                resource_type="fiado_credito",
                resource_id=str(fila.id),
                data={
                    "credito_id": str(fila.id),
                    "cliente_id": str(fila.cliente_id),
                    "monto_total": fila.monto_total,
                    "saldo_pendiente": fila.saldo_pendiente,
                    "fecha_vencimiento": str(fila.fecha_vencimiento),
                },
            )
        await session.commit()
    logger.info("fiado_vencimientos_marcados", tenant=str(ctx.tenant_id), creditos=len(filas))
    return {"creditos_vencidos": len(filas)}
```

y en `construir_jobs`, añadir a la lista devuelta (tras el de retención):

```python
        ScheduledJob(
            name="fiado.vencimientos",
            # 11:30 UTC = 06:30 en Colombia: el recordatorio llega antes de
            # abrir la tienda, que es cuando el tendero decide a quién le
            # cobra hoy. Desplazado de la hora en punto, como la retención.
            cron="30 11 * * *",
            handler=marcar_vencimientos_fiado,
            # Una pasada por negocio activo (el planificador siembra el
            # ContextVar por iteración y audita por negocio): el handler es
            # chico y el fan-out ya está resuelto por el scheduler.
            scope="tenant",
            description="Marca vencidos los fiados del día y encola el recordatorio",
            timeout_sec=300,
        ),
```

El tipo del parámetro de `construir_jobs` admite el `runner` que ya recibe; el test lo pasa en `None` porque el handler de retención no se invoca en el registro. (Si la firma actual lo exige no-nulo, el test construye un `RetentionRunner` real como en `worker/__main__.py`.)

- [ ] **Paso 3: verificar en verde.**

```bash
cd backend && uv run pytest tests/test_fiado_vencimientos.py -q
# Esperado: 4 passed — 0 SKIPPED
uv run pytest tests/test_jobs_scheduler.py -q
# Esperado: verde (el registro nuevo no rompe el scheduler)
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/worker/worker/jobs.py backend/tests/test_fiado_vencimientos.py
git commit -m "Trabajo diario fiado.vencimientos: marca vencidos y encola el recordatorio una sola vez por crédito"
```

**Criterios de aceptación:** el candado de ADR-022 pasa literal (vencimiento de ayer → `vencido` + exactamente un `fiado.credito_vencido`, idempotente al re-correr); el futuro, el sin-fecha, el saldado y el vecino no se tocan; el payload no lleva PII (sin nombre de cliente); el trabajo está registrado con `scope="tenant"` y su cron de 06:30 Colombia; los 4 tests pasan (0 SKIPPED); `ruff` limpio.

---

## Tarea 9: Activar los puntos de cambio de caja — abonos reales en el arqueo y cobros en el forecast

**Files:**
- Modify: `backend/services/api/app/modules/caja/service.py` (`_abonos_en_efectivo_de_la_sesion` real)
- Modify: `backend/services/api/app/modules/caja/reportes.py` (cobros de fiado reales)
- Modify: `backend/services/api/app/modules/caja/schemas.py` (docstrings que decían «0 hasta el módulo 5»)
- Modify: `backend/tests/test_caja_servicio.py` (el arqueo con abonos)
- Modify: `backend/tests/test_reportes_servicio.py` (el forecast con cobros)

**Interfaces:**
- Consume: el punto de cambio único declarado por el módulo 4 (decisión 3 de su plan): el `SUM` va DENTRO de `_abonos_en_efectivo_de_la_sesion` y ni el arqueo, ni el esperado vivo, ni el forecast cambian de forma. `FiadoAbono.sesion_caja_id` (Tarea 6) y `FiadoCredito` (Tarea 2).
- Produce: el esperado que suma los abonos en efectivo de la sesión y el forecast que proyecta cobros reales, cada fuente declarada.

- [ ] **Paso 1: escribir los tests que fallan.** Al final de `backend/tests/test_caja_servicio.py` (los imports nuevos van arriba: ninguno — se usa SQL y lo ya importado):

```python
# --- Los abonos de fiado en el arqueo (módulo 5, decisión 9 del plan de fiado) ---------


async def _fiado_con_abono(pg_platform_url, semilla, sesion_id, monto_abono: int, metodo: str = "efectivo", consecutivo: int = 900) -> None:
    """Un cliente, una venta fiada, su crédito y un abono atado a la sesión
    (como lo deja `registrar_abono` del módulo 5)."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            cliente, venta, credito, abono = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            await conn.execute(
                text("INSERT INTO clientes (id, tenant_id, nombre) VALUES (:c, :t, 'Don Carlos')"),
                {"c": cliente, "t": T1},
            )
            await conn.execute(
                text("INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                     "medio_pago, total_centavos, cliente_id, creada_en_cliente, secuencia_dispositivo) "
                     "VALUES (:v, :t, :d, :s, :cons, 'fiado', 100000, :c, now(), 1)"),
                {"v": venta, "t": T1, "d": semilla["dispositivo"], "s": sesion_id, "c": cliente, "cons": consecutivo},
            )
            await conn.execute(
                text("INSERT INTO fiado_creditos (id, tenant_id, cliente_id, venta_id, monto_total, saldo_pendiente, estado) "
                     "VALUES (:cr, :t, :c, :v, 100000, :s, 'vigente')"),
                {"cr": credito, "t": T1, "c": cliente, "v": venta, "s": 100000 - monto_abono},
            )
            await conn.execute(
                text("INSERT INTO fiado_abonos (id, tenant_id, credito_id, sesion_caja_id, monto, metodo_pago, registrado_por) "
                     "VALUES (:a, :t, :cr, :sc, :m, :mp, 'dueno')"),
                {"a": abono, "t": T1, "cr": credito, "sc": sesion_id if metodo == "efectivo" else None,
                 "m": monto_abono, "mp": metodo},
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_el_arqueo_suma_los_abonos_en_efectivo_de_la_sesion(servicio, semilla, pg_platform_url):
    """El punto de cambio activado: `esperado = base + ventas efectivo +
    abonos efectivo + ingresos − egresos − devoluciones` (ADR-021). La
    transferencia NO entra: no tocó la gaveta (decisión 9)."""
    sesion = await servicio.abrir_sesion(SesionAbrir.model_validate({"base_inicial": 10000}))
    await servicio._session.commit()
    await _fiado_con_abono(pg_platform_url, semilla, sesion.id, 30000, "efectivo", consecutivo=900)
    await _fiado_con_abono(pg_platform_url, semilla, sesion.id, 20000, "transferencia", consecutivo=901)

    desglose = await calcular_desglose(servicio._session, sesion)
    assert desglose.abonos_efectivo == 30000
    assert desglose.esperado == 10000 + 30000
    arqueo = await servicio.cerrar_sesion(sesion.id, SesionCerrar.model_validate({"contado": 40000}))
    assert arqueo.efectivo_esperado == 40000 and arqueo.diferencia == 0
```

y al final de `backend/tests/test_reportes_servicio.py`:

```python
# --- Cobros de fiado en el forecast (módulo 5, decisión 11 del plan de fiado) ---------


@pytest.mark.asyncio
async def test_el_forecast_proyecta_los_cobros_de_fiado(servicio, pg_platform_url, semilla):
    """`cobros = SUM(saldo_pendiente)` de vigente/vencido con vencimiento a
    30 días o menos (decisión 11): el ya vencido cuenta (el cuaderno espera
    cobrarlo); el que vence en 60 días y el sin fecha, no."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO clientes (id, tenant_id, nombre) VALUES (:c, :t, 'Don Carlos')"),
                {"c": uuid.uuid4(), "t": T1},
            )
            cliente = (await conn.execute(text("SELECT id FROM clientes WHERE tenant_id = :t"), {"t": T1})).scalar_one()
            # Sesión CERRADA de relleno para la FK de las ventas sembradas:
            # no compite con la abierta del fixture (el índice único parcial
            # solo vela por las abiertas) y el forecast la ignora.
            sesion = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO caja_sesiones (id, tenant_id, abierta_por, base_inicial, estado, cerrada_por, "
                     "cerrada_en, efectivo_esperado, efectivo_contado, diferencia) "
                     "VALUES (:s, :t, 'dueno', 0, 'cerrada', 'dueno', now(), 0, 0, 0)"),
                {"s": sesion, "t": T1},
            )
            dispositivo = semilla["dispositivo"]
            for consecutivo, (vencimiento, saldo) in enumerate((("CURRENT_DATE - 2", 20000), ("CURRENT_DATE + 15", 30000),
                                       ("CURRENT_DATE + 60", 99000), ("NULL", 88000)), start=901):
                venta, credito = uuid.uuid4(), uuid.uuid4()
                await conn.execute(
                    text("INSERT INTO ventas (id, tenant_id, dispositivo_id, sesion_caja_id, consecutivo_local, "
                         "medio_pago, total_centavos, cliente_id, creada_en_cliente, secuencia_dispositivo) "
                         "VALUES (:v, :t, :d, :s, :cons, 'fiado', :m, :c, now(), 1)"),
                    {"v": venta, "t": T1, "d": dispositivo, "s": sesion, "m": saldo, "c": cliente, "cons": consecutivo},
                )
                await conn.execute(
                    text(f"INSERT INTO fiado_creditos (id, tenant_id, cliente_id, venta_id, monto_total, "
                         f"saldo_pendiente, fecha_vencimiento, estado) "
                         f"VALUES (:cr, :t, :c, :v, :m, :s, {vencimiento}, 'vigente')"),
                    {"cr": credito, "t": T1, "c": cliente, "v": venta, "m": saldo, "s": saldo},
                )
    finally:
        await engine.dispose()

    forecast = await servicio.forecast()
    assert forecast.cobros_fiado_proyectados_centavos == 50000  # 20.000 + 30.000
    assert "vigente" in forecast.fuentes["cobros_fiado"]
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_caja_servicio.py -q -k abonos_en_efectivo
# Esperado: FAILED — assert 0 == 30000 (el stub sigue retornando 0)
uv run pytest tests/test_reportes_servicio.py -q -k cobros_de_fiado
# Esperado: FAILED — assert 0 == 50000 (cobros sigue en 0)
```

- [ ] **Paso 2: activar el punto de cambio del arqueo.** En `backend/services/api/app/modules/caja/service.py`, reemplazar `_abonos_en_efectivo_de_la_sesion` por:

```python
async def _abonos_en_efectivo_de_la_sesion(session: AsyncSession, sesion: CajaSesion) -> int:
    """Los abonos de fiado en efectivo cobrados en esta sesión (ADR-021:
    entran al arqueo como la venta en efectivo, sumados desde su tabla de
    origen — nunca duplicados como movimiento de caja).

    El abono guarda su `sesion_caja_id` al registrarse (módulo 5, decisión 9
    del plan de fiado: el efectivo cae en la sesión abierta en ese momento,
    como las ventas y los movimientos); los demás métodos llevan NULL y no
    tocan la gaveta. Este es el punto de cambio único que la decisión 3 del
    plan de caja dejó declarado: ni el arqueo, ni el esperado vivo, ni el
    forecast cambian de forma — cambia la cuenta que aquí dentro era 0."""
    abonos = await session.scalar(
        select(func.coalesce(func.sum(FiadoAbono.monto), 0)).where(
            FiadoAbono.sesion_caja_id == sesion.id,
            FiadoAbono.metodo_pago == "efectivo",
        )
    )
    return int(abonos)
```

añadiendo el import `from app.modules.fiado.models import FiadoAbono` y actualizando el docstring de cabecera del módulo y el de `calcular_desglose` (la viñeta «Abonos de fiado en efectivo: 0 (punto de cambio único, arriba)» pasa a describir el SUM real por `sesion_caja_id`).

- [ ] **Paso 3: activar los cobros del forecast.** En `backend/services/api/app/modules/caja/reportes.py`, reemplazar la línea `cobros = 0  # ADR-022 (módulo 5): la tabla de abonos no existe.` por:

```python
        hoy = datetime.now(ZONA_LOCAL).date()
        # Los cobros que deberían entrar si cada fiado se paga a tiempo
        # (módulo 5, decisión 11 del plan de fiado): saldo vivo de créditos
        # vigente/vencido con vencimiento a 30 días o menos. Los ya vencidos
        # cuentan — el cuaderno espera cobrarlos —; los sin fecha, no: sin
        # fecha no hay promesa de pago (ADR-022).
        cobros = int(
            await self._session.scalar(
                select(func.coalesce(func.sum(FiadoCredito.saldo_pendiente), 0)).where(
                    FiadoCredito.estado.in_(("vigente", "vencido")),
                    FiadoCredito.fecha_vencimiento.is_not(None),
                    FiadoCredito.fecha_vencimiento <= hoy + timedelta(days=DIAS_DE_FORECAST),
                )
            )
        )
```

con el import `from app.modules.fiado.models import FiadoCredito`, y actualizar `fuentes["cobros_fiado"]` a:

```python
                "cobros_fiado": (
                    "Suma del saldo pendiente de los fiados vigentes o vencidos que vencen en los próximos 30 "
                    "días (los ya vencidos cuentan). Los fiados sin fecha de vencimiento no entran: sin fecha "
                    "no hay promesa de pago (ADR-022)."
                ),
```

- [ ] **Paso 4: barrer los textos que prometían 0.** En `backend/services/api/app/modules/caja/schemas.py`: el docstring de `DesgloseSalida` («`abonos_efectivo` es 0 hasta el módulo 5 — declarado en `docs/api/README.md`») pasa a «`abonos_efectivo` son los abonos de fiado en efectivo de la sesión (ADR-021/022), sumados desde `fiado_abonos`»; el docstring de `ForecastSalida` («lo que no tiene fuente todavía (cobros de fiado) viaja en 0 y lo dice») pasa a «cada número declara su fuente; los cobros de fiado proyectan el saldo de los créditos que vencen en la ventana (los sin fecha no entran, declarado)». En el router de caja, el docstring del cierre y del forecast que dicen «abonos (0 hasta el módulo 5)» se actualizan igual.

- [ ] **Paso 5: verificar en verde.**

```bash
cd backend && uv run pytest tests/test_caja_servicio.py tests/test_reportes_servicio.py -q
# Esperado: verde, incluidos los 2 tests nuevos — 0 SKIPPED
uv run pytest tests/api/test_caja_api.py -q
# Esperado: verde (la forma del contrato no cambió: cambian los números)
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 6: commit**

```bash
git add backend/services/api/app/modules/caja/ backend/tests/test_caja_servicio.py backend/tests/test_reportes_servicio.py
git commit -m "Puntos de cambio activados: el arqueo suma los abonos en efectivo y el forecast proyecta cobros de fiado"
```

**Criterios de aceptación:** el arqueo cuadra al peso con abonos en efectivo (y la transferencia no entra); el forecast proyecta `SUM(saldo_pendiente)` de vigente/vencido a 30 días con la fuente declarada; ningún texto del código sigue diciendo «0 hasta el módulo 5»; la forma del contrato (schemas) no cambió — solo los números y las fuentes; toda la suite de caja y reportes verde (0 SKIPPED); `ruff` limpio.

---

## Tarea 10: Router REST de clientes y del cuaderno, con sus guards

**Files:**
- Create: `backend/services/api/app/modules/fiado/dependencies.py`
- Create: `backend/services/api/app/modules/fiado/router.py`
- Create: `backend/tests/api/test_fiado_api.py` (primero: el test que falla)
- Modify: `backend/services/api/app/factory.py` (montar el router)
- Modify: `backend/tests/api/conftest.py` (limpieza de las tres tablas)

**Interfaces:**
- Consume: `FiadoService` (Tareas 5-6), `exigir_permiso`/`sesion_de_tenant`, `PagedList`, los permisos de la Tarea 4.
- Produce: las 8 rutas (`/clientes` ×4, `/fiado/creditos` ×4) con el reparto de ADR-023.

- [ ] **Paso 1: extender la limpieza del conftest de API.** En `backend/tests/api/conftest.py`, en la tupla de tablas del borrado, añadir `"fiado_abonos"` y `"fiado_creditos"` AL PRINCIPIO (referencian ventas, sesiones y clientes: se borran primero, como manda el orden de las FK) y `"clientes"` tras `"dispositivos"`:

```python
                for tabla in (
                    "fiado_abonos",
                    "fiado_creditos",
                    "caja_movimientos",
                    "movimientos_inventario",
                    "compra_items",
                    "ajustes_inventario",
                    "compras",
                    "ventas_items",
                    "ventas",
                    "caja_sesiones",
                    "dispositivos",
                    "clientes",
                ):
```

- [ ] **Paso 2: escribir el test de API que falla.** Crear `backend/tests/api/test_fiado_api.py`:

```python
"""Los endpoints de clientes y del cuaderno contra el PostgreSQL real.

Misma regla que `test_caja_api.py`: la base no se dobla, cada test crea su
negocio por el camino real y opera con tokens de roles distintos, porque lo
que se mide aquí es quién puede hacer qué (ADR-023): el cajero gestiona
clientes, fía y cobra; el almacenista recibe 403 en todo lo del fiado.
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


def _cliente(cliente_http, cabeceras, **cambios) -> dict:
    datos = {"nombre": "Don Carlos", "telefono": "300 123 4567", "limite_credito": 100000, **cambios}
    respuesta = cliente_http.post("/api/v1/clientes", json=datos, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _fiado(cliente_http, cabeceras, dispositivo: str, cliente_id: str, total: int, consecutivo: int = 1) -> str:
    """Una venta fiada por el camino real del sync: es donde nace el crédito."""
    venta_id = str(uuid.uuid4())
    lote = {
        "dispositivo_id": dispositivo,
        "operaciones": [{
            "id": venta_id, "tipo": "venta.crear", "secuencia": 1,
            "datos": {
                "consecutivo_local": consecutivo, "medio_pago": "fiado", "total_centavos": total,
                "cliente_id": cliente_id, "creada_en_cliente": "2026-07-28T10:00:00+00:00",
                "fecha_vencimiento": "2026-08-15",
                "items": [{"producto_id": None, "cantidad": "1", "precio_unitario_centavos": total}],
            },
        }],
    }
    return venta_id, lote


def _alta_minima(cliente_http, cabeceras):
    """Producto + dispositivo + caja abierta: lo mínimo para fiar y cobrar."""
    producto = cliente_http.post(
        "/api/v1/catalogo/productos",
        json={"nombre": "Arroz 500g", "precio_venta": 2500},
        headers=cabeceras,
    )
    assert producto.status_code == 201, producto.text
    dispositivo = cliente_http.post(
        "/api/v1/sync/dispositivos", json={"nombre": "Caja 1"}, headers=cabeceras
    )
    assert dispositivo.status_code in (200, 201), dispositivo.text
    caja = cliente_http.post("/api/v1/caja/sesiones", json={"base_inicial": 0}, headers=cabeceras)
    assert caja.status_code == 201, caja.text
    return producto.json()["id"], dispositivo.json()["id"]


def test_el_cajero_gestiona_clientes_y_el_almacenista_no(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 1")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c1")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a1")

    creado = _cliente(cliente, cajero)
    assert creado["telefono"] == "3001234567"
    assert cliente.get("/api/v1/clientes", headers=cajero).json()["total"] == 1
    assert cliente.post("/api/v1/clientes", json={"nombre": "Otro"}, headers=almacenista).status_code == 403
    assert cliente.get("/api/v1/clientes", headers=almacenista).status_code == 403
    assert cliente.get(f"/api/v1/clientes/{creado['id']}", headers=almacenista).status_code == 403


def test_el_alta_de_cliente_es_idempotente_por_su_id(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 2")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d2")
    ancla = str(uuid.uuid4())
    datos = {"id": ancla, "nombre": "El pipe"}

    primero = cliente.post("/api/v1/clientes", json=datos, headers=dueno)
    assert primero.status_code == 201
    segundo = cliente.post("/api/v1/clientes", json=datos, headers=dueno)
    assert segundo.status_code == 201 and segundo.json()["id"] == ancla
    divergente = cliente.post("/api/v1/clientes", json={**datos, "nombre": "Otro"}, headers=dueno)
    assert divergente.status_code == 409 and divergente.json()["code"] == "cliente_id_divergente"


def test_la_ficha_trae_saldo_y_cupo(app_con_base):
    """El saldo se calcula en cada lectura (ADR-022) y el cupo viaja con él
    (decisión 8): 120.000 fiados con límite 100.000 → `cupo_excedido`."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 3")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d3")
    producto_id, dispositivo_id = _alta_minima(cliente, dueno)
    don_carlos = _cliente(cliente, dueno)

    venta_id, lote = _fiado(cliente, dueno, dispositivo_id, don_carlos["id"], 120000)
    lote["operaciones"][0]["datos"]["items"][0]["producto_id"] = producto_id
    sync = cliente.post("/api/v1/sync/lotes", json=lote, headers=dueno)
    assert sync.status_code == 200, sync.text
    assert sync.json()["resultados"][0]["resultado"] == "aceptada"
    assert sync.json()["resultados"][0]["detalles"] == {"cupo_excedido": True}

    ficha = cliente.get(f"/api/v1/clientes/{don_carlos['id']}", headers=dueno)
    assert ficha.status_code == 200
    cuerpo = ficha.json()
    assert cuerpo["saldo_pendiente_total"] == 120000 and cuerpo["cupo_excedido"] is True
    assert len(cuerpo["creditos"]) == 1 and cuerpo["creditos"][0]["estado"] == "vigente"


def test_el_abono_descuenta_y_el_cuaderno_lo_cuenta(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 4")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d4")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c4")
    producto_id, dispositivo_id = _alta_minima(cliente, dueno)
    don_carlos = _cliente(cliente, dueno, limite_credito=None)
    venta_id, lote = _fiado(cliente, dueno, dispositivo_id, don_carlos["id"], 100000)
    lote["operaciones"][0]["datos"]["items"][0]["producto_id"] = producto_id
    assert cliente.post("/api/v1/sync/lotes", json=lote, headers=dueno).status_code == 200

    cuaderno = cliente.get("/api/v1/fiado/creditos", headers=cajero)
    assert cuaderno.status_code == 200 and cuaderno.json()["total"] == 1
    credito = cuaderno.json()["items"][0]
    assert credito["cliente_nombre"] == "Don Carlos"

    abono_id = str(uuid.uuid4())
    abono = cliente.post(
        f"/api/v1/fiado/creditos/{credito['id']}/abonos",
        json={"id": abono_id, "monto": 30000, "metodo_pago": "efectivo"},
        headers=cajero,  # el cajero cobra (ADR-023)
    )
    assert abono.status_code == 201, abono.text
    reintento = cliente.post(
        f"/api/v1/fiado/creditos/{credito['id']}/abonos",
        json={"id": abono_id, "monto": 30000, "metodo_pago": "efectivo"},
        headers=cajero,
    )
    assert reintento.status_code == 201  # idempotente: no descuenta dos veces
    detalle = cliente.get(f"/api/v1/fiado/creditos/{credito['id']}", headers=dueno)
    assert detalle.json()["saldo_pendiente"] == 70000
    assert len(detalle.json()["abonos"]) == 1
    assert detalle.json()["whatsapp_url"].startswith("https://wa.me/573001234567?text=")


def test_el_abono_mayor_que_el_saldo_es_422(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 5")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d5")
    producto_id, dispositivo_id = _alta_minima(cliente, dueno)
    don_carlos = _cliente(cliente, dueno, limite_credito=None)
    venta_id, lote = _fiado(cliente, dueno, dispositivo_id, don_carlos["id"], 40000)
    lote["operaciones"][0]["datos"]["items"][0]["producto_id"] = producto_id
    assert cliente.post("/api/v1/sync/lotes", json=lote, headers=dueno).status_code == 200
    credito = cliente.get("/api/v1/fiado/creditos", headers=dueno).json()["items"][0]

    exceso = cliente.post(
        f"/api/v1/fiado/creditos/{credito['id']}/abonos",
        json={"id": str(uuid.uuid4()), "monto": 41000, "metodo_pago": "efectivo"},
        headers=dueno,
    )
    assert exceso.status_code == 422 and exceso.json()["code"] == "abono_excede_saldo"


def test_el_almacenista_recibe_403_en_todo_el_cuaderno(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 6")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a6")
    cualquiera = str(uuid.uuid4())
    assert cliente.get("/api/v1/fiado/creditos", headers=almacenista).status_code == 403
    assert cliente.get(f"/api/v1/fiado/creditos/{cualquiera}", headers=almacenista).status_code == 403
    assert cliente.patch(f"/api/v1/fiado/creditos/{cualquiera}", json={"fecha_vencimiento": "2026-09-01"}, headers=almacenista).status_code == 403
    abono = cliente.post(
        f"/api/v1/fiado/creditos/{cualquiera}/abonos",
        json={"id": str(uuid.uuid4()), "monto": 1000, "metodo_pago": "efectivo"},
        headers=almacenista,
    )
    assert abono.status_code == 403 and abono.json()["code"] == "permiso_ausente"


def test_el_credito_del_vecino_es_invisible(app_con_base):
    cliente, validador, _ = app_con_base
    negocio_a = _crear_negocio(cliente, validador, "Fiado 7A")
    negocio_b = _crear_negocio(cliente, validador, "Fiado 7B")
    dueno_a = _cabeceras_de(validador, ROL_DUENO, negocio_a, "tok-d7a")
    dueno_b = _cabeceras_de(validador, ROL_DUENO, negocio_b, "tok-d7b")
    don_carlos = _cliente(cliente, dueno_a)

    assert cliente.get(f"/api/v1/clientes/{don_carlos['id']}", headers=dueno_b).status_code == 404
    assert cliente.get("/api/v1/clientes", headers=dueno_b).json()["total"] == 0
    assert cliente.get("/api/v1/fiado/creditos", headers=dueno_b).json()["total"] == 0
    abono_ajeno = cliente.post(
        f"/api/v1/fiado/creditos/{uuid.uuid4()}/abonos",
        json={"id": str(uuid.uuid4()), "monto": 1000, "metodo_pago": "otro"},
        headers=dueno_b,
    )
    assert abono_ajeno.status_code == 404


def test_las_cotas_son_422_nunca_500(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Fiado 8")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d8")
    assert cliente.post("/api/v1/clientes", json={"nombre": "X"}, headers=dueno).status_code == 422
    assert cliente.post("/api/v1/clientes", json={"nombre": "Ok", "limite_credito": 2**31}, headers=dueno).status_code == 422
    assert cliente.post("/api/v1/clientes", json={"nombre": "Ok", "telefono": "123"}, headers=dueno).status_code == 422
    assert cliente.post(
        "/api/v1/clientes", json={"nombre": "Ok", "tenant_id": str(uuid.uuid4())}, headers=dueno
    ).status_code == 422
    mal_metodo = cliente.post(
        f"/api/v1/fiado/creditos/{uuid.uuid4()}/abonos",
        json={"id": str(uuid.uuid4()), "monto": 100, "metodo_pago": "nequi"},
        headers=dueno,
    )
    assert mal_metodo.status_code == 422
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/api/test_fiado_api.py -q
# Esperado: 404 en todas las rutas — el router no existe aún
```

**Nota para el ejecutor:** las rutas del alta de producto y del registro de dispositivo (`POST /api/v1/catalogo/productos`, `POST /api/v1/sync/lotes`, `POST /api/v1/sync/dispositivos`) son las del contrato vigente; si alguna difiere (nombre del recurso del lote o del dispositivo), se ajusta el helper a lo que use `test_caja_api.py`/`test_ventas_sync.py` — los asserts del fiado no cambian.

- [ ] **Paso 3: escribir las dependencias.** Crear `backend/services/api/app/modules/fiado/dependencies.py`:

```python
"""Dependencias del módulo `fiado`.

El guard de permisos vive en `app.dependencies.exigir_permiso` (su casa desde
el módulo ventas). El reparto (ADR-023 y decisión 10 del plan): clientes →
`cliente:gestionar`; el cuaderno (créditos y su reprogramación) →
`fiado:crear`; cobrar → `fiado:abonar`. El cajero tiene los tres — fía y
cobra, que es el modo normal de la tienda —; el almacenista recibe 403 en
todo, y es la respuesta correcta y esperada.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import exigir_permiso, sesion_de_tenant
from app.modules.fiado.service import FiadoService
from app.modules.tenants.dependencies import exigir_negocio_activo
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.auth.policies import PERM_CLIENTE_GESTIONAR, PERM_FIADO_ABONAR, PERM_FIADO_CREAR
from vendi_core.tenant.context import TenantContext

exigir_cliente_gestionar = exigir_permiso(PERM_CLIENTE_GESTIONAR)
exigir_fiado_crear = exigir_permiso(PERM_FIADO_CREAR)
exigir_fiado_abonar = exigir_permiso(PERM_FIADO_ABONAR)


async def servicio_de_fiado(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
    user: UserContext = Depends(get_current_user),
) -> FiadoService:
    """El servicio del negocio del token, con la sesión que la RLS acota.

    `exigir_negocio_activo` va primero: un negocio suspendido no opera el
    cuaderno (403 `tenant_suspendido`). El `actor_id` queda en cada abono:
    la auditoría del gesto con dinero."""
    return FiadoService(session=session, tenant_id=tenant.tenant_id, actor_id=user.user_id)


__all__ = [
    "exigir_cliente_gestionar",
    "exigir_fiado_abonar",
    "exigir_fiado_crear",
    "servicio_de_fiado",
]
```

- [ ] **Paso 4: escribir el router.** Crear `backend/services/api/app/modules/fiado/router.py`:

```python
"""Clientes y el cuaderno: `/api/v1/clientes/*` y `/api/v1/fiado/creditos/*`.

Los endpoints de ABONOS son REST ONLINE puros (decisión 6 del plan): el
abono offline por el lote llega con su propia decisión (D-27), y el `id`
requerido ya deja puesta su ancla. Los créditos NACEN en el sync (Tarea 7):
aquí se consultan, se reprograman y se cobran. Todo trabaja con la sesión
de TENANT (rol `vendi_app`, RLS activo): ningún handler recibe `tenant_id`.
El 403 por rol es la respuesta correcta y esperada (ADR-023).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.modules.fiado.dependencies import (
    exigir_cliente_gestionar,
    exigir_fiado_abonar,
    exigir_fiado_crear,
    servicio_de_fiado,
)
from app.modules.fiado.schemas import (
    AbonoCrear,
    AbonoSalida,
    ClienteConSaldo,
    ClienteCrear,
    ClienteDetalleSalida,
    ClienteEditar,
    ClienteSalida,
    CreditoDetalleSalida,
    CreditoReprogramar,
    CreditoResumenSalida,
)
from app.modules.fiado.service import FiadoService
from vendi_core.auth.context import UserContext
from vendi_core.models.pagination import PagedList
from vendi_core.models.responses import ErrorResponse

router = APIRouter(tags=["fiado"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    422: {"model": ErrorResponse, "description": "Request malformado (validación de estructura o de dominio)"},
}


@router.post(
    "/clientes",
    response_model=ClienteSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un cliente",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "El id ya existe con datos distintos (o está en uso)"},
    },
)
async def crear_cliente(
    datos: ClienteCrear,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_cliente_gestionar),
) -> ClienteSalida:
    """Idempotente por el `id` del cliente (ADR-017): reenviar el mismo alta
    devuelve el existente; con otro contenido, 409 `cliente_id_divergente`."""
    return await servicio.crear_cliente(datos)


@router.get(
    "/clientes",
    response_model=PagedList[ClienteConSaldo],
    summary="La libreta de clientes con su deuda viva",
    responses=_RESPUESTAS_COMUNES,
)
async def listar_clientes(
    q: str | None = Query(default=None, max_length=160),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_cliente_gestionar),
) -> PagedList[ClienteConSaldo]:
    """El saldo es `SUM(saldo_pendiente)` de vigente/vencido, calculado en
    cada lectura (ADR-022): nunca una columna que se desactualice. `q`
    busca por nombre."""
    filas, total = await servicio.listar_clientes(q, skip=skip, limit=limit)
    return PagedList[ClienteConSaldo](items=filas, total=total, skip=skip, limit=limit)


@router.get(
    "/clientes/{cliente_id}",
    response_model=ClienteDetalleSalida,
    summary="La ficha del cliente: saldo, cupo y sus fiados con deuda",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "El cliente no existe"}},
)
async def obtener_cliente(
    cliente_id: uuid.UUID,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_cliente_gestionar),
) -> ClienteDetalleSalida:
    """Con `saldo_pendiente_total` y `cupo_excedido` calculados (decisión 8):
    es lo que el POS muestra antes de fiarle más."""
    return await servicio.obtener_cliente(cliente_id)


@router.patch(
    "/clientes/{cliente_id}",
    response_model=ClienteSalida,
    summary="Editar un cliente",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "El cliente no existe"}},
)
async def editar_cliente(
    cliente_id: uuid.UUID,
    datos: ClienteEditar,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_cliente_gestionar),
) -> ClienteSalida:
    """`null` explícito borra el valor (quitar el cupo vuelve a «sin tope»).
    El cliente no se borra (decisión 13): el cuaderno lo referencia."""
    return await servicio.editar_cliente(cliente_id, datos)


@router.get(
    "/fiado/creditos",
    response_model=PagedList[CreditoResumenSalida],
    summary="El cuaderno: los fiados, lo que vence primero arriba",
    responses=_RESPUESTAS_COMUNES,
)
async def listar_creditos(
    estado: str | None = Query(default=None, pattern="^(vigente|vencido|saldado|anulado|todos)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_fiado_crear),
) -> PagedList[CreditoResumenSalida]:
    """Por defecto solo lo que se debe (`vigente` + `vencido`); `estado=todos`
    incluye la historia. El fiado ES el cuaderno (ADR-009)."""
    filas, total = await servicio.listar_creditos(estado, skip=skip, limit=limit)
    return PagedList[CreditoResumenSalida](items=filas, total=total, skip=skip, limit=limit)


@router.get(
    "/fiado/creditos/{credito_id}",
    response_model=CreditoDetalleSalida,
    summary="El fiado: historial de pagos y enlace de WhatsApp prearmado",
    responses={**_RESPUESTAS_COMUNES, 404: {"model": ErrorResponse, "description": "El crédito no existe"}},
)
async def obtener_credito(
    credito_id: uuid.UUID,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_fiado_crear),
) -> CreditoDetalleSalida:
    """El historial de abonos es la verdad y no se reescribe (ADR-022). El
    `wa.me` va prearmado con el saldo; `null` si el cliente no tiene teléfono."""
    return await servicio.obtener_credito(credito_id)


@router.patch(
    "/fiado/creditos/{credito_id}",
    response_model=CreditoResumenSalida,
    summary="Reprogramar la fecha de vencimiento",
    responses={
        **_RESPUESTAS_COMUNES,
        404: {"model": ErrorResponse, "description": "El crédito no existe"},
        409: {"model": ErrorResponse, "description": "El crédito está saldado o anulado"},
    },
)
async def reprogramar_credito(
    credito_id: uuid.UUID,
    datos: CreditoReprogramar,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_fiado_crear),
) -> CreditoResumenSalida:
    """«Deme hasta el otro viernes»: un `vencido` reprogramado a futuro (o
    dejado sin fecha) vuelve a `vigente` (decisión 7)."""
    return await servicio.reprogramar_vencimiento(credito_id, datos)


@router.post(
    "/fiado/creditos/{credito_id}/abonos",
    response_model=AbonoSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un abono",
    responses={
        **_RESPUESTAS_COMUNES,
        404: {"model": ErrorResponse, "description": "El crédito no existe"},
        409: {"model": ErrorResponse, "description": "El crédito no admite abonos, no hay caja abierta, o el id diverge"},
    },
)
async def registrar_abono(
    credito_id: uuid.UUID,
    datos: AbonoCrear,
    servicio: FiadoService = Depends(servicio_de_fiado),
    _actor: UserContext = Depends(exigir_fiado_abonar),
) -> AbonoSalida:
    """El saldo se descuenta en la misma transacción con el CHECK como red
    (ADR-022). `efectivo` entra al arqueo de la sesión abierta (decisión 9);
    un abono mayor que el saldo es 422 `abono_excede_saldo`."""
    return await servicio.registrar_abono(credito_id, datos)
```

- [ ] **Paso 5: montar el router.** En `backend/services/api/app/factory.py`, añadir el import tras el de caja:

```python
from app.modules.fiado.router import router as router_fiado
```

y tras `app.include_router(router_caja, prefix="/api/v1")`:

```python
    app.include_router(router_fiado, prefix="/api/v1")
```

- [ ] **Paso 6: verificar.**

```bash
cd backend && uv run pytest tests/api/test_fiado_api.py -q
# Esperado: 8 passed — 0 SKIPPED
uv run pytest tests/api -q
# Esperado: toda la carpeta verde (catálogo, ventas, inventario, caja y tenants siguen pasando)
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 7: commit**

```bash
git add backend/services/api/app/modules/fiado/dependencies.py backend/services/api/app/modules/fiado/router.py backend/services/api/app/factory.py backend/tests/api/test_fiado_api.py backend/tests/api/conftest.py
git commit -m "Endpoints REST de clientes y del cuaderno: CRUD, saldo y cupo, reprogramación y abonos"
```

**Criterios de aceptación:** los 8 tests de API pasan contra el stack real (0 SKIPPED); el cajero gestiona clientes, ve el cuaderno y cobra; el almacenista recibe 403 `permiso_ausente` en las 8 rutas; el crédito nace por el sync y se cobra por REST; la ficha muestra saldo y cupo calculados; el cliente y el crédito del vecino son 404/listas vacías; las cotas son 422 y nunca 500; `tests/api` completo verde (con la limpieza cubriendo las tres tablas); `ruff` limpio.

---

## Tarea 11: Check 23 con los 14 permisos, OpenAPI congelado y cliente TypeScript

**Files:**
- Modify: `scripts/verify-setup.sh` (bloque del check 23)
- Modify: `docs/api/openapi-fase0.json` (regenerado, mismo archivo)
- Modify: `docs/api/README.md` (tabla de rutas, códigos, notas)
- Modify: `frontend/projects/libs/data-access/src/lib/api-client/openapi.json` e `index.ts` (salida del codegen)

**Interfaces:**
- Consume: el generador de tokens de ejemplo que el check 23 ya usa; la API viva con `DOCS_PUBLICOS=true` y `scripts/codegen-api-client.sh` en modo congelado.
- Produce: el check 23 exigiendo los 14 permisos de dominio en el token del dueño; el contrato con las 8 rutas nuevas; el cliente TS sin deriva.

- [ ] **Paso 1: extender el bucle de permisos del check 23.** En `scripts/verify-setup.sh`, dentro del heredoc `python3 - <<'PY'` del check 23, reemplazar la línea del bucle por:

```python
for permiso in ("producto:leer", "producto:editar", "venta:crear", "venta:anular", "inventario:ajustar", "compra:crear", "caja:leer", "caja:abrir", "caja:cerrar", "caja:movimiento", "reporte:leer", "cliente:gestionar", "fiado:crear", "fiado:abonar"):
```

y el mensaje del `ok` por:

```bash
        ok "aud=${KEYCLOAK_AUDIENCE:-vendi-backend}, rol de negocio y los 14 permisos de dominio en el token del dueño"
```

- [ ] **Paso 2: verificar contra el stack.**

```bash
bash scripts/seed.sh && bash scripts/verify-setup.sh 2>&1 | grep -E "^\[(OK|FALLO|OMITIDO)\].*23"
# Esperado: [OK] 23 ... los 14 permisos de dominio en el token del dueño
```

Prueba negativa (obligatoria): quitar temporalmente `fiado:abonar` del mapeo del grupo `cajero`... no — el check mira el token del DUEÑO: quitar `fiado:crear` del mapeo del grupo `dueno` en la consola de Keycloak (`https://accounts.vendi.co`, con `--resolve accounts.vendi.co:443:127.0.0.1`), re-ejecutar el check y verlo fallar con el mensaje de siembra; restaurar con `bash scripts/seed.sh` y ver el OK.

- [ ] **Paso 3: regenerar el contrato congelado desde la API viva.** Con el stack levantado y la migración aplicada:

```bash
curl -sS --resolve api.vendi.co:443:127.0.0.1 https://api.vendi.co/openapi.json \
  | python3 -c 'import json,sys; json.dump(json.load(sys.stdin), open("docs/api/openapi-fase0.json","w"), indent=2, ensure_ascii=False, sort_keys=True)'
python3 -c 'import json; d=json.load(open("docs/api/openapi-fase0.json")); print(sorted(p for p in d["paths"] if "clientes" in p or "fiado" in p))'
# Esperado: ['/api/v1/clientes', '/api/v1/clientes/{cliente_id}', '/api/v1/fiado/creditos',
#            '/api/v1/fiado/creditos/{credito_id}', '/api/v1/fiado/creditos/{credito_id}/abonos']
```

- [ ] **Paso 4: actualizar `docs/api/README.md`.** Añadir a la tabla de rutas:

```markdown
| `POST /api/v1/clientes` | `cliente:gestionar` | alta con `id` del cliente opcional (idempotente); divergente = 409 `cliente_id_divergente`; choque de id ajeno = 409 `cliente_id_en_conflicto` |
| `GET /api/v1/clientes` | `cliente:gestionar` | la libreta con `saldo_pendiente_total` (SUM calculado, ADR-022) y `cupo_excedido`; `q` busca por nombre |
| `GET /api/v1/clientes/{id}` | `cliente:gestionar` | ficha con saldo, cupo y los fiados con deuda (lo que vence primero arriba) |
| `PATCH /api/v1/clientes/{id}` | `cliente:gestionar` | edición parcial; `null` explícito borra (quitar el cupo = «sin tope»); no hay DELETE (el cuaderno referencia) |
| `GET /api/v1/fiado/creditos` | `fiado:crear` | el cuaderno: pendientes por defecto (`vigente`+`vencido`), `estado=todos` incluye la historia |
| `GET /api/v1/fiado/creditos/{id}` | `fiado:crear` | detalle con historial de abonos y `whatsapp_url` prearmada (null sin teléfono) |
| `PATCH /api/v1/fiado/creditos/{id}` | `fiado:crear` | reprogramar vencimiento; un `vencido` a futuro vuelve a `vigente`; `saldado`/`anulado` = 409 `credito_no_editable` |
| `POST /api/v1/fiado/creditos/{id}/abonos` | `fiado:abonar` | descuenta el saldo en la misma transacción (CHECK como red); `id` requerido (ancla); exceso = 422 `abono_excede_saldo`; `efectivo` exige caja abierta (409 `caja_sin_sesion_abierta`) y entra al arqueo |
```

A la lista de `code` estables: `cliente_id_divergente`, `cliente_id_en_conflicto`, `cliente_no_encontrado`, `credito_no_encontrado`, `credito_no_abonable`, `credito_no_editable`, `abono_excede_saldo`, `abono_id_divergente`. Y a las notas finales:

```markdown
El crédito nace en el sync (misma transacción de la venta fiada): el lote
gana la operación `cliente.crear` (el id del dispositivo ES la PK del
cliente) y la venta con `medio_pago="fiado"` acepta `fecha_vencimiento`
opcional. El servidor NO rechaza por cupo (ADR-018): la operación aceptada
lo señala con `detalles.cupo_excedido=true`. La anulación de la venta fiada
anula el crédito (`anulado`, saldo 0); los abonos son historia intocable y
la devolución del dinero es un egreso de caja manual.

Eventos nuevos del outbox en este contrato: `fiado.credito_creado`,
`fiado.abono_registrado`, `fiado.credito_saldado`, `fiado.credito_anulado` y
`fiado.credito_vencido` (este último lo emite el trabajo diario del worker;
lo consume el módulo de notificaciones para el push — sin PII en el
payload, ADR-025). El WhatsApp del recordatorio es un `wa.me` prearmado en
el detalle del crédito: manual y de coste cero (ADR-022).

Los abonos en efectivo entran al arqueo de la sesión abierta (sumados desde
`fiado_abonos`, nunca duplicados como movimiento) y el forecast proyecta los
cobros de fiado del saldo que vence en 30 días (los sin fecha no entran).
```

- [ ] **Paso 5: regenerar el cliente y demostrar que no hay deriva.**

```bash
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh
cd frontend && npm run build:libs && npx ng build vendi-admin
# Esperado: build de libs y de vendi-admin en verde
git add docs/api frontend/projects/libs/data-access/src/lib/api-client
git diff --cached --stat
```

- [ ] **Paso 6: commit**

```bash
git add scripts/verify-setup.sh
git commit -m "Check 23 con los 14 permisos de dominio, contrato OpenAPI del fiado y cliente TypeScript regenerado"
```

**Criterios de aceptación:** el check 23 pasa con la siembra al día y falla —con mensaje accionable— si falta cualquiera de los 14 permisos de dominio; el OpenAPI congelado contiene las 5 rutas nuevas (8 endpoints) con sus schemas (`ClienteCrear`, `ClienteEditar`, `ClienteSalida`, `ClienteConSaldo`, `ClienteDetalleSalida`, `CreditoResumenSalida`, `CreditoDetalleSalida`, `CreditoReprogramar`, `AbonoCrear`, `AbonoSalida`); el job `frontend-contratos` del CI queda en verde; `vendi-admin` compila contra el cliente regenerado.

---

## Tarea 12: Cierre del módulo — gate de la Etapa 1.2, `docs/estado.md` y cierre de D-10

**Files:**
- Modify: `docs/estado.md` (sección nueva del módulo fiado y clientes, con fecha de corte y evidencia comando+salida)
- Modify: `docs/deuda-tecnica.md` (D-10 pasa a «Cerradas en Fase 1» con su evidencia; D-27 y D-28 se registran)

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
# Esperado: todo [OK], con el check 23 exigiendo los 14 permisos
```

Gate por módulo (del plan maestro de Fase 1), a verificar ítem a ítem:
- [ ] Migración con RLS + índice + grants, revisada por el agente de seguridad.
- [ ] Tests de integración con aislamiento cross-tenant nuevo por tabla (`test_aislamiento_fiado.py`: las tres tablas con su policy y el `WITH CHECK`), 0 SKIPPED.
- [ ] Los candados firmados de ADR-022: el saldo al peso (crédito de 100, abonos de 30+30 → 40; el de 41 revienta — aquí como 422 tipado con el CHECK de red, probado en aislamiento), el trabajo diario (vencimiento de ayer → `vencido` + exactamente un `fiado.credito_vencido`, idempotente al re-correr), y el aislamiento por tabla.
- [ ] El candado firmado de ADR-023: almacenista que cobra fiado → 403, mismo gesto con dueño/cajero → 201 (`test_el_almacenista_recibe_403_en_todo_el_cuaderno` + `test_el_abono_descuenta_y_el_cuaderno_lo_cuenta`), y `PERMISOS_POR_ROL ⊆ PERMISSION_CATALOG` verde.
- [ ] OpenAPI congelado actualizado + codegen + `contrato.ts` sigue compilando.
- [ ] Eventos de outbox emitidos según ADR-022 (+`fiado.credito_anulado`, decisión 3) con clave `<tenant_id>.<evento>`; `pytest -m integration` verde; `ruff` verde.

- [ ] **Paso 2: actualizar `docs/estado.md`.** Añadir una sección «Módulo fiado y clientes (Fase 1, Etapa 1.2)» con: fecha de corte, qué se entregó (las tres tablas con el saldo materializado y su CHECK, el crédito que nace en el sync —incluida la venta tardía—, `cliente.crear` en el lote con el id del dispositivo como PK, la anulación que anula el crédito sin tocar abonos, los abonos REST al peso con los eventos, el cuaderno con `wa.me`, la reprogramación, el trabajo diario de vencidos una-sola-vez, el arqueo que ya suma abonos y el forecast que ya proyecta cobros, los tres permisos y su reparto, las 8 rutas, D-10 cerrada), y **al lado de cada afirmación el comando que la demuestra** con su salida pegada (regla del documento: no promete nada que un comando no demuestre).

- [ ] **Paso 3: cerrar D-10 y registrar D-27/D-28 en `docs/deuda-tecnica.md`.**

- **D-10** (`ventas.cliente_id` sin FK) pasa a «Cerradas en Fase 1»: se cerró ADOPTANDO el `cliente_id` del dispositivo como PK de `clientes` (operación `cliente.crear` del lote + `id` opcional en el POST), como manda su vencimiento — la columna `ventas.cliente_id` se queda sin FK a propósito (decisión 4 del plan: la venta no se rechaza jamás y Postgres no aplica RLS al verificar llaves, así que la FK no añadiría aislamiento, solo fragilidad). Evidencia: `uv run pytest tests/test_fiado_sync.py -q` → 11 passed (el cliente sube por el lote y la venta fiada crea su crédito), y `tests/test_aislamiento_fiado.py` verde.
- **D-27 (nueva):** el abono de fiado NO viaja por el lote del sync — es REST online (decisión 6 del plan; ADR-022 contempla el abono offline). El ancla ya está puesta (el `id` es requerido en el POST), así que `fiado.abonar` entra después sin romper nada. Vencimiento: Fase 1, antes del piloto.
- **D-28 (nueva):** no hay delta de clientes hacia dispositivos (decisión 13 del plan): un cliente creado en una caja llega a la otra solo online (GET /clientes); offline, cada dispositivo ve los clientes que él mismo creó. Vencimiento: Fase 1, antes del piloto.

Formato del registro para ambas: qué es, por qué se aceptó, riesgo si se olvida, vencimiento, candados mientras tanto.

- [ ] **Paso 4: commit de cierre**

```bash
git add docs/estado.md docs/deuda-tecnica.md
git commit -m "Módulo fiado y clientes cerrado: gate de la Etapa 1.2 verificado, estado actualizado y D-10 cerrada"
```

---

## Superficie de ataque para QA — módulo fiado y clientes (créditos, abonos, recordatorios)

Para el agente de QA adversarial de la Etapa 1.4 (agente distinto del implementador; su KPI son hallazgos). Los escenarios marcados (firmado) ya tienen test que los fija: verificarlos, no «redescubrirlos»; el hallazgo sería que el test miente.

- **El saldo (el corazón):** crédito de 100, abonos de 30+30 → 40, y el de 41 → 422 `abono_excede_saldo` (firmado); abono EXACTAMENTE igual al saldo (saldado, dos eventos — firmado); dos abonos concurrentes del mismo crédito (el FOR UPDATE los serializa: suma exacta, un solo `credito_saldado` si aplica — intentar provocar el CHECK y verificar que sale 422, nunca 500); abono a crédito `vencido` (SÍ se puede: la deuda sigue viva — verificar); abono con el `id` de un abono de OTRO crédito (409 `abono_id_divergente` por `credito_id` — firmado); abono de otro tenant (404 — firmado); abono en efectivo en el instante del cierre de caja (el FOR UPDATE de la sesión los serializa: entra antes del arqueo o recibe 409 — nunca queda atado a una sesión cerrada).
- **La conversión venta → crédito:** venta fiada y su `cliente.crear` en el mismo lote (firmado); venta fiada SIN cliente (placeholder `(sin nombre)` + crédito — firmado); venta fiada tardía tras el cierre de caja (cae en la sesión nueva como cualquier venta Y crea su crédito — verificar las dos cosas); venta fiada con total 0 (aceptada sin crédito — verificar y fijar); venta fiada con `fecha_vencimiento` en el pasado (se acepta: el cuaderno se anota tarde; el trabajo diario la marca vencida esa noche — verificar); reenvío del lote (un crédito, un evento — firmado); carrera de dos PRIMERAS aplicaciones de la misma venta fiada (¿`ux_fiado_creditos_venta` → `duplicada` y un solo crédito? provocarla).
- **La anulación:** sin abonos (`anulado`, saldo 0, evento con `total_abonado` 0 — firmado); con abonos (historia intacta, evento con el total — firmado); anulación de fiada ya SALDADA (pasa a `anulado`, el dinero cobrado no se reabre: «saldado nunca vuelve a vigente» — verificar); anulación y abono concurrentes del mismo crédito (el FOR UPDATE decide un orden: abono-then-anula o anula-then-409/422 — ninguno debe dejar saldo negativo ni crédito `anulado` con abono nuevo); anulación de venta fiada de OTRO tenant (rechazada `venta_no_encontrada` — verificar); el dinero de los abonos anulados: el arqueo lo sigue contando (está en la gaveta) hasta el egreso manual — verificar que el egreso `otro` con motivo cuadra la sesión.
- **El cupo:** venta que lo supera (aceptada con `detalles.cupo_excedido` — firmado); segunda venta que supera aún más (sigue señalando — firmado); abono que baja el saldo por debajo del límite (la ficha deja de mostrar exceso sin tocar ninguna bandera — firmado); límite 0 (cualquier fiado excede — verificar); límite NULL (nunca excede — firmado); editar el límite por debajo del saldo actual (la ficha lo muestra excedido al instante — verificar).
- **El trabajo diario:** vencimiento de ayer → `vencido` + un evento (firmado); re-corrida y corrida concurrente (cero duplicados — firmado el primero; la concurrencia, provocarla: los bloqueos del UPDATE deciden); venta que vence HOY (no vence hasta mañana: `< hoy` — verificar el borde); reprogramar un `vencido` a futuro (vuelve a `vigente` y volverá a vencer con su evento — firmado el primero, verificar el segundo ciclo completo); reprogramar a una fecha del pasado (sigue `vencido` o vuelve a `vigente` hasta la noche — fijar el comportamiento); tenant suspendido (no recibe pasada: el lector solo lista activos — verificar); crédito `anulado` con fecha pasada (no vence ni emite — verificar); el payload del evento sin nombre de cliente (ADR-025 — verificar).
- **Aislamiento:** las tres tablas con `WITH CHECK` (firmado); ficha/cuaderno/abono del vecino (404/listas vacías — firmado); `tenant_id` inyectado en los cuerpos (422 `extra_forbidden` — firmado); un `fiado.credito_vencido` de T1 nunca sale con routing key de T2 (verificar con el payload); el `SUM` del saldo por cliente nunca suma al vecino (RLS — verificar con dos tenants con créditos idénticos).
- **Validación y bordes:** `monto`/`limite_credito` en 2^31 (422 — firmado); teléfono con letras/espacios/prefijos (422/limpieza — firmado); nombre de 1 letra, de puros espacios, de 161 caracteres (422 — firmado); nota con HTML/emoji (viaja como texto — el XSS es del render); `estado` del cuaderno fuera de lista (422 por el `pattern` del Query — verificar); paginación `limit=201` (422 — verificar); `PATCH /clientes/{id}` con cuerpo vacío (200 sin cambios — verificar y fijar).
- **Permisos:** almacenista en las 8 rutas (403 — firmado); cajero (201/200 en todo lo del fiado — firmado); token con `fiado:crear` pero sin `fiado:abonar` editado a mano en Keycloak (ve el cuaderno pero no cobra — los guards son por permiso, no por rol); token sin `cliente:gestionar` cuya app sincroniza `cliente.crear` (rechazada `permiso_ausente` por operación, el lote sigue — firmado); token sin `fiado:crear` que sincroniza una venta fiada (rechazada, sin venta ni crédito — firmado); negocio suspendido (403 `tenant_suspendido` — verificar).
- **Caja y forecast con fiado real:** arqueo al peso con abonos en efectivo (firmado); abono por transferencia (no entra al arqueo — firmado); abono en efectivo de una sesión YA cerrada (imposible: se ata a la abierta — verificar que un abono insertado por SQL con `sesion_caja_id` de una cerrada NO altera su arqueo congelado: las columnas congeladas no se recalculan jamás); forecast con vencidos y sin-fecha (firmado); esperado vivo del cajero (sigue en `null` — el fiado no cambia esa regla; verificar).
- **Eventos:** rollback a mitad del abono (provocar fallo tras el flush: ni abono, ni saldo descontado, ni eventos — la garantía outbox); `fiado.credito_creado` una sola vez por venta aceptada (firmado); `fiado.abono_registrado` sin la nota en el payload (verificar y fijar: la nota puede llevar PII); el reintento del abono NO re-emite (firmado).

---

## Self-Review

- **Cobertura del spec:** ADR-022 (tres tablas con RLS, `saldo_pendiente` materializado con `CHECK >= 0` y descuento en la misma transacción, saldo por cliente como SUM nunca guardado, abono contra el crédito tocado, cupo que se puede superar con señal, recordatorio diario push + `wa.me` manual, ids del cliente para abonos, eventos del outbox, candados de saldo/trabajo diario/cross-tenant) → Tareas 1, 2, 5, 6, 8 + decisiones 1-9. ADR-009 (el fiado es el cuaderno: historial de pagos y base mínima de clientes) → Tareas 5, 6, 10. ADR-018 (fiado sin red sin rechazo, exceso registrado y mostrado, venta fiada existente con `cliente_id` sin FK) → Tarea 7 + decisiones 1, 2, 4, 8. Decisión 8 del plan de ventas (la creación del `fiado_creditos` es de este módulo) → Tarea 7. ADR-023 (los tres permisos del catálogo de 14, reparto exacto, candado de autorización, check 23) → Tareas 4, 7, 10, 11 + decisión 10. ADR-025 (`fiado.credito_vencido` sin PII para que el módulo 7 lo traduzca; `wa.me` manual) → Tareas 6, 8 + decisión 12. ADR-021 (abonos en el arqueo sin duplicar movimiento) → Tareas 6, 9 + decisión 9. ADR-006 (forecast con fuentes declaradas) → Tarea 9 + decisión 11. Deuda D-10 → Tarea 7 + cierre en Tarea 12. Lecciones de los módulos 1-4 (cotas `le=`, validadores sin asunción de `str`, FOR UPDATE en read-modify-write, traducción de IntegrityError, idempotencia no ciega a la divergencia, visibilidad por permiso, evidencia real en cierres) → Global Constraints, Tareas 1, 3, 5, 6, 10, 12. Items del encargo 1-9 → Tareas 1-12.
- **Placeholders:** ninguno. Todo paso lleva código completo, comando exacto y salida esperada. Los conteos de tests son los escritos (10 aislamiento, 5 modelos, 11 schemas, 17 servicio, 11 sync, 4 vencimientos, 8 API, 1 arqueo con abonos, 1 forecast, 2 policies); si el ejecutor añade casos, ajusta el número (los comandos de gate son de suite, no de conteo).
- **Consistencia de tipos/contratos:** nombres de tablas, columnas, índices y CHECK coinciden entre migración (Tarea 1), modelos (Tarea 2), tests de metadata y schemas (Tarea 3); los `code` de error coinciden entre servicio, tests de servicio, tests de API y la tabla de `docs/api/README.md` (`cliente_id_divergente`, `cliente_id_en_conflicto`, `cliente_no_encontrado`, `credito_no_encontrado`, `credito_no_abonable`, `credito_no_editable`, `abono_excede_saldo`, `abono_id_divergente`, `caja_sin_sesion_abierta` reusado); las listas cerradas (`ESTADOS_DE_CREDITO`, `METODOS_DE_PAGO_ABONO`) tienen una sola definición (modelo) reusada por schema y migración; los eventos usan la firma real de `DomainEventService.emit`; los schemas reusan `TOPE_PRECIO`/`_limpiar_texto` del catálogo; el motivo estable del sync (`permiso_ausente`, `cliente_id_divergente`, `fecha_vencimiento_solo_en_fiado`) coincide entre `ventas/service.py`, `fiado/sync.py` y los tests; los flags nuevos de `VentasService` son fail-closed por defecto y ningún test previo cambia (verificado: solo `test_ventas_servicio.py:269` usa fiado por el servicio y sus operaciones se rechazan por las reglas de datos ANTES del chequeo de permiso).
- **Riesgos conocidos y declarados:** (1) una venta fiada cuyo `cliente_id` choca con un cliente de OTRO tenant (bug del cliente: reutilizar ids) sale `rechazada` `cliente_id_divergente` en la auto-alta placeholder — la no-rechazable de ADR-018 es por cupo; este caso patológico queda en la superficie de QA; (2) el abono offline no existe todavía (D-27 registrada con vencimiento piloto): tensión declarada con ADR-022, no escondida; (3) el placeholder `(sin nombre)` llena la libreta de clientes mudos si una app envía ventas fiadas sin sincronizar sus clientes — visible y editable, que es la intención; (4) el filtro del trabajo diario es SQL crudo sobre sesión de plataforma: si alguien quita el `tenant_id = :tenant_id` toca todos los negocios — el test `test_no_toca_el_futuro...` lo fija; (5) `registrar_abono` lee la sesión abierta con FOR UPDATE: dos abonos en efectivo concurrentes se serializan en la fila de la sesión (despreciable a la escala de una tienda, mismo costo aceptado en caja); (6) los clientes no se borran (decisión 13): si el piloto pide borrado vendrá con su decisión, probablemente lógico y con créditos saldados; (7) `fecha_vencimiento` pasada en una venta nueva se acepta y vence esa misma noche (el cuaderno se anota tarde): declarado en la superficie de QA.
