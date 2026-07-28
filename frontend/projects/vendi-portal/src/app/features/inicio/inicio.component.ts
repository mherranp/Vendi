import { Component } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';

import { ConfianzaComponent } from './confianza/confianza.component';
import { HeroComponent } from './hero/hero.component';
import { PreciosComponent } from './precios/precios.component';

/**
 * La landing pública de Vendi (Fase 1, Etapa 1.3, pista comercial).
 *
 * Una sola página con anclas: hero (propuesta de valor y captación por
 * WhatsApp), precios (ADR-010) y confianza. Sin rutas nuevas: `/precios`
 * como ruta llegará con el `/pro` transaccional de Fase 2.
 *
 * El enlace a la consola se escribe como URL absoluta y no como ruta de
 * Angular porque `app.vendi.co` es **otra aplicación**, servida por otro
 * origen; un `routerLink` no llegaría allí.
 */
@Component({
  selector: 'vd-inicio',
  imports: [TranslateModule, HeroComponent, PreciosComponent, ConfianzaComponent],
  templateUrl: './inicio.component.html',
  styleUrl: './inicio.component.scss',
})
export class InicioComponent {
  readonly urlDeLaConsola = 'https://app.vendi.co';
}
