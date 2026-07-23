# ADR-005 — Telemetría y analítica del POS

**Fecha:** — · **Estado:** ⏳ **Abierta**

## Contexto

Hace falta saber qué pantallas se usan, dónde se abandona el alta y si el
briefing de IA se lee. La duda es el «cómo»: PostHog autoalojado (más control,
más operación) frente a uno gestionado (menos operación, el dato sale de la
región).

## Por qué sigue abierta

Decidirlo bien exige saber qué eventos importan, y eso no se sabe hasta tener
el POS en manos de tiendas reales (Fase 1). Decidirlo antes sería elegir
herramienta sin conocer el problema.

## Restricción que ya está fijada, aunque la decisión no lo esté

Sea cual sea la herramienta, **la telemetría no puede sacar datos personales ni
de negocio de la región** (ADR-003). Eso descarta de entrada cualquier opción
gestionada que no permita alojamiento en la región o anonimización en origen.

## Qué hay hoy

Métricas técnicas (Prometheus + Grafana) y auditoría (`audit_events`). Es
observabilidad de sistema, no analítica de producto: responde «¿va lento?», no
«¿la gente entiende esta pantalla?».
