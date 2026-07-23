import { Component, input } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';

/**
 * Cabecera de página: título, subtítulo opcional y ranura de acciones.
 *
 * Cosechado de `ui-components/page-header`. Las acciones se proyectan con
 * `<div slot="acciones">…</div>`.
 */
@Component({
  selector: 'vd-page-header',
  imports: [TranslateModule],
  templateUrl: './page-header.component.html',
  styleUrls: ['./page-header.component.scss'],
})
export class PageHeaderComponent {
  readonly titulo = input.required<string>();
  readonly subtitulo = input<string>('');
}
