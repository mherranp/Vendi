# ADR-002 — RabbitMQ como broker de tareas, Redis como cache

**Fecha:** 2026-07-20 · **Estado:** Firmada
**Origen:** `docs/plan-tecnico.md` §4, migrado a archivo en la Etapa 5 de Fase 0.

## Contexto

Hay trabajo que no puede ocurrir dentro de la petición HTTP: facturación fiscal
(Factus/DIAN), sincronización del POS offline, notificaciones, retención de
datos. Se pidió evaluar RabbitMQ frente a usar Redis como cola.

## Decisión

**RabbitMQ es el broker de tareas. Redis es cache, rate limiting y estado
efímero — nunca la cola principal.**

## Alternativas descartadas

- **Redis como cola.** Redis no tiene *dead-letter queue* de verdad ni acuse de
  entrega duradero; una tarea fiscal perdida es una factura que la DIAN no
  recibió y que nadie sabe que falta. Reconstruir esas garantías encima de
  Redis es escribir un broker peor.

## Consecuencias

- Los reintentos con backoff y la DLQ son de fábrica: es lo que sostiene el
  riesgo «pérdida de jobs fiscales» del plan maestro.
- Fase 0 no usa Celery: el `worker` (`backend/services/worker/`) consume el
  outbox transaccional y publica en RabbitMQ con `aio_pika`. Celery se evaluará
  cuando haya tareas de negocio de verdad.
- El patrón de publicación es **outbox transaccional**: el evento se escribe en
  la misma transacción que el dato, y un dispatcher lo drena. Sin eso, un
  `commit` seguido de un fallo al publicar produce eventos fantasma o eventos
  perdidos según el orden.
