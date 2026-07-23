"""Dependencias de FastAPI para autenticación y autorización.

Cosechado de `base_saas.auth.dependencies`. Se quita el camino de API keys
(`sk_live_*` / `sk_test_*`) y su `api_key_resolver`: el módulo `api_keys` está
fuera del alcance de Fase 0 (restricción global del plan), y dejar el prefijo
reconocido sin resolver registrado produciría un 401 con el mensaje equivocado
("API key auth not supported") ante lo que en realidad es un token mal formado.
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from vendi_core.auth.context import UserContext
from vendi_core.auth.jwt import JWTValidator
from vendi_core.auth.policies import has_permission

_bearer_scheme = HTTPBearer()


def get_jwt_validator(request: Request) -> JWTValidator:
    return request.app.state.jwt_validator


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    validator: JWTValidator = Depends(get_jwt_validator),
) -> UserContext:
    """Dependencia de FastAPI: extrae y valida el usuario del bearer token.

    Reutiliza la validación que ya hizo `TenantMiddleware` **solo** si el token
    es byte a byte el mismo. La comparación no es paranoia gratuita: sin ella,
    bastaría con que algún handler o middleware intermedio dejara un
    `request.state.user` a su gusto para que esta dependencia lo aceptara como
    usuario autenticado. Con ella, el usuario reutilizado procede
    demostrablemente del mismo token que acaba de llegar en la cabecera.
    """
    token = credentials.credentials
    ya_validado = getattr(request.state, "token_validado", None)
    if ya_validado is not None and ya_validado == token:
        usuario_previo = getattr(request.state, "user", None)
        if usuario_previo is not None:
            return usuario_previo
    try:
        user = await validator.validate_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    request.state.user = user
    return user


def require_role(*roles: str) -> Callable:
    """Fábrica de dependencias: exige uno de los roles de negocio dados."""

    async def _comprobar_rol(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not user.has_any_role(*roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requiere uno de estos roles: {', '.join(roles)}",
            )
        return user

    return _comprobar_rol


def require_permission(permission: str) -> Callable:
    """Fábrica de dependencias: exige un permiso concreto."""

    async def _comprobar_permiso(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Falta el permiso requerido: {permission}",
            )
        return user

    return _comprobar_permiso
