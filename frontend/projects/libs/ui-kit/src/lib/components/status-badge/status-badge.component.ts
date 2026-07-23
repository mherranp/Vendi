import { Component, input } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';

export type VarianteEstado = 'exito' | 'info' | 'aviso' | 'peligro' | 'neutro';

/**
 * Etiqueta de estado. Cosechado de `ui-components/status-badge` con las
 * variantes renombradas al español.
 */
@Component({
  selector: 'vd-status-badge',
  imports: [TranslateModule],
  templateUrl: './status-badge.component.html',
  styleUrls: ['./status-badge.component.scss'],
})
export class StatusBadgeComponent {
  readonly etiqueta = input.required<string>();
  readonly variante = input<VarianteEstado>('neutro');
}
