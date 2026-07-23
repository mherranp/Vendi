"""Validación de JWT: realm restringido y claim `organization` polimórfico.

Los tokens se firman aquí con una clave RSA generada al vuelo y el JWKS se
sirve monkeypatcheando `_fetch_jwks`. Así el test es determinista y no depende
de que Keycloak esté arriba: lo que se prueba es la lógica del validador, no la
disponibilidad del IdP. Los tests que sí necesitan Keycloak de verdad están en
`test_keycloak_admin_orgs.py` y van por `https://accounts.vendi.co`.
"""

from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt

from vendi_core.auth.jwt import REALM_VENDI, JWTValidator, parsear_claim_organization

KC = "https://accounts.vendi.co"
ALIAS_1 = "1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e"
ALIAS_2 = "2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f"


@pytest.fixture(scope="module")
def clave():
    """Par RSA + su representación JWK, generado una vez por módulo."""
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = privada.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    numeros = privada.public_key().public_numbers()

    def b64(n: int) -> str:
        import base64

        largo = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(largo, "big")).decode().rstrip("=")

    jwk = {
        "kty": "RSA",
        "kid": "clave-de-prueba",
        "use": "sig",
        "alg": "RS256",
        "n": b64(numeros.n),
        "e": b64(numeros.e),
    }
    return pem, {"keys": [jwk]}


def _firmar(pem: str, claims: dict, kid: str = "clave-de-prueba") -> str:
    return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


def _claims(realm: str = REALM_VENDI, **extra) -> dict:
    base = {
        "iss": f"{KC}/realms/{realm}",
        "sub": "usuario-1",
        "preferred_username": "cajera1",
        "email": "cajera1@demo.vendi.co",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "realm_access": {"roles": ["dueno"]},
        "acr": "1",
    }
    base.update(extra)
    return base


@pytest.fixture
def validador(clave, monkeypatch):
    _, jwks = clave
    v = JWTValidator(KC, allowed_realms=(REALM_VENDI,))

    async def _jwks_falso(realm: str):
        return jwks

    monkeypatch.setattr(v, "_fetch_jwks", _jwks_falso)
    return v


# --- El parser del claim, aislado -------------------------------------------


def test_parser_acepta_la_lista_de_alias():
    """Forma por DEFECTO del mapper de Keycloak (`addOrganizationId=false`)."""
    assert parsear_claim_organization([ALIAS_1, ALIAS_2]) == {ALIAS_1: "", ALIAS_2: ""}


def test_parser_acepta_el_mapa_alias_a_id():
    """Forma con `addOrganizationId=true`, que es la que fija el realm como código."""
    crudo = {ALIAS_1: {"id": "org-interno-1"}, ALIAS_2: {"id": "org-interno-2"}}
    assert parsear_claim_organization(crudo) == {
        ALIAS_1: "org-interno-1",
        ALIAS_2: "org-interno-2",
    }


@pytest.mark.parametrize(
    "crudo",
    [None, "", "no-soy-una-lista", 42, {ALIAS_1: None}, {ALIAS_1: "texto"}],
)
def test_parser_no_revienta_con_basura(crudo):
    """Cualquier forma inesperada es "sin organizaciones", nunca una excepción.

    Una excepción aquí sería un 500 en el camino de autenticación de TODA la
    API, provocable por quien controle la configuración del mapper.
    """
    resultado = parsear_claim_organization(crudo)
    assert isinstance(resultado, dict)


# --- El validador -----------------------------------------------------------


@pytest.mark.asyncio
async def test_token_del_realm_master_se_rechaza(clave, validador):
    """El agujero que `allowed_realms` cierra.

    El token está bien firmado con la misma clave y su `iss` es perfectamente
    válido: lo único malo es el realm. Sin `allowed_realms`, un administrador
    del servidor de Keycloak entraría en la API de negocio.
    """
    pem, _ = clave
    token = _firmar(pem, _claims(realm="master"))
    with pytest.raises(ValueError, match="Realm no permitido"):
        await validador.validate_token(token)


@pytest.mark.asyncio
async def test_token_del_realm_vendi_se_acepta(clave, validador):
    pem, _ = clave
    token = _firmar(pem, _claims(organization=[ALIAS_1]))
    user = await validador.validate_token(token)
    assert user.realm == REALM_VENDI
    assert user.organizations == {ALIAS_1: ""}
    assert user.username == "cajera1"


@pytest.mark.asyncio
async def test_claim_organization_ausente_no_es_excepcion(clave, validador):
    """Sin claim → `organizations == {}`. Quien decide qué hacer es el middleware."""
    pem, _ = clave
    user = await validador.validate_token(_firmar(pem, _claims()))
    assert user.organizations == {}


@pytest.mark.asyncio
async def test_claim_organization_como_mapa(clave, validador):
    pem, _ = clave
    token = _firmar(pem, _claims(organization={ALIAS_1: {"id": "org-1"}}))
    user = await validador.validate_token(token)
    assert user.organizations == {ALIAS_1: "org-1"}


@pytest.mark.asyncio
async def test_token_expirado(clave, validador):
    pem, _ = clave
    token = _firmar(pem, _claims(exp=int(time.time()) - 10))
    with pytest.raises(ValueError, match="Token expirado"):
        await validador.validate_token(token)


@pytest.mark.asyncio
async def test_token_sin_kid(clave, validador):
    pem, _ = clave
    token = jose_jwt.encode(_claims(), pem, algorithm="RS256")
    with pytest.raises(ValueError, match="no trae cabecera kid"):
        await validador.validate_token(token)


@pytest.mark.asyncio
async def test_token_con_kid_desconocido(clave, validador):
    pem, _ = clave
    token = _firmar(pem, _claims(), kid="kid-que-no-existe")
    with pytest.raises(ValueError, match="No hay clave que corresponda"):
        await validador.validate_token(token)


@pytest.mark.asyncio
async def test_token_sin_aud_cuando_se_exige_audiencia(clave, monkeypatch):
    """python-jose se salta `aud` si el claim no está. El validador no."""
    pem, jwks = clave
    v = JWTValidator(KC, audience="vendi-api", allowed_realms=(REALM_VENDI,))

    async def _jwks_falso(realm: str):
        return jwks

    monkeypatch.setattr(v, "_fetch_jwks", _jwks_falso)
    with pytest.raises(ValueError, match="falta el claim 'aud'"):
        await v.validate_token(_firmar(pem, _claims()))


@pytest.mark.asyncio
async def test_token_con_aud_equivocada(clave, monkeypatch):
    pem, jwks = clave
    v = JWTValidator(KC, audience="vendi-api", allowed_realms=(REALM_VENDI,))

    async def _jwks_falso(realm: str):
        return jwks

    monkeypatch.setattr(v, "_fetch_jwks", _jwks_falso)
    with pytest.raises(ValueError, match="Falló la validación del token"):
        await v.validate_token(_firmar(pem, _claims(aud="otra-api")))


@pytest.mark.asyncio
async def test_texto_que_no_es_un_token(validador):
    with pytest.raises(ValueError, match="Formato de token inválido"):
        await validador.validate_token("esto-no-es-un-jwt")


def test_allowed_realms_vacio_se_rechaza_en_construccion():
    """No se puede pedir "cualquier realm" ni por accidente."""
    with pytest.raises(ValueError, match="allowed_realms no puede estar vacío"):
        JWTValidator(KC, allowed_realms=())


@pytest.mark.asyncio
async def test_no_se_descarga_jwks_de_un_realm_no_permitido(clave, monkeypatch):
    """El rechazo de realm ocurre ANTES de la petición HTTP.

    Importa por dos razones: no se le hace una petición a Keycloak por cada
    token basura que llegue (amplificación trivial de denegación de servicio con
    un `iss` inventado), y no se consulta un realm arbitrario que el atacante
    elija.
    """
    pem, jwks = clave
    llamadas: list[str] = []

    v = JWTValidator(KC, allowed_realms=(REALM_VENDI,))

    async def _jwks_espia(realm: str):
        llamadas.append(realm)
        return jwks

    monkeypatch.setattr(v, "_fetch_jwks", _jwks_espia)
    with pytest.raises(ValueError, match="Realm no permitido"):
        await v.validate_token(_firmar(pem, _claims(realm="realm-del-atacante")))
    assert llamadas == [], f"se pidió el JWKS de un realm no permitido: {llamadas}"
