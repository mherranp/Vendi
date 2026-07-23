/*
 * Envolturas de respuesta de la API de Vendi.
 *
 * Cosechado de `ui-core/src/lib/models/api-response.model.ts` de BaseSaaS con
 * dos cambios:
 *
 *  1. Se elimina `PaginatedResponse` (marcado `@deprecated` en el origen): era
 *     el formato antiguo `page/page_size/total_pages`. Vendi nace con la
 *     paginación `skip/limit` de la API (ver contrato de la Tarea 4.2), así que
 *     arrastrar el tipo muerto solo invitaría a usarlo.
 *  2. `Tenant` sale de aquí y vive en `tenant.model.ts`: no es una envoltura de
 *     transporte, es una entidad de negocio.
 */

/**
 * Envoltura estándar de las respuestas de un solo recurso.
 *
 * Nota: la mayoría de endpoints de Fase 0 devuelven el recurso desnudo. Este
 * tipo existe para los que sí envuelven (y para el cliente generado por
 * `codegen-api-client.sh`), no como obligación de toda respuesta.
 */
export interface ApiResponse<T = unknown> {
  success: boolean;
  data: T;
  message?: string;
}

/**
 * Envoltura de listado paginado (`skip`/`limit`) que devuelven los endpoints de
 * colección. `total` es el número de filas que la consulta vería sin paginar,
 * ya filtradas por RLS: nunca cuenta filas de otro tenant.
 */
export interface PagedList<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

/**
 * Cuerpo de error estándar de la API (`ErrorResponse` del backend).
 *
 * `codigo` viaja como `code` en el JSON; se declara con el nombre del cable
 * porque este tipo describe lo que llega por HTTP, no un modelo interno.
 */
export interface ApiError {
  message: string;
  code?: string;
}
