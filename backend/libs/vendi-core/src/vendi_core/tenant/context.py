"""Contexto de tenant del request en curso.

El `ContextVar` es el único canal entre "quién pidió esto" (el middleware, que
lee el claim `organization` del token) y "qué filas puede ver" (el evento
`after_begin` de la sesión, que emite el `SET LOCAL vendi.tenant_id`).

Por qué un `ContextVar` y no `request.state`: el `SET LOCAL` no se puede emitir
una sola vez por request. El spike de RLS midió (escenario B.3 del informe
`2026-07-22-verificacion-rls.md`) que **`SET LOCAL` muere en el `COMMIT`**, y
que la siguiente consulta de la misma sesión devuelve cero filas *en silencio*.
Es decir: un handler que commitea a mitad y sigue consultando dejaría de ver sus
propios datos sin ningún error. Por eso lo reinstala la sesión en cada
transacción nueva, y para eso necesita leer el tenant desde un sitio al que
llegue sin tener el `Request` a mano. Ese sitio es este ContextVar.

Y `ContextVar` —no una global— porque asyncio ejecuta requests concurrentes en
la misma hebra: una global se contaminaría entre negocios.
"""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass

# None = no hay tenant en el contexto. La sesión de tenant NO emite `SET LOCAL`
# en ese caso, así que la policy ve el GUC en '' y devuelve cero filas: el
# camino fail-closed verificado en el spike.
current_tenant_id: ContextVar[uuid.UUID | None] = ContextVar("current_tenant_id", default=None)


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Lo que `TenantMiddleware` publica en `request.state.tenant`.

    Fase 0 solo necesita el id. El nombre y el estado del negocio viven en la
    tabla `tenants` y los resuelve el módulo homónimo (tarea 4.2); meterlos aquí
    obligaría a una consulta a base por request antes de saber siquiera si la
    ruta necesita tenant.
    """

    tenant_id: uuid.UUID
