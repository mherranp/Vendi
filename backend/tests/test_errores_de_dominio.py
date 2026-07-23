"""Errores de dominio: código HTTP y código de aplicación por subclase.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_errors.py`.
Adaptaciones: `base_saas` → `vendi_core`, y se añade `ExternalServiceError`,
que no existía en BaseSaaS y es propio de Vendi: convierte un Keycloak (o
MinIO, o RabbitMQ) caído en un 502 tipado en vez de un traceback crudo.
"""

from __future__ import annotations

from vendi_core.errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    ExternalServiceError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)


def test_el_error_base_tiene_400_y_codigo_generico():
    err = DomainError("vaya")
    assert err.status_code == 400
    assert err.code == "DOMAIN_ERROR"
    assert err.details == {}
    assert err.message == "vaya"


def test_cada_subclase_lleva_su_codigo_http():
    assert NotFoundError("x").status_code == 404
    assert ValidationError("x").status_code == 422
    assert AuthenticationError("x").status_code == 401
    assert PermissionDeniedError("x").status_code == 403
    assert ConflictError("x").status_code == 409
    assert ExternalServiceError("x").status_code == 502


def test_cada_subclase_lleva_su_codigo_de_aplicacion():
    assert NotFoundError("x").code == "NOT_FOUND"
    assert ValidationError("x").code == "VALIDATION_ERROR"
    assert AuthenticationError("x").code == "AUTHENTICATION_REQUIRED"
    assert PermissionDeniedError("x").code == "PERMISSION_DENIED"
    assert ConflictError("x").code == "CONFLICT"
    assert ExternalServiceError("x").code == "EXTERNAL_SERVICE_ERROR"


def test_un_codigo_explicito_pisa_al_de_la_clase():
    err = ConflictError("el nombre ya existe", code="NOMBRE_OCUPADO", details={"nombre": "acme"})
    assert err.code == "NOMBRE_OCUPADO"
    assert err.details == {"nombre": "acme"}


def test_el_codigo_explicito_no_contamina_a_la_clase():
    """`self.code = code` asigna en la instancia; si algún día alguien lo
    cambiara por `type(self).code = code`, el siguiente error de esa clase
    heredaría un código ajeno. Este assert lo vigila."""
    ConflictError("uno", code="A_MEDIDA")
    assert ConflictError("dos").code == "CONFLICT"
