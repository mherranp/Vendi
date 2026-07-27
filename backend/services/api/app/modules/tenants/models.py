"""Catálogo de negocios. Tabla de PLATAFORMA: sin RLS y fuera del alcance de la API.

`Tenant` **no** hereda `TenantModel`, y la diferencia es de fondo, no de forma:
`TenantModel` es el mixin de las tablas que PERTENECEN a un negocio y llevan la
policy `tenant_isolation`. `tenants` no pertenece a ningún negocio — *es* el
negocio. Por eso está en `vendi_core.db.base.TABLAS_DE_PLATAFORMA` y el candado
`test_rls_coverage.py` no le exige policy.

## Y por eso `vendi_app` no la alcanza en absoluto

Una tabla de plataforma sin policy y con `SELECT` para el rol de la API sería
peor que una tabla de negocio mal configurada: cualquier handler podría listar
todos los negocios de la región. La migración `0002` le hace
`REVOKE ALL ... FROM vendi_app`, igual que a `audit_events`, y el único camino
de lectura es la sesión de plataforma filtrando en Python por el `tenant_id` que
salió del token (`GET /tenants/me`). Lo vigila
`test_vendi_app_no_alcanza_las_tablas_de_plataforma`.

## El estado es de la aplicación, no del IdP

El spike de Keycloak midió que deshabilitar una Organization **no impide el
login**: solo la saca del claim y no invalida los tokens ya emitidos. Así que la
suspensión de un negocio vive aquí, en la columna `estado`, y la comprueba la
API en cada request (con cache de 60 s). Ver
`app/modules/tenants/dependencies.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import UUID, CheckConstraint, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, TimestampMixin


class EstadoTenant(StrEnum):
    """Estados de un negocio. Sin tildes ni eñes: viajan en JSON y en URLs."""

    ACTIVO = "activo"
    SUSPENDIDO = "suspendido"
    ELIMINADO = "eliminado"


#: Estados con los que se sirve tráfico. Todo lo demás corta con 403.
ESTADOS_QUE_SIRVEN: frozenset[str] = frozenset({EstadoTenant.ACTIVO})

#: Se guarda como texto y no como `ENUM` de PostgreSQL a propósito: añadir un
#: valor a un tipo enum en Postgres es DDL con sus propias reglas (no se puede
#: dentro de una transacción en versiones antiguas, no se puede quitar nunca), y
#: el conjunto es corto y estable. El `CHECK` da la misma garantía y se cambia
#: con un `ALTER ... DROP/ADD CONSTRAINT` normal.
_VALORES_DE_ESTADO = ", ".join(f"'{e.value}'" for e in EstadoTenant)


class Tenant(Base, TimestampMixin):
    """Un negocio de Vendi. El `id` es el alias de su Organization en Keycloak."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(f"estado IN ({_VALORES_DE_ESTADO})", name="ck_tenants_estado"),
        # El listado de la consola pagina por estado y fecha; sin este índice
        # ordena con un sort en memoria en cuanto haya miles de negocios.
        Index("ix_tenants_estado_created_at", "estado", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    #: Nombre legible del negocio. **No es único**: dos "Tienda Don Carlos" en
    #: la misma región son dos negocios distintos y ambos tienen derecho a
    #: existir. La identidad es el `id`. Ver la nota de
    #: `vendi_core.auth.keycloak_aprovisionamiento.VendiKeycloakAprovisionamiento.create_organization`
    #: sobre por qué el `name` de la Organization NO es este nombre.
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    estado: Mapped[str] = mapped_column(
        String(16),
        default=EstadoTenant.ACTIVO,
        server_default=EstadoTenant.ACTIVO.value,
        nullable=False,
    )
    #: Id interno de la Organization en Keycloak. Se queda a NULL cuando la
    #: organización se borra (baja del negocio): así el reconciliador distingue
    #: "nunca tuvo" de "la tenía y ya no".
    kc_org_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Borrado lógico. La fila se conserva para la auditoría y para que el `id`
    #: —que fue alias de una Organization— no se reutilice jamás.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Tenant {self.id} {self.nombre!r} {self.estado}>"
