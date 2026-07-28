import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { formatearPesos } from 'domain';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit/form-renderer';

/** Datos con los que se abre el diálogo de cierre. */
export interface DatosCerrarCaja {
  /** El esperado vivo, o null si el backend no lo dio (no debería: cerrar exige `caja:cerrar`). */
  esperado: number | null;
}

/**
 * El arqueo (ADR-021): el tendero cuenta la gaveta y el servidor calcula y
 * congela esperado y diferencia. El diálogo muestra el esperado ANTES de
 * cerrar — quien llega hasta aquí tiene `caja:cerrar`, así que el backend ya
 * se lo reveló en `sesiones/actual`.
 */
@Component({
  selector: 'vd-cerrar-caja-dialogo',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  template: `
    <h2 mat-dialog-title>{{ 'caja.cerrar.titulo' | translate }}</h2>
    <mat-dialog-content>
      @if (datos.esperado !== null) {
        <p>{{ 'caja.cerrar.esperado' | translate: { monto: formatear(datos.esperado) } }}</p>
      }
      <vd-form-renderer
        [configuracion]="configuracion"
        [formulario]="formulario"
        textoEnviar="caja.cerrar.confirmar"
        textoCancelar="comun.cancelar"
        (enviado)="alEnviar($event)"
        (cancelado)="cancelar()"
      />
    </mat-dialog-content>
  `,
})
export class CerrarCajaDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref = inject<MatDialogRef<CerrarCajaDialogoComponent, number | undefined>>(MatDialogRef);
  readonly datos = inject<DatosCerrarCaja>(MAT_DIALOG_DATA);

  readonly formatear = formatearPesos;

  readonly configuracion: ConfiguracionFormulario = {
    campos: [
      {
        clave: 'contado_pesos',
        etiqueta: 'caja.cerrar.contado',
        tipo: 'number',
        ayuda: 'caja.cerrar.contado_ayuda',
        validadores: [{ tipo: 'required' }, { tipo: 'min', valor: 0 }],
      },
    ],
  };

  readonly formulario: FormGroup = FormRendererComponent.construirFormulario(
    this.fb,
    this.configuracion,
  );

  private readonly enviando = signal(false);

  alEnviar(valores: Record<string, unknown>): void {
    if (this.enviando()) {
      return;
    }
    const pesos = Number(valores['contado_pesos']);
    if (!Number.isFinite(pesos) || pesos < 0) {
      return;
    }
    this.enviando.set(true);
    this.ref.close(Math.round(pesos * 100));
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
