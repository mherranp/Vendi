"""La sesión de tenant siembra el GUC en CADA transacción (tarea 3.3).

Este archivo es el que demuestra la decisión número 2 del informe del spike de
RLS: el `SET LOCAL` no lo emite el middleware una vez por request, lo reinstala
el evento `after_begin` de la sesión en cada transacción nueva.

El primer test es literalmente el exploit: commitea a mitad y sigue
consultando. Sin el listener devuelve cero filas **en silencio**.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from datos_de_prueba import T1, T2
from sqlalchemy import text

from vendi_core.db.engine import create_engine
from vendi_core.db.session import (
    create_platform_session_factory,
    create_session_factory,
    es_sesion_de_plataforma,
)
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_set_local_se_reemite_tras_commit(pg_app_url, ventas_de_prueba):
    """EL test de la tarea. Commit a mitad de request y seguir consultando."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            n1 = (await s.execute(text(f"SELECT count(*) FROM {ventas_de_prueba}"))).scalar()
            assert n1 == 1, "la primera consulta ya no ve las filas de T1"

            await s.commit()  # aquí muere el SET LOCAL de la transacción anterior

            n2 = (await s.execute(text(f"SELECT count(*) FROM {ventas_de_prueba}"))).scalar()
            assert n2 == 1, (
                "tras el COMMIT la sesión dejó de ver sus filas: el listener after_begin no re-emitió el SET LOCAL"
            )
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


@pytest.mark.asyncio
async def test_set_local_se_reemite_tras_rollback(pg_app_url, ventas_de_prueba):
    """La otra mitad del exploit: `rollback()` también mata el SET LOCAL."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            assert (await s.execute(text(f"SELECT count(*) FROM {ventas_de_prueba}"))).scalar() == 1
            await s.rollback()
            assert (await s.execute(text(f"SELECT count(*) FROM {ventas_de_prueba}"))).scalar() == 1, (
                "tras el ROLLBACK la sesión dejó de ver sus filas"
            )
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


@pytest.mark.asyncio
async def test_sin_tenant_cero_filas_sin_error(pg_app_url, ventas_de_prueba):
    """Fail-closed: sin tenant en el contexto, cero filas y CERO excepciones."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as s:
            assert (await s.execute(text(f"SELECT count(*) FROM {ventas_de_prueba}"))).scalar() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_platform_session_no_emite_set_local(pg_platform_url, ventas_de_prueba):
    """La fábrica de plataforma ve TODAS las filas aunque haya tenant en contexto.

    Es la comprobación de que el listener quedó acotado a la subclase de sesión
    de la fábrica de tenant y no se registró en la clase `Session` global de
    SQLAlchemy. Si se hubiera registrado global, esta sesión emitiría el
    `SET LOCAL` de T1 — que con `BYPASSRLS` daría igual para el filtrado, pero
    delataría el registro global en `current_setting`.
    """
    engine = create_engine(pg_platform_url)
    factory = create_platform_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            assert es_sesion_de_plataforma(s), "la sesión de plataforma no viene marcada"
            total = (await s.execute(text(f"SELECT count(*) FROM {ventas_de_prueba}"))).scalar()
            assert total == 2, "la sesión de plataforma no ve las filas de los dos negocios"
            guc = (await s.execute(text("SELECT current_setting('vendi.tenant_id', true)"))).scalar()
            assert guc in ("", None), (
                f"la sesión de plataforma emitió el SET LOCAL (GUC={guc!r}): el listener "
                "se registró en la clase Session global"
            )
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


@pytest.mark.asyncio
async def test_dos_tenants_concurrentes_sobre_pool_de_una_conexion(pg_app_url, ventas_de_prueba):
    """Dos "requests" simultáneos con negocios distintos sobre UNA conexión.

    `pool_size=1, max_overflow=0` fuerza que las dos corrutinas se turnen la
    misma conexión física, que es donde una fuga de GUC entre negocios sería
    visible. Cada corrutina corre en su propio contexto de `contextvars`
    (`asyncio.create_task` copia el contexto), igual que un request de Starlette.
    """
    engine = create_engine(pg_app_url, pool_size=1, max_overflow=0)
    factory = create_session_factory(engine)

    async def leer(tenant: uuid.UUID, esperado: int) -> None:
        marca = current_tenant_id.set(tenant)
        try:
            for _ in range(10):
                async with factory() as s:
                    filas = (await s.execute(text(f"SELECT tenant_id FROM {ventas_de_prueba}"))).scalars().all()
                    assert len(filas) == esperado
                    assert all(f == tenant for f in filas), f"fuga: el negocio {tenant} vio filas de otro"
                await asyncio.sleep(0)
        finally:
            current_tenant_id.reset(marca)

    try:
        await asyncio.gather(leer(T1, 1), leer(T2, 1))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_no_uuid_en_el_contextvar_falla_ruidoso(pg_app_url, ventas_de_prueba):
    """Un string en el ContextVar es un error de programación y suena como tal.

    Sin esta guarda, un string con forma de UUID ajeno se sembraría tal cual: es
    decir, saltarse el middleware sería suficiente para leer datos de otro
    negocio. Y un string que no sea UUID produciría `invalid input syntax for
    type uuid` desde el driver, abortando la transacción con un 500 sin pistas.
    """
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set("11111111-1111-1111-1111-111111111111")  # type: ignore[arg-type]
    try:
        with pytest.raises(TypeError, match="current_tenant_id debe ser uuid.UUID"):
            async with factory() as s:
                await s.execute(text(f"SELECT count(*) FROM {ventas_de_prueba}"))
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()
