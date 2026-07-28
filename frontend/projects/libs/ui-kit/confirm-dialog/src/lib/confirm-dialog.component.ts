import { Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';

export interface ConfirmDialogData {
  /** Clave de traducción o texto ya resuelto. */
  titulo: string;
  mensaje: string;
  /** Clave del botón de confirmar. Por defecto, "Aceptar". */
  textoConfirmar?: string;
  /** Clave del botón de cancelar. Por defecto, "Cancelar". */
  textoCancelar?: string;
  /** Pinta la acción en rojo: para borrados y otras operaciones destructivas. */
  peligroso?: boolean;
}

/**
 * Diálogo de confirmación. Devuelve `true` si el usuario confirma, `false` si
 * cancela o cierra.
 *
 * Cosechado de `ui-components/confirm-dialog` con el prefijo `bs-` → `vd-` y
 * los textos convertidos en claves de ngx-translate.
 */
@Component({
  selector: 'vd-confirm-dialog',
  imports: [MatDialogModule, MatButtonModule, TranslateModule],
  templateUrl: './confirm-dialog.component.html',
  styleUrls: ['./confirm-dialog.component.scss'],
})
export class ConfirmDialogComponent {
  readonly ref = inject(MatDialogRef<ConfirmDialogComponent, boolean>);
  readonly data = inject<ConfirmDialogData>(MAT_DIALOG_DATA);
}
