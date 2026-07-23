import { Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { Router } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthService } from 'auth';
import { TenantDeApi, esEstadoTenant } from 'domain';
import {
  LoadingSpinnerComponent,
  PageHeaderComponent,
  StatusBadgeComponent,
  VarianteEstado,
} from 'ui-kit';
import { MiNegocioService } from './mi-negocio.service';

/**
 * "Mi negocio": lo que la API dice del tenant del token.
 *
 * Es la pantalla que demuestra, de punta a punta, la cadena de identidad de
 * Fase 0: passkey → token con claim `organization` → `tenant_id` → RLS → fila.
 * Por eso enseña también el identificador resuelto del claim: si algún día el
 * tenant del token y el que devuelve la API no coincidieran, aquí se vería.
 */
@Component({
  selector: 'vd-mi-negocio',
  imports: [
    TranslateModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    PageHeaderComponent,
    StatusBadgeComponent,
    LoadingSpinnerComponent,
  ],
  templateUrl: './mi-negocio.component.html',
  styleUrl: './mi-negocio.component.scss',
})
export class MiNegocioComponent {
  private readonly servicio = inject(MiNegocioService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly negocio = signal<TenantDeApi | null>(null);
  readonly cargando = signal(false);
  readonly fallo = signal(false);

  /**
   * Tenant resuelto del claim `organization`, no de la respuesta de la API.
   *
   * Son dos fuentes distintas a propósito: el claim es lo que el navegador
   * cree, la respuesta es lo que el servidor confirma. Enseñar el primero al
   * lado del segundo convierte una incoherencia silenciosa en algo visible.
   */
  readonly tenantDelToken = this.auth.tenantId;

  /** Negocios del token: con más de uno, la pantalla ofrece cambiar. */
  readonly organizaciones = this.auth.organizaciones;

  constructor() {
    this.cargar();
  }

  cargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    this.servicio.obtener().subscribe({
      next: (tenant) => {
        this.negocio.set(tenant);
        this.cargando.set(false);
      },
      error: () => {
        // El mensaje traducido ya lo emitió `errorInterceptor` (incluido el
        // 403 `tenant_suspendido`). Aquí solo se sale del estado "cargando"
        // para no dejar un spinner eterno.
        this.cargando.set(false);
        this.fallo.set(true);
      },
    });
  }

  /**
   * Vuelve al selector de negocio sin cerrar sesión.
   *
   * Soltar la selección **no** basta: los guards solo corren al navegar, así
   * que sin el `navigate()` el usuario se quedaba en esta misma pantalla
   * mirando los datos de un negocio que ya no está seleccionado, y sin ninguna
   * forma de llegar al selector desde la interfaz.
   */
  cambiarDeNegocio(): void {
    this.auth.limpiarSeleccionDeTenant();
    this.router.navigate(['/elegir-negocio']).catch((error: unknown) => {
      console.error('No se pudo abrir el selector de negocio.', error);
    });
  }

  varianteDeEstado(estado: string): VarianteEstado {
    if (!esEstadoTenant(estado)) {
      return 'neutro';
    }
    switch (estado) {
      case 'activo':
        return 'exito';
      case 'suspendido':
        return 'aviso';
      case 'eliminado':
        return 'peligro';
    }
  }

  etiquetaDeEstado(estado: string): string {
    return esEstadoTenant(estado) ? `negocio.estado.${estado}` : estado;
  }
}
