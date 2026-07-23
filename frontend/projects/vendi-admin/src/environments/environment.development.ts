/**
 * Entorno de DESARROLLO de `vendi-admin`.
 *
 * Apunta al stack local de `infra/` (`*.vendi.co` vía Traefik + dnsmasq).
 * Se activa por `fileReplacements` en la configuración `development` de
 * angular.json.
 *
 * En desarrollo esta app se sirve con `ng serve` en el puerto **4203**, no por
 * Traefik: el redirect URI que ve Keycloak es `http://localhost:4203/*` y está
 * registrado en el cliente `vendi-admin` del realm. Si cambias el puerto en
 * angular.json, cambia también el redirect URI en
 * `infra/keycloak/realm-vendi-co.json` o el login falla con
 * `invalid_redirect_uri`.
 */
export const environment = {
  production: false,
  apiUrl: 'https://api.vendi.co/api/v1',
  keycloakUrl: 'https://accounts.vendi.co',
  realm: 'vendi-co',
  clientId: 'vendi-admin',
};
