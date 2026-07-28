import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit/form-renderer';
import { ClienteConSaldo, ClienteNuevo } from './contrato';

/** Datos con los que se abre el diálogo. Sin `cliente` es un alta. */
export interface DatosClienteDialogo {
  cliente?: ClienteConSaldo;
}

/** Lo que el formulario produce; el `id` idempotente lo pone quien abre. */
export type ResultadoCliente = Omit<ClienteNuevo, 'id'>;

/**
 * Alta y edición de cliente del cuaderno (ADR-022).
 *
 * Conversiones en el borde: el cupo entra en pesos y sale en centavos
 * (`Math.round(pesos * 100)`); vacío es `null` = sin cupo — y en edición ese
 * `null` explícito BORRA el cupo en el backend, semántica que la ayuda del
 * campo declara. El teléfono alimenta el `wa.me` que prearma el servidor.
 */
@Component({
  selector: 'vd-cliente-dialogo',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  template: `
    <h2 mat-dialog-title>
      {{ (esEdicion ? 'cuaderno.editar_cliente' : 'cuaderno.nuevo_cliente') | translate }}
    </h2>
    <mat-dialog-content>
      <vd-form-renderer
        [configuracion]="configuracion"
        [formulario]="formulario"
        textoEnviar="comun.guardar"
        textoCancelar="comun.cancelar"
        (enviado)="alEnviar($event)"
        (cancelado)="cancelar()"
      />
      @if (errorFormulario()) {
        <p role="alert">{{ 'cuaderno.formulario.invalido' | translate }}</p>
      }
    </mat-dialog-content>
  `,
})
export class ClienteDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref =
    inject<MatDialogRef<ClienteDialogoComponent, ResultadoCliente | undefined>>(MatDialogRef);
  readonly datos = inject<DatosClienteDialogo>(MAT_DIALOG_DATA, { optional: true }) ?? {};

  readonly esEdicion = !!this.datos.cliente;
  readonly errorFormulario = signal(false);

  readonly configuracion: ConfiguracionFormulario = {
    disposicion: 'una-columna',
    campos: [
      {
        clave: 'nombre',
        etiqueta: 'cuaderno.campo.nombre',
        tipo: 'text',
        valorPorDefecto: this.datos.cliente?.nombre ?? '',
        validadores: [
          { tipo: 'required' },
          { tipo: 'minLength', valor: 2 },
          { tipo: 'maxLength', valor: 120 },
        ],
      },
      {
        clave: 'telefono',
        etiqueta: 'cuaderno.campo.telefono',
        tipo: 'tel',
        ayuda: 'cuaderno.campo.telefono_ayuda',
        valorPorDefecto: this.datos.cliente?.telefono ?? '',
      },
      {
        clave: 'limite_pesos',
        etiqueta: 'cuaderno.campo.cupo',
        tipo: 'number',
        ayuda: 'cuaderno.campo.cupo_ayuda',
        valorPorDefecto: this.datos.cliente?.limite_credito
          ? this.datos.cliente.limite_credito / 100
          : null,
        validadores: [{ tipo: 'min', valor: 0 }],
      },
      {
        clave: 'nota',
        etiqueta: 'cuaderno.campo.nota',
        tipo: 'textarea',
        valorPorDefecto: this.datos.cliente?.nota ?? '',
        validadores: [{ tipo: 'maxLength', valor: 500 }],
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
    const nombre = String(valores['nombre'] ?? '').trim();
    const crudoCupo = valores['limite_pesos'];
    const cupoVacio = crudoCupo === null || crudoCupo === undefined || crudoCupo === '';
    const pesos = cupoVacio ? null : Number(crudoCupo);
    if (nombre.length < 2 || (pesos !== null && (!Number.isFinite(pesos) || pesos < 0))) {
      this.errorFormulario.set(true);
      return;
    }
    this.enviando.set(true);
    const telefono = String(valores['telefono'] ?? '').trim();
    const nota = String(valores['nota'] ?? '').trim();
    this.ref.close({
      nombre,
      telefono: telefono.length > 0 ? telefono : null,
      // Vacío = sin cupo; en edición, el null explícito BORRA el cupo.
      limite_credito: pesos === null ? null : Math.round(pesos * 100),
      nota: nota.length > 0 ? nota : null,
    });
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
