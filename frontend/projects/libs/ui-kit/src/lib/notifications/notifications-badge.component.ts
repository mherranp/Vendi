import { Component, computed, input, output } from '@angular/core';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

export interface NotificacionEnPantalla {
  id: string;
  titulo: string;
  cuerpo?: string;
  /** Ruta interna a la que lleva la notificación, si tiene destino. */
  enlace?: string;
  leida: boolean;
}

/** Máximo de notificaciones que se pintan en el panel. */
const MAXIMO_VISIBLES = 20;

/**
 * Campana con contador de no leídas y panel desplegable.
 *
 * Cosechado de `ui-core/src/lib/components/notifications-badge` con **un cambio
 * estructural**: el original inyectaba `ApiService` y hacía
 * `GET /notifications` en `ngOnInit` y `POST /notifications/read-all` al marcar
 * como leídas. Eso viola la frontera de ADR-011 ("ui-kit no hace HTTP") que el
 * propio plan reafirma en el Paso 2 de la Tarea 3.12 para el banner de
 * suplantación; aquí se aplica el mismo criterio. El componente recibe la lista
 * por input y emite `marcarTodasLeidas`: quien habla con la API es la app.
 *
 * (En Fase 0 el módulo `notifications` del backend no existe: el componente
 * queda listo para la Etapa en que exista.)
 */
@Component({
  selector: 'vd-notifications-badge',
  imports: [
    RouterLink,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatBadgeModule,
    MatDividerModule,
    TranslateModule,
  ],
  templateUrl: './notifications-badge.component.html',
  styleUrls: ['./notifications-badge.component.scss'],
})
export class NotificationsBadgeComponent {
  readonly notificaciones = input<NotificacionEnPantalla[]>([]);

  readonly marcarTodasLeidas = output<void>();

  readonly noLeidas = computed(() => this.notificaciones().filter((n) => !n.leida).length);
  readonly visibles = computed(() => this.notificaciones().slice(0, MAXIMO_VISIBLES));
}
