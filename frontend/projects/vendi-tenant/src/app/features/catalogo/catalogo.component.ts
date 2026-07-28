import { Component, TemplateRef, computed, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatMenuModule } from '@angular/material/menu';
import { PageEvent } from '@angular/material/paginator';
import { TranslateModule } from '@ngx-translate/core';
import { HasPermissionDirective } from 'auth';
import { formatearPesos } from 'domain';
import { PageHeaderComponent } from 'ui-kit';
import { ConfirmDialogComponent, ConfirmDialogData } from 'ui-kit/confirm-dialog';
import { ColumnaTabla, DataTableComponent } from 'ui-kit/data-table';
import { CatalogoService } from './catalogo.service';
import { ProductoNuevo, ProductoSalida } from './contrato';
import { DatosProductoDialogo, ProductoDialogoComponent } from './producto-dialogo.component';

const TAMANO_PAGINA_INICIAL = 10;

/**
 * Fila de la tabla: el producto más una clave técnica para la columna de
 * acciones. `ColumnaTabla<T>.clave` es `keyof T` y los botones no corresponden
 * a ningún campo: `never` opcional no puede tomar ningún valor, así que nadie
 * va a intentar leerlo (mismo truco que `FilaTenant` de vendi-admin).
 */
export interface FilaProducto extends ProductoSalida {
  acciones?: never;
}

/**
 * Mi catálogo: el CRUD de productos del negocio (ADR-019).
 *
 * Lo que cada rol puede hacer lo manda el backend; la pantalla solo se ahorra
 * el 403 (ADR-023): quien no tiene `producto:editar` (el cajero) ve la lista
 * sin el botón de alta ni el menú de edición. El `ultimo_costo` tampoco se
 * pinta: el backend ya lo anula para quien no tiene `compra:crear` y el costo
 * decide en la compra y en el P&L, no aquí (decisión 9 del plan).
 */
@Component({
  selector: 'vd-catalogo',
  imports: [
    TranslateModule,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatMenuModule,
    HasPermissionDirective,
    PageHeaderComponent,
    DataTableComponent,
  ],
  templateUrl: './catalogo.component.html',
  styleUrl: './catalogo.component.scss',
})
export class CatalogoComponent {
  private readonly servicio = inject(CatalogoService);
  private readonly dialogos = inject(MatDialog);

  readonly filas = signal<FilaProducto[]>([]);
  readonly total = signal(0);
  readonly cargando = signal(false);
  /** `true` si la última carga falló: la pantalla ofrece reintentar. */
  readonly fallo = signal(false);
  readonly indicePagina = signal(0);
  readonly tamanoPagina = signal(TAMANO_PAGINA_INICIAL);
  readonly consulta = signal('');

  /**
   * Candado del diálogo (alta, edición o confirmación): sin él, dos clics
   * rápidos abren dos diálogos apilados y el usuario puede enviar los dos.
   */
  private readonly dialogoAbierto = signal(false);

  private readonly plantillaPrecio =
    viewChild<TemplateRef<{ $implicit: FilaProducto }>>('celdaPrecio');
  private readonly plantillaStock =
    viewChild<TemplateRef<{ $implicit: FilaProducto }>>('celdaStock');
  private readonly plantillaAcciones =
    viewChild<TemplateRef<{ $implicit: FilaProducto }>>('celdaAcciones');

  // Las plantillas son consultas de vista: la primera pasada de detección de
  // cambios las ve todavía como `undefined`. No es un problema —`ColumnaTabla`
  // declara `plantilla` opcional y la tabla cae a pintar el valor crudo—, y en
  // cuanto la consulta se resuelve, la señal notifica, el `computed` se
  // recalcula y la celda pasa a su plantilla. Por eso `viewChild()` y no
  // `viewChild.required()`, que lanzaría en esa primera lectura.
  readonly columnas = computed<ColumnaTabla<FilaProducto>[]>(() => [
    { clave: 'nombre', etiqueta: 'catalogo.columna.nombre' },
    { clave: 'categoria', etiqueta: 'catalogo.columna.categoria' },
    {
      clave: 'precio_venta',
      etiqueta: 'catalogo.columna.precio',
      plantilla: this.plantillaPrecio(),
    },
    {
      clave: 'stock_actual',
      etiqueta: 'catalogo.columna.stock',
      plantilla: this.plantillaStock(),
    },
    {
      clave: 'acciones',
      etiqueta: 'catalogo.columna.acciones',
      plantilla: this.plantillaAcciones(),
      ancho: '9rem',
    },
  ]);

  readonly formatear = formatearPesos;

  constructor() {
    this.recargar();
  }

  recargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    const skip = this.indicePagina() * this.tamanoPagina();
    this.servicio.listar(skip, this.tamanoPagina(), this.consulta()).subscribe({
      next: (pagina) => {
        // Última página vaciada: el usuario estaba en la página 4, eliminó el
        // único producto que quedaba en ella y el servidor devuelve cero filas
        // con un total que dice que sí hay productos. Sin esta corrección la
        // pantalla enseña «Todavía no hay productos» —una afirmación FALSA— y
        // el paginador deja al usuario encallado en una página que ya no
        // existe. Se retrocede una página y se vuelve a pedir; el retroceso
        // converge porque `indicePagina` decrece.
        if (pagina.items.length === 0 && pagina.total > 0 && this.indicePagina() > 0) {
          this.indicePagina.update((indice) => indice - 1);
          this.recargar();
          return;
        }
        this.filas.set(pagina.items);
        this.total.set(pagina.total);
        this.cargando.set(false);
      },
      error: () => {
        // El aviso traducido ya lo emitió `errorInterceptor`. Aquí solo se
        // apaga el indicador y se deja la pantalla en un estado del que se
        // pueda salir: sin esto queda un spinner eterno.
        this.cargando.set(false);
        this.fallo.set(true);
      },
    });
  }

  buscar(): void {
    // Vuelta a la primera página: el conjunto filtrado cambia de tamaño y
    // quedarse en la página 7 de un listado que ahora tiene 3 enseñaría una
    // tabla vacía que parecería un error.
    this.indicePagina.set(0);
    this.recargar();
  }

  alPaginar(evento: PageEvent): void {
    this.indicePagina.set(evento.pageIndex);
    this.tamanoPagina.set(evento.pageSize);
    this.recargar();
  }

  crear(): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    // El id se genera AL ABRIR: el reenvío del mismo formulario es el no-op
    // idempotente del servidor, no un producto duplicado (decisión 7).
    const id = crypto.randomUUID();
    this.dialogos
      .open<ProductoDialogoComponent, DatosProductoDialogo, Omit<ProductoNuevo, 'id'> | undefined>(
        ProductoDialogoComponent,
        { width: '40rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargando.set(true);
        this.servicio.crear({ id, ...resultado }).subscribe({
          // Se recarga en vez de insertar la fila en memoria: el alta puede
          // haber cambiado la página (orden del servidor) y el `total` del
          // paginador es del servidor, no de lo que tengamos cargado.
          next: () => this.recargar(),
          // El interceptor ya avisó (EAN duplicado, límite del plan, etc.).
          error: () => this.cargando.set(false),
        });
      });
  }

  editar(producto: FilaProducto): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const datos: DatosProductoDialogo = { producto };
    this.dialogos
      .open<ProductoDialogoComponent, DatosProductoDialogo, Omit<ProductoNuevo, 'id'> | undefined>(
        ProductoDialogoComponent,
        { data: datos, width: '40rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargando.set(true);
        this.servicio.actualizar(producto.id, resultado).subscribe({
          next: () => this.recargar(),
          error: () => this.cargando.set(false),
        });
      });
  }

  eliminar(producto: FilaProducto): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const datos: ConfirmDialogData = {
      titulo: 'catalogo.confirmar.eliminar_titulo',
      mensaje: 'catalogo.confirmar.eliminar_mensaje',
      textoConfirmar: 'catalogo.confirmar.eliminar_accion',
      peligroso: true,
    };
    this.dialogos
      .open<ConfirmDialogComponent, ConfirmDialogData, boolean>(ConfirmDialogComponent, {
        data: datos,
      })
      .afterClosed()
      .subscribe((confirmado) => {
        this.dialogoAbierto.set(false);
        if (!confirmado) {
          return;
        }
        this.cargando.set(true);
        this.servicio.eliminar(producto.id).subscribe({
          next: () => this.recargar(),
          error: () => this.cargando.set(false),
        });
      });
  }
}
