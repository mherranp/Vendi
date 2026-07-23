"""Planificador de trabajos: timeout, reintentos, backoff y siembra del tenant.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_job_timeout_retry.py`,
portado con dos adaptaciones y una ampliación.

Adaptaciones:
  - `_run_one` recibía el par (slug del inquilino, schema del inquilino) y ahora
    recibe `tenant_id=...`: en Vendi el inquilino es un UUID que gobierna el GUC
    de RLS, no un schema de Postgres.
  - la métrica pasa de `basesaas_job_failed_total` a `vendi_job_failed_total`.

Ampliación (lo que BaseSaaS no podía tener, porque aislaba por schema): los
cuatro tests de `## Siembra del ContextVar`. Son la razón por la que este
archivo es obligatorio y no un extra: `jobs/scheduler.py` se modificó en la
tarea 3.6 precisamente para sembrar `current_tenant_id` por negocio, y esa
siembra no la ejercía ni una línea de la suite.

No hace falta Postgres: se sustituye el escritor de auditoría por un doble.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from prometheus_client import REGISTRY

from vendi_core.jobs import JobContext, JobScheduler, ScheduledJob
from vendi_core.tenant.context import current_tenant_id


def _leer_fallos(job: str, reason: str) -> float:
    v = REGISTRY.get_sample_value("vendi_job_failed_total", labels={"job": job, "reason": reason})
    return float(v or 0.0)


class _Auditoria:
    """Captura las llamadas a `_write_audit` para inspeccionar estado y error."""

    def __init__(self) -> None:
        self.filas: list[dict[str, Any]] = []

    async def write(self, **kwargs: Any) -> None:
        self.filas.append(kwargs)


def _construir(
    job: ScheduledJob,
    auditoria: _Auditoria,
    *,
    list_active_tenant_ids=None,
) -> JobScheduler:
    scheduler = JobScheduler(
        session_factory=lambda: None,  # nunca se usa: la auditoría va doblada
        engine=None,  # type: ignore[arg-type]
        jobs=[job],
        service_name="worker-de-prueba",
        list_active_tenant_ids=list_active_tenant_ids,
    )

    async def _write_audit_doblado(**kwargs: Any) -> None:
        await auditoria.write(**kwargs)

    scheduler._write_audit = _write_audit_doblado  # type: ignore[assignment]
    return scheduler


# ---------------------------------------------------------------------------
# Timeout, reintentos y backoff
# ---------------------------------------------------------------------------


async def test_el_timeout_cancela_el_manejador_y_registra_el_fallo():
    """Manejador de 3 s con presupuesto de 1 s: se cancela, la fila de auditoría
    dice `status='failure'` / `error='timeout'` y el contador sube."""
    nombre = "prueba.timeout.duerme"

    async def _lento(ctx: JobContext):
        await asyncio.sleep(3.0)
        return {"nunca": "se llega"}

    job = ScheduledJob(name=nombre, cron="0 0 * * *", handler=_lento, timeout_sec=1)
    auditoria = _Auditoria()
    scheduler = _construir(job, auditoria)

    antes = _leer_fallos(nombre, "timeout")
    await scheduler._run_one(job, tenant_id=None)
    assert _leer_fallos(nombre, "timeout") == antes + 1

    assert len(auditoria.filas) == 1
    assert auditoria.filas[0]["status"] == "failure"
    assert auditoria.filas[0]["error"] == "timeout"


async def test_el_manejador_reintenta_y_acaba_saliendo_bien():
    """Con `max_retries=3` y un manejador que falla dos veces, el tercer intento
    sale bien: una sola fila de auditoría, en éxito, y ningún contador movido."""
    nombre = "prueba.reintento.acaba_bien"
    llamadas = {"n": 0}

    async def _inestable(ctx: JobContext):
        llamadas["n"] += 1
        if llamadas["n"] <= 2:
            raise RuntimeError(f"pum #{llamadas['n']}")
        return {"intentos_necesarios": llamadas["n"]}

    job = ScheduledJob(
        name=nombre,
        cron="0 0 * * *",
        handler=_inestable,
        max_retries=3,
        retry_backoff_sec=0,
    )
    auditoria = _Auditoria()
    scheduler = _construir(job, auditoria)

    max_retries_antes = _leer_fallos(nombre, "max_retries")
    error_antes = _leer_fallos(nombre, "error")

    await scheduler._run_one(job, tenant_id=None)

    assert llamadas["n"] == 3
    assert len(auditoria.filas) == 1
    assert auditoria.filas[0]["status"] == "success"
    assert auditoria.filas[0]["error"] == ""
    assert auditoria.filas[0]["changes"] == {"intentos_necesarios": 3}
    assert _leer_fallos(nombre, "max_retries") == max_retries_antes
    assert _leer_fallos(nombre, "error") == error_antes


async def test_agotar_los_reintentos_registra_el_motivo_max_retries():
    nombre = "prueba.reintento.siempre_falla"
    llamadas = {"n": 0}

    async def _siempre_falla(ctx: JobContext):
        llamadas["n"] += 1
        raise RuntimeError("caída persistente aguas abajo")

    job = ScheduledJob(
        name=nombre,
        cron="0 0 * * *",
        handler=_siempre_falla,
        max_retries=2,
        retry_backoff_sec=0,
    )
    auditoria = _Auditoria()
    scheduler = _construir(job, auditoria)

    antes = _leer_fallos(nombre, "max_retries")
    await scheduler._run_one(job, tenant_id=None)

    assert llamadas["n"] == 3  # el inicial + 2 reintentos
    assert len(auditoria.filas) == 1
    assert auditoria.filas[0]["status"] == "failure"
    assert auditoria.filas[0]["error"] == "max_retries"
    assert _leer_fallos(nombre, "max_retries") == antes + 1


async def test_sin_reintentos_el_fallo_conserva_el_texto_de_la_excepcion():
    """Con `max_retries=0` (el defecto) el motivo es `error` y la fila lleva el
    mensaje original, que es lo que un operador necesita leer."""
    nombre = "prueba.reintento.un_solo_disparo"

    async def _pum(ctx: JobContext):
        raise ValueError("el primero y único")

    job = ScheduledJob(name=nombre, cron="0 0 * * *", handler=_pum)
    auditoria = _Auditoria()
    scheduler = _construir(job, auditoria)

    error_antes = _leer_fallos(nombre, "error")
    max_retries_antes = _leer_fallos(nombre, "max_retries")

    await scheduler._run_one(job, tenant_id=None)

    assert auditoria.filas[0]["status"] == "failure"
    assert auditoria.filas[0]["error"] == "el primero y único"
    assert _leer_fallos(nombre, "error") == error_antes + 1
    assert _leer_fallos(nombre, "max_retries") == max_retries_antes


async def test_el_backoff_entre_intentos_es_exponencial(monkeypatch):
    """Fórmula: `retry_backoff_sec * 2**intento`. Se dobla `asyncio.sleep` del
    módulo para que el test dure microsegundos y no minutos."""
    nombre = "prueba.reintento.forma_del_backoff"
    llamadas = {"n": 0}

    async def _siempre_falla(ctx: JobContext):
        llamadas["n"] += 1
        raise RuntimeError("siempre")

    job = ScheduledJob(
        name=nombre,
        cron="0 0 * * *",
        handler=_siempre_falla,
        max_retries=3,
        retry_backoff_sec=5,
    )
    auditoria = _Auditoria()
    scheduler = _construir(job, auditoria)

    import vendi_core.jobs.scheduler as mod_sched

    esperas: list[float] = []
    sleep_real = asyncio.sleep

    async def _sleep_doblado(delay, *args, **kwargs):
        esperas.append(delay)
        await sleep_real(0)

    monkeypatch.setattr(mod_sched.asyncio, "sleep", _sleep_doblado)

    await scheduler._run_one(job, tenant_id=None)

    assert llamadas["n"] == 4  # 1 inicial + 3 reintentos
    assert esperas == [5, 10, 20]  # 5*2^0, 5*2^1, 5*2^2


# ---------------------------------------------------------------------------
# Siembra del ContextVar: lo propio de Vendi (tarea 3.6)
# ---------------------------------------------------------------------------


async def test_el_manejador_ve_el_tenant_en_el_contextvar():
    """El manejador tiene que ver el mismo `current_tenant_id` que vería un
    handler de la API: es lo que hace que sus sesiones emitan el `SET LOCAL`."""
    negocio = uuid.uuid4()
    visto: dict[str, Any] = {}

    async def _mira_el_contexto(ctx: JobContext):
        visto["contextvar"] = current_tenant_id.get()
        visto["ctx"] = ctx.tenant_id
        return None

    job = ScheduledJob(name="prueba.tenancy.ve", cron="0 0 * * *", handler=_mira_el_contexto, scope="tenant")
    scheduler = _construir(job, _Auditoria())

    await scheduler._run_one(job, tenant_id=negocio)

    assert visto["contextvar"] == negocio
    assert visto["ctx"] == negocio


async def test_el_contextvar_se_restaura_aunque_el_manejador_reviente():
    """Si no se restaurase, la iteración del siguiente negocio heredaría el
    tenant del anterior: la fuga cross-tenant más fácil de escribir sin querer
    en un worker."""
    externo = uuid.uuid4()
    marca = current_tenant_id.set(externo)
    try:

        async def _pum(ctx: JobContext):
            raise RuntimeError("pum")

        job = ScheduledJob(name="prueba.tenancy.restaura", cron="0 0 * * *", handler=_pum, scope="tenant")
        scheduler = _construir(job, _Auditoria())

        await scheduler._run_one(job, tenant_id=uuid.uuid4())

        assert current_tenant_id.get() == externo
    finally:
        current_tenant_id.reset(marca)


async def test_un_trabajo_por_negocio_dispara_una_vez_por_negocio_con_su_tenant():
    """`_fire` con scope de tenant: un disparo por negocio activo, cada uno con
    su propio ContextVar, y una fila de auditoría por negocio."""
    negocios = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    vistos: list[uuid.UUID | None] = []

    async def _anota(ctx: JobContext):
        vistos.append(current_tenant_id.get())
        return {"negocio": str(ctx.tenant_id)}

    async def _listar():
        return list(negocios)

    job = ScheduledJob(name="prueba.tenancy.itera", cron="0 0 * * *", handler=_anota, scope="tenant")
    auditoria = _Auditoria()
    scheduler = _construir(job, auditoria, list_active_tenant_ids=_listar)

    resultados = await scheduler._fire(job)

    assert vistos == negocios, "cada iteración debe ver su propio negocio, no el del anterior"
    assert [r.tenant_id for r in resultados] == negocios
    assert [f["tenant_id"] for f in auditoria.filas] == negocios


async def test_sin_lista_de_negocios_un_trabajo_por_negocio_no_dispara_para_nadie():
    """Preferimos que no corra —y se vea en el log— a que corra sin tenant y
    toque las filas de todos los negocios de la región."""
    llamadas = {"n": 0}

    async def _no_deberia(ctx: JobContext):
        llamadas["n"] += 1
        return None

    job = ScheduledJob(name="prueba.tenancy.sin_lista", cron="0 0 * * *", handler=_no_deberia, scope="tenant")
    auditoria = _Auditoria()
    scheduler = _construir(job, auditoria, list_active_tenant_ids=None)

    resultados = await scheduler._fire(job)

    assert resultados == []
    assert llamadas["n"] == 0
    assert auditoria.filas == []


async def test_un_trabajo_de_plataforma_no_siembra_ningun_tenant():
    """El complemento del anterior: con scope de plataforma el ContextVar tiene
    que quedar en `None`, no arrastrar lo que hubiera antes en el worker."""
    residuo = current_tenant_id.set(uuid.uuid4())
    try:
        visto: dict[str, Any] = {}

        async def _mira(ctx: JobContext):
            visto["contextvar"] = current_tenant_id.get()
            return None

        job = ScheduledJob(name="prueba.tenancy.plataforma", cron="0 0 * * *", handler=_mira, scope="platform")
        scheduler = _construir(job, _Auditoria())

        await scheduler._fire(job)

        assert visto["contextvar"] is None
    finally:
        current_tenant_id.reset(residuo)


async def test_run_now_rechaza_un_trabajo_desconocido():
    async def _nada(ctx: JobContext):
        return None

    job = ScheduledJob(name="prueba.existe", cron="0 0 * * *", handler=_nada)
    scheduler = _construir(job, _Auditoria())

    with pytest.raises(ValueError, match="prueba.no_existe"):
        await scheduler.run_now("prueba.no_existe")
