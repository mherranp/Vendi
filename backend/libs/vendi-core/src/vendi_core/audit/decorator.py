import functools
import time
from collections.abc import Awaitable, Callable

from fastapi import Request

from vendi_core.audit.events import AuditEvent, AuditStatus
from vendi_core.audit.service import AuditService
from vendi_core.middleware import trusted_client_ip
from vendi_core.tracing.context import get_correlation_id


def audit_operation(
    action: str,
    resource_type: str = "",
    resource_id_arg: str | None = None,
) -> Callable:
    """Decorator for FastAPI endpoints that audits success/failure.

    La función decorada debe tener un parámetro `request: Request`.
    `request.app.state.audit_service` debe ser una instancia de `AuditService`.
    `request.state.user` (opcional) aporta user_id/email.
    `request.state.tenant` (opcional, lo pone `TenantMiddleware`) aporta el
    `tenant_id`; si no hay tenant en el request el evento es de plataforma y
    viaja con `tenant_id=None`.
    """

    def decorator(func: Callable[..., Awaitable]) -> Callable[..., Awaitable]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request: Request | None = kwargs.get("request")
            if request is None:
                for candidate in args:
                    if isinstance(candidate, Request):
                        request = candidate
                        break

            start = time.monotonic()
            error_msg = ""
            status = AuditStatus.SUCCESS
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as exc:
                status = AuditStatus.FAILURE
                error_msg = str(exc)
                raise
            finally:
                if request is not None:
                    duration_ms = int((time.monotonic() - start) * 1000)
                    user = getattr(request.state, "user", None)
                    tenant = getattr(request.state, "tenant", None)
                    resource_id = ""
                    if resource_id_arg and resource_id_arg in kwargs:
                        resource_id = str(kwargs[resource_id_arg])
                    metadata: dict = {}
                    # Aquí BaseSaaS publicaba el claim `act` de RFC 8693 —el
                    # actor original de un token obtenido por token-exchange—
                    # para poder preguntar "qué hizo el admin X mientras
                    # suplantaba a Y". En Vendi ese bloque se elimina: la Etapa 2
                    # quitó el rol `impersonation` de la cuenta de servicio por
                    # ser un agujero de aislamiento multi-negocio y la Fase 0 no
                    # tiene suplantación. `UserContext` no tiene atributo
                    # `actor`, así que el bloque era código muerto en el camino
                    # de auditoría: justo la capacidad que esta fase declara
                    # inexistente, sugerida por el propio código. Lo vigila
                    # `test_auditoria_decorator.py`.
                    #
                    # La IP del rastro de auditoría tiene que venir de una
                    # fuente de confianza. `trusted_client_ip()` solo hace caso
                    # a `X-Forwarded-For` cuando el peer está en
                    # `app.state.trusted_proxies`; si no, devuelve el peer. Con
                    # `trusted_proxies` vacío siempre devuelve el peer, así que
                    # falsificar la cabecera es imposible.
                    trusted = getattr(request.app.state, "trusted_proxies", ())
                    client_ip = trusted_client_ip(request, trusted) or ""
                    if client_ip:
                        metadata["ip"] = client_ip
                    event = AuditEvent(
                        correlation_id=get_correlation_id(),
                        tenant_id=tenant.tenant_id if tenant else None,
                        user_id=user.user_id if user else "",
                        user_email=user.email if user else "",
                        action=action,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        status=status,
                        duration_ms=duration_ms,
                        error=error_msg,
                        metadata=metadata,
                    )
                    audit_service: AuditService | None = getattr(request.app.state, "audit_service", None)
                    if audit_service is not None:
                        await audit_service.log(event)

        return wrapper

    return decorator
