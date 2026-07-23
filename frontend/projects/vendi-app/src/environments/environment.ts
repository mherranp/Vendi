/**
 * Entorno de PRODUCCIÓN de `vendi-app` (móvil Capacitor).
 *
 * Este es el archivo que se compila por defecto (`defaultConfiguration:
 * "production"` en angular.json) y, por tanto, **el que acaba dentro del AAB**.
 * No puede contener jamás una URL de desarrollo: el reemplazo va en la
 * dirección contraria (`fileReplacements` de la configuración `development`
 * sustituye este archivo por `environment.development.ts`).
 *
 * Dominio de producción: `vendi.co` (BASE_DOMAIN de producción; en desarrollo
 * el stack de `infra/` usa `vendi.co` vía dnsmasq + certificados locales).
 *
 * Identidad: `vendi-app` y `vendi-tenant` comparten el cliente público PKCE
 * `vendi-web` del realm `vendi-co` (Tarea 2.4, Paso 1). En Fase 0 la app móvil
 * todavía NO hace login —la autenticación móvil es el subproyecto 2—, pero la
 * configuración se declara aquí para que el cableado de la Etapa 4 no tenga
 * que tocar dos sitios.
 */
export const environment = {
  production: true,
  apiUrl: 'https://api.vendi.co/api/v1',
  keycloakUrl: 'https://accounts.vendi.co',
  realm: 'vendi-co',
  clientId: 'vendi-web',
};
