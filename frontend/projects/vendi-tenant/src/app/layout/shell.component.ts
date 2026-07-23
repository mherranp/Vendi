import { Component, computed, inject } from '@angular/core';
import { AuthService } from 'auth';
import { ElementoDeNavegacion, FullLayoutComponent } from 'ui-kit';
import { AvisosComponent } from './avisos.component';

/**
 * Marco de la consola web del negocio.
 *
 * Igual que en `vendi-admin`, `FullLayoutComponent` no conoce la sesión
 * (ADR-011) y este componente es el puente: nombre del usuario, navegación y
 * cierre de sesión.
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

  readonly nombreUsuario = this.auth.displayName;

  readonly navegacion = computed<ElementoDeNavegacion[]>(() => [
    { etiqueta: 'negocio.titulo', icono: 'storefront', ruta: '/mi-negocio' },
  ]);

  cerrarSesion(): void {
    this.auth.logout();
  }
}
