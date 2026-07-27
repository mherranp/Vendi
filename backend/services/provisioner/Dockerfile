# Imagen del provisioner de Vendi. Mismo contexto de build que la API y el
# worker (`backend/`, la raíz del workspace uv) y las mismas razones: un único
# lockfile compartido por todos los miembros.
FROM python:3.12-slim AS base

RUN pip install --no-cache-dir uv

WORKDIR /src

# Manifiestos primero: si no cambian, la capa de dependencias se reutiliza.
COPY pyproject.toml uv.lock .python-version ./
COPY libs/ libs/
COPY services/api/pyproject.toml services/api/
COPY services/worker/pyproject.toml services/worker/
COPY services/provisioner/pyproject.toml services/provisioner/
# Los paquetes de los miembros tienen que existir para que hatchling pueda
# construir los editables durante `uv sync`.
COPY services/api/app/ services/api/app/
COPY services/worker/worker/ services/worker/worker/
COPY services/provisioner/provisioner/ services/provisioner/provisioner/

RUN uv sync --frozen --no-dev

# --- Usuario sin privilegios -------------------------------------------------
# Mismo patrón que la API y el worker: este proceso no necesita root para nada
# (escucha en 8000, no escribe fuera de /src y /tmp), y menos aún ESTE proceso,
# que es el que custodia la credencial con manage-realm. El UID/GID se fija
# (10001) para que un futuro volumen tenga dueño estable entre reconstrucciones.
#
# El HOME sí se crea: `uv run` inicializa su caché en $HOME/.cache/uv y aborta
# con «Failed to initialize cache ... Permission denied» si no puede escribir
# ahí. Medido al arrancar el contenedor la primera vez con USER.
RUN groupadd --gid 10001 vendi \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin vendi \
 && chown -R vendi:vendi /src
ENV UV_CACHE_DIR=/home/vendi/.cache/uv
USER vendi

WORKDIR /src/services/provisioner

# El EXPOSE es documentación: el compose NO publica este puerto. Solo se
# alcanza desde la red interna (la API) y, en desarrollo, desde loopback por
# el override, para los tests de integración.
EXPOSE 8000

CMD ["uv", "run", "--project", "/src", "--no-sync", \
     "uvicorn", "provisioner.main:app", "--host", "0.0.0.0", "--port", "8000"]
