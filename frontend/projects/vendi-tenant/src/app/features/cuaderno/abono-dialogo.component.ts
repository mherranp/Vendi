import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { formatearPesos } from 'domain';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit/form-renderer';
import { AbonoNuevo } from './contrato';

/** Datos con los que se abre el diálogo: el saldo vivo, solo para mostrarlo. */
export interface DatosAbonoDialogo {
  /** Centavos. */
  saldoPendiente: number;
}

/** Lo que el formulario produce; el `id` idempotente lo pone quien abre. */
export type ResultadoAbono = Omit<AbonoNuevo, 'id'>;

/**
 * Abono contra el crédito que el usuario tocó (ADR-022).
 *
 * El saldo se muestra formateado pero NO se valida contra él: el tope lo
 * impone el servidor (`abono_excede_saldo`) y el fiado nunca bloquea. El
 * monto entra en pesos y sale en centavos; en efectivo entra a la caja
 * abierta del momento — sin caja, el 409 `caja_sin_sesion_abierta` llega con
 * el mensaje del backend.
 */
@Component({
  selector: 'vd-abono-dialogo',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  template: `
    <h2 mat-dialog-title>{{ 'cuaderno.abono.titulo' | translate }}</h2>
    <mat-dialog-content>
      <p class="vd-abono-dialogo__saldo">
        {{ 'cuaderno.abono.saldo' | translate: { monto: saldoFormateado } }}
      </p>
      <vd-form-renderer
        [configuracion]="configuracion"
        [formulario]="formulario"
        textoEnviar="comun.guardar"
        textoCancelar="comun.cancelar"
        (enviado)="alEnviar($event)"
        (cancelado)="cancelar()"
      />
      @if (errorFormulario()) {
        <p role="alert">{{ 'cuaderno.abono.invalido' | translate }}</p>
      }
    </mat-dialog-content>
  `,
})
export class AbonoDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref =
    inject<MatDialogRef<AbonoDialogoComponent, ResultadoAbono | undefined>>(MatDialogRef);
  readonly datos = inject<DatosAbonoDialogo>(MAT_DIALOG_DATA);

  readonly saldoFormateado = formatearPesos(this.datos.saldoPendiente);
  readonly errorFormulario = signal(false);

  readonly configuracion: ConfiguracionFormulario = {
    disposicion: 'una-columna',
    campos: [
      {
        clave: 'monto_pesos',
        etiqueta: 'cuaderno.abono.monto',
        tipo: 'number',
        ayuda: 'cuaderno.abono.monto_ayuda',
        validadores: [{ tipo: 'required' }, { tipo: 'min', valor: 1 }],
      },
      {
        clave: 'metodo_pago',
        etiqueta: 'cuaderno.abono.metodo',
        tipo: 'select',
        valorPorDefecto: 'efectivo',
        opciones: [
          { etiqueta: 'cuaderno.metodo.efectivo', valor: 'efectivo' },
          { etiqueta: 'cuaderno.metodo.transferencia', valor: 'transferencia' },
          { etiqueta: 'cuaderno.metodo.otro', valor: 'otro' },
        ],
      },
      {
        clave: 'nota',
        etiqueta: 'cuaderno.campo.nota',
        tipo: 'text',
        validadores: [{ tipo: 'maxLength', valor: 300 }],
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
    const pesos = Number(valores['monto_pesos']);
    if (!Number.isFinite(pesos) || pesos <= 0) {
      this.errorFormulario.set(true);
      return;
    }
    this.enviando.set(true);
    const nota = String(valores['nota'] ?? '').trim();
    this.ref.close({
      metodo_pago: valores['metodo_pago'] as ResultadoAbono['metodo_pago'],
      monto: Math.round(pesos * 100),
      nota: nota.length > 0 ? nota : null,
    });
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
