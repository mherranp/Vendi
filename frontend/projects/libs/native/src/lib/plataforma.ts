import { Capacitor } from '@capacitor/core';

/**
 * Fachada de detección de plataforma.
 *
 * Es el **único** punto del workspace, junto con el resto de esta librería, que
 * puede importar `@capacitor/*` (ADR-011, spec §6.3). Las aplicaciones —incluida
 * `vendi-app`— consultan la plataforma a través de aquí, nunca importando
 * `@capacitor/core` directamente: así el día que Capacitor cambie de API o se
 * sustituya, el cambio queda contenido en `native`.
 *
 * Deliberadamente es una función suelta y no un servicio inyectable: se usa en
 * `app.config.ts`, durante la construcción de los providers, antes de que exista
 * un inyector del que tirar.
 */

/**
 * ¿La aplicación corre dentro del contenedor nativo (Android/iOS) o como web?
 *
 * Devuelve `false` en cualquier navegador, incluido el servidor de desarrollo y
 * la PWA instalada.
 */
export function esPlataformaNativa(): boolean {
  return Capacitor.isNativePlatform();
}

/**
 * Nombre de la plataforma en la que corre la aplicación: `'android'`, `'ios'` o
 * `'web'`. Útil para decisiones de tres vías donde `esPlataformaNativa()` se
 * queda corta.
 */
export function nombreDePlataforma(): string {
  return Capacitor.getPlatform();
}
