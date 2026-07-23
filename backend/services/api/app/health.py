"""Sondas de salud: `/health` (vida) y `/health/ready` (disponibilidad).

La distinción no es burocracia de Kubernetes; también la usan el healthcheck del
compose y `scripts/verify-setup.sh`:

- `/health` responde sin tocar NADA externo. Contesta ⇒ el proceso está vivo y
  sirviendo HTTP. Si esta sonda dependiera de Postgres, un Postgres caído haría
  que el orquestador matara y reiniciara la API en bucle, cuando la API no tiene
  nada que arreglar.
- `/health/ready` sí consulta las dependencias, en paralelo y con tope de
  tiempo, y devuelve 503 si alguna falla. Es la que decide si este proceso
  puede recibir tráfico.

Ambas son públicas (`RUTAS_PUBLICAS` de `TenantMiddleware`): una sonda que
necesita credenciales es una sonda que el orquestador no puede usar. Por eso
`/health/ready` no dice **por qué** falla una dependencia, solo cuál: el detalle
va al log, no a un cuerpo HTTP que cualquiera puede pedir desde fuera.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from vendi_core.auth.ssl import keycloak_ssl_verify

logger = structlog.get_logger()

router = APIRouter(tags=["salud"])

# Tope por dependencia. Corto a propósito: una sonda de disponibilidad que tarda
# más que el intervalo del orquestador deja de ser una sonda.
TIMEOUT_SONDA = 3.0


@router.get("/health", summary="Sonda de vida")
async def health() -> dict[str, str]:
    """Responde sin tocar ninguna dependencia externa."""
    return {"status": "ok"}


@router.get("/health/live", summary="Sonda de vida (alias)")
async def live() -> dict[str, str]:
    return {"status": "ok"}


async def _sondar_postgres(engine) -> None:  # noqa: ANN001
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _sondar_redis(cache) -> None:  # noqa: ANN001
    if cache is None:
        raise RuntimeError("Redis no está cableado")
    await cache.set("vendi:health:ready", "1", ttl=30)


async def _sondar_keycloak(url: str, realm: str) -> None:
    destino = f"{url}/realms/{realm}/.well-known/openid-configuration"
    async with httpx.AsyncClient(verify=keycloak_ssl_verify(), timeout=TIMEOUT_SONDA) as cliente:
        respuesta = await cliente.get(destino)
        respuesta.raise_for_status()
        if "issuer" not in respuesta.json():
            raise RuntimeError("el descubrimiento OIDC no trae 'issuer'")


@router.get("/health/ready", summary="Sonda de disponibilidad")
async def ready(request: Request, response: Response) -> dict:
    recursos = request.app.state.recursos
    settings = recursos.settings

    sondas = {
        "postgres_app": _sondar_postgres(recursos.engine_tenant),
        "postgres_plataforma": _sondar_postgres(recursos.engine_plataforma),
        "redis": _sondar_redis(recursos.redis),
        "keycloak": _sondar_keycloak(settings.keycloak_url_normalizada, settings.keycloak_realm),
    }

    async def _con_tope(corrutina):
        try:
            await asyncio.wait_for(corrutina, timeout=TIMEOUT_SONDA)
            return True, ""
        except TimeoutError:
            return False, "timeout"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    nombres = list(sondas)
    resultados = await asyncio.gather(*(_con_tope(sondas[n]) for n in nombres))

    estado: dict[str, str] = {}
    caidas: list[str] = []
    for nombre, (bien, motivo) in zip(nombres, resultados, strict=True):
        estado[nombre] = "ok" if bien else "fallo"
        if not bien:
            caidas.append(nombre)
            # El motivo va al log, no al cuerpo: la ruta es pública.
            logger.warning("health_ready_dependencia_caida", dependencia=nombre, motivo=motivo)

    if caidas:
        response.status_code = 503
        return {"status": "no_disponible", "dependencias": estado, "caidas": sorted(caidas)}
    return {"status": "listo", "dependencias": estado}
