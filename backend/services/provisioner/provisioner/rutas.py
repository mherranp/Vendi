"""Rutas del provisioner: la superficie ACOTADA de lo que necesita `manage-realm`.

Dos decisiones de diseño que hay que leer antes de añadir una ruta:

1. **Esto no es un proxy de la Admin API de Keycloak.** Cada ruta es una
   operación de negocio concreta (crear la Organization de un tenant, sembrar
   el realm), no un verbo genérico sobre un recurso del IdP. Un proxy genérico
   convertiría al provisioner en `manage-realm` accesible por HTTP: la misma
   credencial que D-02 sacó de la API, servida en bandeja a cualquier proceso
   de la red interna. Antes de añadir una ruta, la pregunta es «¿qué operación
   del producto la necesita?», nunca «¿qué endpoint de Keycloak falta?».

2. **La autenticación es la red.** El servicio no publica puertos (solo la red
   interna del compose; el override de desarrollo lo expone en 127.0.0.1 para
   los tests de integración) y no tiene router en Traefik. Quien pueda hablar
   con este proceso puede pedirle estas operaciones acotadas — es el riesgo
   residual documentado en ADR-027, y es deliberadamente mucho menor que el
   realm entero. No se añade un token compartido porque sería una segunda
   credencial custodiada por la API para proteger la primera: el mismo
   problema con otro nombre.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field

from provisioner import semilla
from vendi_core.auth.keycloak_aprovisionamiento import VendiKeycloakAprovisionamiento
from vendi_core.errors.domain import NotFoundError

router = APIRouter(tags=["provisioner"])


def _kc(request: Request) -> VendiKeycloakAprovisionamiento:
    return request.app.state.kc


# --- Esquemas ----------------------------------------------------------------


class CrearOrganizacion(BaseModel):
    tenant_id: uuid.UUID
    # El mismo tope que valida la API para el nombre del negocio. La
    # `description` de la Organization se recorta a 255 de todos modos, pero
    # rechazar aquí un nombre imposible es mejor que recortarlo en silencio.
    nombre: str = Field(min_length=1, max_length=120)


class SiembraConClave(BaseModel):
    password: str = Field(min_length=1)


class SiembraDueno(SiembraConClave):
    tenant_id: uuid.UUID


# --- Salud -------------------------------------------------------------------


@router.get("/health", summary="Sonda de vida")
async def health() -> dict[str, str]:
    """Responde sin tocar Keycloak: contesta ⇒ el proceso está vivo y sirviendo."""
    return {"status": "ok"}


# --- Organizations ------------------------------------------------------------


@router.post("/interno/v1/organizaciones", status_code=201)
async def crear_organizacion(cuerpo: CrearOrganizacion, request: Request) -> dict[str, str]:
    """Crea la Organization de un negocio. Un alias duplicado devuelve 409."""
    org_id = await _kc(request).create_organization(cuerpo.tenant_id, cuerpo.nombre)
    return {"kc_org_id": org_id}


@router.get("/interno/v1/organizaciones")
async def consultar_organizaciones(
    request: Request,
    alias: uuid.UUID | None = None,
    first: int = Query(default=0, ge=0),
    max: int = Query(default=100, ge=1, le=500),  # noqa: A002
) -> dict[str, Any]:
    """Por `alias` (= tenant_id) devuelve UNA organización o 404; sin él, la lista paginada."""
    kc = _kc(request)
    if alias is not None:
        org = await kc.get_organization_by_alias(alias)
        if org is None:
            raise NotFoundError(
                f"No existe organización con alias {alias}.",
                code="organizacion_no_encontrada",
            )
        return dict(org)
    return {"items": await kc.list_organizations(first=first, max_result=max)}


@router.delete("/interno/v1/organizaciones/{org_id}", status_code=204)
async def borrar_organizacion(org_id: str, request: Request) -> Response:
    """Borra la Organization. Idempotente: un 404 de Keycloak es "ya no está"."""
    await _kc(request).delete_organization(org_id)
    return Response(status_code=204)


@router.put("/interno/v1/organizaciones/{org_id}/miembros/{user_id}", status_code=204)
async def agregar_miembro(org_id: str, user_id: str, request: Request) -> Response:
    """Añade un usuario a la Organization. Idempotente."""
    await _kc(request).add_member(org_id, user_id)
    return Response(status_code=204)


@router.get("/interno/v1/usuarios/{user_id}/organizaciones")
async def organizaciones_del_usuario(user_id: str, request: Request) -> dict[str, Any]:
    """Las organizaciones de un usuario. Lo usa el reconciliador y el diagnóstico."""
    return {"items": await _kc(request).get_user_organizations(user_id)}


# --- Siembra ------------------------------------------------------------------


@router.post("/interno/v1/semilla/realm")
async def sembrar_realm(request: Request) -> dict[str, Any]:
    """Asegura permisos (roles de realm), roles de negocio, grupos y mapeos."""
    return await semilla.sembrar_realm(_kc(request))


@router.post("/interno/v1/semilla/admin-plataforma", status_code=201)
async def sembrar_admin(cuerpo: SiembraConClave, request: Request) -> dict[str, Any]:
    """Crea (si falta) `admin@vendi.co` con `platform:admin`. Usuario fijo, no parametrizable."""
    return await semilla.sembrar_admin_de_plataforma(_kc(request), cuerpo.password)


@router.post("/interno/v1/semilla/dueno-demo", status_code=201)
async def sembrar_dueno(cuerpo: SiembraDueno, request: Request) -> dict[str, Any]:
    """Crea (si falta) `dueno@demo.vendi.co` y lo mete en la Organization del tenant."""
    return await semilla.sembrar_dueno_demo(_kc(request), cuerpo.tenant_id, cuerpo.password)
