# ADR-004 — Cobro de suscripciones web-first

**Fecha:** 2026-07-20 · **Estado:** Firmada
**Origen:** `docs/plan-tecnico.md` §6 y `docs/monetizacion-web.md`.

## Contexto

Vender la suscripción dentro de la app obliga a usar la facturación de Play y
App Store: 15–30 % de comisión, y ninguna de las dos soporta los medios de pago
que usa el tendero colombiano (PSE, Nequi, efectivo).

## Decisión

**La suscripción se cobra fuera de la app**, en un portal web con pasarela
local. Dentro de la app no hay CTAs de compra ni *steering* hacia el portal.

## Alternativas descartadas

- **Compra in-app.** Comisión alta, y sobre todo: no se puede pagar en efectivo
  ni por Nequi, que es como paga el segmento.

## Consecuencias

- El plan gratuito tiene que ser genuinamente usable: es lo que hace que la app
  cumpla las políticas de tienda sin *steering*.
- Los *entitlements* llegan por webhook de la pasarela al backend, no por recibo
  de la tienda.
- `vendi-portal` (la app pública) existe por esto: es el sitio donde ocurre la
  conversión. Ver ADR-012.
