"""Esquemas de entrada y salida del módulo `tenants`.

El contrato que consume el frontend sale de aquí vía `openapi.json`, así que
cada cambio en estos modelos es un cambio de contrato: se regenera
`docs/api/openapi-fase0.json` y con él el cliente de Angular.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.tenants.models import EstadoTenant

#: Longitud máxima del nombre. 120 y no 255 por dos motivos: es de sobra para un
#: nombre comercial, y deja margen antes del límite de `description` de Keycloak
#: (donde viaja el nombre legible de la Organization).
LARGO_MAX_NOMBRE = 120
LARGO_MIN_NOMBRE = 2


class TenantCrear(BaseModel):
    nombre: str = Field(min_length=LARGO_MIN_NOMBRE, max_length=LARGO_MAX_NOMBRE)

    @field_validator("nombre")
    @classmethod
    def _sin_espacios_sobrantes(cls, valor: str) -> str:
        limpio = " ".join(valor.split())
        if len(limpio) < LARGO_MIN_NOMBRE:
            raise ValueError(f"El nombre del negocio necesita al menos {LARGO_MIN_NOMBRE} caracteres.")
        return limpio


class TenantActualizar(BaseModel):
    """Todo opcional: es un PATCH. `None` significa "no lo toques"."""

    nombre: str | None = Field(default=None, min_length=LARGO_MIN_NOMBRE, max_length=LARGO_MAX_NOMBRE)
    estado: EstadoTenant | None = None

    @field_validator("nombre")
    @classmethod
    def _sin_espacios_sobrantes(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        limpio = " ".join(valor.split())
        if len(limpio) < LARGO_MIN_NOMBRE:
            raise ValueError(f"El nombre del negocio necesita al menos {LARGO_MIN_NOMBRE} caracteres.")
        return limpio

    @field_validator("estado")
    @classmethod
    def _no_se_elimina_por_patch(cls, valor: EstadoTenant | None) -> EstadoTenant | None:
        # Dar de baja un negocio tiene efectos en Keycloak (se borra su
        # Organization) y no puede ocurrir como efecto colateral de un PATCH que
        # el cliente creía que solo cambiaba el nombre. Para eso está DELETE.
        if valor == EstadoTenant.ELIMINADO:
            raise ValueError("Para dar de baja un negocio usa DELETE, no un cambio de estado.")
        return valor


class TenantMioSalida(BaseModel):
    """Lo mínimo para el selector de negocio: id, nombre y estado.

    Sin `kc_org_id`: es un identificador del IdP que el tendero no necesita.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    estado: EstadoTenant


class TenantSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    estado: EstadoTenant
    #: Id de la Organization en Keycloak. `null` mientras no exista (o tras la
    #: baja). Lo usa la consola para enlazar con el IdP.
    kc_org_id: str | None = None
    created_at: datetime | None = None
