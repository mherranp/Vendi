/**
 * Entorno de DESARROLLO de `vendi-app`.
 *
 * Se activa por `fileReplacements` en la configuración `development` de
 * angular.json: nunca se empaqueta en un build de producción ni en el AAB.
 *
 * Apunta al stack local de `infra/` (Traefik + dnsmasq + certificados de
 * `scripts/setup-certs.sh`), no a `localhost:8000`: la API y Keycloak solo se
 * exponen por sus hosts `*.vendi.local`.
 *
 * En web esta app se sirve con `ng serve` en el puerto **4200**; su redirect
 * URI (`http://localhost:4200/*`) está registrado en el cliente `vendi-web`
 * del realm, junto a los esquemas nativos (`capacitor://localhost/*`,
 * `co.vendi.app://*`) que usará la Etapa de auth móvil.
 */
export const environment = {
  production: false,
  apiUrl: 'https://api.vendi.local/api/v1',
  keycloakUrl: 'https://accounts.vendi.local',
  realm: 'vendi-co',
  clientId: 'vendi-web',
};
