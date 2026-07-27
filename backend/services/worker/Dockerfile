# Imagen del worker de Vendi. Mismo contexto de build que la API (`backend/`)
# y las mismas razones: es un workspace uv con un único lockfile.
FROM python:3.12-slim AS base

RUN pip install --no-cache-dir uv

WORKDIR /src

COPY pyproject.toml uv.lock .python-version ./
COPY libs/ libs/
COPY services/api/pyproject.toml services/api/
COPY services/worker/pyproject.toml services/worker/
COPY services/provisioner/pyproject.toml services/provisioner/
COPY services/api/app/ services/api/app/
COPY services/worker/worker/ services/worker/worker/
COPY services/provisioner/provisioner/ services/provisioner/provisioner/

RUN uv sync --frozen --no-dev

# --- Usuario sin privilegios -------------------------------------------------
# El contenedor corría como root sin necesitarlo: el worker no abre puertos ni
# escribe fuera de /src y de /tmp (ahí va el archivo de latido). Con root,
# cualquier ejecución de código
# arbitraria dentro del contenedor empieza con todos los privilegios del
# proceso, y el volumen o el montaje que se añada mañana se escribe como root.
#
# El UID/GID se fija (10001) para que un futuro volumen tenga dueño estable
# entre reconstrucciones de la imagen.
#
# El HOME sí se crea: `uv run` inicializa su caché en $HOME/.cache/uv y aborta
# con «Failed to initialize cache ... Permission denied» si no puede escribir
# ahí. Medido al arrancar el contenedor la primera vez con USER.
RUN groupadd --gid 10001 vendi \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin vendi \
 && chown -R vendi:vendi /src
ENV UV_CACHE_DIR=/home/vendi/.cache/uv
USER vendi

WORKDIR /src/services/worker

# Sin EXPOSE: el worker no sirve HTTP en Fase 0. El endpoint de métricas
# Prometheus llega con el dispatcher real (tarea 4.3).
CMD ["uv", "run", "--project", "/src", "--no-sync", "python", "-m", "worker"]
