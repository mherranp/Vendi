/**
 * Entorno de DESARROLLO de `vendi-portal`.
 *
 * Apunta al stack local de `infra/` (`*.vendi.co` vía Traefik + dnsmasq).
 * Sin Keycloak, igual que en producción: el portal es público.
 *
 * Para probar el CTA de WhatsApp en local, pon aquí un número de prueba en
 * formato `wa.me` (solo dígitos); en producción el CTA nace oculto hasta que
 * exista el número oficial.
 */
export const environment = {
  production: false,
  apiUrl: 'https://api.vendi.co/api/v1',
  whatsappComercial: '',
};
