/**
 * Entorno de DESARROLLO de `vendi-portal`.
 *
 * Apunta al stack local de `infra/` (`*.vendi.local` vía Traefik + dnsmasq).
 * Sin Keycloak, igual que en producción: el portal es público.
 */
export const environment = {
  production: false,
  apiUrl: 'https://api.vendi.local/api/v1',
};
