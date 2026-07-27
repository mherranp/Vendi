"""Cliente HTTP del servicio `provisioner` (cierre de D-02, ADR-027).

Desde que el aprovisionamiento vive en su propia unidad de despliegue, la API
**no tiene** la credencial de `vendi-provisioning` (`manage-realm`): las
operaciones que la necesitan —crear y borrar Organizations, la siembra del
realm— se piden a `provisioner` por HTTP interno, dentro de la red del compose,
sin pasar por el borde.

## El contrato que este cliente hace respetar

- **Timeout siempre.** Una llamada de red sin tope es un hilo de la API
  secuestrado por un provisioner colgado. El alta de un negocio es síncrona:
  si el provisioner no responde, el alta falla con 502 tipado y la
  compensación (rollback) se ejecuta — mismo contrato que cuando la llamada
  era directa a Keycloak.
- **Reintentos acotados** (2 por defecto) solo ante errores de transporte y
  5xx. Los 4xx son una respuesta, no un accidente: reintentarlos es martillear
  un "no" que no va a cambiar. Las operaciones expuestas son idempotentes o
  fallan limpio (un alta repetida devuelve 409, que el llamante ya sabe
  tratar), así que reintentar no duplica efectos.
- **Correlation-id propagado** en `X-Correlation-ID`: el provisioner lo recoge
  con su `CorrelationIdMiddleware` y una línea de log de la API se cruza con
  la del provisioner y con la de Keycloak sin hacer joins mentales.
- **Errores tipados de vuelta.** El provisioner responde los errores con el
  mismo sobre que la API (`{"success": false, "code", "message"}`); aquí se
  traducen de nuevo a las excepciones de dominio, de modo que para
  `TenantService` el cambio de transporte es invisible: un 409 de Keycloak
  sigue llegando como `ConflictError`.

Los nombres de los métodos replican a propósito los de
`VendiKeycloakAprovisionamiento`: el puerto que consume `TenantService` no
cambió, cambió quién está al otro lado.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Protocol

import httpx
import structlog

from vendi_core.errors.domain import ConflictError, ExternalServiceError, NotFoundError, ValidationError
from vendi_core.tracing.context import get_correlation_id

logger = structlog.get_logger()

#: Pausa base entre reintentos; crece exponencialmente (0.2 s, 0.4 s, ...).
PAUSA_BASE_REINTENTO = 0.2


class PuertoAprovisionamiento(Protocol):
    """Lo que `TenantService` necesita del aprovisionamiento. Nada más.

    Que el puerto tenga exactamente dos métodos es la medida del alcance del
    servicio: el alta y la baja de negocios. Cualquier cosa más ancha
    (listar organizaciones, tocar miembros) pertenece a la operación —el
    reconciliador, la siembra— y no pasa por aquí.
    """

    async def create_organization(self, tenant_id: uuid.UUID, name: str) -> str: ...

    async def delete_organization(self, org_id: str) -> None: ...


class ClienteAprovisionamiento:
    """Habla con `provisioner` por HTTP interno. Implementa `PuertoAprovisionamiento`."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        reintentos: int = 2,
        cliente_http: httpx.AsyncClient | None = None,
    ):
        self._reintentos = reintentos
        # El cliente inyectado es para los tests (MockTransport); en producción
        # se crea aquí con el timeout puesto y se cierra en `aclose`.
        self._http = cliente_http or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- Núcleo: una llamada con correlación, timeout y reintentos ----------

    async def _llamar(self, metodo: str, ruta: str, **kwargs: Any) -> httpx.Response:
        cabeceras = dict(kwargs.pop("headers", {}) or {})
        correlacion = get_correlation_id()
        if correlacion:
            cabeceras["X-Correlation-ID"] = correlacion

        ultimo_error: httpx.TransportError | None = None
        for intento in range(self._reintentos + 1):
            try:
                respuesta = await self._http.request(metodo, ruta, headers=cabeceras, **kwargs)
            except httpx.TransportError as exc:
                # Red caída, DNS, conexión rechazada: transitorio por definición.
                ultimo_error = exc
                if intento < self._reintentos:
                    await asyncio.sleep(PAUSA_BASE_REINTENTO * (2**intento))
                continue
            if respuesta.status_code < 500 or intento == self._reintentos:
                return respuesta
            # 5xx del provisioner: puede ser un Keycloak reiniciándose debajo.
            logger.warning(
                "provisioner_5xx",
                ruta=ruta,
                status=respuesta.status_code,
                intento=intento + 1,
            )
            await asyncio.sleep(PAUSA_BASE_REINTENTO * (2**intento))

        raise ExternalServiceError(
            "El servicio de aprovisionamiento no responde",
            details={"ruta": ruta, "error": str(ultimo_error)},
        ) from ultimo_error

    def _traducir_error(self, respuesta: httpx.Response, operacion: str, **contexto: Any) -> Exception:
        """El sobre de error del provisioner, de vuelta a excepción de dominio."""
        try:
            cuerpo = respuesta.json()
        except ValueError:
            cuerpo = {}
        mensaje = cuerpo.get("message") or f"El provisioner respondió {respuesta.status_code} ({operacion})"
        codigo = cuerpo.get("code", "")
        detalles = {"status": respuesta.status_code, **contexto}
        if codigo == ConflictError.code or respuesta.status_code == 409:
            return ConflictError(mensaje, details=detalles)
        if codigo == NotFoundError.code or respuesta.status_code == 404:
            return NotFoundError(mensaje, details=detalles)
        if codigo == ValidationError.code or respuesta.status_code == 422:
            return ValidationError(mensaje, details=detalles)
        return ExternalServiceError(mensaje, details=detalles)

    def _exigir_ok(self, respuesta: httpx.Response, operacion: str, **contexto: Any) -> httpx.Response:
        if respuesta.status_code >= 400:
            raise self._traducir_error(respuesta, operacion, **contexto)
        return respuesta

    # --- Organizations (el puerto de `TenantService`) -----------------------

    async def create_organization(self, tenant_id: uuid.UUID, name: str) -> str:
        respuesta = self._exigir_ok(
            await self._llamar(
                "POST",
                "/interno/v1/organizaciones",
                json={"tenant_id": str(tenant_id), "nombre": name},
            ),
            "create_organization",
            tenant_id=str(tenant_id),
        )
        org_id = respuesta.json().get("kc_org_id")
        if not org_id:
            raise ExternalServiceError(
                "El provisioner creó la organización pero no devolvió su id",
                details={"tenant_id": str(tenant_id)},
            )
        return str(org_id)

    async def delete_organization(self, org_id: str) -> None:
        respuesta = await self._llamar("DELETE", f"/interno/v1/organizaciones/{org_id}")
        # Un 404 al borrar es "ya no está": idempotente, igual que el cliente
        # de Keycloak al que sustituye.
        if respuesta.status_code == 404:
            return
        self._exigir_ok(respuesta, "delete_organization", org_id=org_id)

    async def get_organization_by_alias(self, tenant_id: uuid.UUID) -> dict | None:
        respuesta = await self._llamar(
            "GET",
            "/interno/v1/organizaciones",
            params={"alias": str(tenant_id)},
        )
        if respuesta.status_code == 404:
            return None
        return dict(self._exigir_ok(respuesta, "get_organization_by_alias", tenant_id=str(tenant_id)).json())

    async def list_organizations(self, first: int = 0, max_result: int = 100) -> list[dict]:
        respuesta = self._exigir_ok(
            await self._llamar(
                "GET",
                "/interno/v1/organizaciones",
                params={"first": first, "max": max_result},
            ),
            "list_organizations",
        )
        return list(respuesta.json().get("items", []))

    async def add_member(self, org_id: str, user_id: str) -> None:
        respuesta = await self._llamar(
            "PUT",
            f"/interno/v1/organizaciones/{org_id}/miembros/{user_id}",
        )
        self._exigir_ok(respuesta, "add_member", org_id=org_id, user_id=user_id)

    async def get_user_organizations(self, user_id: str) -> list[dict]:
        respuesta = self._exigir_ok(
            await self._llamar("GET", f"/interno/v1/usuarios/{user_id}/organizaciones"),
            "get_user_organizations",
            user_id=user_id,
        )
        return list(respuesta.json().get("items", []))

    # --- Siembra (scripts/seed.sh) -------------------------------------------

    async def sembrar_realm(self) -> dict:
        """Asegura roles de permisos, roles de negocio, grupos y mapeos."""
        respuesta = self._exigir_ok(await self._llamar("POST", "/interno/v1/semilla/realm"), "sembrar_realm")
        return dict(respuesta.json())

    async def sembrar_admin_de_plataforma(self, password: str) -> dict:
        """Crea (si falta) `admin@vendi.co` con `platform:admin`. Devuelve {user_id, creado}."""
        respuesta = self._exigir_ok(
            await self._llamar("POST", "/interno/v1/semilla/admin-plataforma", json={"password": password}),
            "sembrar_admin_de_plataforma",
        )
        return dict(respuesta.json())

    async def sembrar_dueno_demo(self, tenant_id: uuid.UUID, password: str) -> dict:
        """Crea (si falta) `dueno@demo.vendi.co`, en el grupo `dueno` y miembro de la org."""
        respuesta = self._exigir_ok(
            await self._llamar(
                "POST",
                "/interno/v1/semilla/dueno-demo",
                json={"tenant_id": str(tenant_id), "password": password},
            ),
            "sembrar_dueno_demo",
            tenant_id=str(tenant_id),
        )
        return dict(respuesta.json())
