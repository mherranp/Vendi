# Contrato de la API — esquema congelado

`openapi-fase0.json` es el esquema **congelado** de la API. Se llama así por
historia —nació en la Fase 0— pero contiene el contrato vigente completo; es la
fuente única del codegen y del job `frontend-contratos` del CI. De él sale el
cliente TypeScript de las apps Angular:

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

## Qué hay dentro

| Ruta | Quién puede | Qué hace |
|---|---|---|
| `GET /health` | cualquiera | sonda de vida, sin dependencias |
| `GET /health/ready` | cualquiera | sonda de disponibilidad (PG, Redis, Keycloak) |
| `GET /metrics` | credencial propia (`METRICS_TOKEN`) | exposición Prometheus; el borde además la bloquea |
| `POST /api/v1/platform/tenants` | `platform:admin` | alta de negocio + Organization con compensación |
| `GET /api/v1/platform/tenants` | `platform:admin` | listado paginado (`PagedList`) |
| `GET/PATCH/DELETE /api/v1/platform/tenants/{id}` | `platform:admin` | ver, renombrar/suspender, dar de baja |
| `GET /api/v1/tenants/me` | miembro del negocio | el negocio del token, y solo ése |
| `POST /api/v1/productos` | `producto:editar` | alta; acepta `id` del cliente (idempotente, ADR-017); 409 por EAN duplicado; 403 por límite del tier |
| `GET /api/v1/productos` | `producto:leer` | listado paginado (`PagedList`) con `q` (nombre) y `categoria` |
| `GET /api/v1/productos/por-codigo/{codigo}` | `producto:leer` | el camino del escáner: un EAN → un producto |
| `GET/PATCH/DELETE /api/v1/productos/{id}` | `producto:leer` / `producto:editar` | ver, editar (sin `stock_actual` ni `ultimo_costo`), borrado lógico |
| `POST /api/v1/dispositivos` | `venta:crear` | registro de dispositivo; acepta `id` del cliente (idempotente, ADR-017) |
| `POST /api/v1/sync/lotes` | `venta:crear` | lote de ≤200 operaciones; 200 con resultado por operación (`aceptada`/`duplicada`/`rechazada`); eventos una sola vez por aceptada |
| `GET /api/v1/sync/delta` | `producto:leer` | cambios del catálogo desde `desde`; `hasta` es el próximo watermark (reloj del servidor); `eliminados` son tumbas |

Todos los errores usan el mismo sobre: `{"success": false, "message": "...",
"code": "..."}`. El `code` es estable y es el que debe consumir el frontend para
decidir qué mensaje mostrar — `tenant_suspendido`, `requiere_platform_admin`,
`sin_organizacion_en_token`, `tenant_no_especificado`, `token_ausente`,
`token_invalido`, `producto_no_encontrado`, `codigo_barras_duplicado`,
`producto_id_duplicado`, `padre_no_encontrado`, `padre_es_el_mismo`,
`limite_de_productos_alcanzado`, `permiso_ausente`, `dispositivo_no_encontrado`,
`fecha_sin_zona`, `campos_desconocidos`.

En `POST /api/v1/sync/lotes` los rechazos de una operación NO son errores HTTP:
viajan en `ResultadoOperacion.motivo` cuando el resultado es `rechazada`. Los
motivos estables son `tipo_desconocido`, `datos_invalidos`,
`venta_id_divergente`, `producto_no_encontrado`, `consecutivo_duplicado`,
`fiado_requiere_cliente`, `cliente_solo_en_fiado`, `total_incoherente`,
`venta_no_encontrada`, `permiso_ausente`.
