"""vendi-core: librería transversal del backend de Vendi.

Cosechada de `base_saas` (BaseSaaS) con la tenancy reescrita: donde BaseSaaS
usaba schema-per-tenant y `search_path`, Vendi usa schema único regional con
Row Level Security de PostgreSQL y el GUC `vendi.tenant_id`.

Los paquetes (`db`, `tenant`, `auth`, `audit`, `messaging`, ...) llegan en la
Etapa 3 del plan de Fase 0. En la Etapa 2 este paquete solo existe para que el
workspace uv resuelva y los servicios puedan declararlo como dependencia.
"""

__version__ = "0.1.0"
