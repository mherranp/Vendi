import { Component, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TranslateModule } from '@ngx-translate/core';

/**
 * Banda imposible de ignorar que avisa de que la sesión actual está suplantando
 * a otro usuario.
 *
 * ⚠ **En Fase 0 no hay suplantación y este componente no se usa.** El rol
 * `impersonation` se retiró de la cuenta de servicio de `vendi-backend` en la
 * Etapa 2 por ser un agujero de aislamiento multi-tenant, así que no existe el
 * intercambio de token que la haría posible. El componente se cosecha porque el
 * plan lo pide y porque es presentación pura —sin lógica de sesión, sin HTTP—,
 * pero **no** está cableado en `vd-full-layout`: no se paga nada por tenerlo, y
 * el día que vuelva la suplantación por otro mecanismo, la parte visual ya está
 * y ya es accesible.
 *
 * Diferencia con el original de BaseSaaS: allí inyectaba `ImpersonationService`
 * y decidía solo si mostrarse. Aquí recibe `actor` y `expiraEnSegundos` por
 * input y emite `detener`; la lógica de sesión vive en `auth`, no en `ui-kit`.
 */
@Component({
  selector: 'vd-impersonation-banner',
  imports: [MatButtonModule, MatIconModule, TranslateModule],
  templateUrl: './impersonation-banner.component.html',
  styleUrls: ['./impersonation-banner.component.scss'],
})
export class ImpersonationBannerComponent {
  /** Usuario suplantado. Vacío o nulo = la banda no se pinta. */
  readonly actor = input<string | null>(null);
  /** Segundos que le quedan a la sesión suplantada. */
  readonly expiraEnSegundos = input<number | null>(null);

  readonly detener = output<void>();
}
