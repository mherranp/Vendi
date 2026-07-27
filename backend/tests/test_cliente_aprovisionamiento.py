"""El cliente HTTP del provisioner: timeout, reintentos, correlación y errores tipados.

Estos tests corren en seco con `httpx.MockTransport`: lo que se prueba es el
contrato del cliente (qué hace con cada respuesta y con cada fallo de red), no
el provisioner — ese lo cubren `tests/provisioner/` y los tests `integration`.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from vendi_core.errors.domain import ConflictError, ExternalServiceError, NotFoundError
from vendi_core.provisioning.cliente import ClienteAprovisionamiento
from vendi_core.tracing.context import bind_correlation_id, clear_context


def _cliente(handler, reintentos: int = 2) -> ClienteAprovisionamiento:  # noqa: ANN001
    transporte = httpx.MockTransport(handler)
    http = httpx.AsyncClient(base_url="http://provisioner:8000", transport=transporte)
    return ClienteAprovisionamiento("http://provisioner:8000", reintentos=reintentos, cliente_http=http)


@pytest.fixture(autouse=True)
def _contexto_limpio():
    clear_context()
    yield
    clear_context()


# --- Camino feliz y correlación ----------------------------------------------


async def test_crear_organizacion_devuelve_el_id_y_propaga_la_correlacion():
    peticiones: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        peticiones.append(request)
        return httpx.Response(201, json={"kc_org_id": "org-123"})

    bind_correlation_id("correlacion-de-prueba")
    cliente = _cliente(handler)
    tenant_id = uuid.uuid4()

    org_id = await cliente.create_organization(tenant_id, "Tienda de prueba")

    assert org_id == "org-123"
    assert len(peticiones) == 1
    enviada = peticiones[0]
    assert enviada.url.path == "/interno/v1/organizaciones"
    assert enviada.headers["X-Correlation-ID"] == "correlacion-de-prueba"
    assert json.loads(enviada.read()) == {"tenant_id": str(tenant_id), "nombre": "Tienda de prueba"}


async def test_borrar_organizacion_inexistente_es_idempotente():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"success": False, "message": "no está", "code": "NOT_FOUND"})

    cliente = _cliente(handler)
    await cliente.delete_organization("org-que-ya-no-esta")  # no lanza


async def test_buscar_por_alias_inexistente_devuelve_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"success": False, "message": "no está", "code": "NOT_FOUND"})

    cliente = _cliente(handler)
    assert await cliente.get_organization_by_alias(uuid.uuid4()) is None


# --- Errores tipados de vuelta -------------------------------------------------


async def test_un_conflicto_del_provisioner_vuelve_como_conflict_error():
    """El alta duplicada llega como `ConflictError`, como llegaba de Keycloak.

    Es lo que permite a `TenantService` tratar el 409 sin saber que ahora hay
    HTTP de por medio.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"success": False, "message": "ya existe", "code": "CONFLICT"})

    cliente = _cliente(handler)
    with pytest.raises(ConflictError):
        await cliente.create_organization(uuid.uuid4(), "Repetida")


async def test_un_404_al_consultar_un_recurso_vuelve_como_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"success": False, "message": "no existe", "code": "NOT_FOUND"})

    cliente = _cliente(handler)
    with pytest.raises(NotFoundError):
        await cliente.sembrar_dueno_demo(uuid.uuid4(), "clave")


async def test_un_error_del_provisioner_sin_sobre_vuelve_como_external_service():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    cliente = _cliente(handler, reintentos=0)
    with pytest.raises(ExternalServiceError):
        await cliente.list_organizations()


# --- Reintentos acotados -------------------------------------------------------


async def test_un_5xx_se_reintenta_y_el_segundo_intento_puede_ganar():
    llamadas = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal llamadas
        llamadas += 1
        if llamadas == 1:
            return httpx.Response(500, json={"success": False, "message": "boom", "code": "INTERNAL_ERROR"})
        return httpx.Response(201, json={"kc_org_id": "org-tras-reintento"})

    cliente = _cliente(handler)
    org_id = await cliente.create_organization(uuid.uuid4(), "Con un tropiezo")
    assert org_id == "org-tras-reintento"
    assert llamadas == 2


async def test_los_reintentos_tienen_tope_y_el_error_final_es_tipado():
    llamadas = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal llamadas
        llamadas += 1
        return httpx.Response(500, json={"success": False, "message": "boom", "code": "INTERNAL_ERROR"})

    cliente = _cliente(handler)
    with pytest.raises(ExternalServiceError):
        await cliente.list_organizations()
    assert llamadas == 3  # intento inicial + 2 reintentos, ni uno más


async def test_un_error_de_transporte_se_reintenta_y_acaba_en_external_service():
    llamadas = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal llamadas
        llamadas += 1
        raise httpx.ConnectError("connection refused", request=request)

    cliente = _cliente(handler)
    with pytest.raises(ExternalServiceError, match="no responde"):
        await cliente.list_organizations()
    assert llamadas == 3


async def test_un_4xx_no_se_reintenta():
    """Reintentar un "no" que no va a cambiar es martillear al provisioner."""
    llamadas = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal llamadas
        llamadas += 1
        return httpx.Response(409, json={"success": False, "message": "duplicado", "code": "CONFLICT"})

    cliente = _cliente(handler)
    with pytest.raises(ConflictError):
        await cliente.create_organization(uuid.uuid4(), "Duplicada")
    assert llamadas == 1
