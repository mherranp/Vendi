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
                    text(
                        "SELECT column_name, is_nullable, data_type FROM information_schema.columns "
                        "WHERE table_name = 'caja_movimientos' ORDER BY ordinal_position"
                    )
                )
            ).all()
            indices = (
                await conn.execute(
                    text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'caja_movimientos'")
                )
            ).all()
            checks = (
                await conn.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid = 'caja_movimientos'::regclass AND contype = 'c'"
                    )
                )
            ).all()
            checks_sesiones = (
                (
                    await conn.execute(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conrelid = 'caja_sesiones'::regclass AND contype = 'c'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            col_anulada = (
                await conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'ventas' AND column_name = 'anulada_en'"
                    )
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
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "sesion_caja_id",
        "tipo",
        "categoria",
        "monto",
        "motivo",
        "registrado_por",
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
