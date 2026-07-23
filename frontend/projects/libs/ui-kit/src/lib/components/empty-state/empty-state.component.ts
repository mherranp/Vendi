import { Component, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TranslateModule } from '@ngx-translate/core';

/**
 * Estado vacío: icono, título, descripción y una acción opcional.
 *
 * Cosechado de `ui-components/empty-state`. Los valores por defecto son claves
 * de traducción; quien lo use puede pasar las suyas.
 */
@Component({
  selector: 'vd-empty-state',
  imports: [MatIconModule, MatButtonModule, TranslateModule],
  templateUrl: './empty-state.component.html',
  styleUrls: ['./empty-state.component.scss'],
})
export class EmptyStateComponent {
  readonly icono = input<string>('inbox');
  readonly titulo = input<string>('ui.vacio.titulo');
  readonly descripcion = input<string>('');
  readonly textoAccion = input<string>('');
  readonly accion = output<void>();
}
