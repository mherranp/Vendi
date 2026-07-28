/*
 * Public API Surface of auth
 *
 * Identidad (OIDC contra Keycloak), sesión y entitlements de plan.
 * El login abre el navegador del sistema vía la fachada de native,
 * NUNCA dentro del WebView: los passkeys no funcionan ahí.
 */

export { AuthService, SCOPE_ORGANIZACIONES } from './lib/auth.service';
export type { ConfiguracionAuth } from './lib/auth.service';
export { authGuard, roleGuard, tenantGuard } from './lib/auth.guard';
export { permisoGuard } from './lib/permiso.guard';
export { proveerSesion } from './lib/sesion.provider';
export { authInterceptor } from './lib/auth.interceptor';
export { HasPermissionDirective } from './lib/has-permission.directive';
export { aliasDeOrganizaciones, rolesDeRealm } from './lib/token';
export type { ClaimOrganizacion, VendiTokenParsed } from './lib/token';

// El doble de Keycloak vive en el punto de entrada secundario `auth/testing`,
// no aquí. Las apps lo necesitan en sus propios specs y duplicarlo en cada una
// sería garantizar que se desincronicen del claim real, pero exportarlo desde
// este barril creaba un ciclo: la fábrica de `vi.mock('keycloak-js', …)`
// importaría `auth` → `AuthService` → `keycloak-js`, el módulo que está
// resolviendo. Ver `testing/src/public-api.ts`.
