# Contrato de la API — Fase 0

`openapi-fase0.json` es el esquema **congelado** de la API de Fase 0. De él sale
el cliente TypeScript de las apps Angular:

```bash
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json ./scripts/codegen-api-client.sh
```

## Por qué está congelado en el repositorio

El frontend no puede depender de que la API esté levantada para compilar, ni de
que la persona que regenera el cliente tenga exactamente la misma revisión del
backend corriendo. Con el esquema versionado, el cliente generado es una función
pura de un archivo del repositorio: `codegen` + `git diff --exit-code` demuestra
que nadie lo editó a mano.

## Cómo se regenera

Por el dominio y a través de Traefik, con la resolución fijada a esta máquina
(`vendi.co` es un dominio registrado por un tercero; ver
`docs/runbooks/dns-y-tls-local.md`):

```bash
curl -sS --resolve api.vendi.co:443:127.0.0.1 https://api.vendi.co/openapi.json \
  | python3 -c 'import json,sys; json.dump(json.load(sys.stdin), open("docs/api/openapi-fase0.json","w"), indent=2, ensure_ascii=False, sort_keys=True)'
```

`sort_keys=True` e `indent=2` no son cosméticos: sin un orden estable, cada
regeneración produce un diff enorme e ilegible y las revisiones dejan de mirar
qué cambió en el contrato.

## Qué hay dentro (Fase 0)

| Ruta | Quién puede | Qué hace |
|---|---|---|
| `GET /health` | cualquiera | sonda de vida, sin dependencias |
| `GET /health/ready` | cualquiera | sonda de disponibilidad (PG, Redis, Keycloak) |
| `GET /metrics` | credencial propia (`METRICS_TOKEN`) | exposición Prometheus; el borde además la bloquea |
| `POST /api/v1/platform/tenants` | `platform:admin` | alta de negocio + Organization con compensación |
| `GET /api/v1/platform/tenants` | `platform:admin` | listado paginado (`PagedList`) |
| `GET/PATCH/DELETE /api/v1/platform/tenants/{id}` | `platform:admin` | ver, renombrar/suspender, dar de baja |
| `GET /api/v1/tenants/me` | miembro del negocio | el negocio del token, y solo ése |

Todos los errores usan el mismo sobre: `{"success": false, "message": "...",
"code": "..."}`. El `code` es estable y es el que debe consumir el frontend para
decidir qué mensaje mostrar — `tenant_suspendido`, `requiere_platform_admin`,
`sin_organizacion_en_token`, `tenant_no_especificado`, `token_ausente`,
`token_invalido`.
