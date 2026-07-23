#!/bin/sh
# =============================================================================
# 01-roles.sh — roles y bases de datos de Vendi.
#
# El entrypoint oficial de la imagen `postgres` ejecuta los *.sh de
# /docker-entrypoint-initdb.d con el entorno del contenedor, SOLO cuando el
# datadir está vacío (primer arranque o tras `docker compose down -v`).
#
# Lo que deja montado (decisiones del informe scripts/../verificacion-rls.md):
#
#   vendi_platform  LOGIN BYPASSRLS  — dueño del schema `public` y de las
#                   tablas. Es el DSN de Alembic y de la sesión de plataforma
#                   (worker, consola). Bajo FORCE ROW LEVEL SECURITY, un
#                   backfill hecho por cualquier rol SIN BYPASSRLS vería cero
#                   filas: por eso las migraciones corren con este.
#   vendi_app       LOGIN, sin BYPASSRLS, sin ownership, sin CREATE en
#                   `public` — es el DSN de la API. Que no pueda saltarse RLS
#                   es la garantía central del aislamiento multi-tenant.
#
#   base `vendi`    OWNER vendi_platform. Con eso vendi_platform es miembro
#                   implícito de pg_database_owner y hace DDL en `public` sin
#                   ningún ALTER SCHEMA (verificado en el spike). El
#                   ALTER SCHEMA de abajo se conserva como medida defensiva y
#                   explícita, no como requisito.
#   base `keycloak` OWNER del superusuario — la gestiona Keycloak, no Vendi.
#
# Idempotente a propósito: aunque el hook solo corra con el datadir vacío, un
# operador puede reejecutarlo a mano tras un incidente y no debe reventar.
#
# POSIX sh (la imagen alpine no trae bash). Sin `pipefail`.
# =============================================================================
set -eu

: "${VENDI_PLATFORM_DB_PASSWORD:?falta VENDI_PLATFORM_DB_PASSWORD en el entorno del contenedor postgres}"
: "${VENDI_APP_DB_PASSWORD:?falta VENDI_APP_DB_PASSWORD en el entorno del contenedor postgres}"

echo "[01-roles] creando roles vendi_platform / vendi_app y la base vendi"

# Las contraseñas se pasan como variables de psql y se citan con format(%L),
# nunca por interpolación de shell dentro del SQL: así una contraseña con
# comillas simples no rompe la sentencia (ni permite inyección).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v pw_platform="$VENDI_PLATFORM_DB_PASSWORD" \
     -v pw_app="$VENDI_APP_DB_PASSWORD" <<-'SQL'
	-- Rol de plataforma: BYPASSRLS, sin superusuario.
	SELECT format('CREATE ROLE vendi_platform LOGIN BYPASSRLS PASSWORD %L', :'pw_platform')
	 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vendi_platform')
	\gexec
	SELECT format('ALTER ROLE vendi_platform WITH LOGIN BYPASSRLS PASSWORD %L', :'pw_platform')
	\gexec

	-- Rol de la API: explícitamente NOBYPASSRLS. El atributo se reafirma en
	-- el ALTER porque un operador podría habérselo dado a mano; este script
	-- es también la forma de volver al estado correcto.
	SELECT format('CREATE ROLE vendi_app LOGIN NOBYPASSRLS PASSWORD %L', :'pw_app')
	 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vendi_app')
	\gexec
	SELECT format('ALTER ROLE vendi_app WITH LOGIN NOBYPASSRLS PASSWORD %L', :'pw_app')
	\gexec

	-- PostgreSQL no tiene CREATE DATABASE IF NOT EXISTS: se sondea pg_database.
	SELECT 'CREATE DATABASE vendi OWNER vendi_platform'
	 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'vendi')
	\gexec

	-- Base propia de Keycloak, separada de la de la aplicación.
	SELECT format('CREATE DATABASE keycloak OWNER %I', current_user)
	 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'keycloak')
	\gexec

	-- PostgreSQL da CONNECT a PUBLIC sobre toda base nueva, así que vendi_app
	-- podía abrir sesión contra la base de Keycloak (verificado: psql -U
	-- vendi_app -d keycloak conectaba). No lee nada útil ahí —no tiene
	-- privilegios sobre sus tablas—, pero es una puerta que no le hace falta:
	-- una inyección con control del DSN podría enumerar el catálogo del IdP.
	-- Se cierra a PUBLIC y se deja abierta solo para el superusuario, que es
	-- con quien se conecta Keycloak.
	REVOKE CONNECT ON DATABASE keycloak FROM PUBLIC;
	SELECT format('GRANT CONNECT ON DATABASE keycloak TO %I', current_user)
	\gexec

	-- Mismo criterio en la base de la aplicación: solo los dos roles del
	-- modelo (el GRANT explícito está más abajo) y el superusuario.
	REVOKE CONNECT ON DATABASE vendi FROM PUBLIC;
SQL

echo "[01-roles] configurando privilegios dentro de la base vendi"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname vendi <<-'SQL'
	-- Defensivo: hace la propiedad explícita e independiente del orden de
	-- creación de la base (ver decisión 7 del informe de RLS).
	ALTER SCHEMA public OWNER TO vendi_platform;

	-- Desde PG 15 PUBLIC ya no tiene CREATE sobre `public`; se revoca igual
	-- para que quede escrito y no dependa del default de la versión.
	REVOKE CREATE ON SCHEMA public FROM PUBLIC;

	-- vendi_app puede ver el schema pero no crear nada en él.
	GRANT USAGE ON SCHEMA public TO vendi_app;
	GRANT CONNECT ON DATABASE vendi TO vendi_app, vendi_platform;

	-- Privilegios por defecto: toda tabla/secuencia que cree vendi_platform
	-- (es decir, toda migración de Alembic) queda utilizable por vendi_app
	-- sin un GRANT manual por tabla. Ojo: solo aplica a objetos FUTUROS.
	ALTER DEFAULT PRIVILEGES FOR ROLE vendi_platform IN SCHEMA public
	  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vendi_app;
	ALTER DEFAULT PRIVILEGES FOR ROLE vendi_platform IN SCHEMA public
	  GRANT USAGE, SELECT ON SEQUENCES TO vendi_app;

	-- Y por si el script se reejecuta sobre una base que ya tiene tablas.
	GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO vendi_app;
	GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO vendi_app;
SQL

echo "[01-roles] listo:"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname vendi -c \
  "SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname LIKE 'vendi%' ORDER BY rolname"
