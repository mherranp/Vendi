"""`audit_operation` y la redacción de secretos del rastro de auditoría.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_audit_xff.py` y
`test_oidc_client_secret_redaction.py`, portados y ampliados.

Ampliación propia de Vendi y motivo por el que este archivo existe:
`test_el_decorador_no_publica_ningun_actor_de_suplantacion`. El decorador
arrastraba de BaseSaaS un bloque que publicaba el claim `act` de RFC 8693
—el actor original de un token obtenido por token-exchange— en los metadatos de
cada fila. La Etapa 2 eliminó el rol `impersonation` de la cuenta de servicio
por ser un agujero de aislamiento multi-negocio, así que ese bloque era código
muerto que anunciaba una capacidad inexistente en el camino de auditoría. Se
quitó, y este test impide que vuelva por copia-pega.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from vendi_core.audit import SECRET_FIELD_NAMES, redact_secrets
from vendi_core.audit.decorator import audit_operation
from vendi_core.audit.events import AuditEvent, AuditStatus


class _AuditServiceDoblado:
    def __init__(self) -> None:
        self.eventos: list[AuditEvent] = []

    async def log(self, evento: AuditEvent) -> None:
        self.eventos.append(evento)


def _peticion(
    *,
    peer: str = "10.0.0.5",
    xff: str | None = None,
    trusted: tuple[str, ...] = (),
    user=None,
    tenant=None,
    audit_service=None,
):
    """Doble mínimo de `Request`: solo lo que el decorador consulta."""
    headers = {"x-forwarded-for": xff} if xff else {}
    estado_app = SimpleNamespace(trusted_proxies=trusted, audit_service=audit_service)
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=headers,
        app=SimpleNamespace(state=estado_app),
        state=SimpleNamespace(user=user, tenant=tenant),
    )


# ---------------------------------------------------------------------------
# El decorador
# ---------------------------------------------------------------------------


async def test_una_operacion_correcta_se_audita_como_exito():
    servicio = _AuditServiceDoblado()
    tenant = SimpleNamespace(tenant_id=uuid.uuid4())
    user = SimpleNamespace(user_id="kc-1", email="ana@ejemplo.test")

    @audit_operation("venta.crear", resource_type="venta", resource_id_arg="venta_id")
    async def handler(*, request, venta_id):
        return {"ok": True}

    peticion = _peticion(user=user, tenant=tenant, audit_service=servicio)
    assert await handler(request=peticion, venta_id="v-1") == {"ok": True}

    assert len(servicio.eventos) == 1
    ev = servicio.eventos[0]
    assert ev.action == "venta.crear"
    assert ev.resource_type == "venta"
    assert ev.resource_id == "v-1"
    assert ev.status == AuditStatus.SUCCESS
    assert ev.error == ""
    assert ev.tenant_id == tenant.tenant_id
    assert ev.user_id == "kc-1"
    assert ev.user_email == "ana@ejemplo.test"


async def test_una_operacion_que_revienta_se_audita_como_fallo_y_relanza():
    """La excepción tiene que llegar a quien llamó: auditar no es tragarse."""
    servicio = _AuditServiceDoblado()

    @audit_operation("venta.crear")
    async def handler(*, request):
        raise RuntimeError("sin caja abierta")

    with pytest.raises(RuntimeError, match="sin caja abierta"):
        await handler(request=_peticion(audit_service=servicio))

    assert servicio.eventos[0].status == AuditStatus.FAILURE
    assert servicio.eventos[0].error == "sin caja abierta"


async def test_sin_negocio_en_la_peticion_el_evento_es_de_plataforma():
    servicio = _AuditServiceDoblado()

    @audit_operation("plataforma.algo")
    async def handler(*, request):
        return None

    await handler(request=_peticion(audit_service=servicio, tenant=None, user=None))

    assert servicio.eventos[0].tenant_id is None
    assert servicio.eventos[0].user_id == ""


async def test_sin_audit_service_cableado_el_handler_sigue_funcionando():
    """Auditar es un efecto lateral: que falte el servicio no puede tumbar el
    endpoint."""

    @audit_operation("venta.crear")
    async def handler(*, request):
        return "listo"

    assert await handler(request=_peticion(audit_service=None)) == "listo"


async def test_un_peer_no_confiable_no_puede_falsificar_la_ip_del_rastro():
    """Portado de `test_audit_xff.py`: un cliente en 8.8.8.8 que manda
    `X-Forwarded-For: 1.2.3.4` queda auditado como 8.8.8.8."""
    servicio = _AuditServiceDoblado()

    @audit_operation("venta.crear")
    async def handler(*, request):
        return None

    await handler(request=_peticion(peer="8.8.8.8", xff="1.2.3.4", trusted=("10.0.0.0/8",), audit_service=servicio))
    assert servicio.eventos[0].metadata["ip"] == "8.8.8.8"


async def test_un_proxy_de_confianza_sí_aporta_la_ip_real():
    servicio = _AuditServiceDoblado()

    @audit_operation("venta.crear")
    async def handler(*, request):
        return None

    await handler(request=_peticion(peer="10.0.0.5", xff="1.2.3.4", trusted=("10.0.0.0/8",), audit_service=servicio))
    assert servicio.eventos[0].metadata["ip"] == "1.2.3.4"


async def test_el_decorador_no_publica_ningun_actor_de_suplantacion():
    """Fase 0 no tiene suplantación. Aunque el contexto de usuario trajera un
    claim `act` (no debería: `UserContext` ni siquiera declara el atributo), el
    decorador no puede convertirlo en metadatos de auditoría."""
    servicio = _AuditServiceDoblado()
    user = SimpleNamespace(
        user_id="kc-admin",
        email="admin@vendi.local",
        actor={"sub": "kc-victima", "username": "duenio"},
    )

    @audit_operation("venta.crear")
    async def handler(*, request):
        return None

    await handler(request=_peticion(user=user, audit_service=servicio))

    assert "actor" not in servicio.eventos[0].metadata
    assert set(servicio.eventos[0].metadata) <= {"ip"}


def test_el_contexto_de_usuario_no_declara_ningun_campo_de_suplantacion():
    """El candado por el otro lado: si alguien reintroduce `actor` en
    `UserContext`, el bloque del decorador tendría de dónde leer."""
    from vendi_core.auth.context import UserContext

    campos = set(UserContext.__dataclass_fields__)
    assert campos & {"actor", "act", "impersonator"} == set()


# ---------------------------------------------------------------------------
# Redacción de secretos
# ---------------------------------------------------------------------------


def test_se_redacta_un_secreto_de_primer_nivel():
    assert redact_secrets({"proveedor": "google", "client_secret": "fuga"}) == {
        "proveedor": "google",
        "client_secret": "***",
    }


def test_la_redaccion_no_distingue_mayusculas_y_es_por_subcadena():
    salida = redact_secrets({"Client_Secret": "x", "CLIENT_SECRET": "y", "ClientSecret": "z"})
    assert salida == {"Client_Secret": "***", "CLIENT_SECRET": "***", "ClientSecret": "***"}


def test_la_redaccion_baja_por_diccionarios_anidados():
    salida = redact_secrets(
        {
            "proveedor": "github",
            "config": {
                "client_id": "id-publico",
                "client_secret": "fuga",
                "anidado": {"access_key": "tambien-fuga", "etiqueta": "se-queda"},
            },
        }
    )
    assert salida["config"]["client_id"] == "id-publico"
    assert salida["config"]["client_secret"] == "***"
    assert salida["config"]["anidado"]["access_key"] == "***"
    assert salida["config"]["anidado"]["etiqueta"] == "se-queda"


def test_la_redaccion_baja_por_listas_y_tuplas():
    salida = redact_secrets({"cuentas": [{"password": "p"}, {"usuario": "ana"}]})
    assert salida["cuentas"][0]["password"] == "***"
    assert salida["cuentas"][1]["usuario"] == "ana"
    assert redact_secrets(({"token": "t"},)) == ({"token": "***"},)


def test_la_redaccion_no_muta_la_entrada():
    entrada = {"password": "p", "anidado": {"api_key": "k"}}
    redact_secrets(entrada)
    assert entrada == {"password": "p", "anidado": {"api_key": "k"}}


def test_un_valor_que_no_es_diccionario_pasa_tal_cual():
    assert redact_secrets("hola") == "hola"
    assert redact_secrets(7) == 7
    assert redact_secrets(None) is None


@pytest.mark.parametrize(
    "clave",
    ["password", "new_password", "client_secret", "api_key", "private_key", "authorization", "MAIL_FERNET_KEY"],
)
def test_las_formas_habituales_de_secreto_caen_en_la_lista(clave):
    assert redact_secrets({clave: "v"})[clave] == "***"


def test_la_lista_de_nombres_secretos_cubre_lo_declarado():
    assert "password" in SECRET_FIELD_NAMES
    assert "client_secret" in SECRET_FIELD_NAMES
    assert "token" in SECRET_FIELD_NAMES
