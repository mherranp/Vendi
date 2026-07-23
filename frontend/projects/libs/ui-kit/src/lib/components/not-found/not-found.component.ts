import { Component, input } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

/** Página 404. Cosechado de `ui-components/not-found`. */
@Component({
  selector: 'vd-not-found',
  imports: [MatIconModule, MatButtonModule, RouterLink, TranslateModule],
  templateUrl: './not-found.component.html',
  styleUrls: ['./not-found.component.scss'],
})
export class NotFoundComponent {
  readonly enlaceInicio = input<string>('/');
  readonly textoInicio = input<string>('ui.404.volver');
  readonly titulo = input<string>('ui.404.titulo');
  readonly descripcion = input<string>('ui.404.descripcion');
}
