# ADR-012 — Topología: cuatro aplicaciones Angular

**Fecha:** 2026-07-22 · **Estado:** Firmada (Fase 0)

## Contexto

Vendi tiene cuatro superficies con públicos, requisitos y ciclos de vida
distintos: el sitio público donde se vende, la consola del negocio, la consola
interna de la plataforma y el POS móvil.

## Decisión

Cuatro aplicaciones en el mismo workspace, cada una con su hostname:

| App | Hostname | Público | Autenticación |
|---|---|---|---|
| `vendi-portal` | `vendi.co`, `www.vendi.co` | anónimo | ninguna |
| `vendi-tenant` | `app.vendi.co` | dueño y empleados del negocio | Keycloak (`vendi-web`) |
| `vendi-admin` | `admin.vendi.co` | empleados de Vendi | Keycloak (`vendi-admin`) |
| `vendi-app` | binario Android/iOS | dueño y empleados, en el mostrador | Fase posterior |

## Alternativas descartadas

- **Una sola app con rutas.** El portal público tendría que descargar el bundle
  de la consola de administración para enseñar una página de precios, y el
  `redirectUri` del cliente de Keycloak cubriría también el sitio anónimo. Peor
  rendimiento en la superficie más sensible a él y una frontera de seguridad
  menos.
- **Cuatro repositorios.** Cuadruplica el coste de cambiar una lib compartida y
  garantiza que las versiones se desincronicen.

## Consecuencias

- Cada app tiene su cliente de Keycloak, con sus `redirectUris`. Un fallo de
  configuración en la consola de plataforma no abre la consola del negocio.
- **Vendi NO enruta por subdominio de negocio.** No hay `HostRegexp` comodín en
  Traefik: el negocio se resuelve del claim `organization` del token (ADR-014).
  Es lo que permite que un usuario con varios negocios cambie entre ellos sin
  cambiar de dominio ni volver a autenticarse.
- El coste real: cuatro `ng build` en CI y cuatro presupuestos de bundle que
  vigilar.
