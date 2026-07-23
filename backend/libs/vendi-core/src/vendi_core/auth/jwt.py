"""Validación de JWT contra el realm regional de Keycloak.

Cosechado de `base_saas.auth.jwt` con dos cambios que no son cosméticos:

## 1. `allowed_realms` — el agujero que abre el realm único

El validador de BaseSaaS extraía el realm del claim `iss` y descargaba el JWKS
de **ese** realm, cualquiera que fuese. En realm-per-tenant eso era correcto por
construcción: cada tenant tenía su realm y el propio realm identificaba al
inquilino. En Vendi hay un solo realm de negocio, `vendi-co`, pero el servidor
de Keycloak sigue teniendo `master` — y `master` tiene usuarios, los
administradores del servidor. Con el validador original, **un token del realm
`master` pasaba la validación**: firma legítima, JWKS legítimo, `iss` legítimo.
Lo único que faltaba era comprobar que el realm es el que esperamos, y no se
comprobaba. Por eso `allowed_realms` es obligatorio y su valor en Vendi es
`("vendi-co",)`.

Es defensa en profundidad y no un parche cosmético: aunque el token de `master`
no traería `organization` y `TenantMiddleware` lo pararía en rutas de tenant,
sí pasaría por rutas de plataforma si además llevara el permiso, y el
aislamiento no debe depender de esa cadena de casualidades.

## 2. El claim `organization` es polimórfico

El informe `2026-07-22-verificacion-kc-organizations.md` (refutación 1) midió
que el mapper de fábrica emite una **lista de alias**, y que solo con
`addOrganizationId=true` emite el **mapa `alias → {"id": ...}`**. El realm como
código fija `addOrganizationId=true`, pero el parser acepta las dos formas: un
realm importado a medias, un cliente creado a mano o un drift de configuración
devolverían la lista, y un parser que asumiera el mapa reventaría con
`AttributeError` sobre un `list` — es decir, un 500 en el camino de
autenticación de toda la API.
"""

import time
from typing import Any

import httpx
from jose import JWTError, jwt

from vendi_core.auth.context import UserContext
from vendi_core.auth.ssl import keycloak_ssl_verify

# El realm de negocio de Vendi. Aquí como constante para que quien cablee la
# app no tenga que recordar el literal ni pueda equivocarse de guion.
REALM_VENDI = "vendi-co"


def parsear_claim_organization(crudo: Any) -> dict[str, str]:
    """Normaliza el claim `organization` a `{alias: id_interno}`.

    Acepta las dos formas que emite Keycloak 26.6.4:

    - `["<alias>", ...]` — mapper de fábrica (`addOrganizationId=false`). El id
      interno no viaja, así que queda en `""`.
    - `{"<alias>": {"id": "..."}}` — mapper con `addOrganizationId=true`.

    Cualquier otra cosa (None, string, número, un dict con valores raros)
    devuelve `{}`. Es deliberado: un claim que no entendemos es un claim sin
    organizaciones, y `TenantMiddleware` responde 403 en rutas de tenant. Fallar
    cerrado y en silencio aquí es correcto; el ruido lo hace el middleware, que
    es quien sabe si la ruta necesitaba tenant.
    """
    if isinstance(crudo, list):
        # Mapper sin addOrganizationId: lista de alias, sin el id interno.
        return {str(alias): "" for alias in crudo if isinstance(alias, str | int)}
    if isinstance(crudo, dict):
        salida: dict[str, str] = {}
        for alias, valor in crudo.items():
            if isinstance(valor, dict):
                salida[str(alias)] = str(valor.get("id") or "")
            else:
                salida[str(alias)] = ""
        return salida
    return {}


class JWTValidator:
    """Validador de JWT con caché de JWKS y realm restringido."""

    def __init__(
        self,
        keycloak_url: str,
        jwks_cache_ttl: int = 600,
        audience: str | None = None,
        allowed_realms: tuple[str, ...] | list[str] = (REALM_VENDI,),
    ):
        self._keycloak_url = keycloak_url.rstrip("/")
        self._jwks_cache_ttl = jwks_cache_ttl
        self._jwks_cache: dict[str, dict[str, Any]] = {}
        # Una cadena vacía en la variable de entorno significa "sin audiencia":
        # si no, todos los tokens fallarían la validación de `aud`, que es peor
        # que la línea base que estamos intentando cerrar.
        self._audience = audience if audience else None
        realms = tuple(allowed_realms)
        if not realms:
            # Lista vacía = "acepto cualquier realm". Es exactamente el agujero
            # que este parámetro existe para cerrar, así que no se permite
            # expresarlo ni por accidente.
            raise ValueError(
                "allowed_realms no puede estar vacío: un validador que acepta "
                "cualquier realm admite tokens del realm master."
            )
        self._allowed_realms = frozenset(realms)

    @property
    def allowed_realms(self) -> frozenset[str]:
        return self._allowed_realms

    async def validate_token(self, token: str) -> UserContext:
        try:
            unverified_header = jwt.get_unverified_header(token)
            unverified_claims = jwt.get_unverified_claims(token)
        except JWTError as e:
            raise ValueError(f"Formato de token inválido: {e}") from e

        kid = unverified_header.get("kid")
        if not kid:
            raise ValueError("El token no trae cabecera kid")

        issuer = unverified_claims.get("iss", "")
        realm = self._extract_realm(issuer)
        if not realm:
            raise ValueError(f"No se puede extraer el realm del issuer: {issuer}")
        if realm not in self._allowed_realms:
            # ANTES de descargar el JWKS: si el realm no vale, no hay ningún
            # motivo para hacerle una petición HTTP a Keycloak, y menos una que
            # un atacante pueda provocar a voluntad con un `iss` inventado.
            raise ValueError(f"Realm no permitido: {realm!r} (permitidos: {sorted(self._allowed_realms)})")

        jwks = await self._get_jwks(realm)
        key = self._find_key(jwks, kid)
        if not key:
            jwks = await self._fetch_and_cache_jwks(realm)
            key = self._find_key(jwks, kid)
            if not key:
                raise ValueError(f"No hay clave que corresponda al kid: {kid}")

        decode_options: dict[str, Any] = {}
        decode_kwargs: dict[str, Any] = {}
        if self._audience is None:
            decode_options["verify_aud"] = False
        else:
            decode_kwargs["audience"] = self._audience
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                options=decode_options,
                **decode_kwargs,
            )
        except jwt.ExpiredSignatureError as e:
            raise ValueError("Token expirado") from e
        except JWTError as e:
            # JWTClaimsError (audiencia que no coincide) hereda de JWTError, así
            # que cae aquí. Se relanza como ValueError para que la superficie de
            # error sea una sola.
            raise ValueError(f"Falló la validación del token: {e}") from e

        # python-jose se salta en silencio la validación de `aud` cuando el
        # token no trae el claim (solo lo comprueba si está presente). Se fuerza
        # explícitamente para que un token sin `aud` se rechace igual que uno
        # con `aud` equivocada.
        if self._audience is not None:
            token_aud = claims.get("aud")
            if token_aud is None:
                raise ValueError("Falló la validación del token: falta el claim 'aud'")
            # `aud` puede ser string o lista de strings (RFC 7519 admite ambas).
            aud_list = [token_aud] if isinstance(token_aud, str) else list(token_aud)
            if self._audience not in aud_list:
                raise ValueError(f"Falló la validación del token: la audiencia '{self._audience}' no está en aud")

        return self._build_user_context(claims, realm)

    def _extract_realm(self, issuer: str) -> str:
        parts = issuer.rstrip("/").split("/realms/")
        if len(parts) == 2:
            return parts[1]
        return ""

    async def _get_jwks(self, realm: str) -> dict:
        cached = self._jwks_cache.get(realm)
        if cached and (time.time() - cached["fetched_at"]) < self._jwks_cache_ttl:
            return cached["jwks"]
        return await self._fetch_and_cache_jwks(realm)

    async def _fetch_and_cache_jwks(self, realm: str) -> dict:
        jwks = await self._fetch_jwks(realm)
        self._jwks_cache[realm] = {"jwks": jwks, "fetched_at": time.time()}
        return jwks

    async def _fetch_jwks(self, realm: str) -> dict:
        url = f"{self._keycloak_url}/realms/{realm}/protocol/openid-connect/certs"
        async with httpx.AsyncClient(verify=keycloak_ssl_verify()) as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _find_key(jwks: dict, kid: str) -> dict | None:
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None

    @staticmethod
    def _build_user_context(claims: dict, realm: str) -> UserContext:
        realm_access = claims.get("realm_access", {})
        # `realm_access.roles` es el ÚNICO canal de autorización del token: trae
        # los permisos y los roles de negocio (`dueno`, `cajero`, `almacenista`),
        # que en Vendi son roles de realm. El claim `groups` ya no se lee: el
        # realm no lo emite y leerlo daba una comprobación de rol siempre falsa
        # (deuda D-08, cerrada en la Etapa 5; ver ADR-015).
        roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
        exp_raw = claims.get("exp")
        token_exp = int(exp_raw) if exp_raw is not None else None
        return UserContext(
            user_id=claims.get("sub", ""),
            username=claims.get("preferred_username", ""),
            email=claims.get("email", ""),
            roles=roles,
            realm=realm,
            organizations=parsear_claim_organization(claims.get("organization")),
            acr=claims.get("acr"),
            token_exp=token_exp,
        )
