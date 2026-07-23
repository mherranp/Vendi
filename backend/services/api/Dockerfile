# Imagen de la API de Vendi.
#
# El contexto de build es `backend/` (la raíz del workspace uv), no
# `services/api/`: uv necesita el pyproject y el lock de la raíz junto con
# TODOS los miembros del workspace para resolver con `--frozen`.
FROM python:3.12-slim AS base

RUN pip install --no-cache-dir uv

WORKDIR /src

# Manifiestos primero: si no cambian, la capa de dependencias se reutiliza.
COPY pyproject.toml uv.lock .python-version ./
COPY libs/ libs/
COPY services/api/pyproject.toml services/api/
COPY services/worker/pyproject.toml services/worker/
# Los paquetes de los miembros tienen que existir para que hatchling pueda
# construir los editables durante `uv sync`.
COPY services/api/app/ services/api/app/
COPY services/worker/worker/ services/worker/worker/
# Alembic: `scripts/migrate.sh` ejecuta `alembic upgrade head` dentro de esta
# imagen desde /src/services/api, así que el .ini y las revisiones tienen que
# viajar en ella. Sin esto, migrate.sh falla con "No config file 'alembic.ini'".
COPY services/api/alembic.ini services/api/
COPY services/api/alembic/ services/api/alembic/

RUN uv sync --frozen --no-dev

# --- Usuario sin privilegios -------------------------------------------------
# Los contenedores corrían como root. Ni la API ni el worker necesitan root
# para nada: no abren puertos por debajo de 1024 (la API escucha en 8000) ni
# escriben fuera de /src y /tmp. Con root, cualquier ejecución de código
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

WORKDIR /src/services/api

EXPOSE 8000

CMD ["uv", "run", "--project", "/src", "--no-sync", \
     "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
