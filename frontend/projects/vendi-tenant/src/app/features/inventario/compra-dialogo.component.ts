import { Component, inject, signal } from '@angular/core';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { TranslateModule } from '@ngx-translate/core';
import { miliDeCantidad, textoDeCantidad } from 'domain';
import { CompraNueva, StockSalida } from './contrato';

/** Datos del diálogo: el catálogo con stock (de donde se eligen los ítems). */
export interface DatosCompraDialogo {
  productos: StockSalida[];
}

/** Resultado listo para el servicio salvo el `id`. */
export type ResultadoCompra = Omit<CompraNueva, 'id'>;

/**
 * Registro de una compra a proveedor (ADR-020): el proveedor es texto libre
 * (la factura es un papel; no hay módulo de proveedores) y cada ítem lleva su
 * costo de ESTA compra. El total no se calcula aquí: lo calcula el servidor.
 */
@Component({
  selector: 'vd-compra-dialogo',
  imports: [MatDialogModule, MatButtonModule, MatIconModule, ReactiveFormsModule, TranslateModule],
  templateUrl: './compra-dialogo.component.html',
})
export class CompraDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref =
    inject<MatDialogRef<CompraDialogoComponent, ResultadoCompra | undefined>>(MatDialogRef);
  readonly datos = inject<DatosCompraDialogo>(MAT_DIALOG_DATA);

  readonly errorFormulario = signal(false);
  private readonly enviando = signal(false);

  readonly formulario = this.fb.group({
    proveedor_nombre: [
      '',
      [Validators.required, Validators.minLength(2), Validators.maxLength(160)],
    ],
    items: this.fb.array([this.nuevoItem()]),
  });

  get items(): FormArray<FormGroup> {
    return this.formulario.get('items') as FormArray<FormGroup>;
  }

  agregarItem(): void {
    this.items.push(this.nuevoItem());
  }

  quitarItem(indice: number): void {
    if (this.items.length > 1) {
      this.items.removeAt(indice);
    }
  }

  alEnviar(): void {
    if (this.enviando() || this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      this.errorFormulario.set(this.formulario.invalid);
      return;
    }
    try {
      const bruto = this.formulario.getRawValue() as {
        proveedor_nombre: string;
        items: { producto_id: string; cantidad: string; costo_pesos: number }[];
      };
      const items = bruto.items.map((item) => ({
        producto_id: item.producto_id,
        cantidad: textoDeCantidad(miliDeCantidad(Number(String(item.cantidad).replace(',', '.')))),
        costo_unitario_centavos: Math.round(Number(item.costo_pesos) * 100),
      }));
      this.enviando.set(true);
      this.ref.close({ proveedor_nombre: bruto.proveedor_nombre.trim(), items });
    } catch {
      // Una cantidad ilegible o <= 0: el diálogo no cierra con basura.
      this.errorFormulario.set(true);
    }
  }

  cancelar(): void {
    this.ref.close(undefined);
  }

  private nuevoItem(): FormGroup {
    return this.fb.group({
      producto_id: ['', Validators.required],
      cantidad: ['', Validators.required],
      costo_pesos: [null as number | null, [Validators.required, Validators.min(0)]],
    });
  }
}
