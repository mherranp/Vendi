import { Component, effect, inject, input } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { TranslateService } from '@ngx-translate/core';

/**
 * El aviso tal como lo necesita el anfitrión. Es estructuralmente compatible
 * con el `Aviso` de `data-access` (que trae además `instante`): la app pasa
 * `notificador.ultimo()` tal cual, sin mapear nada.
 *
 * Se declara aquí y no se importa de `data-access` porque la frontera de
 * ADR-011 lo prohíbe: `ui-kit` es presentación pura.
 */
export interface AvisoEnPantalla {
  id: string;
  tipo: string;
  mensaje: string;
}

/** Cuánto se queda en pantalla cada aviso, por tipo. */
const DURACION_MS: Record<string, number> = {
  exito: 3_000,
  info: 4_000,
  advertencia: 6_000,
  // Un error se lee, no se pilla al vuelo: se queda hasta que lo cierren.
  error: 0,
};

/**
 * Pinta el aviso vigente en una `MatSnackBar`.
 *
 * Antes vivía duplicado en `layout/avisos.component.ts` de `vendi-admin` y
 * `vendi-tenant` inyectando `Notificador` — imposible aquí por la frontera.
 * La inversión es el arreglo de la Etapa 1.3: el kit recibe el aviso por
 * input y la app hace el puente con una línea.
 *
 * La deduplicación va por `id`: dos avisos idénticos consecutivos tienen ids
 * distintos (los genera el `Notificador` con marca de tiempo y aleatorio), así
 * que el segundo sí se ve.
 */
@Component({
  selector: 'vd-avisos',
  template: '',
})
export class AvisosComponent {
  /** El aviso a mostrar; `null` cuando no hay ninguno. */
  readonly aviso = input<AvisoEnPantalla | null>(null);

  private readonly barra = inject(MatSnackBar);
  private readonly traductor = inject(TranslateService);
  private ultimoMostrado: string | null = null;

  constructor() {
    effect(() => {
      const actual = this.aviso();
      if (!actual || actual.id === this.ultimoMostrado) {
        return;
      }
      this.ultimoMostrado = actual.id;
      const cerrar = this.traductor.instant('comun.cerrar');
      this.barra.open(actual.mensaje, cerrar === 'comun.cerrar' ? 'Cerrar' : cerrar, {
        duration: DURACION_MS[actual.tipo] ?? 4_000,
        panelClass: `vd-aviso--${actual.tipo}`,
      });
    });
  }
}
