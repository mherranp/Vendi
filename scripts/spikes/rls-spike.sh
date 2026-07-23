#!/usr/bin/env bash
# =====================================================================
# rls-spike.sh — levanta un PostgreSQL 17 efímero y ejecuta el spike de RLS.
#
# Uso:
#   bash scripts/spikes/rls-spike.sh
#
# Variables de entorno:
#   SPIKE_DOBLE_EJECUCION=0   no repite el .sql (por defecto lo ejecuta dos
#                             veces seguidas para demostrar idempotencia)
#   SPIKE_MANTENER=1          deja el contenedor vivo al terminar
#   SPIKE_PG_PORT=55433       puerto publicado en el host
#
# El script no depende de tener psql en el host: todo corre dentro del
# contenedor vía `docker exec`.
# =====================================================================
set -euo pipefail

CONT="vendi-rls-spike"
PG_IMG="postgres:17-alpine"
PG_PORT="${SPIKE_PG_PORT:-55433}"
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== Limpiando contenedor previo (si existe) =="
docker rm -f "$CONT" >/dev/null 2>&1 || true

echo "== Levantando $PG_IMG efímero en el puerto $PG_PORT =="
docker run -d --name "$CONT" \
  -e POSTGRES_PASSWORD=spike \
  -e POSTGRES_DB=postgres \
  -p "${PG_PORT}:5432" \
  "$PG_IMG" >/dev/null

echo "== Esperando a que PostgreSQL acepte conexiones =="
for _ in $(seq 1 60); do
  if docker exec "$CONT" pg_isready -U postgres -q; then break; fi
  sleep 1
done
docker exec "$CONT" pg_isready -U postgres

echo
docker exec "$CONT" psql -U postgres -tAc "SELECT version()"

# --- Primera ejecución -------------------------------------------------
echo
echo "#########################################################"
echo "##  PRIMERA EJECUCIÓN de rls-spike.sql                 ##"
echo "#########################################################"
docker exec -i "$CONT" psql -U postgres -d postgres -v ON_ERROR_STOP=0 \
  < "$AQUI/rls-spike.sql"

# --- Escenarios que exigen una conexión real como vendi_app ------------
echo
echo "#########################################################"
echo "##  rls-spike-app.sql — conexión REAL como vendi_app   ##"
echo "#########################################################"
docker exec -i -e PGPASSWORD=spike "$CONT" \
  psql -h 127.0.0.1 -U vendi_app -d postgres -v ON_ERROR_STOP=0 \
  < "$AQUI/rls-spike-app.sql"

# --- Segunda ejecución: demuestra que el .sql es re-ejecutable ---------
if [[ "${SPIKE_DOBLE_EJECUCION:-1}" == "1" ]]; then
  echo
  echo "#########################################################"
  echo "##  SEGUNDA EJECUCIÓN de rls-spike.sql (idempotencia)  ##"
  echo "##  Debe dar exactamente los mismos resultados.        ##"
  echo "#########################################################"
  docker exec -i "$CONT" psql -U postgres -d postgres -v ON_ERROR_STOP=0 \
    < "$AQUI/rls-spike.sql"
fi

echo
if [[ "${SPIKE_MANTENER:-0}" == "1" ]]; then
  echo "Contenedor '$CONT' vivo en localhost:${PG_PORT} (usuario postgres / vendi_app, clave 'spike')."
  echo "Bórralo con: docker rm -f $CONT"
else
  docker rm -f "$CONT" >/dev/null
  echo "Contenedor '$CONT' eliminado. Usa SPIKE_MANTENER=1 para conservarlo."
fi
echo "== Spike de RLS terminado =="
