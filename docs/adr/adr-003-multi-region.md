# ADR-003 — Arquitectura multi-región federada por país

**Fecha:** 2026-07-20 · **Estado:** Firmada · **Actualizada en la Etapa 5 de Fase 0**
**Origen:** `docs/plan-tecnico.md` §2, migrado a archivo.

## Contexto

Vendi apunta a Colombia primero y a México y Perú después. Los tres países
tienen ley de residencia de datos (Ley 1581, LFPDPPP, Ley 29733) y régimen
fiscal propio. Un tendero colombiano nunca necesita datos de México.

## Decisión

**Una región autónoma por país**, con el negocio anclado a su región de origen.
Sin replicación cruzada de datos operativos, sin active-active, sin clustering
de Keycloak entre regiones. Capa global delgada: CI/CD, observabilidad y (Fase
3) analítica anonimizada.

## Alternativas descartadas

- **Una sola región global.** Incumple residencia de datos por diseño y mete
  latencia transcontinental en el POS, que es la pantalla más usada del
  producto.
- **Clustering de Keycloak entre regiones.** Es la parte más frágil de Keycloak
  y no aporta nada aquí: el usuario no viaja entre países.

## Consecuencias

- La app resuelve su región por subdominio (`co.`, `mx.`, `pe.`). El realm de
  Keycloak, la base y el broker son por región. Ver ADR-014.
- Failover entre regiones **no** es objetivo en v1: RPO/RTO se cubren con
  respaldos regionales cifrados (`docs/respaldo-y-restauracion.md`).

## Consecuencia nueva de la Etapa 5: **Terraform se difiere a Fase 2**

El plan maestro §7 y el plan técnico §8 listaban «IaC por región» como
entregable de Fase 0. Se corrige, y la corrección está escrita en los dos
documentos.

Motivo: con **una** región y **un** servidor, un módulo de Terraform es coste de
mantenimiento sin ningún despliegue que lo ejercite —y el IaC que nadie aplica
se pudre en silencio: diverge del servidor real y la primera vez que se usa de
verdad no funciona. El primer uso genuino de la plantilla de región es levantar
México, que es Fase 3.

Lo que da reproducibilidad en el intervalo, y que sí existe hoy:

- `infra/docker-compose.yml` + `infra/docker-compose.override.prod.yml`
  versionados: la topología entera es un archivo del repositorio.
- `.github/workflows/deploy.yml`: sincroniza esa infraestructura a la VM y
  levanta el stack, con comprobación de humo por el borde.
- El realm de Keycloak como código (`infra/keycloak/realm-vendi-co.json`) y
  `scripts/reconcile-keycloak.sh` para la deriva.

Lo que **no** compra el compose y sí compraría Terraform, dicho en voz alta: el
aprovisionamiento de la VM, la red, el DNS y los discos siguen siendo trabajo
manual documentado en un runbook. Con un servidor es aceptable; con cinco, no.
Ese es el disparador para retomarlo.
