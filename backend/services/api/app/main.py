"""Punto de entrada de la API de Vendi.

Esqueleto de la Etapa 2: lo mínimo para que el servicio arranque en el compose
y el resto de la fundación (scripts, healthchecks, CI) tenga algo real contra
lo que verificar.

Qué NO hay aquí todavía, a propósito:

- Cadena de middlewares (correlación, cabeceras de seguridad, JWT, tenant):
  llega en la tarea 4.1, cuando `vendi-core` ya exista (Etapa 3).
- `/health/ready` con dependencias (PostgreSQL, Redis, Keycloak): también 4.1.
  Añadirlo ahora produciría un "verde falso" —no hay nada que comprobar— y
  `scripts/verify-setup.sh` lo reporta explícitamente como SKIP.
"""

from fastapi import FastAPI

app = FastAPI(
    title="Vendi API",
    version="0.1.0",
    description="API regional de Vendi. Fase 0: fundación.",
)


@app.get("/health", tags=["salud"])
async def health() -> dict[str, str]:
    """Sonda de vida: responde sin tocar ninguna dependencia externa.

    Es deliberadamente tonta. Que responda solo prueba que el proceso está
    vivo y sirviendo HTTP; la sonda con dependencias es `/health/ready` y
    llega en la Etapa 4.
    """
    return {"status": "ok"}
