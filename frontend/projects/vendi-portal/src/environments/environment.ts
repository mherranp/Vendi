/**
 * Entorno de PRODUCCIÓN de `vendi-portal` (sitio público: producto y planes).
 *
 * Se sirve en `https://vendi.co` y `https://www.vendi.co`
 * (ver `infra/traefik/templates/dynamic.yml.tpl`).
 *
 * **No lleva configuración de Keycloak a propósito** (Tarea 2.4, Paso 1: "el
 * portal no usa Keycloak"). El portal es contenido público sin sesión;
 * declarar aquí un `clientId` sugeriría un flujo de login que no existe.
 * Cuando llegue `/cuenta` (subproyecto de monetización, Fase 2) se añadirá
 * entonces, con su redirect URI registrado en el realm.
 *
 * `whatsappComercial`: número oficial de ventas en formato `wa.me` (solo
 * dígitos, con código de país, sin '+'). Vacío = aún no existe: el CTA de
 * captación no se pinta (decisión 3 del plan comercial, Etapa 1.3). Cuando
 * operaciones lo tenga, es esta línea y rebuild de la imagen.
 */
export const environment = {
  production: true,
  apiUrl: 'https://api.vendi.co/api/v1',
  whatsappComercial: '',
};
