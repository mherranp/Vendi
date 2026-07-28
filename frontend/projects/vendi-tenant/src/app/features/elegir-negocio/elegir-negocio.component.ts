import { Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { Router } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthService } from 'auth';
import { ElegirNegocioService, TenantMioSalida } from './elegir-negocio.service';

/**
 * Selector de negocio para el dueño que tiene más de uno.
 *
 * Desde la Etapa 1.3 la lista muestra NOMBRES: `/tenants/mios` traduce los
 * alias del token a negocios vivos. El token sigue mandando — un alias que el
 * endpoint no devuelve (negocio eliminado entre el login y ahora) no se
 * ofrece, y `selectTenant` rechaza cualquier id que no venga en el token.
 * Si el endpoint falla, se degrada a la lista de alias como en Fase 0: feo,
 * honesto y funcional.
 */
@Component({
  selector: 'vd-elegir-negocio',
  imports: [TranslateModule, MatListModule, MatButtonModule, MatIconModule],
  templateUrl: './elegir-negocio.component.html',
  styleUrl: './elegir-negocio.component.scss',
})
export class ElegirNegocioComponent {
  private readonly auth = inject(AuthService);
  private readonly servicio = inject(ElegirNegocioService);
  private readonly router = inject(Router);

  readonly organizaciones = this.auth.organizaciones;

  /** null mientras carga; lista vacía si el endpoint falló (→ degradación). */
  readonly negocios = signal<TenantMioSalida[] | null>(null);

  constructor() {
    this.servicio.mios().subscribe({
      next: (mios) => {
        // Defensa en profundidad: solo se ofrecen ids que están en el token.
        const elegibles = new Set(this.organizaciones());
        this.negocios.set(mios.filter((negocio) => elegibles.has(negocio.id)));
      },
      error: () => this.negocios.set([]),
    });
  }

  elegir(alias: string): void {
    if (!this.auth.selectTenant(alias)) {
      return;
    }
    this.router.navigate(['/mi-negocio']).catch((error: unknown) => {
      console.error('No se pudo abrir «Mi negocio» tras elegir el negocio.', error);
    });
  }

  cerrarSesion(): void {
    this.auth.logout();
  }
}
