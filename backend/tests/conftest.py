"""Fixtures compartidas de la suite del backend.

Los tests marcados `integration` necesitan el Postgres del compose levantado
(`bash scripts/dev.sh`). Los demás corren en seco.

Sobre la conexión: los tests corren en el host, no dentro de un contenedor, así
que hablan con Postgres por el puerto que el compose publica en loopback
(`127.0.0.1:5432`). Esto **no** contradice la regla de "probar siempre por el
dominio y a través de Traefik": Traefik enruta HTTP, y Postgres no habla HTTP.
Lo que sí va por el dominio es todo lo que es HTTP —Keycloak por
`https://accounts.vendi.co`, la API por `https://api.vendi.co`— y así
está escrito en los tests que los usan.

## Por qué la resolución se fija en el cliente

`vendi.co` es un dominio **real y registrado**. Un test que se limite a pedir
`https://accounts.vendi.co` no está pidiendo "el stack local": está pidiendo
"lo que sea que conteste a ese nombre". Mientras falte `/etc/resolver/vendi.co`
—un paso de anfitrión que necesita `sudo`— ese nombre resuelve a un host
público en Internet, y el `client_secret` de `vendi-provisioning` viaja en el
cuerpo de un POST hasta allí.

No es hipotético: así se entregó la rama. `pytest` producía
`405 Not Allowed ... openresty` desde `64.190.63.222`, un servidor que no es
nuestro, con un certificado DigiCert válido para ese nombre exacto. La prueba
llegaba a un tercero y seguía adelante en vez de abortar.

`fijar_resolucion_local` es el equivalente en proceso de `curl --resolve`: fija
la resolución a 127.0.0.1 sin tocar nada más. El hostname, el SNI, la cabecera
`Host`, el enrutado por `Host()` de Traefik y la validación completa del
certificado siguen siendo los reales — no se afloja nada, se quita del medio
una consulta DNS que hoy contesta un extraño.

Fijar la resolución es la mitad. La otra mitad es `exigir_stack_local`, que
comprueba **de quién es el certificado** del otro extremo antes de dejar correr
un solo test. Las dos juntas hacen imposible que una prueba pase, o casi pase,
contra un servidor ajeno: para engañarla haría falta estar en 127.0.0.1 *y*
presentar una cadena firmada por una CA que solo existe en este portátil.
"""

from __future__ import annotations

import os
import pathlib
import socket
import ssl
import urllib.parse

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2, TABLA_PRUEBA
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.auth.ssl import mkcert_ca_bundle


def _cargar_env() -> None:
    """Lee el `.env` de la raíz del repo si las variables no están ya puestas.

    Sin esto, `uv run pytest` desde `backend/` no ve las contraseñas y los tests
    de integración fallarían con un error de autenticación que parece un
    problema de Postgres y no lo es.
    """
    raiz = pathlib.Path(__file__).resolve().parents[2]
    archivo = raiz / ".env"
    if not archivo.exists():
        return
    for linea in archivo.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip())


_cargar_env()

BASE_DOMAIN = os.getenv("BASE_DOMAIN", "vendi.co")

_getaddrinfo_real = socket.getaddrinfo


def _es_del_dominio(host: object, dominio: str) -> bool:
    """¿`host` es `dominio` o un subdominio suyo?

    Acepta `bytes` además de `str`, y no es un detalle cosmético: `anyio` pasa
    el nombre por `idna2008_resolve()` antes de resolver, que devuelve **bytes**.
    Una comprobación solo-`str` deja pasar de largo exactamente el camino
    asíncrono —el que usa python-keycloak para todas sus llamadas `a_*`— y la
    fijación de resolución queda de adorno: el test sigue saliendo a Internet
    mientras el fixture aparenta haberlo atado. Se descubrió así, con
    `anyio.getaddrinfo` devolviendo 64.190.63.222 y `loop.getaddrinfo`
    devolviendo 127.0.0.1 en el mismo proceso.
    """
    if isinstance(host, bytes | bytearray):
        try:
            host = bytes(host).decode("ascii")
        except UnicodeDecodeError:
            return False
    return isinstance(host, str) and (host == dominio or host.endswith(f".{dominio}"))


@pytest.fixture
def fijar_resolucion_local(monkeypatch):
    """Equivalente en proceso de `curl --resolve <host>:443:127.0.0.1`.

    Sustituye **solo** la resolución de `*.BASE_DOMAIN` por 127.0.0.1,
    delegando en la resolución real todo lo demás. Se parchea
    `socket.getaddrinfo`, que es por donde acaban pasando tanto `requests`
    (urllib3 → `socket.create_connection`) como `httpx`/`anyio`, así que cubre
    los dos clientes que usa python-keycloak sin depender de sus internos.
    """

    def parcheado(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        if _es_del_dominio(host, BASE_DOMAIN):
            return _getaddrinfo_real("127.0.0.1", port, family, type, proto, flags)
        return _getaddrinfo_real(host, port, family, type, proto, flags)

    monkeypatch.setattr(socket, "getaddrinfo", parcheado)
    return parcheado


def identidad_del_peer(url: str) -> dict:
    """Handshake TLS real contra `url`, validando contra la CA de mkcert.

    Devuelve `{"ip", "issuer", "subject"}`. Propaga la excepción si el
    certificado no valida — que es justo la señal que interesa: significa que
    al otro lado no está nuestro stack.
    """
    partes = urllib.parse.urlparse(url)
    host = partes.hostname or ""
    puerto = partes.port or (443 if partes.scheme == "https" else 80)

    ca = mkcert_ca_bundle()
    contexto = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
    with socket.create_connection((host, puerto), timeout=8) as crudo:
        ip = crudo.getpeername()[0]
        with contexto.wrap_socket(crudo, server_hostname=host) as tls:
            cert = tls.getpeercert() or {}
    aplanar = lambda campo: {k: v for par in cert.get(campo, ()) for (k, v) in par}  # noqa: E731
    return {"ip": ip, "issuer": aplanar("issuer"), "subject": aplanar("subject")}


@pytest.fixture
def exigir_stack_local(fijar_resolucion_local):
    """Aserción de identidad del peer. Corre ANTES que cualquier credencial.

    Sin esto, una prueba de integración solo comprueba "alguien contestó en ese
    nombre". Con `vendi.co` —un TLD real— ese alguien puede ser un host de
    Internet con un certificado públicamente válido para el mismo nombre, y la
    prueba le entregaría el `client_secret` sin enterarse.

    Se exigen dos cosas a la vez, y ninguna de las dos es falsificable por un
    tercero:

    · el otro extremo está en loopback, y
    · su certificado lo firmó la CA de mkcert de ESTA máquina.

    Falla (no omite) si no se cumplen: un entorno que no puede probarse de
    forma segura es un fallo declarado, no un test que desaparece del recuento.
    """

    def _comprobar(url: str) -> dict:
        try:
            peer = identidad_del_peer(url)
        except ssl.SSLError as exc:
            pytest.fail(
                f"El certificado de {url} no valida contra la CA de mkcert ({exc}). "
                "Si esto ocurre con la resolución fijada a 127.0.0.1, el certificado del "
                "borde está mal: mkcert -install && ./scripts/setup-certs.sh && "
                "docker compose restart traefik"
            )
        except OSError as exc:
            pytest.fail(
                f"No se pudo abrir una conexión TLS con {url} ({exc}). ¿Está el stack levantado?  bash scripts/dev.sh"
            )

        if peer["ip"] not in {"127.0.0.1", "::1"}:
            pytest.fail(
                f"{url} resolvió a {peer['ip']}, que NO es esta máquina. Abortando antes "
                "de transmitir ninguna credencial: vendi.co es un dominio real y ese host "
                "es de un tercero. Ver docs/runbooks/dns-y-tls-local.md."
            )
        emisor = peer["issuer"].get("organizationName", "") + peer["issuer"].get("commonName", "")
        if "mkcert" not in emisor:
            pytest.fail(
                f"El certificado de {url} lo emitió «{emisor}», no la CA local de mkcert. "
                "Al otro lado NO está el stack de Vendi; no se le manda ninguna credencial."
            )
        return peer

    return _comprobar


PG_HOST = os.getenv("VENDI_TEST_PG_HOST", "127.0.0.1")
PG_PORT = os.getenv("VENDI_TEST_PG_PORT", "5432")
PG_DB = os.getenv("VENDI_TEST_PG_DB", "vendi")


def _dsn(rol: str, password_env: str) -> str:
    clave = os.getenv(password_env, "")
    return f"postgresql+asyncpg://{rol}:{clave}@{PG_HOST}:{PG_PORT}/{PG_DB}"


@pytest.fixture(scope="session")
def pg_app_url() -> str:
    """DSN del rol `vendi_app`: sin BYPASSRLS. Es el que usa la API."""
    return _dsn("vendi_app", "VENDI_APP_DB_PASSWORD")


@pytest.fixture(scope="session")
def pg_platform_url() -> str:
    """DSN del rol `vendi_platform`: con BYPASSRLS. Es el de Alembic y el worker."""
    return _dsn("vendi_platform", "VENDI_PLATFORM_DB_PASSWORD")


@pytest_asyncio.fixture
async def ventas_de_prueba(pg_platform_url: str):
    """Crea `ventas_de_prueba` con la policy del spike y una fila por negocio.

    Se crea y se destruye por test **a propósito**, no por sesión: la superficie
    de ataque de QA exige que la suite sea re-entrante (correr `pytest` dos
    veces seguidas contra el mismo compose sin limpiar a mano). Un `DROP TABLE
    IF EXISTS` al principio y otro al final lo garantizan aunque una corrida
    anterior se haya muerto a mitad.

    El DDL va con `vendi_platform` porque `vendi_app` no tiene `CREATE` en
    `public` — verificado en el escenario J del spike de RLS.
    """
    engine = create_async_engine(pg_platform_url, poolclass=None)
    ddl = f"""
    DROP TABLE IF EXISTS {TABLA_PRUEBA};
    CREATE TABLE {TABLA_PRUEBA} (
        id        serial PRIMARY KEY,
        tenant_id uuid NOT NULL,
        total     numeric NOT NULL DEFAULT 0
    );
    CREATE INDEX ix_{TABLA_PRUEBA}_tenant_id ON {TABLA_PRUEBA} (tenant_id);
    GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLA_PRUEBA} TO vendi_app;
    GRANT USAGE, SELECT ON SEQUENCE {TABLA_PRUEBA}_id_seq TO vendi_app;
    ALTER TABLE {TABLA_PRUEBA} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {TABLA_PRUEBA} FORCE  ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON {TABLA_PRUEBA}
      USING      (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid);
    """
    async with engine.begin() as conn:
        for sentencia in filter(None, (x.strip() for x in ddl.split(";"))):
            await conn.execute(text(sentencia))
        await conn.execute(
            text(f"INSERT INTO {TABLA_PRUEBA} (tenant_id, total) VALUES (:t, 100)"),
            {"t": T1},
        )
        await conn.execute(
            text(f"INSERT INTO {TABLA_PRUEBA} (tenant_id, total) VALUES (:t, 200)"),
            {"t": T2},
        )
    try:
        yield TABLA_PRUEBA
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {TABLA_PRUEBA}"))
        await engine.dispose()
