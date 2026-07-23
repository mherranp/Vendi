/**
 * Entorno de PRODUCCIÓN de `vendi-tenant` (consola web del dueño del negocio).
 *
 * Se sirve en `https://app.vendi.co` (ver `infra/traefik/templates/dynamic.yml.tpl`).
 * Comparte con `vendi-app` el cliente público PKCE `vendi-web` del realm
 * `vendi-co` (Tarea 2.4, Paso 1).
 *
 * Nunca debe contener URLs de desarrollo: el reemplazo lo hace
 * `fileReplacements` de la configuración `development`, no al revés.
 */
export const environment = {
  production: true,
  apiUrl: 'https://api.vendi.co/api/v1',
  keycloakUrl: 'https://accounts.vendi.co',
  realm: 'vendi-co',
  clientId: 'vendi-web',
};
