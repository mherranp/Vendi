class DomainError(Exception):
    """Base class for domain errors. Maps to HTTP 400 by default."""

    status_code: int = 400
    code: str = "DOMAIN_ERROR"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class NotFoundError(DomainError):
    status_code = 404
    code = "NOT_FOUND"


class ValidationError(DomainError):
    status_code = 422
    code = "VALIDATION_ERROR"


class AuthenticationError(DomainError):
    status_code = 401
    code = "AUTHENTICATION_REQUIRED"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "PERMISSION_DENIED"


class ConflictError(DomainError):
    status_code = 409
    code = "CONFLICT"


class ExternalServiceError(DomainError):
    """Falló un servicio del que dependemos (Keycloak, MinIO, RabbitMQ).

    Añadido en Vendi. Existe para que un Keycloak caído produzca un 502 tipado
    con mensaje en español y no un traceback crudo de `KeycloakError` subiendo
    hasta el manejador genérico: la diferencia entre "el sistema de cuentas no
    responde, reintenta" y un 500 sin explicación.
    """

    status_code = 502
    code = "EXTERNAL_SERVICE_ERROR"
