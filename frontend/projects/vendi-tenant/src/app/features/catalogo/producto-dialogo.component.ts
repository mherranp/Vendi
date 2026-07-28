import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { miliDeCantidad, textoDeCantidad } from 'domain';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit/form-renderer';
import { ProductoNuevo, ProductoSalida, TASAS_IVA, UNIDADES_DE_MEDIDA } from './contrato';

/** Datos con los que se abre el diálogo. Sin `producto` es un alta. */
export interface DatosProductoDialogo {
  producto?: ProductoSalida;
}

/**
 * Alta y edición de producto (ADR-019).
 *
 * Conversiones en el borde: el precio entra en pesos y sale en centavos; el
 * stock mínimo entra como texto (coma o punto) y sale como string de 3
 * decimales vía `miliDeCantidad`/`textoDeCantidad` — la misma regla del POS,
 * compartida en `domain`. El EAN es opcional porque gran parte del surtido
 * de barrio no lo tiene.
 */
@Component({
  selector: 'vd-producto-dialogo',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  template: `
    <h2 mat-dialog-title>
      {{ (esEdicion ? 'catalogo.editar.titulo' : 'catalogo.nuevo.titulo') | translate }}
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
        <p role="alert">{{ 'catalogo.formulario.invalido' | translate }}</p>
      }
    </mat-dialog-content>
  `,
})
export class ProductoDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref =
    inject<MatDialogRef<ProductoDialogoComponent, Omit<ProductoNuevo, 'id'> | undefined>>(
      MatDialogRef,
    );
  readonly datos = inject<DatosProductoDialogo>(MAT_DIALOG_DATA, { optional: true }) ?? {};

  readonly esEdicion = !!this.datos.producto;
  readonly errorFormulario = signal(false);

  readonly configuracion: ConfiguracionFormulario = {
    disposicion: 'dos-columnas',
    campos: [
      {
        clave: 'nombre',
        etiqueta: 'catalogo.campo.nombre',
        tipo: 'text',
        valorPorDefecto: this.datos.producto?.nombre ?? '',
        validadores: [
          { tipo: 'required' },
          { tipo: 'minLength', valor: 2 },
          { tipo: 'maxLength', valor: 160 },
        ],
      },
      {
        clave: 'categoria',
        etiqueta: 'catalogo.campo.categoria',
        tipo: 'text',
        ayuda: 'catalogo.campo.categoria_ayuda',
        valorPorDefecto: this.datos.producto?.categoria ?? '',
      },
      {
        clave: 'codigo_barras',
        etiqueta: 'catalogo.campo.ean',
        tipo: 'text',
        ayuda: 'catalogo.campo.ean_ayuda',
        valorPorDefecto: this.datos.producto?.codigo_barras ?? '',
        validadores: [{ tipo: 'maxLength', valor: 32 }],
      },
      {
        clave: 'precio_pesos',
        etiqueta: 'catalogo.campo.precio',
        tipo: 'number',
        valorPorDefecto: this.datos.producto ? this.datos.producto.precio_venta / 100 : null,
        validadores: [{ tipo: 'required' }, { tipo: 'min', valor: 0 }],
      },
      {
        clave: 'unidad_medida',
        etiqueta: 'catalogo.campo.unidad',
        tipo: 'select',
        valorPorDefecto: this.datos.producto?.unidad_medida ?? 'unidad',
        validadores: [{ tipo: 'required' }],
        opciones: UNIDADES_DE_MEDIDA.map((unidad) => ({
          etiqueta: `catalogo.unidad.${unidad}`,
          valor: unidad,
        })),
      },
      {
        clave: 'iva_pct',
        etiqueta: 'catalogo.campo.iva',
        tipo: 'select',
        valorPorDefecto: this.datos.producto ? Number(this.datos.producto.iva_pct) : 0,
        opciones: TASAS_IVA.map((tasa) => ({
          etiqueta: `catalogo.iva.${tasa}`,
          valor: tasa,
        })),
      },
      {
        clave: 'stock_minimo',
        etiqueta: 'catalogo.campo.stock_minimo',
        tipo: 'text',
        ayuda: 'catalogo.campo.stock_minimo_ayuda',
        valorPorDefecto: this.datos.producto?.stock_minimo ?? '0',
        validadores: [{ tipo: 'required' }],
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
    const pesos = Number(valores['precio_pesos']);
    let stockMinimo: string;
    try {
      stockMinimo = textoDeCantidad(
        miliDeCantidad(Number(String(valores['stock_minimo'] ?? '').replace(',', '.'))),
      );
    } catch {
      // Cantidad ilegible o <= 0: el diálogo no cierra con un payload inválido.
      // Ojo: un mínimo de 0 ES legítimo (sin alertas); se trata aparte.
      const crudo = String(valores['stock_minimo'] ?? '')
        .replace(',', '.')
        .trim();
      if (Number(crudo) === 0) {
        stockMinimo = '0.000';
      } else {
        this.errorFormulario.set(true);
        return;
      }
    }
    if (nombre.length < 2 || !Number.isFinite(pesos) || pesos < 0) {
      this.errorFormulario.set(true);
      return;
    }
    this.enviando.set(true);
    const ean = String(valores['codigo_barras'] ?? '').trim();
    const categoria = String(valores['categoria'] ?? '').trim();
    this.ref.close({
      nombre,
      categoria: categoria.length > 0 ? categoria : null,
      codigo_barras: ean.length > 0 ? ean : null,
      precio_venta: Math.round(pesos * 100),
      unidad_medida: valores['unidad_medida'] as ProductoNuevo['unidad_medida'],
      iva_pct: Number(valores['iva_pct'] ?? 0),
      stock_minimo: stockMinimo,
    });
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
