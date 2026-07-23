# Cliente generado de la API

Este directorio lo escribe `scripts/codegen-api-client.sh`. **Nada de lo que hay
aquí se edita a mano.**

| Archivo | Qué es |
|---|---|
| `openapi.json` | El esquema OpenAPI tal cual lo sirvió la API, guardado para poder auditar de qué contrato salieron los tipos |
| `index.ts` | Los tipos TypeScript (`paths`, `components`, `operations`) generados con `openapi-typescript` |

Ambos se commitean: el criterio de integración de la Etapa 4 exige que
regenerar el cliente y ejecutar `git diff --exit-code` no produzca cambios, y
eso solo se puede comprobar si el resultado está versionado.

## Regenerar

```bash
# Contra la API viva del stack local (necesita ./scripts/dev.sh levantado)
./scripts/codegen-api-client.sh

# Contra el esquema congelado de Fase 0 (reproducible, no necesita stack)
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json ./scripts/codegen-api-client.sh
```

En Fase 0, hasta que la Etapa 4 entregue el módulo `tenants`, no hay esquema que
consumir: el script falla en rojo con el motivo, y ese es el comportamiento
correcto — nunca deja un cliente a medias ni reutiliza el anterior en silencio.

## Exposición

Los tipos se consumen desde las apps a través del barril de `data-access`
(`import type { paths } from 'data-access'`). La reexportación desde
`src/public-api.ts` se añade en la Tarea 3.10, cuando la librería deja de estar
vacía.
