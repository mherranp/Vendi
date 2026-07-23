"""Bases declarativas de SQLAlchemy.

Cosechado de `base_saas.db.base`. La adaptación central de Vendi está en
`TenantModel`: en BaseSaaS el aislamiento lo daba el schema (una tabla `ventas`
por cada tenant, seleccionada con `search_path`), así que el modelo **no tenía
columna de tenant**. En Vendi hay una sola tabla `ventas` para toda la región y
el aislamiento lo da Row Level Security, así que `tenant_id` es una columna
obligatoria y es lo que la policy `tenant_isolation` compara contra el GUC
`vendi.tenant_id`.
"""

import uuid
from datetime import datetime

from sqlalchemy import UUID, DateTime, Index, MetaData, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class TenantModel(TimestampMixin):
    """Mixin base de todo modelo con dueño de negocio: PK UUID + `tenant_id` + timestamps.

    `server_default` está para que un INSERT en SQL crudo pueda omitir `id` y
    dejar que Postgres lo genere. El `default` de Python se mantiene para los
    creates a nivel ORM.

    **Regla obligatoria de índice.** Toda tabla que herede de `TenantModel`
    tiene que tener un índice cuya PRIMERA columna sea `tenant_id` — solo o
    compuesto. No es una preferencia de rendimiento: el spike de RLS (escenario
    F del informe `2026-07-22-verificacion-rls.md`) midió que el planificador
    resuelve el predicado de la policy como `Index Cond`. Sin ese índice, el
    predicado degenera en un filtro post-scan y **cada consulta recorre las
    filas de todos los negocios de la región** antes de descartarlas. Con
    decenas de miles de negocios en una sola tabla eso no es lento: es
    inutilizable.

    Esta clase declara `ix_<tabla>_tenant_id` por defecto vía `__table_args__`,
    de modo que la regla se cumple sin que nadie tenga que acordarse. Una tabla
    que prefiera un índice compuesto (`(tenant_id, creado_en)`) puede
    sobrescribir `__table_args__`, y entonces la vigilan los dos candados:
    `verificar_indices_de_tenant()` sobre el metadata (unitario) y
    `test_rls_coverage.py` sobre la base real (integración).
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        # Índice por defecto que satisface la regla. `sorted` no aplica: el
        # orden de las columnas del índice es el contrato.
        return (Index(f"ix_{cls.__tablename__}_tenant_id", "tenant_id"),)


class SoftDeleteMixin:
    """Borrado lógico opcional. Las tablas que lo incluyen ganan `deleted_at`;
    los servicios lo marcan en vez de hacer `DELETE`. Las consultas de listado
    deben filtrar `deleted_at IS NULL`. El runner de retención purga físicamente
    las filas cuyo `deleted_at` supera el periodo de gracia configurado.

    Los índices únicos parciales (p. ej. `UNIQUE (nombre) WHERE deleted_at IS
    NULL`) viven en la migración de Alembic: el mixin no restringe unicidad por
    su cuenta.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


# Tablas de plataforma: existen en el mismo schema regional, tienen (o pueden
# tener) una columna `tenant_id`, y **deliberadamente no llevan RLS**. Cada
# entrada aquí es una excepción firmada, no un olvido. Los dos candados —el de
# metadata y el de base real— leen esta lista.
TABLAS_DE_PLATAFORMA: frozenset[str] = frozenset(
    {
        # Auditoría: la consola de plataforma consulta cross-tenant por
        # definición ("qué hizo el admin X en todos los negocios").
        "audit_events",
        # Outbox: el dispatcher drena la cola de todos los negocios en una
        # pasada. Con RLS vería cero filas o exigiría una transacción por
        # tenant.
        "outbox_messages",
        # Catálogo de negocios. No pertenece a ningún negocio: ES el negocio.
        # Se cablea en la tarea 4.2; se declara aquí para que el candado no
        # tenga que cambiar de manos entre etapas.
        "tenants",
        # Versión de esquema de Alembic.
        "alembic_version",
    }
)


# Privilegios que el rol de la API (`vendi_app`) DEBE tener sobre cada tabla del
# esquema regional. Es un candado **invertido**: enumera lo permitido, no lo
# prohibido.
#
# Por qué invertido (deuda D-06). El candado anterior enumeraba las tablas
# prohibidas y comprobaba que `vendi_app` no las alcanzaba. Una lista de
# prohibidos siempre se queda corta: `alembic_version` —la tabla que decide qué
# DDL se considera aplicado— nunca estuvo en ella, y `vendi_app` conservó
# SELECT/INSERT/UPDATE/DELETE sobre ella durante cuatro etapas sin que ningún
# test lo dijera. Con la lista invertida, una tabla nueva sin clasificar pone el
# test rojo aunque nadie se acuerde de tocarlo.
#
# La regla implícita para lo que NO está aquí: es tabla de negocio, tiene
# `tenant_id`, lleva RLS forzada con policy, y `vendi_app` tiene los cuatro
# privilegios (RLS es lo que la acota, no el GRANT).
PRIVILEGIOS_DE_VENDI_APP: dict[str, frozenset[str]] = {
    # Escribe la auditoría la fábrica de sesión de PLATAFORMA, a propósito y
    # fuera de la transacción del llamante. El rol de la API no la toca.
    "audit_events": frozenset(),
    # INSERT y solo INSERT: `enqueue()` escribe en la sesión del llamante para
    # que el evento y la escritura de negocio compartan transacción. No lee la
    # cola de nadie, no marca procesado, no borra. Además pasa por la policy
    # `outbox_encolado_del_tenant`.
    "outbox_messages": frozenset({"INSERT"}),
    # El catálogo de negocios: sin policy y con SELECT, cualquier handler
    # listaría todos los negocios de la región. Migración 0002.
    "tenants": frozenset(),
    # La tabla que decide qué migraciones se consideran aplicadas. Migración
    # 0003; ver la deuda D-06.
    "alembic_version": frozenset(),
}

#: Los cuatro privilegios que una tabla de negocio sí debe conceder.
PRIVILEGIOS_DE_TABLA_DE_NEGOCIO: frozenset[str] = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})


def verificar_indices_de_tenant(metadata: MetaData) -> list[str]:
    """Devuelve los nombres de las tablas que incumplen la regla del índice.

    Una tabla la incumple si tiene columna `tenant_id`, no está en
    `TABLAS_DE_PLATAFORMA`, y ningún índice suyo empieza por `tenant_id`.
    Se cuentan también los índices implícitos de una PK compuesta que empiece
    por `tenant_id`, porque Postgres crea el índice igual.

    Es el candado barato: corre sin base de datos sobre `Base.metadata` en un
    test unitario. El caro —`test_rls_coverage.py`— mira la base ya migrada y
    pilla además lo que se cree en SQL a mano dentro de una migración.
    """
    incumplen: list[str] = []
    for tabla in metadata.tables.values():
        if "tenant_id" not in tabla.columns:
            continue
        if tabla.name in TABLAS_DE_PLATAFORMA:
            continue
        candidatos = [list(idx.columns) for idx in tabla.indexes]
        if tabla.primary_key is not None:
            candidatos.append(list(tabla.primary_key.columns))
        if not any(cols and cols[0].name == "tenant_id" for cols in candidatos):
            incumplen.append(tabla.name)
    return sorted(incumplen)
