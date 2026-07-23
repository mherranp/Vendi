"""Exposición de métricas Prometheus, **con credencial**.

## Por qué `/metrics` no puede ser público

El router `api` de Traefik enruta por `Host`, no por path: todo lo que la
aplicación sirva queda publicado en `https://api.<dominio>/...`. Una exposición
de Prometheus no es un dato neutro — lleva el mapa completo de rutas internas,
los contadores de error por endpoint, el volumen de tráfico y, en cuanto haya
métricas por negocio, etiquetas con identificadores de negocio. Servirlo sin
credencial a Internet es regalar la telemetría del producto y una buena parte de
su superficie.

Estuvo en `RUTAS_PUBLICAS` de `TenantMiddleware` mientras no había endpoint que
montar. Al montarlo, se saca de ahí y pasa a `RUTAS_CON_CREDENCIAL_PROPIA`: el
middleware no le exige un JWT —el scrapper de Prometheus no es un usuario y no
tiene sesión en Keycloak— pero la ruta comprueba su propia credencial.

## Qué credencial

Un token compartido en `Authorization: Bearer <METRICS_TOKEN>`, comparado en
tiempo constante. Lo pone Prometheus vía `authorization.credentials_file`
(infra/prometheus/prometheus.yml).

**Sin `METRICS_TOKEN` configurado la ruta devuelve 503, nunca 200.** Falla
cerrado: la alternativa —"si no hay token, no pido token"— es exactamente el
modo en que estas protecciones desaparecen sin que nadie lo note, porque el
único síntoma es que todo sigue funcionando.

Defensa en profundidad, no la única: Traefik además responde 403 a
`Host(api.<dominio>) && PathPrefix(/metrics)` (router `api-metrics-bloqueado`),
de modo que la exposición no sale del perímetro aunque el token se filtre.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from vendi_core.errors.domain import AuthenticationError, DomainError

router = APIRouter(tags=["observabilidad"])


class MetricasNoConfiguradas(DomainError):
    """No hay credencial definida para `/metrics`. Se falla cerrado."""

    status_code = 503
    code = "metricas_no_configuradas"


def _credencial_del_request(request: Request) -> str:
    cabecera = request.headers.get("Authorization", "")
    if cabecera.startswith("Bearer "):
        return cabecera[7:]
    return ""


@router.get("/metrics", summary="Métricas Prometheus (requiere credencial propia)")
async def metrics(request: Request) -> Response:
    esperado: str = request.app.state.settings.metrics_token
    if not esperado:
        raise MetricasNoConfiguradas(
            "La exposición de métricas está deshabilitada porque no hay METRICS_TOKEN configurado."
        )
    if not hmac.compare_digest(_credencial_del_request(request), esperado):
        raise AuthenticationError(
            "Credencial de métricas ausente o incorrecta.",
            code="credencial_de_metricas_invalida",
        )
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
