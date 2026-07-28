import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit/form-renderer';
import { CategoriaMovimiento, TipoMovimiento } from './contrato';

/** Lo que devuelve el diálogo; `undefined` si se canceló. */
export interface ResultadoMovimiento {
  tipo: TipoMovimiento;
  categoria: CategoriaMovimiento;
  /** Centavos enteros, convertidos en el borde. */
  montoCentavos: number;
  motivo: string;
}

/**
 * Ingreso/egreso manual de la gaveta (ADR-021). El `motivo` es obligatorio
 * porque un movimiento sin justificación es un desfalco con buenos modales.
 */
@Component({
  selector: 'vd-movimiento-dialogo',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  template: `
    <h2 mat-dialog-title>{{ 'caja.movimiento.titulo' | translate }}</h2>
    <mat-dialog-content>
      <vd-form-renderer
        [configuracion]="configuracion"
        [formulario]="formulario"
        textoEnviar="comun.guardar"
        textoCancelar="comun.cancelar"
        (enviado)="alEnviar($event)"
        (cancelado)="cancelar()"
      />
    </mat-dialog-content>
  `,
})
export class MovimientoDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref =
    inject<MatDialogRef<MovimientoDialogoComponent, ResultadoMovimiento | undefined>>(MatDialogRef);

  readonly configuracion: ConfiguracionFormulario = {
    campos: [
      {
        clave: 'tipo',
        etiqueta: 'caja.movimiento.tipo',
        tipo: 'select',
        valorPorDefecto: 'egreso',
        validadores: [{ tipo: 'required' }],
        opciones: [
          { etiqueta: 'caja.movimiento.ingreso', valor: 'ingreso' },
          { etiqueta: 'caja.movimiento.egreso', valor: 'egreso' },
        ],
      },
      {
        clave: 'categoria',
        etiqueta: 'caja.movimiento.categoria',
        tipo: 'select',
        valorPorDefecto: 'otro',
        validadores: [{ tipo: 'required' }],
        opciones: [
          { etiqueta: 'caja.categoria.arriendo', valor: 'arriendo' },
          { etiqueta: 'caja.categoria.servicios', valor: 'servicios' },
          { etiqueta: 'caja.categoria.retiro_dueno', valor: 'retiro_dueno' },
          { etiqueta: 'caja.categoria.otro', valor: 'otro' },
        ],
      },
      {
        clave: 'monto_pesos',
        etiqueta: 'caja.movimiento.monto',
        tipo: 'number',
        validadores: [{ tipo: 'required' }, { tipo: 'min', valor: 1 }],
      },
      {
        clave: 'motivo',
        etiqueta: 'caja.movimiento.motivo',
        tipo: 'text',
        marcador: 'caja.movimiento.motivo_marcador',
        validadores: [
          { tipo: 'required' },
          { tipo: 'minLength', valor: 3 },
          { tipo: 'maxLength', valor: 300 },
        ],
      },
    ],
  };

  readonly formulario: FormGroup = FormRendererComponent.construirFormulario(
    this.fb,
    this.configuracion,
  );

  /** Candado de doble envío: MatDialogRef.close() no es síncrono. */
  private readonly enviando = signal(false);

  alEnviar(valores: Record<string, unknown>): void {
    if (this.enviando()) {
      return;
    }
    const pesos = Number(valores['monto_pesos']);
    const motivo = String(valores['motivo'] ?? '').trim();
    if (!Number.isFinite(pesos) || pesos <= 0 || motivo.length < 3) {
      return;
    }
    this.enviando.set(true);
    this.ref.close({
      tipo: valores['tipo'] as TipoMovimiento,
      categoria: valores['categoria'] as CategoriaMovimiento,
      montoCentavos: Math.round(pesos * 100),
      motivo,
    });
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
