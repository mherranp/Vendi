# Poner Vendi en marcha en una máquina limpia

Objetivo: de un `git clone` a **iniciar sesión con passkey en la consola del
negocio**. Debería llevar entre 20 y 40 minutos, casi todo esperando a que
Docker descargue imágenes.

Esta guía es la prueba de fuego de la fundación: **cada desvío que tengas que
inventar es un defecto**, no una particularidad de tu máquina. Si algo no
funciona siguiendo estos pasos al pie de la letra, abre una incidencia con el
paso exacto y la salida real.

Sistema de referencia: macOS con Docker Desktop. En Linux cambian solo los
gestores de paquetes y el procedimiento de DNS, que se señala donde toca.

---

## 0. Lo que tienes que tener antes de empezar

| Herramienta | Para qué | Comprobación |
|---|---|---|
| Docker + `docker compose` | todo el stack | `docker info` |
| Node 22 | el frontend | `node --version` |
| Python 3.12 | el backend | `python3 --version` |
| [`uv`](https://docs.astral.sh/uv/) | dependencias del backend | `uv --version` |
| [`mkcert`](https://github.com/FiloSottile/mkcert) | certificados TLS de confianza | `mkcert -version` |
| `dnsmasq` (macOS, por Homebrew) | resolver `*.vendi.co` a tu máquina | `brew list dnsmasq` |

En macOS: `brew install node python@3.12 uv mkcert dnsmasq`.

**Vas a necesitar `sudo` dos veces**, las dos en el paso 2 (DNS). No hay forma
de evitarlo: escribir en `/etc/resolver/` y arrancar un servicio del sistema son
operaciones privilegiadas. Todo lo demás corre sin privilegios.

---

## 1. Clonar y configurar

```bash
git clone <url-del-repositorio> vendi
cd vendi/software
cp .env.example .env
```

Abre `.env` y **cambia todas las contraseñas**. Las del ejemplo llevan el
prefijo `cambiar_` a propósito: `verify-setup.sh` (check 17) falla si las
encuentra con `APP_ENV=production`.

Dos valores tienen que ser **distintos entre sí**: `VENDI_BACKEND_CLIENT_SECRET`
y `VENDI_PROVISIONING_CLIENT_SECRET`. Son dos credenciales de Keycloak con
privilegios distintos a propósito (ver `docs/deuda-tecnica.md`, D-02); ponerles
el mismo valor las convierte en una sola y anula la separación.

Referencia completa de variables: [`docs/env-reference.md`](env-reference.md).

---

## 2. DNS y certificados — el paso que necesita `sudo`

> ⚠️ **Léelo antes de ejecutarlo.** `vendi.co` es un dominio **real y
> registrado por un tercero**. Hasta que termines este paso, cada
> `https://accounts.vendi.co` que hagas sale a Internet, a un servidor que no es
> nuestro y que presenta un certificado válido — así que nada te avisa. El
> detalle completo está en
> [`docs/runbooks/dns-y-tls-local.md`](runbooks/dns-y-tls-local.md).

```bash
./scripts/setup-dnsmasq.sh     # pedirá sudo: escribe /etc/resolver/vendi.co
mkcert -install                # instala la CA local en el almacén del sistema
./scripts/setup-certs.sh       # emite infra/certs/vendi.co{,-key}.pem
```

Comprueba que el DNS quedó bien **antes de seguir**:

```bash
dscacheutil -q host -a name api.vendi.co        # macOS
getent hosts api.vendi.co                       # Linux
```

Tiene que decir `127.0.0.1`. Si dice `64.190.63.222`, el resolver no está
puesto: repite el paso A del runbook. **No sigas** hasta que resuelva a
loopback.

En Linux no hay `/etc/resolver/`: añade las entradas a `/etc/hosts`
(`vendi.co`, `api.`, `accounts.`, `app.`, `admin.`, `grafana.`, `mail.`) o
configura tu `dnsmasq` del sistema.

---

## 3. Levantar el stack

```bash
./scripts/dev.sh
```

Construye las imágenes de `api`, `worker` y las tres SPAs (`portal`, `tenant`,
`admin`) y levanta los quince contenedores. La primera vez tarda: descarga
PostgreSQL 17, Keycloak 26.6.4, RabbitMQ, MinIO, Redis, Traefik, Prometheus y
Grafana, y compila Angular tres veces dentro de Docker.

> Si te saltaste el paso 2, `dev.sh` **se niega a arrancar** con
> «resolución insegura de `*.vendi.co`: apunta a Internet, no a esta máquina».
> No es un fallo del script: es el guarda haciendo su trabajo. Vuelve al paso 2.

Cuando termine:

```bash
bash scripts/migrate.sh        # aplica las migraciones con el rol vendi_platform
bash scripts/seed.sh           # crea el negocio de demostración y sus usuarios
```

`seed.sh` necesita `SEED_ADMIN_PASSWORD` y `SEED_DUENO_PASSWORD` en el `.env`.
No tienen valor por defecto a propósito: una contraseña por defecto en un script
de siembra acaba siendo una contraseña en producción.

---

## 4. Verificar

```bash
bash scripts/verify-setup.sh
```

Son 27 comprobaciones. **Todas tienen que salir en verde** salvo la 17, que se
omite fuera de producción y lo dice. Si la 11b o la 11c fallan, es el DNS del
paso 2: vuelve allí.

El resumen final distingue fallos de omisiones, y el código de salida es 0 solo
si no hubo ningún fallo.

---

## 5. Entrar

Las tres aplicaciones web se sirven **por su dominio, a través de Traefik**,
igual que en producción:

| App | URL |
|---|---|
| `vendi-portal` | `https://vendi.co` (y `https://www.vendi.co`) |
| `vendi-tenant` | `https://app.vendi.co` |
| `vendi-admin` | `https://admin.vendi.co` |

Para iterar en el código Angular con recarga en caliente sigue existiendo
`ng serve` (`cd frontend && npm ci && npm run start:tenant`, puerto 4202),
pero **no vale para verificar nada que toque Keycloak o la API**: eso se
prueba siempre por el dominio (véase `frontend/README.md`). Tras cambiar
código, reconstruye la imagen: `docker compose ... build tenant && docker
compose ... up -d tenant`.

Usuarios que dejó la siembra:

| Usuario | Contraseña | Dónde entra |
|---|---|---|
| `dueno@demo.vendi.co` | `SEED_DUENO_PASSWORD` de tu `.env` | consola del negocio |
| `admin@vendi.co` | `SEED_ADMIN_PASSWORD` de tu `.env` | consola de plataforma (`npm run start:admin`) |

El login es **identity-first**: primero el usuario, después la credencial. En la
segunda pantalla verás la contraseña; la passkey está detrás de «Pruebe de otra
manera» (es deuda conocida de la pista de frontend).

### Registrar una passkey

1. Entra con contraseña en `https://app.vendi.co`.
2. Ve a `https://accounts.vendi.co/realms/vendi-co/account/#/security/signingin`.
3. «Passkey» → «Configurar». Tu llavero o llave de seguridad hará el resto.
4. Cierra sesión y vuelve a entrar: ahora la passkey es la credencial por
   defecto.

---

## 6. Los tests

```bash
cd backend
uv sync --all-extras
uv run pytest -q -m 'not integration'    # rápidos, sin stack
uv run pytest -q                         # todos, exige el stack levantado
```

Los marcados `integration` hablan con el PostgreSQL, el RabbitMQ y el Keycloak
del compose, y con la API **por su dominio**. No se omiten si el stack no está:
fallan, y con un mensaje que dice qué falta. Un test que desaparece del recuento
no prueba nada.

Frontend:

```bash
cd frontend
npm run build:libs && npx ng test --watch=false
npm run e2e                               # Playwright, exige el stack
```

---

## Cuando algo falla

| Síntoma | Causa casi siempre | Arreglo |
|---|---|---|
| `curl` a `*.vendi.co` devuelve 436 o un HTML raro | falta el resolver; estás hablando con Internet | paso 2 |
| El navegador avisa del certificado | falta `mkcert -install` | paso 2 |
| `verify-setup.sh` 11b/11c en rojo | ídem | paso 2 |
| `seed.sh`: «Falta SEED_ADMIN_PASSWORD» | el `.env` no las tiene | paso 1 |
| La API responde 401 con un token recién obtenido | el token no lleva `aud=vendi-backend` | `RECONCILE_APLICAR_CONFIG=1 bash scripts/reconcile-keycloak.sh` |
| «Account is not fully set up» al entrar | al usuario le faltan nombre y apellido | créalo con `firstName` y `lastName` |
| Cambiaste el realm JSON y no se aplica | `--import-realm` no reimporta un realm existente | `bash scripts/reconcile-keycloak.sh` para ver la deriva |

Puertos ocupados, contenedores zombi, o quieres empezar de cero:

```bash
docker compose -f infra/docker-compose.yml -f infra/docker-compose.override.dev.yml down -v
```

`-v` borra los volúmenes: se van la base de datos **y el realm de Keycloak**.
Tras eso hay que repetir `dev.sh`, `migrate.sh` y `seed.sh`.
