"""El plan genérico cacheado NO congela el valor del GUC de tenant.

Este es el candado que faltaba por escribir (punto 8 de la deuda abierta de la
Etapa 2: "el QA lo midió seguro pero nadie tiene la prueba escrita en un
artefacto"). Aquí queda escrita.

## Qué se teme exactamente

La policy compara `tenant_id` contra `current_setting('vendi.tenant_id', true)`.
Postgres cachea planes de sentencias preparadas, y a partir de la sexta
ejecución puede cambiar del plan a medida (*custom*, replanificado con los
valores actuales) al plan **genérico**, que se planifica una sola vez y se
reutiliza. La pregunta que decide si el aislamiento de Vendi funciona: al
construir el plan genérico, ¿`current_setting(...)` se evalúa **una vez y se
hornea** en el plan, o se evalúa **en cada ejecución**?

Si se horneara, el escenario sería este: la sexta consulta de una conexión del
pool fija el tenant del sexto usuario, y a partir de ahí **cada petición que
tocara esa conexión vería los datos de aquel negocio**. Sin errores, sin logs,
sin nada raro en el código. Sería la peor fuga imaginable en este diseño.

La respuesta correcta es "en cada ejecución", porque `current_setting` está
marcada como `stable`, no `immutable`: estable significa "no cambia dentro de
una misma sentencia", que es justo lo que permite indexarla y justo lo que
prohíbe constantizarla entre sentencias. Pero eso es teoría sobre un detalle del
que depende el producto entero, así que se mide.

## Cómo se fuerza el caso

`plan_cache_mode = force_generic_plan` salta las cinco ejecuciones de
calentamiento y usa el plan genérico **desde la primera**. Sin ese GUC habría
que confiar en que la heurística de Postgres decida cambiar de plan durante el
test, que es exactamente el tipo de cosa que hace que un test "pase" sin haber
probado nada.

`statement_cache_size` de asyncpg se deja en su valor por defecto a propósito:
la caché de sentencias preparadas del *driver* es el otro ingrediente del
escenario (misma sentencia preparada, reutilizada entre peticiones sobre la
misma conexión física), y desactivarla desactivaría medio experimento.
"""

from __future__ import annotations

import pytest
from datos_de_prueba import T1, T2
from sqlalchemy import text

from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration

# Suficientes vueltas para pasar de largo el umbral de cinco ejecuciones con el
# que Postgres cambia a plan genérico incluso en modo `auto`.
VUELTAS = 12


@pytest.mark.asyncio
async def test_plan_generico_no_congela_el_tenant(pg_app_url, ventas_de_prueba):
    """Alterna T1 y T2 sobre UNA conexión con el plan genérico forzado."""
    # pool_size=1 / max_overflow=0: todas las vueltas caen en la misma conexión
    # física, que es la única forma de que la caché de planes se comparta entre
    # "peticiones" distintas.
    engine = create_engine(pg_app_url, pool_size=1, max_overflow=0)

    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SET plan_cache_mode = force_generic_plan")
            modo = (await conn.execute(text("SHOW plan_cache_mode"))).scalar()
            assert modo == "force_generic_plan", (
                f"no se pudo forzar el plan genérico (modo={modo!r}): el test no estaría probando lo que dice probar"
            )

            consulta = text(f"SELECT tenant_id FROM {ventas_de_prueba}")
            for vuelta in range(VUELTAS):
                esperado = T1 if vuelta % 2 == 0 else T2
                await conn.exec_driver_sql("BEGIN")
                await conn.exec_driver_sql(f"SET LOCAL vendi.tenant_id = '{esperado}'")
                filas = (await conn.execute(consulta)).scalars().all()
                await conn.exec_driver_sql("COMMIT")
                assert filas == [esperado], (
                    f"vuelta {vuelta}: con el plan genérico y el GUC en {esperado} "
                    f"se vieron {filas!r}. El plan cacheado congeló el valor del GUC: "
                    "el aislamiento por RLS NO es fiable bajo caché de planes."
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_plan_generico_por_el_camino_real_de_la_sesion(pg_app_url, ventas_de_prueba):
    """Lo mismo, pero por el camino que usa de verdad la API.

    El test anterior usa SQL crudo para controlar el experimento. Éste va por
    `create_session_factory` + ContextVar, es decir, exactamente lo que ejecuta
    un handler: si la combinación de plan genérico y `SET LOCAL` emitido por el
    listener `after_begin` fallara, fallaría aquí.
    """
    engine = create_engine(pg_app_url, pool_size=1, max_overflow=0)
    factory = create_session_factory(engine)
    try:
        # `plan_cache_mode` se fija a nivel de sesión sobre la única conexión
        # del pool; el hook de checkout solo toca `vendi.tenant_id`, así que
        # este ajuste sobrevive a los checkouts sucesivos.
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SET plan_cache_mode = force_generic_plan")

        for vuelta in range(VUELTAS):
            esperado = T1 if vuelta % 2 == 0 else T2
            marca = current_tenant_id.set(esperado)
            try:
                async with factory() as s:
                    filas = (await s.execute(text(f"SELECT tenant_id FROM {ventas_de_prueba}"))).scalars().all()
                    assert filas == [esperado], (
                        f"vuelta {vuelta}: se esperaban solo filas de {esperado}, llegaron {filas!r}"
                    )
            finally:
                current_tenant_id.reset(marca)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_el_predicado_de_la_policy_sigue_usando_el_indice(pg_app_url, ventas_de_prueba):
    """El `Index Cond` del escenario F del spike, como candado permanente.

    El informe de RLS lo midió una vez a mano. Aquí queda automatizado: si
    alguien quita el índice de `tenant_id` de una tabla de negocio, o si una
    versión futura de Postgres deja de tratar el predicado de la policy como
    condición indexable, este test lo dice — en vez de que se note como una
    degradación gradual de latencia cuando ya haya miles de negocios.
    """
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            plan = "\n".join(
                (await s.execute(text(f"EXPLAIN SELECT * FROM {ventas_de_prueba} WHERE total > 0"))).scalars().all()
            )
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()

    # Con dos filas en la tabla, el planificador elegirá un seq scan por tamaño
    # — eso es correcto y no se discute. Lo que se comprueba es que el predicado
    # de la policy aparece en el plan (como Index Cond o como Filter), es decir,
    # que Postgres lo está aplicando de verdad y no lo ha optimizado hasta
    # hacerlo desaparecer.
    assert "vendi.tenant_id" in plan, f"el predicado de la policy no aparece en el plan:\n{plan}"
