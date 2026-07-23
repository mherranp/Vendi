import { Component, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatMenuModule } from '@angular/material/menu';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

export interface ElementoDeNavegacion {
  /** Clave de traducción de la etiqueta. */
  etiqueta: string;
  /** Nombre del icono de Material Symbols. */
  icono: string;
  ruta: string;
}

/**
 * Shell de aplicación: barra lateral, barra superior y `router-outlet`.
 *
 * Cosechado de `ui-core/src/lib/layouts/full-layout` con tres cambios de fondo,
 * los tres exigidos por la frontera de ADR-011 ("ui-kit es presentación pura")
 * o por el alcance de Fase 0:
 *
 *  1. **No inyecta `AuthService`.** El original leía `auth.displayName()`,
 *     `auth.hasPermission()` y llamaba a `auth.logout()`. Aquí el nombre llega
 *     por `nombreUsuario`, el cierre de sesión sale como evento
 *     `cerrarSesion`, y el filtrado por permisos lo hace la app antes de pasar
 *     `navegacion` — que es quien conoce la sesión. `ui-kit` no puede importar
 *     `auth`: el lint lo impide.
 *  2. **Sin selector de idioma.** Fase 0 es solo Colombia y solo español; el
 *     menú de idiomas del original (y su `LOCALE_STORAGE_KEY`) sobra.
 *  3. **Sin campana de notificaciones empotrada.** El original instanciaba un
 *     componente que hacía HTTP. Aquí hay una ranura `[slot=acciones]` donde la
 *     app coloca lo que quiera, incluida `<vd-notifications-badge>` ya
 *     alimentada por ella.
 */
@Component({
  selector: 'vd-full-layout',
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatSidenavModule,
    MatToolbarModule,
    MatListModule,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatDividerModule,
    TranslateModule,
  ],
  templateUrl: './full-layout.component.html',
  styleUrls: ['./full-layout.component.scss'],
})
export class FullLayoutComponent {
  /** Nombre de la app que se pinta en la barra lateral. */
  readonly marca = input<string>('');
  /** Elementos de navegación **ya filtrados** por permisos por la app. */
  readonly navegacion = input<ElementoDeNavegacion[]>([]);
  /** Nombre visible del usuario en el menú de cuenta. */
  readonly nombreUsuario = input<string>('');
  /** Ruta del enlace "Mi cuenta". Vacío para ocultarlo. */
  readonly rutaCuenta = input<string>('');

  readonly cerrarSesion = output<void>();

  private readonly _lateralAbierto = signal(true);
  readonly lateralAbierto = this._lateralAbierto.asReadonly();

  alternarLateral(): void {
    this._lateralAbierto.update((v) => !v);
  }
}
