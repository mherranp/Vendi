"""Tests de unidad del `VentasService`: lo que no necesita PostgreSQL.

Hoy solo cubre el filtro del `IntegrityError` en `_resolver_sesion_caja`:
el choque de `ux_caja_sesion_abierta` (la carrera de aperturas implícitas,
ADR-021) se traduce re-leyendo la ganadora; cualquier OTRO IntegrityError es
un fallo real y debe propagarse — antes se tragaba cualquiera y se re-leía
sobre una sesión rota.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.ventas.service import VentasService


class _Resultado:
    def __init__(self, fila: object) -> None:
        self._fila = fila

    def scalar_one_or_none(self) -> object:
        return self._fila

    def scalar_one(self) -> object:
        return self._fila


class _SesionFalsa:
    """Lo mínimo que `_resolver_sesion_caja` toca de la sesión: la primera
    consulta no encuentra sesión abierta y el flush de la nueva revienta con
    el IntegrityError inyectado; la segunda consulta devuelve la ganadora."""

    def __init__(self, error: IntegrityError, ganadora: object) -> None:
        self._error = error
        self._ganadora = ganadora
        self._consultas = 0

    async def execute(self, consulta: object) -> _Resultado:
        self._consultas += 1
        return _Resultado(None if self._consultas == 1 else self._ganadora)

    def add(self, objeto: object) -> None:
        pass

    def begin_nested(self):
        @asynccontextmanager
        async def savepoint():
            yield

        return savepoint()

    async def flush(self) -> None:
        raise self._error


def _integridad(nombre_constraint: str) -> IntegrityError:
    return IntegrityError(
        "INSERT INTO caja_sesiones (tenant_id, abierta_por) VALUES (...)",
        {},
        Exception(f'duplicate key value violates unique constraint "{nombre_constraint}"'),
    )


def _servicio_con(error: IntegrityError, ganadora: object) -> VentasService:
    return VentasService(
        session=_SesionFalsa(error, ganadora),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        actor_id="cajero-prueba",
        puede_anular=True,
    )


async def test_el_choque_de_apertura_implicita_usa_la_sesion_ganadora():
    ganadora = object()
    servicio = _servicio_con(_integridad("ux_caja_sesion_abierta"), ganadora)
    assert await servicio._resolver_sesion_caja() is ganadora


async def test_otro_integrity_error_en_la_apertura_de_caja_propaga():
    servicio = _servicio_con(_integridad("fk_caja_sesiones_tenant"), object())
    with pytest.raises(IntegrityError):
        await servicio._resolver_sesion_caja()
