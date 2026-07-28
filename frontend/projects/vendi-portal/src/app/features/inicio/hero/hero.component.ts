import { Component, inject } from '@angular/core';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

import { WHATSAPP_COMERCIAL } from '../whatsapp-comercial.token';

/**
 * Hero de la landing: la propuesta de valor («del cuaderno al celular») y los
 * dos caminos del visitante.
 *
 * Captación de Fase 1, alcance honesto (decisiones 1 y 2 del plan): NO hay
 * formulario de interés con backend —la infra de notificación es Fase 2 y una
 * tabla de leads sin consumidor es peor que no tenerla— y NO hay
 * auto-registro —el realm no lo tiene abierto, así que un «empieza gratis»
 * hacia la app sería mentira—. El canal de captación es el que ya usa la
 * venta: WhatsApp con mensaje prearmado. Mientras no haya número oficial
 * configurado, el CTA no se pinta.
 */
@Component({
  selector: 'vd-hero',
  imports: [TranslateModule],
  templateUrl: './hero.component.html',
  styleUrl: './hero.component.scss',
})
export class HeroComponent {
  /**
   * Consola web del negocio. URL absoluta fija a propósito: `app.vendi.co` es
   * OTRA aplicación servida en otro origen; un `routerLink` no llegaría allí.
   */
  readonly urlDeLaConsola = 'https://app.vendi.co';

  /**
   * Enlace `wa.me` con el mensaje prearmado, o `null` cuando no hay número
   * configurado: la plantilla no pinta el CTA con `null`.
   */
  readonly enlaceWhatsapp: string | null;

  constructor() {
    const numero = inject(WHATSAPP_COMERCIAL);
    const traductor = inject(TranslateService);
    this.enlaceWhatsapp = numero
      ? `https://wa.me/${numero}?text=${encodeURIComponent(traductor.instant('portal.hero.whatsapp_mensaje'))}`
      : null;
  }
}
