"""Modos de fallo de `AuditService`.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_audit_service_failure.py`
y `test_audit_pool_exhaust.py`, unificados. Adaptaciones: `base_saas` →
`vendi_core` y la métrica `basesaas_audit_write_failed_total` →
`vendi_audit_write_failed_total`.

Lo que se fija:

- modo `warn` (el defecto): un fallo de escritura registra un aviso, sube el
  contador y NO interrumpe a quien llamó;
- modo `raise`: además, la excepción se propaga;
- un valor inválido en `AUDIT_WRITE_FAILURE_MODE` cae a `warn` en vez de
  convertir una errata de despliegue en una caída;
- el agotamiento del pool de conexiones se separa del resto: log a nivel ERROR
  y etiqueta `reason="pool_exhaust"`, porque es un problema de carga que hay que
  paginar aparte de un fallo de escritura cualquiera.

La fábrica de sesión es un doble que revienta en `__aenter__`, así que no hace
falta Postgres para ejercer el camino de excepción.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.exc import TimeoutError as SATimeoutError

from vendi_core.audit import AuditEvent, AuditService
from vendi_core.audit.metrics import audit_write_failed_counter  # noqa: F401 — fuerza el registro


class _FabricaQueRevienta:
    """Fábrica de sesión cuyo gestor de contexto siempre falla al entrar.

    Corta el camino de escritura antes de cualquier trabajo del ORM, que es
    justo lo suficiente para ejercer el `except` de `_write`.
    """

    def __init__(self, exc: BaseException | None = None):
        self._exc = exc or RuntimeError("caída de base de datos simulada")

    def __call__(self):
        return self

    async def __aenter__(self):
        raise self._exc

    async def __aexit__(self, *exc):
        return False


def _leer_fallos(service_name: str, reason: str = "generic") -> float:
    valor = REGISTRY.get_sample_value(
        "vendi_audit_write_failed_total",
        labels={"service_name": service_name, "reason": reason},
    )
    return float(valor or 0.0)


@pytest.fixture
def sin_variable_de_modo(monkeypatch):
    monkeypatch.delenv("AUDIT_WRITE_FAILURE_MODE", raising=False)
    yield


async def test_el_modo_warn_sube_el_contador_y_se_traga_el_fallo(sin_variable_de_modo):
    servicio = "prueba-modo-warn"
    antes = _leer_fallos(servicio)

    svc = AuditService(_FabricaQueRevienta(), service_name=servicio)
    assert svc.failure_mode == "warn"

    # Se dobla el logger del módulo: `caplog` solo captura la stdlib y aquí el
    # logger es de structlog.
    with patch("vendi_core.audit.service.logger") as logger_doblado:
        # `log_sync` en vez de `log` para esperar la escritura de forma
        # determinista, sin depender del planificador de asyncio.
        await svc.log_sync(AuditEvent(action="usuario.crear"))

    assert _leer_fallos(servicio) == antes + 1
    assert logger_doblado.warning.called
    evento, *_ = logger_doblado.warning.call_args.args
    assert evento == "audit_write_failed"


async def test_el_modo_raise_sube_el_contador_y_relanza(sin_variable_de_modo):
    servicio = "prueba-modo-raise"
    antes = _leer_fallos(servicio)

    svc = AuditService(_FabricaQueRevienta(), service_name=servicio, failure_mode="raise")
    assert svc.failure_mode == "raise"

    with patch("vendi_core.audit.service.logger") as logger_doblado:
        with pytest.raises(RuntimeError, match="caída de base de datos simulada"):
            await svc.log_sync(AuditEvent(action="usuario.borrar"))

    assert _leer_fallos(servicio) == antes + 1
    assert logger_doblado.warning.called


def test_un_valor_invalido_del_entorno_cae_a_warn(monkeypatch):
    """Una errata en `AUDIT_WRITE_FAILURE_MODE` no puede escalar a caída."""
    monkeypatch.setenv("AUDIT_WRITE_FAILURE_MODE", "reventar-por-favor")
    svc = AuditService(_FabricaQueRevienta(), service_name="prueba-entorno-invalido")
    assert svc.failure_mode == "warn"


def test_un_valor_invalido_pasado_como_argumento_cae_a_warn(sin_variable_de_modo):
    svc = AuditService(
        _FabricaQueRevienta(),
        service_name="prueba-argumento-invalido",
        failure_mode="explotar",  # type: ignore[arg-type]
    )
    assert svc.failure_mode == "warn"


async def test_un_timeout_del_pool_escala_a_log_de_error(sin_variable_de_modo):
    """Agotar el pool es un problema de carga: log ERROR y contador propio, no
    el mismo cubo que un fallo de escritura cualquiera."""
    servicio = "prueba-pool-sa"
    antes = _leer_fallos(servicio, reason="pool_exhaust")
    generico_antes = _leer_fallos(servicio, reason="generic")

    svc = AuditService(
        _FabricaQueRevienta(SATimeoutError("QueuePool limit reached")),
        service_name=servicio,
    )

    with patch("vendi_core.audit.service.logger") as logger_doblado:
        await svc.log_sync(AuditEvent(action="usuario.crear"))

    assert _leer_fallos(servicio, reason="pool_exhaust") == antes + 1
    assert _leer_fallos(servicio, reason="generic") == generico_antes, (
        "el cubo genérico se movió: la separación no sirve"
    )
    assert logger_doblado.error.called
    evento, *_ = logger_doblado.error.call_args.args
    assert evento == "audit_write_failed"
    assert logger_doblado.error.call_args.kwargs.get("reason") == "pool_exhaust"
    assert not logger_doblado.warning.called


async def test_too_many_connections_de_asyncpg_pasa_por_la_misma_rama(sin_variable_de_modo):
    from asyncpg.exceptions import TooManyConnectionsError

    servicio = "prueba-pool-asyncpg"
    antes = _leer_fallos(servicio, reason="pool_exhaust")

    svc = AuditService(
        _FabricaQueRevienta(TooManyConnectionsError("demasiados clientes")),
        service_name=servicio,
    )
    with patch("vendi_core.audit.service.logger") as logger_doblado:
        await svc.log_sync(AuditEvent(action="usuario.crear"))

    assert _leer_fallos(servicio, reason="pool_exhaust") == antes + 1
    assert logger_doblado.error.called


async def test_el_agotamiento_del_pool_relanza_en_modo_raise(sin_variable_de_modo):
    servicio = "prueba-pool-raise"
    svc = AuditService(
        _FabricaQueRevienta(SATimeoutError("pool seco")),
        service_name=servicio,
        failure_mode="raise",
    )
    with pytest.raises(SATimeoutError):
        await svc.log_sync(AuditEvent(action="usuario.borrar"))
    assert _leer_fallos(servicio, reason="pool_exhaust") >= 1


async def test_un_fallo_generico_sigue_en_la_rama_de_aviso(sin_variable_de_modo):
    servicio = "prueba-generico"
    antes = _leer_fallos(servicio, reason="generic")
    pool_antes = _leer_fallos(servicio, reason="pool_exhaust")

    svc = AuditService(_FabricaQueRevienta(RuntimeError("deriva de esquema")), service_name=servicio)
    with patch("vendi_core.audit.service.logger") as logger_doblado:
        await svc.log_sync(AuditEvent(action="usuario.crear"))

    assert _leer_fallos(servicio, reason="generic") == antes + 1
    assert _leer_fallos(servicio, reason="pool_exhaust") == pool_antes
    assert logger_doblado.warning.called
    assert not logger_doblado.error.called


async def test_log_no_bloquea_y_el_supervisor_conserva_la_tarea(sin_variable_de_modo):
    """`log()` es fire-and-forget. Sin el conjunto supervisor, el recolector de
    basura de Python puede llevarse la tarea entre checkpoints y perder a la vez
    la escritura y el contador de fallo."""
    import asyncio

    servicio = "prueba-supervisor"
    antes = _leer_fallos(servicio)
    svc = AuditService(_FabricaQueRevienta(), service_name=servicio)

    await svc.log(AuditEvent(action="usuario.crear"))
    assert len(svc.inflight_tasks) == 1

    await asyncio.gather(*list(svc.inflight_tasks))

    assert svc.inflight_tasks == set(), "la tarea no se retiró del supervisor al terminar"
    assert _leer_fallos(servicio) == antes + 1
