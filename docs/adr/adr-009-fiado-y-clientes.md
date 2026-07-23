# ADR-009 — Fiado y CRM mínimo de clientes entran al MVP

**Fecha:** 2026-07-21 · **Estado:** Firmada
**Origen:** `docs/plan-maestro.md` §0 y §3.

## Contexto

El fiado no es una funcionalidad opcional en la tienda de barrio colombiana: es
el modo normal de vender a los vecinos, y hoy vive en el cuaderno. Un POS que no
lo soporta obliga al tendero a mantener el cuaderno, y entonces el POS no se usa.

## Decisión

**Venta a crédito con saldo por cliente entra al MVP**, con recordatorios de
vencimiento (WhatsApp/push), historial de pagos y una base mínima de clientes.

## Consecuencias

- Es la razón de que exista una entidad «cliente» en el MVP, y el único motivo.
  El CRM avanzado sigue en Fase 3 (ADR-008).
- El argumento comercial del producto pasa a ser «del cuaderno al celular», que
  es literal: el fiado ES el cuaderno.
