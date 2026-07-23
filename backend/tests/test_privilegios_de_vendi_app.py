"""Candado invertido: qué puede tocar `vendi_app`, tabla por tabla (deuda D-06).

Los candados de la Etapa 3 preguntaban «¿está `audit_events` fuera del alcance?»
—una lista de prohibidos— y por eso `alembic_version` se les escapó durante
cuatro etapas: nadie la había puesto en la lista, y el candado de cobertura RLS
solo mira tablas con columna `tenant_id`, que ésa no tiene. El QA de la Etapa 4
lo demostró con un `UPDATE version_num` que funcionó con el rol de la API.

Este test hace la pregunta al revés: recorre **todas** las tablas del esquema
`public` y exige que los privilegios de `vendi_app` sobre cada una coincidan con
lo declarado en `vendi_core.db.base`. Lo que no está declarado como tabla de
plataforma tiene que ser tabla de negocio con `tenant_id` y los cuatro
privilegios; cualquier otra combinación es un hallazgo.

Consecuencia buscada: la próxima tabla que alguien añada sin pensar en
privilegios pone esto rojo. Un candado que hay que acordarse de actualizar no es
un candado.

Requiere la base migrada (`bash scripts/migrate.sh`), como el resto de los
`integration`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.db.base import PRIVILEGIOS_DE_TABLA_DE_NEGOCIO, PRIVILEGIOS_DE_VENDI_APP, TABLAS_DE_PLATAFORMA

#: El de las dos listas corre siempre (no toca la base). Los otros dos llevan
#: `integration` uno a uno, para que el barato no desaparezca del run por
#: defecto arrastrado por el marcador del módulo.
integracion = pytest.mark.integration

CONSULTA = """
SELECT c.relname AS tabla,
       EXISTS (
           SELECT 1 FROM pg_attribute a
           WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
             AND a.attnum > 0 AND NOT a.attisdropped
       ) AS tiene_tenant_id,
       has_table_privilege('vendi_app', c.oid, 'SELECT') AS p_select,
       has_table_privilege('vendi_app', c.oid, 'INSERT') AS p_insert,
       has_table_privilege('vendi_app', c.oid, 'UPDATE') AS p_update,
       has_table_privilege('vendi_app', c.oid, 'DELETE') AS p_delete
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname
"""


async def _matriz(url: str) -> dict[str, tuple[bool, frozenset[str]]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            filas = (await conn.execute(text(CONSULTA))).all()
    finally:
        await engine.dispose()
    salida: dict[str, tuple[bool, frozenset[str]]] = {}
    for f in filas:
        concedidos = {
            nombre
            for nombre, tiene in (
                ("SELECT", f.p_select),
                ("INSERT", f.p_insert),
                ("UPDATE", f.p_update),
                ("DELETE", f.p_delete),
            )
            if tiene
        }
        salida[f.tabla] = (f.tiene_tenant_id, frozenset(concedidos))
    return salida


def test_las_dos_listas_de_tablas_de_plataforma_no_pueden_divergir():
    """Sin base de datos: `TABLAS_DE_PLATAFORMA` (la que usan los candados de
    RLS) y `PRIVILEGIOS_DE_VENDI_APP` (la de este candado) describen el mismo
    conjunto desde dos ángulos. Si una crece y la otra no, uno de los dos
    candados deja de mirar una tabla."""
    assert set(PRIVILEGIOS_DE_VENDI_APP) == set(TABLAS_DE_PLATAFORMA), (
        "las dos listas de tablas de plataforma han divergido: "
        f"solo en PRIVILEGIOS_DE_VENDI_APP {sorted(set(PRIVILEGIOS_DE_VENDI_APP) - set(TABLAS_DE_PLATAFORMA))}, "
        f"solo en TABLAS_DE_PLATAFORMA {sorted(set(TABLAS_DE_PLATAFORMA) - set(PRIVILEGIOS_DE_VENDI_APP))}"
    )


@integracion
@pytest.mark.asyncio
async def test_ninguna_tabla_concede_a_vendi_app_mas_de_lo_declarado(pg_platform_url):
    matriz = await _matriz(pg_platform_url)
    assert matriz, (
        "no hay ninguna tabla en el esquema public: o la base no está migrada "
        "(`bash scripts/migrate.sh`) o este test está mirando una base vacía y "
        "daría verde diga lo que diga."
    )

    hallazgos: list[str] = []
    for tabla, (tiene_tenant_id, concedidos) in sorted(matriz.items()):
        if tabla in PRIVILEGIOS_DE_VENDI_APP:
            esperados = PRIVILEGIOS_DE_VENDI_APP[tabla]
            if concedidos != esperados:
                hallazgos.append(
                    f"{tabla}: declarada con {sorted(esperados) or 'ningún privilegio'} "
                    f"y la base concede {sorted(concedidos) or 'ninguno'}"
                )
            continue

        if not tiene_tenant_id:
            hallazgos.append(
                f"{tabla}: no tiene `tenant_id` y no está declarada en "
                "PRIVILEGIOS_DE_VENDI_APP. Una tabla sin columna de aislamiento no "
                "puede llevar RLS: o es de plataforma (y se declara, con su porqué "
                "y su REVOKE en la migración) o le falta la columna."
            )
            continue

        if concedidos != PRIVILEGIOS_DE_TABLA_DE_NEGOCIO:
            hallazgos.append(
                f"{tabla}: tabla de negocio con privilegios {sorted(concedidos) or 'ninguno'}; "
                f"se esperaban los cuatro ({sorted(PRIVILEGIOS_DE_TABLA_DE_NEGOCIO)})."
            )

    assert not hallazgos, "Privilegios de vendi_app fuera de lo declarado:\n  - " + "\n  - ".join(hallazgos)


@integracion
@pytest.mark.asyncio
async def test_alembic_version_esta_fuera_del_alcance_de_la_api(pg_app_url):
    """El caso concreto de D-06, con el rol real y una escritura real.

    Se prueba con `UPDATE` y no con `SELECT` porque el daño de esta tabla es la
    escritura: cambiar `version_num` hace que la siguiente migración crea que el
    esquema está en otro punto del que está.
    """
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    engine = create_async_engine(pg_app_url)
    try:
        async with engine.connect() as conn:
            for sentencia in (
                "SELECT count(*) FROM alembic_version",
                "UPDATE alembic_version SET version_num = '0000'",
            ):
                with pytest.raises((DBAPIError, ProgrammingError), match="permission denied"):
                    await conn.execute(text(sentencia))
                await conn.rollback()
    finally:
        await engine.dispose()
