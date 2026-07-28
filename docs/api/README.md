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
| `POST /api/v1/compras` | `compra:crear` | compra a proveedor (texto libre, sin tabla de proveedores); mueve stock y `ultimo_costo` en la misma transacción; idempotente por `id` del cliente; total calculado en el servidor |
| `GET /api/v1/compras` | `compra:crear` | listado paginado (`PagedList`) |
| `GET /api/v1/compras/{id}` | `compra:crear` | detalle con ítems; 404 si es de otro negocio |
| `POST /api/v1/inventario/ajustes` | `inventario:ajustar` | ajuste por conteo o merma; ONLINE (no viaja por el sync, ADR-020); `motivo` e `id` obligatorios; reintento idéntico = no-op, divergente = 409 |
| `GET /api/v1/inventario/ajustes` | `inventario:ajustar` | listado paginado con motivo y `aplicado_por` |
| `GET /api/v1/inventario/stock` | `producto:leer` | stock con nivel derivado (`agotado`/`critico`/`bajo`/`ok`); `solo_alertas=true` filtra |
| `POST /api/v1/caja/sesiones` | `caja:abrir` | abre la caja del día con `base_inicial`; UNA abierta por tienda (índice único parcial, ADR-021); acepta `id` del cliente (idempotente); 409 `caja_ya_abierta` si ya hay |
| `GET /api/v1/caja/sesiones/actual` | `caja:leer` | la sesión abierta; `efectivo_esperado` viaja en `null` sin `caja:cerrar` (mismo patrón que `ultimo_costo`); 404 `caja_sin_sesion_abierta` |
| `GET /api/v1/caja/sesiones` | `caja:cerrar` | historial paginado con el arqueo congelado (faltantes/sobrantes son del dueño) |
| `POST /api/v1/caja/sesiones/{id}/cerrar` | `caja:cerrar` | el arqueo: calcula `esperado = base + ventas efectivo completadas + abonos de fiado en efectivo + ingresos − egresos − devoluciones` desde las tablas de origen y lo CONGELA; reintento con el mismo `contado` devuelve lo firmado, con otro es 409 `caja_ya_cerrada` |
| `POST /api/v1/caja/movimientos` | `caja:movimiento` | ingreso/egreso manual con `categoria` cerrada y `motivo` obligatorio; `id` del cliente requerido; reintento idéntico = no-op, divergente = 409; 409 `caja_sin_sesion_abierta` |
| `GET /api/v1/caja/movimientos` | `caja:leer` | listado paginado de una sesión (la abierta por defecto) |
| `GET /api/v1/reportes/pyl` | `reporte:leer` | P&L simple del período (`dia`/`semana`/`mes` en America/Bogota, `fecha` opcional); cada número declara su fuente en `fuentes`; el costo es `ultimo_costo` ACTUAL (declarado) |
| `GET /api/v1/reportes/forecast` | `reporte:leer` | forecast a 30 días: saldo vivo + promedio ventas efectivo 30d + cobros fiado (saldo de créditos vigente/vencido que vencen en la ventana; los sin fecha no entran) − promedio egresos 30d |
| `POST /api/v1/clientes` | `cliente:gestionar` | alta con `id` del cliente opcional (idempotente); divergente = 409 `cliente_id_divergente`; choque de id ajeno = 409 `cliente_id_en_conflicto` |
| `GET /api/v1/clientes` | `cliente:gestionar` | la libreta con `saldo_pendiente_total` (SUM calculado, ADR-022) y `cupo_excedido`; `q` busca por nombre |
| `GET /api/v1/clientes/{id}` | `cliente:gestionar` | ficha con saldo, cupo y los fiados con deuda (lo que vence primero arriba) |
| `PATCH /api/v1/clientes/{id}` | `cliente:gestionar` | edición parcial; `null` explícito borra (quitar el cupo = «sin tope»); no hay DELETE (el cuaderno referencia) |
| `GET /api/v1/fiado/creditos` | `fiado:crear` | el cuaderno: pendientes por defecto (`vigente`+`vencido`), `estado=todos` incluye la historia |
| `GET /api/v1/fiado/creditos/{id}` | `fiado:crear` | detalle con historial de abonos y `whatsapp_url` prearmada (null sin teléfono) |
| `PATCH /api/v1/fiado/creditos/{id}` | `fiado:crear` | reprogramar vencimiento; `fecha_vencimiento` es REQUERIDA (`null` explícito = «sin fecha»; body `{}` = 422); un `vencido` a futuro vuelve a `vigente`; `saldado`/`anulado` = 409 `credito_no_editable` |
| `POST /api/v1/fiado/creditos/{id}/abonos` | `fiado:abonar` | descuenta el saldo en la misma transacción (CHECK como red); `id` requerido (ancla); exceso = 422 `abono_excede_saldo`; `efectivo` exige caja abierta (409 `caja_sin_sesion_abierta`) y entra al arqueo |

Todos los errores usan el mismo sobre: `{"success": false, "message": "...",
"code": "..."}`. El `code` es estable y es el que debe consumir el frontend para
decidir qué mensaje mostrar — `tenant_suspendido`, `requiere_platform_admin`,
`sin_organizacion_en_token`, `tenant_no_especificado`, `token_ausente`,
`token_invalido`, `producto_no_encontrado`, `codigo_barras_duplicado`,
`producto_id_duplicado`, `padre_no_encontrado`, `padre_es_el_mismo`,
`limite_de_productos_alcanzado`, `permiso_ausente`, `dispositivo_no_encontrado`,
`dispositivo_id_en_conflicto`,
`fecha_sin_zona`, `campos_desconocidos`, `compra_no_encontrada`,
`compra_id_duplicado`, `ajuste_id_divergente`, `total_fuera_de_rango`,
`caja_ya_abierta`, `caja_sin_sesion_abierta`, `caja_sesion_no_encontrada`,
`caja_ya_cerrada`, `sesion_id_duplicado`, `movimiento_id_divergente`,
`cliente_id_divergente`, `cliente_id_en_conflicto`, `cliente_no_encontrado`,
`credito_no_encontrado`, `credito_no_abonable`, `credito_no_editable`,
`abono_excede_saldo`, `abono_id_divergente`.

En las respuestas de productos, `ultimo_costo` viaja en `null` para quien no
tiene `compra:crear` (el cajero): los costos son el margen del negocio y viven
tras ese permiso. El campo sigue presente en el esquema (anulable); lo que
cambia con el permiso es su valor, no la forma de la respuesta.

En `POST /api/v1/sync/lotes` los rechazos de una operación NO son errores HTTP:
viajan en `ResultadoOperacion.motivo` cuando el resultado es `rechazada`. Los
motivos estables son `tipo_desconocido`, `datos_invalidos`,
`venta_id_divergente`, `producto_no_encontrado`, `consecutivo_duplicado`,
`fiado_requiere_cliente`, `cliente_solo_en_fiado`, `total_incoherente`,
`venta_no_encontrada`, `permiso_ausente`.

Eventos nuevos del outbox en este contrato: `compra.registrada` e
`inventario.alerta_stock` — este último se emite solo al cruzar un umbral de
stock hacia abajo, con payload `{producto_id, nivel, stock_actual,
stock_minimo}`, sin PII.

En `GET /api/v1/caja/sesiones/actual`, `efectivo_esperado` viaja en `null`
para quien no tiene `caja:cerrar` (el cajero): el esperado vivo es la cifra
con la que se cuadra un faltante antes del arqueo, y ADR-023 firma que el
cajero no cierra ni ve reportes. El campo sigue presente en el esquema
(anulable); lo que cambia con el permiso es su valor, no la forma.

El arqueo cerrado no se recalcula jamás: las columnas congeladas de la
sesión son la única fuente. Las ventas en efectivo y los abonos de fiado NO
se duplican como movimientos (ADR-021): el arqueo los suma desde su tabla de
origen — los abonos en efectivo desde `fiado_abonos` por la `sesion_caja_id`
que guardan al registrarse (ADR-022); los de otros métodos no tocan la
gaveta. La devolución de una venta anulada tras el cierre
cae en la sesión abierta en ese momento (vía `ventas.anulada_en`).

Eventos nuevos del outbox en este contrato: `caja.sesion_abierta`,
`caja.movimiento_registrado` y `caja.sesion_cerrada` — esta última con el
resumen completo del arqueo (desglose, esperado, contado, diferencia), que
es el insumo del briefing matutino de IA y de la telemetría.

El crédito nace en el sync (misma transacción de la venta fiada): el lote
gana la operación `cliente.crear` (el id del dispositivo ES la PK del
cliente) y la venta con `medio_pago="fiado"` acepta `fecha_vencimiento`
opcional. El servidor NO rechaza por cupo (ADR-018): la operación aceptada
lo señala con `detalles.cupo_excedido=true`. La anulación de la venta fiada
anula el crédito (`anulado`, saldo 0); los abonos son historia intocable y
la devolución del dinero es un egreso de caja manual.

Eventos nuevos del outbox en este contrato: `fiado.credito_creado`,
`fiado.abono_registrado`, `fiado.credito_saldado`, `fiado.credito_anulado` y
`fiado.credito_vencido` (este último lo emite el trabajo diario del worker;
lo consume el módulo de notificaciones para el push — sin PII en el
payload, ADR-025). El WhatsApp del recordatorio es un `wa.me` prearmado en
el detalle del crédito: manual y de coste cero (ADR-022).

Los abonos en efectivo entran al arqueo de la sesión abierta (sumados desde
`fiado_abonos`, nunca duplicados como movimiento) y el forecast proyecta los
cobros de fiado del saldo que vence en 30 días (los sin fecha no entran).
