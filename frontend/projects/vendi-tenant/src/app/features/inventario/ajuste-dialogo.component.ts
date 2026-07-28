import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { miliDeCantidad, miliDeConteo, textoDeCantidad } from 'domain';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit/form-renderer';
import { AjusteNuevo, StockSalida } from './contrato';

/** Datos con los que se abre el ajuste: el producto y su stock del sistema. */
export interface DatosAjusteDialogo {
  producto: StockSalida;
}

/** Resultado del diálogo, listo para el servicio salvo el `id` (lo pone la página). */
export type ResultadoAjuste = Omit<AjusteNuevo, 'id'>;

/**
 * Ajuste por conteo o merma (ADR-020). El formulario dice el stock que el
 * sistema cree que hay, porque el conteo se hace contra ESE número: «conté
 * 14, el sistema dice 16». Es online-obligatorio — el delta lo calcula el
 * servidor— y el motivo no es opcional.
 */
@Component({
  selector: 'vd-ajuste-dialogo',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  template: `
    <h2 mat-dialog-title>
      {{ 'inventario.ajuste.titulo' | translate: { nombre: datos.producto.nombre } }}
    </h2>
    <mat-dialog-content>
      <p>
        {{
          'inventario.ajuste.stock_sistema'
            | translate: { stock: datos.producto.stock_actual, nivel: datos.producto.nivel }
        }}
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
        <p role="alert">{{ 'inventario.ajuste.invalido' | translate }}</p>
      }
    </mat-dialog-content>
  `,
})
export class AjusteDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref =
    inject<MatDialogRef<AjusteDialogoComponent, ResultadoAjuste | undefined>>(MatDialogRef);
  readonly datos = inject<DatosAjusteDialogo>(MAT_DIALOG_DATA);

  readonly errorFormulario = signal(false);

  readonly configuracion: ConfiguracionFormulario = {
    campos: [
      {
        clave: 'tipo',
        etiqueta: 'inventario.ajuste.tipo',
        tipo: 'select',
        valorPorDefecto: 'ajuste',
        validadores: [{ tipo: 'required' }],
        opciones: [
          { etiqueta: 'inventario.ajuste.conteo', valor: 'ajuste' },
          { etiqueta: 'inventario.ajuste.merma', valor: 'merma' },
        ],
      },
      {
        clave: 'cantidad',
        etiqueta: 'inventario.ajuste.cantidad',
        tipo: 'text',
        ayuda: 'inventario.ajuste.cantidad_ayuda',
        validadores: [{ tipo: 'required' }],
      },
      {
        clave: 'motivo',
        etiqueta: 'inventario.ajuste.motivo',
        tipo: 'text',
        marcador: 'inventario.ajuste.motivo_marcador',
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

  private readonly enviando = signal(false);

  alEnviar(valores: Record<string, unknown>): void {
    if (this.enviando()) {
      return;
    }
    const motivo = String(valores['motivo'] ?? '').trim();
    const tipo = valores['tipo'] as 'ajuste' | 'merma';
    let cantidad: string;
    try {
      // Conteo y merma no siguen la misma regla (espejo del backend:
      // `_cuantizar_conteo` vs `_cuantizar_cantidad`): el conteo 0 es
      // legítimo («no queda nada»); la merma 0 no existe.
      const numero = Number(String(valores['cantidad'] ?? '').replace(',', '.'));
      cantidad = textoDeCantidad(tipo === 'ajuste' ? miliDeConteo(numero) : miliDeCantidad(numero));
    } catch {
      // Cantidad ilegible o fuera de rango: el diálogo no cierra con un payload inválido.
      this.errorFormulario.set(true);
      return;
    }
    if (motivo.length < 3) {
      this.errorFormulario.set(true);
      return;
    }
    this.enviando.set(true);
    // Conteo → el servidor calcula el delta contra su stock; merma → el
    // delta es la cantidad que se reporta. Nunca viajan los dos campos.
    this.ref.close(
      tipo === 'ajuste'
        ? { tipo, producto_id: this.datos.producto.producto_id, motivo, stock_contado: cantidad }
        : { tipo, producto_id: this.datos.producto.producto_id, motivo, cantidad },
    );
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
