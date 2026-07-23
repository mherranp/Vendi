import { Component, effect, inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { TranslateService } from '@ngx-translate/core';
import { Notificador, traducir } from 'data-access';

/** Cuánto se queda en pantalla cada aviso, por tipo. */
const DURACION_MS: Record<string, number> = {
  exito: 3_000,
  info: 4_000,
  advertencia: 6_000,
  // Un error se lee, no se pilla al vuelo: se queda hasta que lo cierren.
  error: 0,
};

/**
 * Pinta los avisos que acumula `Notificador`.
 *
 * Existe porque `Notificador` **solo acumula**: es de `data-access`, que por
 * ADR-011 no puede conocer la UI, así que sin un anfitrión como éste el mensaje
 * traducido que produce `errorInterceptor` ante un 500 se queda en una señal
 * que nadie lee y el usuario ve la operación fallar en silencio.
 *
 * Se sitúa dentro del shell y no en `AppComponent` para que no aparezca en las
 * rutas sin sesión.
 */
@Component({
  selector: 'vd-avisos',
  template: '',
})
export class AvisosComponent {
  private readonly notificador = inject(Notificador);
  private readonly barra = inject(MatSnackBar);
  private readonly traductor = inject(TranslateService);
  private ultimoMostrado: string | null = null;

  constructor() {
    effect(() => {
      const aviso = this.notificador.ultimo();
      if (!aviso || aviso.id === this.ultimoMostrado) {
        return;
      }
      this.ultimoMostrado = aviso.id;
      this.barra.open(aviso.mensaje, traducir(this.traductor, 'comun.cerrar', 'Cerrar'), {
        duration: DURACION_MS[aviso.tipo] ?? 4_000,
        panelClass: `vd-aviso--${aviso.tipo}`,
      });
      // No se llama a `descartar()`: quitar el aviso de la cola haría que
      // `ultimo()` pasara a ser el ANTERIOR, el efecto se dispararía otra vez y
      // se repintaría un mensaje viejo. La deduplicación va por `id`, y dos
      // errores idénticos consecutivos tienen ids distintos —los genera
      // `Notificador` con marca de tiempo y aleatorio—, así que el segundo sí
      // se ve.
    });
  }
}
