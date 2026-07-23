# ADR-007 — Capa `AIProvider` con interfaz OpenAI-compatible

**Fecha:** 2026-07-21 · **Estado:** Firmada
**Origen:** `docs/plan-maestro.md` §4.1.

## Contexto

El asistente y el escáner de recibos dependen de un modelo externo. El mercado
de modelos cambia cada pocos meses en precio y calidad, y un proveedor puede
subir precios, degradar el servicio o cerrar la API.

## Decisión

Todo acceso a modelos pasa por una capa `AIProvider` con **interfaz
OpenAI-compatible**. Gemini 2.5 Flash es el primario, GPT-5 mini el respaldo, y
Qwen-VL opcional para recibos manuscritos.

## Consecuencias

- Cambiar de proveedor es configuración, no reescritura.
- La interfaz común es el mínimo común denominador: las funcionalidades
  exclusivas de un proveedor no se usan, o se usan detrás de una bandera que
  degrada limpiamente.
- **No implementado en Fase 0.** Es diseño acordado para Fase 1.
