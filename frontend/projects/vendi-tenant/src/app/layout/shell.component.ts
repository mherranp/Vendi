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

  /**
   * Navegación de la consola, filtrada por los permisos del token (ADR-023).
   *
   * `FullLayoutComponent` no conoce la sesión (ADR-011): el filtro es aquí.
   * Las secciones sin permiso se OCULTAN, no se deshabilitan — un botón gris
   * invita a preguntar «¿por qué no puedo?»; la sección ausente, no. La
   * defensa real es el guard de la ruta y, detrás, el backend.
   */
  readonly navegacion = computed<ElementoDeNavegacion[]>(() => {
    const elementos: ElementoDeNavegacion[] = [
      { etiqueta: 'negocio.titulo', icono: 'storefront', ruta: '/mi-negocio' },
    ];
    if (this.auth.hasPermission('caja:leer')) {
      elementos.push({ etiqueta: 'menu.caja', icono: 'point_of_sale', ruta: '/caja' });
    }
    if (this.auth.hasPermission('producto:leer')) {
      elementos.push(
        { etiqueta: 'menu.catalogo', icono: 'inventory_2', ruta: '/catalogo' },
        { etiqueta: 'menu.inventario', icono: 'warehouse', ruta: '/inventario' },
      );
    }
    if (this.auth.hasPermission('cliente:gestionar')) {
      elementos.push({ etiqueta: 'menu.cuaderno', icono: 'menu_book', ruta: '/cuaderno' });
    }
    if (this.auth.hasPermission('reporte:leer')) {
      elementos.push({ etiqueta: 'menu.numeros', icono: 'monitoring', ruta: '/numeros' });
    }
    return elementos;
  });

  cerrarSesion(): void {
    this.auth.logout();
  }
}
