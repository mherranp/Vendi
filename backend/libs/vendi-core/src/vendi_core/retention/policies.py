"""Declaración de las políticas de retención.

Cada política dice: para la tabla X, borra las filas que cumplan `condition`.
El runner aplica las políticas de plataforma una vez por ciclo, y las de tenant
una vez por cada negocio activo (sembrando su `tenant_id` para que la policy de
RLS acote el borrado).

Cosechado de `base_saas.retention.policies`. La lista de tablas se recorta a lo
que **existe** en Vendi Fase 0: BaseSaaS declaraba políticas para `users`,
`roles`, `smtp_accounts`, `email_templates`, `email_unsubscribes`,
`webhook_endpoints`, `webhook_deliveries`, `email_messages`, `email_events` y
`email_message_routing`. Ninguna de esas tablas existe aquí: los módulos que las
creaban (`api_keys`, `webhooks`, `notifications`, mail por tenant) están fuera
del alcance de Fase 0, y el mailer se redujo a `SystemMailer`. Dejarlas
declaradas produciría un `DELETE FROM tabla_inexistente` por ciclo, que el
runner registra como warning y traga — es decir, ruido diario permanente que
enseña al operador a ignorar los warnings del runner.

Convenciones que se conservan:
- Las filas con borrado lógico (`deleted_at IS NOT NULL`) se purgan 30 días
  después del borrado.
- La auditoría guarda 365 días.
- Los mensajes de outbox ya procesados se limpian a los 7 días.

Los números se cambian editando este archivo: a propósito no son configurables
por variable de entorno, porque forman parte del contrato de la fundación y un
cambio silencioso por entorno haría que "cuánto tiempo guardamos los datos"
dependiera de un `.env`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionPolicy:
    """Una sola regla de DELETE."""

    table: str
    condition: str
    description: str


# Tablas de negocio: llevan `tenant_id` y policy RLS. El runner las recorre una
# vez por negocio activo, con el `tenant_id` sembrado en el ContextVar, así que
# el `DELETE` lo acota la propia policy además de la condición.
#
# Fase 0 solo tiene `files`. Las tablas del MVP (ventas, inventario, cierres de
# caja) añaden aquí sus políticas cuando existan.
TENANT_POLICIES: tuple[RetentionPolicy, ...] = (
    RetentionPolicy(
        "files",
        "deleted_at IS NOT NULL AND deleted_at < now() - interval '30 days'",
        "Purga las filas de archivos borrados lógicamente a los 30 días",
    ),
)

# Tablas de plataforma: sin RLS, cross-tenant. Se aplican una vez por ciclo.
PLATFORM_POLICIES: tuple[RetentionPolicy, ...] = (
    RetentionPolicy(
        "audit_events",
        "timestamp < now() - interval '365 days'",
        "Recorta el rastro de auditoría más viejo de un año",
    ),
    RetentionPolicy(
        "outbox_messages",
        "status = 'processed' AND processed_at < now() - interval '7 days'",
        "Elimina los mensajes de outbox ya procesados a los 7 días",
    ),
)
