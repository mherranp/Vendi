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
export { authInterceptor } from './lib/auth.interceptor';
export { HasPermissionDirective } from './lib/has-permission.directive';
export { aliasDeOrganizaciones, rolesDeRealm } from './lib/token';
export type { ClaimOrganizacion, VendiTokenParsed } from './lib/token';

// El doble de Keycloak se exporta a propósito: las apps lo necesitan en sus
// propios specs (`vi.mock('keycloak-js', …)`) y duplicarlo en cada una sería
// garantizar que se desincronicen del claim real.
export { KeycloakFake, ORG_POR_DEFECTO } from './lib/keycloak.fake';
export type { PerfilFalso } from './lib/keycloak.fake';
