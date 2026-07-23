"""Runner de retención: hooks, concurrencia, timeout, acotado por negocio y
aislamiento de fallos entre políticas.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_retention_hook.py` y
`test_retention_concurrency.py`, portados con estas adaptaciones:

  - `_purge(s, policy, schema="public")` pasa a `_purge(s, policy, ambito=...)`
    y `_purge_tenant(slug, schema)` a `_purge_tenant(tenant_id)`: en Vendi el
    inquilino es un UUID, no un par (slug, schema).
  - la métrica pasa de `basesaas_retention_tenant_skipped_total` a
    `vendi_retention_tenant_skipped_total`.
  - BaseSaaS montaba una SQLite en memoria. Aquí se usa el Postgres del compose
    con el rol `vendi_platform`, que es el que usa el runner de verdad. No es
    purismo: los SAVEPOINT y el estado "transacción abortada" —lo que prueba
    `test_una_politica_rota_no_anula_las_siguientes`— son comportamiento de
    PostgreSQL, y sobre SQLite el test daría verde sin probar nada.

Ampliaciones propias de Vendi (la tarea 3.6 tocó este módulo y no lo cubría
nadie):
  - el acotado explícito `AND tenant_id = :tenant_id`, sin el cual una política
    de tenant borraría las filas vencidas de TODOS los negocios en la primera
    iteración;
  - la siembra y restauración de `current_tenant_id` alrededor de cada negocio;
  - el aislamiento de fallos entre políticas y la fila de auditoría que ya no
    miente.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from prometheus_client import REGISTRY
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vendi_core.retention import RetentionPolicy, RetentionRunner
from vendi_core.retention.runner import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_PER_TENANT_TIMEOUT_SEC,
    retention_tenant_skipped_counter,  # noqa: F401 — fuerza el registro de la métrica
)
from vendi_core.tenant.context import current_tenant_id

TABLA = "cacharros_de_prueba"


def _leer_omitidos(reason: str) -> float:
    valor = REGISTRY.get_sample_value("vendi_retention_tenant_skipped_total", labels={"reason": reason})
    return float(valor or 0.0)


# ---------------------------------------------------------------------------
# Sin base de datos
# ---------------------------------------------------------------------------


def test_los_valores_por_defecto_de_concurrencia_y_timeout_son_parte_del_contrato():
    assert DEFAULT_MAX_CONCURRENCY == 5
    assert DEFAULT_PER_TENANT_TIMEOUT_SEC == 120.0


def test_una_configuracion_invalida_falla_al_construir_y_no_en_produccion():
    with pytest.raises(ValueError):
        RetentionRunner(session_factory=lambda: None, max_concurrency=0)
    with pytest.raises(ValueError):
        RetentionRunner(session_factory=lambda: None, per_tenant_timeout_sec=0)


class _RunnerFalso(RetentionRunner):
    """Sustituye `_purge_tenant` por una espera determinista. Deja bajo prueba
    la orquestación (`_run_one_tenant`: semáforo, timeout, contador) sin tocar
    Postgres."""

    def __init__(self, esperas: dict[uuid.UUID, float], **kwargs):
        super().__init__(session_factory=lambda: None, **kwargs)
        self._esperas = esperas
        self.empezados: list[uuid.UUID] = []
        self.terminados: list[uuid.UUID] = []

    async def _purge_tenant(self, tenant_id: uuid.UUID) -> dict[str, int]:
        self.empezados.append(tenant_id)
        await asyncio.sleep(self._esperas[tenant_id])
        self.terminados.append(tenant_id)
        return {f"{tenant_id}.files": 1}


async def _lanzar(runner: _RunnerFalso, negocios: list[uuid.UUID]) -> dict[str, int]:
    """Reproduce el fan-out de `run_once` sin las sentencias SQL de alrededor."""
    semaforo = asyncio.Semaphore(runner._max_concurrency)

    async def _acotado(tenant_id: uuid.UUID) -> dict[str, int]:
        async with semaforo:
            return await runner._run_one_tenant(tenant_id)

    partes = await asyncio.gather(*(_acotado(t) for t in negocios))
    unido: dict[str, int] = {}
    for parte in partes:
        unido.update(parte)
    return unido


async def test_la_concurrencia_maxima_acota_los_negocios_en_vuelo():
    """10 negocios × 0,5 s con concurrencia 3 tienen que terminar muy por
    debajo de los 5 s que costaría en serie."""
    negocios = [uuid.uuid4() for _ in range(10)]
    runner = _RunnerFalso(dict.fromkeys(negocios, 0.5), max_concurrency=3, per_tenant_timeout_sec=10.0)

    inicio = time.monotonic()
    resultados = await _lanzar(runner, negocios)
    transcurrido = time.monotonic() - inicio

    assert len(resultados) == 10
    assert transcurrido < 3.5, f"se esperaba ejecución concurrente, tardó {transcurrido:.2f}s"
    assert transcurrido >= 1.5, f"se esperaban ~2s de espera, tardó {transcurrido:.2f}s"


async def test_un_negocio_lento_se_omite_y_los_demas_terminan():
    rapido_a, lento, rapido_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    runner = _RunnerFalso(
        {rapido_a: 0.05, lento: 5.0, rapido_b: 0.05},
        max_concurrency=3,
        per_tenant_timeout_sec=0.3,
    )

    antes = _leer_omitidos("timeout")
    inicio = time.monotonic()
    resultados = await _lanzar(runner, [rapido_a, lento, rapido_b])
    transcurrido = time.monotonic() - inicio

    assert transcurrido < 1.5, f"el runner esperó al negocio lento: {transcurrido:.2f}s"
    assert resultados == {f"{rapido_a}.files": 1, f"{rapido_b}.files": 1}
    assert lento in runner.empezados
    assert lento not in runner.terminados
    assert _leer_omitidos("timeout") == antes + 1


# ---------------------------------------------------------------------------
# Contra el Postgres del compose
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def cacharros(pg_platform_url: str):
    """Tabla de usar y tirar con `tenant_id` y `deleted_at`.

    Se crea y se destruye por test para que la suite sea re-entrante: correr
    `pytest` dos veces seguidas contra el mismo compose no puede depender de
    una limpieza manual.
    """
    engine = create_async_engine(pg_platform_url)
    ddl = f"""
    DROP TABLE IF EXISTS {TABLA};
    CREATE TABLE {TABLA} (
        id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id  uuid NOT NULL,
        nombre     text NOT NULL,
        deleted_at timestamptz NULL
    );
    CREATE INDEX ix_{TABLA}_tenant_id ON {TABLA} (tenant_id);
    """
    async with engine.begin() as conn:
        for sentencia in filter(None, (s.strip() for s in ddl.split(";"))):
            await conn.execute(text(sentencia))
    sf = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield sf
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {TABLA}"))
        await engine.dispose()


async def _sembrar(sf: async_sessionmaker, tenant_id: uuid.UUID, *, vencidos: int, vivos: int) -> list[uuid.UUID]:
    pasado = datetime.now(UTC) - timedelta(days=31)
    ids: list[uuid.UUID] = []
    async with sf() as s:
        for i in range(vencidos):
            fila = await s.execute(
                text(f"INSERT INTO {TABLA} (tenant_id, nombre, deleted_at) VALUES (:t, :n, :d) RETURNING id"),
                {"t": tenant_id, "n": f"vencido-{i}", "d": pasado},
            )
            ids.append(fila.scalar_one())
        for i in range(vivos):
            await s.execute(
                text(f"INSERT INTO {TABLA} (tenant_id, nombre, deleted_at) VALUES (:t, :n, NULL)"),
                {"t": tenant_id, "n": f"vivo-{i}"},
            )
        await s.commit()
    return ids


def _politica(tabla: str = TABLA, condicion: str = "deleted_at IS NOT NULL") -> RetentionPolicy:
    return RetentionPolicy(table=tabla, condition=condicion, description="prueba")


@pytest.mark.integration
async def test_el_hook_ve_las_filas_y_el_runner_las_borra(cacharros):
    vencidos = await _sembrar(cacharros, T1, vencidos=3, vivos=2)
    capturado: list[list[dict]] = []

    async def hook(session: AsyncSession, filas: list[dict]) -> None:
        capturado.append([dict(f) for f in filas])

    runner = RetentionRunner(cacharros, pre_purge_hooks={TABLA: hook})
    async with cacharros() as s:
        borradas = await runner._purge(s, _politica(), ambito="plataforma")
        await s.commit()

    assert borradas == 3
    assert len(capturado) == 1
    assert {f["id"] for f in capturado[0]} == set(vencidos)

    async with cacharros() as s:
        quedan = (await s.execute(text(f"SELECT count(*) FROM {TABLA}"))).scalar_one()
    assert quedan == 2


@pytest.mark.integration
async def test_si_el_hook_revienta_las_filas_se_quedan(cacharros):
    vencidos = await _sembrar(cacharros, T1, vencidos=3, vivos=2)

    async def hook_que_falla(session, filas):
        raise RuntimeError("el bucket no responde")

    runner = RetentionRunner(cacharros, pre_purge_hooks={TABLA: hook_que_falla})
    async with cacharros() as s:
        borradas = await runner._purge(s, _politica(), ambito="plataforma")
        await s.commit()

    assert borradas == 0
    async with cacharros() as s:
        siguen = (await s.execute(text(f"SELECT count(*) FROM {TABLA} WHERE deleted_at IS NOT NULL"))).scalar_one()
    assert siguen == len(vencidos)


@pytest.mark.integration
async def test_sin_hook_se_usa_un_delete_directo(cacharros):
    await _sembrar(cacharros, T1, vencidos=3, vivos=2)
    runner = RetentionRunner(cacharros)
    async with cacharros() as s:
        borradas = await runner._purge(s, _politica(), ambito="plataforma")
        await s.commit()
    assert borradas == 3


@pytest.mark.integration
async def test_una_politica_de_tenant_solo_borra_las_filas_de_su_negocio(cacharros):
    """El acotado explícito `AND tenant_id = :tenant_id`.

    La sesión del runner es la de plataforma y salta la policy por `BYPASSRLS`:
    sin ese `AND`, la primera iteración se llevaría las filas vencidas de TODOS
    los negocios y las demás devolverían 0. El síntoma sería un informe de
    retención con números absurdos, no un error.
    """
    await _sembrar(cacharros, T1, vencidos=3, vivos=1)
    await _sembrar(cacharros, T2, vencidos=2, vivos=1)

    runner = RetentionRunner(cacharros)
    async with cacharros() as s:
        borradas = await runner._purge(s, _politica(), ambito=str(T1), tenant_id=T1)
        await s.commit()

    assert borradas == 3
    async with cacharros() as s:
        por_negocio = dict((await s.execute(text(f"SELECT tenant_id, count(*) FROM {TABLA} GROUP BY tenant_id"))).all())
    assert por_negocio[T1] == 1  # solo el vivo
    assert por_negocio[T2] == 3  # intactas: 2 vencidas + 1 viva


@pytest.mark.integration
async def test_purge_tenant_siembra_y_restaura_el_contextvar(cacharros):
    """Los pre-purge hooks abren sus propias sesiones (el de `files` borra el
    objeto del bucket). Tienen que ver el negocio en curso, y el ContextVar
    tiene que quedar como estaba al salir, aunque el hook reviente."""
    await _sembrar(cacharros, T1, vencidos=1, vivos=0)
    visto: list[uuid.UUID | None] = []

    async def hook(session, filas):
        visto.append(current_tenant_id.get())

    runner = RetentionRunner(cacharros, pre_purge_hooks={TABLA: hook})
    # Se apunta la política de tenant a la tabla de prueba sin tocar el módulo.
    import vendi_core.retention.runner as mod_runner

    original = mod_runner.TENANT_POLICIES
    mod_runner.TENANT_POLICIES = (_politica(),)
    marca = current_tenant_id.set(None)
    try:
        parcial = await runner._purge_tenant(T1)
    finally:
        mod_runner.TENANT_POLICIES = original
        current_tenant_id.reset(marca)

    assert visto == [T1]
    assert parcial == {f"{T1}.{TABLA}": 1}
    assert current_tenant_id.get() is None, "el ContextVar se filtró a la iteración siguiente"


@pytest.mark.integration
async def test_una_politica_rota_no_anula_las_siguientes(cacharros):
    """El fallo que convertía la retención entera en un no-op silencioso.

    En PostgreSQL un error deja la transacción **abortada**: sin SAVEPOINT, la
    política siguiente falla con `current transaction is aborted`, el runner se
    lo traga y devuelve 0. Con una tabla mal escrita o aún sin migrar, el ciclo
    entero borraba cero filas y se registraba como éxito.
    """
    await _sembrar(cacharros, T1, vencidos=4, vivos=1)

    runner = RetentionRunner(cacharros)
    runner._failed_this_run = []
    rota = _politica(tabla="tabla_que_no_existe_en_ninguna_parte")

    async with cacharros() as s:
        primera = await runner._purge(s, rota, ambito="plataforma")
        segunda = await runner._purge(s, _politica(), ambito="plataforma")
        await s.commit()

    assert primera == 0
    assert segunda == 4, (
        "la política siguiente devolvió 0: la transacción quedó abortada por el "
        "fallo anterior y la retención se convirtió en un no-op silencioso"
    )
    assert runner._failed_this_run == ["plataforma.tabla_que_no_existe_en_ninguna_parte"]

    async with cacharros() as s:
        quedan = (await s.execute(text(f"SELECT count(*) FROM {TABLA}"))).scalar_one()
    assert quedan == 1


@pytest.mark.integration
async def test_una_pasada_con_una_politica_rota_se_audita_como_fallida(cacharros, pg_platform_url):
    """El ciclo ya no puede cerrarse con `status='success'` mintiendo."""
    marca = f"prueba-{uuid.uuid4().hex[:8]}"
    import vendi_core.retention.runner as mod_runner

    original_plat = mod_runner.PLATFORM_POLICIES
    original_tenant = mod_runner.TENANT_POLICIES
    mod_runner.PLATFORM_POLICIES = (_politica(tabla=f"tabla_inexistente_{marca}"),)
    mod_runner.TENANT_POLICIES = ()
    try:
        runner = RetentionRunner(cacharros, service_name=marca)
        await runner.run_once()
    finally:
        mod_runner.PLATFORM_POLICIES = original_plat
        mod_runner.TENANT_POLICIES = original_tenant

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            fila = (
                await conn.execute(
                    text("SELECT status, changes FROM audit_events WHERE service_name = :svc"),
                    {"svc": marca},
                )
            ).one()
            await conn.execute(text("DELETE FROM audit_events WHERE service_name = :svc"), {"svc": marca})
    finally:
        await engine.dispose()

    assert fila.status == "failure"
    assert fila.changes["politicas_fallidas"] == [f"plataforma.tabla_inexistente_{marca}"]


@pytest.mark.integration
async def test_una_pasada_limpia_se_audita_como_exito(cacharros, pg_platform_url):
    """El complemento del anterior: si nada falla, la fila dice éxito y lleva
    los conteos por política."""
    marca = f"prueba-{uuid.uuid4().hex[:8]}"
    await _sembrar(cacharros, T1, vencidos=2, vivos=1)
    import vendi_core.retention.runner as mod_runner

    original_plat = mod_runner.PLATFORM_POLICIES
    original_tenant = mod_runner.TENANT_POLICIES
    mod_runner.PLATFORM_POLICIES = (_politica(),)
    mod_runner.TENANT_POLICIES = ()
    try:
        runner = RetentionRunner(cacharros, service_name=marca)
        resultados = await runner.run_once()
    finally:
        mod_runner.PLATFORM_POLICIES = original_plat
        mod_runner.TENANT_POLICIES = original_tenant

    assert resultados == {f"plataforma.{TABLA}": 2}

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.begin() as conn:
            fila = (
                await conn.execute(
                    text("SELECT status, changes FROM audit_events WHERE service_name = :svc"),
                    {"svc": marca},
                )
            ).one()
            await conn.execute(text("DELETE FROM audit_events WHERE service_name = :svc"), {"svc": marca})
    finally:
        await engine.dispose()

    assert fila.status == "success"
    assert fila.changes == {f"plataforma.{TABLA}": 2}


@pytest.mark.integration
async def test_sin_lista_de_negocios_no_se_aplica_ninguna_politica_de_tenant(cacharros):
    """Preferimos que no corra —y quede en el log— a que corra sin negocio y
    borre filas de toda la región."""
    await _sembrar(cacharros, T1, vencidos=3, vivos=0)
    import vendi_core.retention.runner as mod_runner

    original_plat = mod_runner.PLATFORM_POLICIES
    original_tenant = mod_runner.TENANT_POLICIES
    mod_runner.PLATFORM_POLICIES = ()
    mod_runner.TENANT_POLICIES = (_politica(),)
    try:
        runner = RetentionRunner(cacharros, service_name=f"prueba-{uuid.uuid4().hex[:8]}", list_active_tenant_ids=None)
        resultados = await runner.run_once()
    finally:
        mod_runner.PLATFORM_POLICIES = original_plat
        mod_runner.TENANT_POLICIES = original_tenant

    assert resultados == {}
    async with cacharros() as s:
        quedan = (await s.execute(text(f"SELECT count(*) FROM {TABLA}"))).scalar_one()
    assert quedan == 3
