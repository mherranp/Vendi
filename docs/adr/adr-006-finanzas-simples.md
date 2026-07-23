# ADR-006 — P&L simple y forecast de caja a 30 días en el MVP

**Fecha:** 2026-07-21 · **Estado:** Firmada
**Origen:** `docs/plan-maestro.md` §0 y §3.

## Contexto

El documento del socio proponía un módulo financiero amplio. El tendero no
lleva contabilidad: lleva un cuaderno. Pero sí necesita saber si el mes va bien
y si le va a alcanzar la plata.

## Decisión

El MVP incluye **P&L simple por período y categoría** y **forecast de flujo de
caja a 30 días**. Queda fuera: contabilidad formal, tesorería, activos fijos y
presupuestos.

## Consecuencias

- El P&L se calcula de lo que ya se registra (ventas, compras, gastos de caja):
  no pide al usuario que introduzca nada nuevo, que es la condición para que se
  use.
- El forecast es una proyección explicada, no una promesa: la pantalla tiene que
  decir de qué datos sale.
