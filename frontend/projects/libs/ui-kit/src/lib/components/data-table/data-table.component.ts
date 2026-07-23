import { NgTemplateOutlet } from '@angular/common';
import { Component, TemplateRef, computed, input, output } from '@angular/core';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatTableModule } from '@angular/material/table';
import { TranslateModule } from '@ngx-translate/core';
import { EmptyStateComponent } from '../empty-state/empty-state.component';

export interface ColumnaTabla<T> {
  clave: keyof T & string;
  /** Clave de traducción del encabezado. */
  etiqueta: string;
  plantilla?: TemplateRef<{ $implicit: T }>;
  ordenable?: boolean;
  ancho?: string;
}

/**
 * Tabla con paginación y ordenación, delegadas al servidor.
 *
 * Cosechado de `ui-components/data-table`. Es presentación pura: no pagina ni
 * ordena en memoria, emite `paginaCambia`/`ordenCambia` y espera recibir las
 * filas ya resueltas. Con RLS eso además es lo correcto: la fuente de verdad
 * de cuántas filas hay es el servidor, no lo que el cliente tenga cargado.
 */
@Component({
  selector: 'vd-data-table',
  imports: [
    NgTemplateOutlet,
    MatTableModule,
    MatSortModule,
    MatPaginatorModule,
    MatProgressBarModule,
    TranslateModule,
    EmptyStateComponent,
  ],
  templateUrl: './data-table.component.html',
  styleUrls: ['./data-table.component.scss'],
})
export class DataTableComponent<T> {
  readonly columnas = input<ColumnaTabla<T>[]>([]);
  readonly filas = input<T[]>([]);
  readonly total = input<number>(0);
  readonly tamanoPagina = input<number>(10);
  readonly indicePagina = input<number>(0);
  readonly cargando = input<boolean>(false);
  readonly mostrarPaginador = input<boolean>(true);
  readonly iconoVacio = input<string>('inbox');
  readonly tituloVacio = input<string>('ui.tabla.vacia');
  readonly descripcionVacio = input<string>('');

  readonly paginaCambia = output<PageEvent>();
  readonly ordenCambia = output<Sort>();

  readonly clavesDeColumna = computed(() => this.columnas().map((c) => c.clave));

  alPaginar(e: PageEvent): void {
    this.paginaCambia.emit(e);
  }

  alOrdenar(e: Sort): void {
    this.ordenCambia.emit(e);
  }
}
