/**
 * Entorno de PRODUCCIÓN de `vendi-admin` (consola de plataforma; somos nosotros).
 *
 * Se sirve en `https://admin.vendi.co` (ver `infra/traefik/templates/dynamic.yml.tpl`).
 * Usa su propio cliente público PKCE `vendi-admin` del realm `vendi-co`: NO
 * comparte cliente con las apps de tenant, para que los redirect URIs de la
 * consola de plataforma y los de los negocios no se solapen.
 *
 * Nunca debe contener URLs de desarrollo.
 */
export const environment = {
  production: true,
  apiUrl: 'https://api.vendi.co/api/v1',
  keycloakUrl: 'https://accounts.vendi.co',
  realm: 'vendi-co',
  clientId: 'vendi-admin',
};
