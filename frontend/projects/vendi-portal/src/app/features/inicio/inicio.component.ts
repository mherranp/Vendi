import { Component } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';

/**
 * Página pública del portal.
 *
 * Fase 0 no incluye monetización ni captación (subproyecto 4), así que aquí no
 * hay formulario de registro ni precios: solo lo que es cierto hoy —qué es
 * Vendi— y un enlace a la consola del negocio.
 *
 * El enlace se escribe como URL absoluta y no como ruta de Angular porque
 * `app.vendi.co` es **otra aplicación**, servida por otro origen; un
 * `routerLink` no llegaría allí.
 */
@Component({
  selector: 'vd-inicio',
  imports: [TranslateModule],
  templateUrl: './inicio.component.html',
  styleUrl: './inicio.component.scss',
})
export class InicioComponent {
  /**
   * Consola web del negocio.
   *
   * Se deja fija en el dominio de producción a propósito: el portal es
   * público y estático, y en desarrollo se abre a mano la app en su puerto.
   * Meterla en `environment` obligaría a mantener una URL más por app sin que
   * nada la lea en Fase 0.
   */
  readonly urlDeLaConsola = 'https://app.vendi.co';
}
