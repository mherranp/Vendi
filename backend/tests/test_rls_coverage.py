"""Candado: ninguna tabla de negocio puede quedarse sin RLS ni sin índice.

El tercero de los tres candados. Los otros dos prueban que RLS funciona; éste
prueba que **está puesto en todas partes**, que es el fallo que de verdad va a
ocurrir: nadie va a romper la policy de `files`, alguien va a añadir la tabla
`ventas` dentro de seis meses y se le va a olvidar la línea de `enable_rls`. Sin
este test, esa tabla sería legible por todos los negocios de la región y nada lo
diría.

Dos niveles, a propósito:

1. **Sobre el metadata** (sin base de datos, sin marcador `integration`): mira
   los modelos declarados. Corre en cada `pytest` y en cada PR, en un segundo.
2. **Sobre la base ya migrada** (marcador `integration`): mira `pg_class` y
   `pg_policy` de verdad. Es el único que pilla una tabla creada con SQL crudo
   dentro de una migración, que es justo el caso que se salta el nivel 1.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Importar los modelos los registra en `Base.metadata`. Sin estos imports el
# test pasaría porque no habría nada que revisar: el peor de los falsos verdes.
from app.modules.catalogo.models import Producto  # noqa: F401
from app.modules.ventas.models import CajaSesion, Dispositivo, MovimientoInventario, Venta, VentaItem  # noqa: F401
from vendi_core.audit.models import AuditLog  # noqa: F401
from vendi_core.db.base import (
    TABLAS_DE_PLATAFORMA,
    Base,
    verificar_indices_de_tenant,
)
from vendi_core.files.models import File  # noqa: F401
from vendi_core.messaging.outbox import OutboxMessage  # noqa: F401


def test_los_modelos_de_negocio_declaran_indice_por_tenant():
    """Nivel 1: sobre el metadata. Sin base de datos."""
    incumplen = verificar_indices_de_tenant(Base.metadata)
    assert not incumplen, (
        f"Tablas con tenant_id sin índice que empiece por tenant_id: {incumplen}. "
        "El predicado de la policy dejaría de resolverse como Index Cond y cada "
        "consulta recorrería las filas de toda la región."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_toda_tabla_de_negocio_tiene_rls_forzado_y_policy(pg_platform_url):
    """Nivel 2: sobre la base ya migrada. Requiere `bash scripts/migrate.sh`."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            filas = (
                await conn.execute(
                    text(
                        """
                        SELECT c.relname,
                               c.relrowsecurity,
                               c.relforcerowsecurity,
                               (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS n_policies
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public'
                          AND c.relkind = 'r'
                          AND EXISTS (
                              -- `pg_attribute` y NO `information_schema.columns`.
                              -- La vista del information_schema solo muestra las
                              -- columnas sobre las que el usuario que consulta
                              -- tiene algún privilegio: una tabla creada por
                              -- otro rol —un superusuario haciendo una
                              -- reparación a mano, por ejemplo— es INVISIBLE
                              -- para el candado, que daría verde sin haberla
                              -- mirado. `pg_attribute` es el catálogo crudo y no
                              -- filtra por privilegios.
                              SELECT 1 FROM pg_attribute a
                              WHERE a.attrelid = c.oid
                                AND a.attname = 'tenant_id'
                                AND a.attnum > 0
                                AND NOT a.attisdropped
                          )
                        ORDER BY c.relname
                        """
                    )
                )
            ).all()
    finally:
        await engine.dispose()

    de_negocio = [f for f in filas if f.relname not in TABLAS_DE_PLATAFORMA]
    assert de_negocio, (
        "no se encontró ninguna tabla de negocio con tenant_id. O la migración no "
        "se ha aplicado (`bash scripts/migrate.sh`), o este test está mirando una "
        "base vacía y daría verde diga lo que diga."
    )

    sin_rls = [f.relname for f in de_negocio if not (f.relrowsecurity and f.relforcerowsecurity and f.n_policies >= 1)]
    assert not sin_rls, (
        f"Tablas con tenant_id sin RLS forzado + policy: {sin_rls}. Falta `enable_rls(op, '<tabla>')` en su migración."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_toda_tabla_de_negocio_tiene_indice_que_empieza_por_tenant_id(pg_platform_url):
    """El mismo candado, sobre los índices reales de la base."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            tablas = (
                (
                    await conn.execute(
                        text(
                            """
                        -- Mismo motivo que arriba: `pg_attribute`, no
                        -- `information_schema.columns`. La vista oculta las
                        -- columnas sobre las que el usuario no tiene privilegios
                        -- y el candado dejaría de ver justo las tablas creadas
                        -- fuera del camino normal.
                        SELECT DISTINCT c.relname AS table_name
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
                        JOIN pg_attribute a ON a.attrelid = c.oid
                        WHERE c.relkind = 'r'
                          AND a.attname = 'tenant_id'
                          AND a.attnum > 0
                          AND NOT a.attisdropped
                        """
                        )
                    )
                )
                .scalars()
                .all()
            )

            sin_indice: list[str] = []
            for tabla in tablas:
                if tabla in TABLAS_DE_PLATAFORMA:
                    continue
                # `pg_index.indkey[0]` es el atributo de la PRIMERA columna del
                # índice: es el orden lo que importa, no la mera presencia de
                # tenant_id en alguna posición.
                primera_col = (
                    (
                        await conn.execute(
                            text(
                                """
                            SELECT a.attname
                            FROM pg_index i
                            JOIN pg_class c   ON c.oid = i.indrelid
                            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
                            WHERE c.relname = :tabla
                            """
                            ),
                            {"tabla": tabla},
                        )
                    )
                    .scalars()
                    .all()
                )
                if "tenant_id" not in primera_col:
                    sin_indice.append(tabla)
    finally:
        await engine.dispose()

    assert not sin_indice, (
        f"Tablas de negocio sin índice que EMPIECE por tenant_id: {sin_indice}. "
        "Un índice donde tenant_id no es la primera columna no sirve: el "
        "planificador no puede usarlo para el predicado de la policy."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vendi_app_no_alcanza_las_tablas_de_plataforma(pg_app_url):
    """Las tablas sin RLS tienen que estar fuera del alcance del rol de la API.

    Es la otra mitad de la excepción: se acepta que `audit_events` y
    `outbox_messages` no lleven policy **porque solo las toca `vendi_platform`**.
    Si `vendi_app` pudiera leerlas, la excepción dejaría de estar justificada y
    tendríamos una tabla cross-tenant al alcance del rol de la API.
    """
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    engine = create_async_engine(pg_app_url)
    try:
        async with engine.connect() as conn:
            # `tenants` entra en la lista desde la Etapa 4, y es la que más
            # duele: sin policy y con SELECT, cualquier handler podría listar
            # todos los negocios de la región —nombres, estados, ids de
            # organización—, que es exactamente el dato que el producto promete
            # no cruzar. La migración 0002 se lo revoca entero.
            for tabla in ("audit_events", "outbox_messages", "tenants"):
                with pytest.raises((DBAPIError, ProgrammingError), match="permission denied"):
                    await conn.execute(text(f"SELECT count(*) FROM {tabla}"))
                await conn.rollback()
    finally:
        await engine.dispose()
