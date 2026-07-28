import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';
import { EmptyStateComponent } from 'ui-kit';

/**
 * Aterrizaje del `permisoGuard`: autenticado, con negocio elegido, pero sin
 * el permiso que la sección pide (un cajero que escribe `/numeros` a mano).
 *
 * No es un error y no se trata como tal: el mensaje dice qué pasó y devuelve
 * al trabajo, sin acusar a nadie. El backend seguiría respondiendo 403 aunque
 * esta pantalla no existiera — esto solo ahorra el viaje.
 */
@Component({
  selector: 'vd-sin-permiso',
  imports: [EmptyStateComponent],
  template: `
    <vd-empty-state
      icono="lock"
      titulo="sin_permiso.titulo"
      descripcion="sin_permiso.descripcion"
      textoAccion="sin_permiso.volver"
      (accion)="volver()"
    />
  `,
})
export class SinPermisoComponent {
  private readonly router = inject(Router);

  volver(): void {
    this.router.navigate(['/mi-negocio']).catch((error: unknown) => {
      console.error('No se pudo volver a «Mi negocio».', error);
    });
  }
}
