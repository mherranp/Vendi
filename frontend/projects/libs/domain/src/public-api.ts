/*
 * Public API Surface of domain
 *
 * Lógica de negocio pura: modelos y motor de reglas deterministas.
 * Sin Angular, sin RxJS, sin red, sin persistencia, sin UI.
 * La regla de oro: el código decide, la IA narra.
 *
 * Los nombres de tipo se mantienen tal como los fija el plan (`ApiResponse`,
 * `PagedList`, `Tenant`, `UserProfile`); los campos, las funciones nuevas y
 * toda la documentación van en español, como el resto del repositorio.
 */

export type { ApiError, ApiResponse, PagedList } from './lib/models/api-response.model';
export type { UserProfile } from './lib/models/user.model';
export type { EstadoTenant, Tenant } from './lib/models/tenant.model';
export { ESTADOS_TENANT, esEstadoTenant } from './lib/models/tenant.model';
export { esEstadoVisible, esIdDeTenant, esTenantOperativo } from './lib/reglas/tenant.reglas';
