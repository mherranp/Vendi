import { Component, computed, inject } from '@angular/core';
import { AuthService } from 'auth';
import { Notificador } from 'data-access';
import { AvisosComponent, ElementoDeNavegacion, FullLayoutComponent } from 'ui-kit';

/**
 * Marco de la consola web del negocio.
 *
 * Igual que en `vendi-admin`, `FullLayoutComponent` no conoce la sesión
 * (ADR-011) y este componente es el puente: nombre del usuario, navegación y
 * cierre de sesión. Los avisos se pintan con el `vd-avisos` de `ui-kit`,
 * al que se le pasa el `Notificador` por input — el kit no puede conocer
 * `data-access` (ADR-011), así que el puente vive aquí.
 *
 * La navegación de Fase 0 tiene una sola entrada. No es un descuido: el alcance
 * de esta fase es demostrar la cadena identidad → tenant → dato, no construir
 * el POS (subproyectos 2-5).
 */
@Component({
  selector: 'vd-shell',
  imports: [FullLayoutComponent, AvisosComponent],
  templateUrl: './shell.component.html',
})
export class ShellComponent {
  private readonly auth = inject(AuthService);

  /** Puente Notificador → ui-kit (el kit no puede conocer data-access). */
  readonly ultimoAviso = inject(Notificador).ultimo;

  readonly nombreUsuario = this.auth.displayName;

  readonly navegacion = computed<ElementoDeNavegacion[]>(() => [
    { etiqueta: 'negocio.titulo', icono: 'storefront', ruta: '/mi-negocio' },
  ]);

  cerrarSesion(): void {
    this.auth.logout();
  }
}
