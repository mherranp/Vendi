/*
 * Public API Surface of native
 *
 * Fachadas de las APIs de plataforma con fallback web.
 * Único punto del workspace autorizado a importar @capacitor/*.
 * Permite que la misma base de código corra como PWA y como app nativa.
 */

export { esPlataformaNativa, nombreDePlataforma } from './lib/plataforma';
