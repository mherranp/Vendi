# Runbook · Outbox, RabbitMQ y mensajes fallidos

## Cómo viaja un evento

```
handler                    worker                         RabbitMQ
   │ DomainEventService.emit  │                              │
   ├─ INSERT en outbox_messages (MISMA transacción) ──────────┤
   │                          │ cada OUTBOX_POLL_INTERVAL     │
   │                          ├─ SELECT status='pending' ─────┤
   │                          ├─ publish(exchange, clave) ───►│ events.tenant
   │                          └─ UPDATE status='processed'    │
```

La garantía del patrón es que la escritura de negocio y el encolado comparten
transacción: si el handler hace rollback, no se publica ningún evento fantasma.

## «Los eventos no llegan»

Diagnóstico en orden, del más probable al menos:

```bash
# 1. ¿El worker está vivo?
docker compose -f infra/docker-compose.yml ps worker
docker compose -f infra/docker-compose.yml logs --tail=50 worker

# 2. ¿Hay mensajes atascados?
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U postgres -d vendi -c \
  "SELECT status, count(*), max(retry_count) FROM outbox_messages GROUP BY status"

# 3. ¿Qué error concreto?
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U postgres -d vendi -c \
  "SELECT id, routing_key, retry_count, last_error FROM outbox_messages
   WHERE status <> 'processed' ORDER BY created_at LIMIT 20"
```

| Lo que ves | Significa |
|---|---|
| `worker_sin_rabbitmq` en el log | `RABBITMQ_URL` vacío: el outbox no se drena y nadie lo dice más alto |
| `pending` creciendo, `retry_count` en 0 | el worker no está corriendo, o no conecta con el broker |
| `failed` con `retry_count` = `OUTBOX_MAX_RETRIES` | agotó reintentos; mira `last_error` |
| `outbox_clave_de_enrutado_corregida` | alguien encoló una clave que no correspondía a su negocio. **El mensaje salió bien** —el dispatcher deriva la clave de la columna `tenant_id`— pero hay un handler mal escrito. Ver D-05 |
| `outbox_exchange_ignorado` | ídem con el `exchange`. El dispatcher publica siempre en el suyo. Ver D-07 |

## Reintentar mensajes fallidos

Un `failed` no se reintenta solo. Cuando hayas arreglado la causa:

```sql
-- Con el rol de PLATAFORMA (vendi_app no tiene UPDATE sobre esta tabla).
UPDATE outbox_messages
   SET status = 'pending', retry_count = 0, last_error = ''
 WHERE status = 'failed' AND created_at > now() - interval '1 day';
```

Antes de ejecutarlo, mira **qué** vas a reintentar: si el error era «el
consumidor rechazó el mensaje por malformado», reintentar solo repite el fallo.

## Purgar lo ya procesado

`outbox_messages` crece indefinidamente si nadie la limpia. La retención se
encarga (`RETENTION_HOUR_UTC`); si hace falta a mano:

```sql
DELETE FROM outbox_messages
 WHERE status = 'processed' AND processed_at < now() - interval '30 days';
```

## Inspeccionar el broker

```bash
docker compose -f infra/docker-compose.yml exec rabbitmq rabbitmqctl list_queues name messages consumers
docker compose -f infra/docker-compose.yml exec rabbitmq rabbitmqctl list_exchanges name type
```

El exchange de eventos es **`events.tenant`**, de tipo `topic`. Las claves de
enrutado tienen la forma `<tenant_id>.<evento>` para los eventos de un negocio y
`plataforma.<evento>` para los que no pertenecen a ninguno — así un consumidor se
liga a `<tenant_id>.#` y recibe **solo** lo suyo.

**Si ves un exchange que no reconoces**, mira si alguien lo declaró a mano: el
dispatcher ya no puede crearlos (D-07), publica siempre en el configurado.
