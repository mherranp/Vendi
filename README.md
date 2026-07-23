# Vendi

Software de gestión para la tienda de barrio: punto de venta, inventario, caja,
fiado y un asistente que explica cómo va el negocio. Colombia primero.

Este repositorio contiene la **fundación técnica** (Fase 0): la infraestructura,
el aislamiento multi-negocio, la identidad y los cuatro esqueletos de
aplicación sobre los que se construirá el producto. El POS y el resto del
dominio son Fase 1.

---

## Empezar

```bash
cp .env.example .env          # y cambia TODAS las contraseñas
./scripts/setup-dnsmasq.sh    # pide sudo: *.vendi.co -> 127.0.0.1
mkcert -install && ./scripts/setup-certs.sh
./scripts/dev.sh
bash scripts/migrate.sh && bash scripts/seed.sh
bash scripts/verify-setup.sh
```

La guía completa, con requisitos previos, usuarios de prueba, cómo registrar una
passkey y qué hacer cuando algo falla: **[`docs/getting-started.md`](docs/getting-started.md)**.

> ⚠️ `vendi.co` es un dominio **real, registrado por un tercero**. Hasta que
> `/etc/resolver/vendi.co` exista, cada petición a `*.vendi.co` sale a Internet
> —a un servidor que no es nuestro y con certificado válido, así que nada
> avisa—. Es el paso que necesita `sudo` y no se puede saltar. Detalle en
> [`docs/runbooks/dns-y-tls-local.md`](docs/runbooks/dns-y-tls-local.md).

---

## Qué hay dentro

```
backend/
  libs/vendi-core/      librería transversal (auth, RLS, auditoría, outbox,
                        retención, almacenamiento, observabilidad)
  services/api/         monolito modular FastAPI + migraciones de Alembic
  services/worker/      dispatcher del outbox y trabajos programados
  tests/                suite única; los `integration` usan servicios reales
frontend/
  projects/libs/        domain · data-access · ui-kit · auth · native
  projects/vendi-portal   sitio público            → vendi.co
  projects/vendi-tenant   consola del negocio      → app.vendi.co
  projects/vendi-admin    consola de plataforma    → admin.vendi.co
  projects/vendi-app      POS móvil (Capacitor)    → Android/iOS
infra/                  docker compose, Traefik, Keycloak (realm como código),
                        PostgreSQL, Prometheus, Grafana
scripts/                dev · migrate · seed · verify-setup · reconcile-keycloak
docs/                   arquitectura, ADRs, runbooks, deuda técnica
```

Stack: Python 3.12 · FastAPI · SQLAlchemy 2 async · PostgreSQL 17 · Angular 21 ·
Capacitor 8 · Keycloak 26.6.4 · RabbitMQ 4 · Redis 7 · MinIO · Traefik · uv.

---

## Las tres decisiones que explican casi todo

1. **Un negocio no ve los datos de otro, y lo garantiza PostgreSQL.**
   Row Level Security en schema único, con dos roles: el de la API **no tiene**
   `BYPASSRLS`, así que no puede saltarse una policy ni por error de
   programación. → [ADR-013](docs/adr/adr-013-rls-schema-unico.md)
2. **La identidad es un realm por región con una Organization por negocio.**
   El alias de la Organization **es** el `tenant_id`, así que el negocio se
   resuelve del token sin consultar a nadie.
   → [ADR-014](docs/adr/adr-014-realm-por-region-organizations.md)
3. **La fundación se cosechó de BaseSaaS, archivo por archivo.**
   Cada archivo lleva en su cabecera de dónde vino y qué se cambió. Lo que no
   se adaptó no entró. → [ADR-016](docs/adr/adr-016-backend-api-worker.md)

---

## Documentación

| Documento | Para qué |
|---|---|
| [`docs/getting-started.md`](docs/getting-started.md) | de cero a iniciar sesión |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | mapa del sistema y registro de la cosecha |
| [`docs/adr/`](docs/adr/) | las 16 decisiones, con su porqué y sus consecuencias |
| [`docs/env-reference.md`](docs/env-reference.md) | qué hace cada variable de entorno |
| [`docs/runbooks/`](docs/runbooks/) | procedimientos de operación |
| [`docs/deuda-tecnica.md`](docs/deuda-tecnica.md) | lo que está mal a sabiendas, con fecha de vencimiento |
| [`docs/estado.md`](docs/estado.md) | qué se entregó de verdad y qué no |
| [`docs/plan-maestro.md`](docs/plan-maestro.md) | producto, mercado y roadmap (fuente canónica) |

---

## Convenciones

- **Todo en español**: código comentado, documentación, mensajes de error de
  cara al usuario. Los identificadores técnicos van sin tildes ni eñes
  (`dueno`, no `dueño`): viajan por roles de Keycloak, claves de JSON, URLs y
  literales de TypeScript, y cada salto es una oportunidad de romper el
  round-trip de UTF-8. La etiqueta que ve el usuario sí lleva la eñe, y vive en
  el catálogo de i18n.
- **Se prueba por el dominio y a través de Traefik**, sobre HTTPS y con el
  certificado del sistema. Nunca `localhost:<puerto>`, nunca `curl -k`. Si algo
  solo funciona por el puerto pelado, eso es un defecto: la topología que se
  despliega es la del dominio.
- **Un comentario explica por qué, no qué.** El código ya dice qué hace.
