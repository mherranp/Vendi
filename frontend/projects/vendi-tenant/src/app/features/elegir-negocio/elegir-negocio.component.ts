import { Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { Router } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthService } from 'auth';

/**
 * Selector de negocio para el dueño que tiene más de uno.
 *
 * Existe porque `AuthService.tenantId` devuelve `null` a propósito cuando hay
 * varias organizaciones en el token y ninguna elegida: adivinar "la primera"
 * sería decidir por el usuario **qué datos ve**, y eso no se adivina. Aquí es
 * donde elige.
 *
 * La lista sale del token y solo del token: `selectTenant()` rechaza cualquier
 * alias que no venga en él. Es decir, esta pantalla no puede usarse para pedir
 * un negocio ajeno, ni escribiendo a mano en la consola del navegador.
 *
 * Fase 0 no tiene endpoint para traducir un `tenant_id` a su nombre comercial
 * sin haberlo seleccionado antes (`GET /tenants/me` devuelve el activo), así
 * que la lista muestra los identificadores. Es feo y es honesto; el nombre
 * llegará cuando exista `GET /tenants/mios` o equivalente.
 */
@Component({
  selector: 'vd-elegir-negocio',
  imports: [TranslateModule, MatListModule, MatButtonModule, MatIconModule],
  templateUrl: './elegir-negocio.component.html',
  styleUrl: './elegir-negocio.component.scss',
})
export class ElegirNegocioComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly organizaciones = this.auth.organizaciones;

  elegir(alias: string): void {
    if (!this.auth.selectTenant(alias)) {
      // `selectTenant` ya dejó constancia en consola. Se corta aquí: navegar de
      // todos modos llevaría a "Mi negocio" a pedir datos con el tenant
      // anterior, que es peor que quedarse en el selector.
      return;
    }
    // El `catch` no es ceremonia: si alguien reorganiza las rutas y
    // `/mi-negocio` deja de existir, `navigate()` devuelve una promesa
    // rechazada que nadie observa y el error aparece como "unhandled
    // rejection" sin decir dónde.
    this.router.navigate(['/mi-negocio']).catch((error: unknown) => {
      console.error('No se pudo abrir «Mi negocio» tras elegir el negocio.', error);
    });
  }

  cerrarSesion(): void {
    this.auth.logout();
  }
}
