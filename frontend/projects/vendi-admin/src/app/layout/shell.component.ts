import { Component, computed, inject } from '@angular/core';
import { AuthService } from 'auth';
import { ElementoDeNavegacion, FullLayoutComponent } from 'ui-kit';
import { PERMISO_PLATAFORMA } from '../nucleo/plataforma.guard';
import { AvisosComponent } from './avisos.component';

/**
 * Marco de la consola de plataforma.
 *
 * `FullLayoutComponent` es presentación pura y no conoce la sesión (ADR-011):
 * este componente es el puente. Filtra la navegación por permisos **aquí**,
 * antes de pasarla, que es la única capa que sabe quién es el usuario.
 *
 * El filtrado es cosmético, no una defensa: quien impide entrar a `/negocios`
 * es `guardPlataforma`, y quien impide leer datos es la API.
 */
@Component({
  selector: 'vd-shell',
  imports: [FullLayoutComponent, AvisosComponent],
  templateUrl: './shell.component.html',
})
export class ShellComponent {
  private readonly auth = inject(AuthService);

  readonly nombreUsuario = this.auth.displayName;

  readonly navegacion = computed<ElementoDeNavegacion[]>(() => {
    if (!this.auth.hasPermission(PERMISO_PLATAFORMA)) {
      return [];
    }
    return [{ etiqueta: 'tenants.titulo', icono: 'storefront', ruta: '/negocios' }];
  });

  cerrarSesion(): void {
    this.auth.logout();
  }
}
