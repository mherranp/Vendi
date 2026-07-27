# Registro de decisiones de arquitectura (ADR)

Un archivo por decisión. El formato es siempre el mismo y es deliberadamente
corto: **contexto** (qué presión obligó a decidir), **decisión** (una frase en
presente), **alternativas descartadas** (con el motivo, que es lo que nadie
recuerda seis meses después) y **consecuencias** (incluidas las malas).

Regla de este directorio: **un ADR no se edita para cambiar de opinión.** Si una
decisión se revierte, se escribe un ADR nuevo que la sustituya y se marca la
anterior como «Sustituida por ADR-0NN». Reescribir la historia borra justo el
dato que hace útil el registro: que en su momento la decisión parecía correcta,
y por qué.

| ADR | Decisión | Estado |
|---|---|---|
| [001](adr-001-capacitor.md) | Capacitor como empaquetado nativo desde el inicio | Firmada |
| [002](adr-002-rabbitmq-redis.md) | RabbitMQ como broker + Redis como cache | Firmada |
| [003](adr-003-multi-region.md) | Arquitectura multi-región federada por país | Firmada (Terraform diferido a Fase 2) |
| [004](adr-004-cobro-web-first.md) | Cobro de suscripciones web-first | Firmada |
| [005](adr-005-telemetria.md) | Telemetría/analytics del POS | **Abierta** |
| [006](adr-006-finanzas-simples.md) | P&L simple + forecast de caja a 30 días en el MVP | Firmada |
| [007](adr-007-ai-provider.md) | Capa `AIProvider` con interfaz OpenAI-compatible | Firmada |
| [008](adr-008-marketing-fase-3.md) | Módulo de marketing/publicidad a Fase 3 | Firmada |
| [009](adr-009-fiado-y-clientes.md) | Fiado + CRM mínimo de clientes en el MVP | Firmada |
| [010](adr-010-tiers-y-precios.md) | Tiers Gratis / Light / Pro + add-on DIAN | Firmada |
| [011](adr-011-fronteras-workspace-angular.md) | Fronteras de importación del workspace Angular | Firmada |
| [012](adr-012-cuatro-apps-angular.md) | Topología de las cuatro aplicaciones Angular | Firmada |
| [013](adr-013-rls-schema-unico.md) | Aislamiento por RLS en schema único, con dos roles | Firmada |
| [014](adr-014-realm-por-region-organizations.md) | Un realm por región con Organizations | Firmada |
| [015](adr-015-roles-de-negocio-como-roles-de-realm.md) | Roles de negocio como roles de realm | Firmada |
| [016](adr-016-backend-api-worker.md) | Backend monolito modular + worker sobre `vendi-core` | Firmada |
| [017](adr-017-sincronizacion-offline-first.md) | Sincronización offline-first: Dexie como verdad local, IDs de cliente, cola FIFO | Firmada |
| [018](adr-018-modelo-de-ventas-offline.md) | Venta append-only con consecutivo por dispositivo; dinero en centavos enteros | Firmada |
| [019](adr-019-catalogo-y-productos.md) | Catálogo: una tabla `productos` con variantes hijas y EAN único parcial | Firmada |
| [020](adr-020-inventario-y-compras.md) | Inventario por libro de movimientos + proyección; compras simples sin tabla proveedores | Firmada |
| [021](adr-021-caja-y-arqueo.md) | Una sesión de caja abierta por tienda; arqueo congelado al cierre | Firmada |
| [022](adr-022-fiado-y-clientes-tecnico.md) | Fiado por crédito individual con saldo materializado; recordatorios por push | Firmada |
| [023](adr-023-multi-empleado-permisos.md) | Catálogo cerrado de 14 permisos `recurso:accion` por rol de realm | Firmada |
| [024](adr-024-escaner-codigos.md) | Escáner en el dispositivo contra catálogo local; alta rápida dentro de la venta | Firmada |
| [025](adr-025-push-fcm.md) | FCM como canal push único de Fase 1, vía el evento único `notificacion.enviar` | Firmada |
| [026](adr-026-ia-v1-alcance-tecnico.md) | IA v1: function calling sobre funciones deterministas bajo RLS; voz solo tier Pro | Firmada |

Los ADR-001 … ADR-010 se decidieron antes de que existiera este directorio y
vivían como filas de una tabla en `docs/plan-maestro.md` §0 (los 001–004 con su
detalle en `docs/plan-tecnico.md` §3–§6). En la Etapa 5 de Fase 0 se migraron a
archivos sin cambiarles el contenido sustantivo; donde se añade algo nuevo, se
dice explícitamente que es de la Etapa 5.

Los ADR-017 … ADR-026 son la Etapa 1.1 de Fase 1 (2026-07-27): el diseño del
dominio de negocio del MVP según el plan de implementación
`docs/superpowers/plans/2026-07-27-fase1-mvp-colombia-plan.md`. Se escribieron
en paralelo por dominios (sync/ventas, catálogo/inventario, caja/fiado/empleados,
escáner/push/IA) y pasaron una revisión de coherencia cruzada antes de firmarse.
