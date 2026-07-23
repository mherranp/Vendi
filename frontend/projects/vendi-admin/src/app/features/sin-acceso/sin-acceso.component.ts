import { Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TranslateModule } from '@ngx-translate/core';
import { AuthService } from 'auth';

/**
 * Pantalla para el usuario autenticado que no administra la plataforma.
 *
 * El requisito (Tarea 4.5, Paso 2) es que **no** vea una consola vacía. La
 * diferencia no es estética: una tabla sin filas dice "no hay negocios" —una
 * afirmación falsa sobre los datos—, mientras que esta pantalla dice "esta
 * consola no es para ti" y ofrece la salida: cerrar sesión y entrar con la
 * cuenta correcta.
 */
@Component({
  selector: 'vd-sin-acceso',
  imports: [TranslateModule, MatButtonModule, MatIconModule],
  templateUrl: './sin-acceso.component.html',
  styleUrl: './sin-acceso.component.scss',
})
export class SinAccesoComponent {
  private readonly auth = inject(AuthService);

  readonly correo = this.auth.user;

  cerrarSesion(): void {
    this.auth.logout();
  }
}
