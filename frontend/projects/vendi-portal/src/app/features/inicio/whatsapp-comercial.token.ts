import { InjectionToken } from '@angular/core';

import { environment } from '../../../environments/environment';

/**
 * Número comercial de WhatsApp en formato `wa.me`: solo dígitos, con código
 * de país y SIN '+' (p. ej. '573001234567'). El spec del hero bloquea ese
 * formato: un '+' o un espacio rompe el enlace silenciosamente.
 *
 * La cadena vacía significa «todavía no hay número oficial»: el CTA de
 * captación no se pinta (decisión 3 del plan). Cuando operaciones tenga el
 * número es UNA línea en `environment.ts` y rebuild — el portal es estático
 * y no hay configuración en caliente.
 */
export const WHATSAPP_COMERCIAL = new InjectionToken<string>('WHATSAPP_COMERCIAL', {
  providedIn: 'root',
  factory: () => environment.whatsappComercial,
});
