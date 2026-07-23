/**
 * Entorno de PRODUCCIÓN de `vendi-portal` (sitio público: producto y planes).
 *
 * Se sirve en `https://vendi.co` y `https://www.vendi.co`
 * (ver `infra/traefik/templates/dynamic.yml.tpl`).
 *
 * **No lleva configuración de Keycloak a propósito** (Tarea 2.4, Paso 1: "el
 * portal no usa Keycloak"). En Fase 0 el portal es contenido público sin
 * sesión; declarar aquí un `clientId` sugeriría un flujo de login que no
 * existe y dejaría configuración muerta que alguien acabaría copiando. Cuando
 * llegue `/cuenta` (subproyecto de monetización) se añadirá entonces, con su
 * redirect URI registrado en el realm.
 */
export const environment = {
  production: true,
  apiUrl: 'https://api.vendi.co/api/v1',
};
