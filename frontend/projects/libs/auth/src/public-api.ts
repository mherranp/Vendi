/*
 * Public API Surface of auth
 *
 * Identidad (OIDC contra Keycloak), sesión y entitlements de plan.
 * El login abre el navegador del sistema vía la fachada de native,
 * NUNCA dentro del WebView: los passkeys no funcionan ahí.
 */

export {};
