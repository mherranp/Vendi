import { TranslateService } from '@ngx-translate/core';
import { textoDeRespaldo } from './catalogo-minimo';

/**
 * Traduce una clave garantizando que **nunca** se devuelve la clave cruda.
 *
 * `TranslateService.instant()` devuelve la propia clave cuando no la encuentra
 * (`'errores.servidor'`), que es exactamente lo que no debe leer un tendero.
 * Aquí, si la traducción coincide con la clave o viene vacía, se cae al texto
 * empotrado del catálogo mínimo y, en último extremo, al respaldo que pase quien
 * llama.
 *
 * @param traductor servicio de ngx-translate ya inyectado
 * @param clave clave con notación de punto
 * @param respaldo texto a usar si ni el catálogo ni el mínimo tienen la clave
 */
export function traducir(traductor: TranslateService, clave: string, respaldo = ''): string {
  let traducido: unknown;
  try {
    traducido = traductor.instant(clave);
  } catch {
    // `instant()` puede reventar si se llama antes de que el store exista
    // (arranque muy temprano, o un test que no configuró el servicio).
    traducido = undefined;
  }
  if (typeof traducido === 'string' && traducido.length > 0 && traducido !== clave) {
    return traducido;
  }
  return textoDeRespaldo(clave) ?? respaldo;
}
