import { Component, input } from '@angular/core';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { TranslateModule } from '@ngx-translate/core';

/** Indicador de carga con etiqueta opcional. Cosechado de `ui-components`. */
@Component({
  selector: 'vd-loading-spinner',
  imports: [MatProgressSpinnerModule, TranslateModule],
  templateUrl: './loading-spinner.component.html',
  styleUrls: ['./loading-spinner.component.scss'],
})
export class LoadingSpinnerComponent {
  readonly tamano = input<number>(40);
  readonly etiqueta = input<string>('');
}
