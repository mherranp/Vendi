/**
 * Entorno de DESARROLLO de `vendi-tenant`.
 *
 * Apunta al stack local de `infra/` (`*.vendi.local` vía Traefik + dnsmasq).
 * Se activa por `fileReplacements` en la configuración `development` de
 * angular.json.
 *
 * En desarrollo esta app se sirve con `ng serve` en el puerto **4202**, no por
 * Traefik: el redirect URI que ve Keycloak es `http://localhost:4202/*` y está
 * registrado en el cliente `vendi-web` del realm. Si cambias el puerto en
 * angular.json, cambia también el redirect URI en
 * `infra/keycloak/realm-vendi-co.json` o el login falla con
 * `invalid_redirect_uri`.
 */
export const environment = {
  production: false,
  apiUrl: 'https://api.vendi.local/api/v1',
  keycloakUrl: 'https://accounts.vendi.local',
  realm: 'vendi-co',
  clientId: 'vendi-web',
};
