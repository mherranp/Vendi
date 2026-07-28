import { Component } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';

/**
 * Las tres pruebas de confianza de la landing.
 *
 * Cada afirmación es cierta del producto de Fase 1 — no es copy inflado:
 * «funciona sin internet» es ADR-017 ya entregado, «cada tienda ve solo lo
 * suyo» es la RLS de ADR-013, y «habla como se habla en el mostrador» es el
 * granel por kilos y el fiado por persona. Si una deja de ser cierta, el copy
 * se corrige el mismo día: la confianza es la moneda del segmento.
 */
@Component({
  selector: 'vd-confianza',
  imports: [TranslateModule],
  templateUrl: './confianza.component.html',
  styleUrl: './confianza.component.scss',
})
export class ConfianzaComponent {
  readonly puntos = ['punto_1', 'punto_2', 'punto_3'] as const;
}
