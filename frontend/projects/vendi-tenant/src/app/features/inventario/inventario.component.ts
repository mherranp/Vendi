import { Component, TemplateRef, computed, inject, signal, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { PageEvent } from '@angular/material/paginator';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { TranslateModule } from '@ngx-translate/core';
import { HasPermissionDirective } from 'auth';
import { PageHeaderComponent, StatusBadgeComponent, VarianteEstado } from 'ui-kit';
import { ColumnaTabla, DataTableComponent } from 'ui-kit/data-table';
import {
  AjusteDialogoComponent,
  DatosAjusteDialogo,
  ResultadoAjuste,
} from './ajuste-dialogo.component';
import {
  CompraDialogoComponent,
  DatosCompraDialogo,
  ResultadoCompra,
} from './compra-dialogo.component';
import { NivelStock, StockSalida } from './contrato';
import { InventarioService } from './inventario.service';

const TAMANO_PAGINA = 10;

interface FilaStock extends StockSalida {
  acciones?: never;
}

const NIVELES: readonly NivelStock[] = ['agotado', 'critico', 'bajo', 'ok'];

/**
 * Mi inventario: el stock con su nivel derivado (ADR-020).
 *
 * El stock negativo se muestra tal cual — «vendiste de más según el sistema»
 * es información, no un error— y las alertas se filtran en el servidor
 * (`solo_alertas`: agotado o por debajo del mínimo). Ajustar y comprar son
 * gestos del almacenista y del dueño; el cajero solo lee. Lo que cada rol
 * puede hacer lo manda el backend; la pantalla solo se ahorra el 403
 * (ADR-023).
 */
@Component({
  selector: 'vd-inventario',
  imports: [
    TranslateModule,
    MatButtonModule,
    MatIconModule,
    MatSlideToggleModule,
    HasPermissionDirective,
    PageHeaderComponent,
    DataTableComponent,
    StatusBadgeComponent,
  ],
  templateUrl: './inventario.component.html',
  styleUrl: './inventario.component.scss',
})
export class InventarioComponent {
  private readonly servicio = inject(InventarioService);
  private readonly dialogos = inject(MatDialog);

  readonly filas = signal<FilaStock[]>([]);
  readonly total = signal(0);
  readonly cargando = signal(false);
  /** `true` si la última carga falló: la pantalla ofrece reintentar. */
  readonly fallo = signal(false);
  readonly indicePagina = signal(0);
  readonly tamanoPagina = TAMANO_PAGINA;
  readonly soloAlertas = signal(false);

  /** Candado del diálogo: dos clics rápidos no abren dos diálogos apilados. */
  private readonly dialogoAbierto = signal(false);

  private readonly plantillaNivel = viewChild<TemplateRef<{ $implicit: FilaStock }>>('celdaNivel');
  private readonly plantillaAcciones =
    viewChild<TemplateRef<{ $implicit: FilaStock }>>('celdaAcciones');

  // Las plantillas son consultas de vista: la primera pasada las ve como
  // `undefined` y la tabla cae a pintar el valor crudo; en cuanto se
  // resuelven, la señal notifica y el `computed` pasa a la plantilla. Por eso
  // `viewChild()` y no `viewChild.required()` (mismo patrón que Catálogo).
  readonly columnas = computed<ColumnaTabla<FilaStock>[]>(() => [
    { clave: 'nombre', etiqueta: 'inventario.columna.nombre' },
    { clave: 'stock_actual', etiqueta: 'inventario.columna.stock' },
    { clave: 'stock_minimo', etiqueta: 'inventario.columna.minimo' },
    { clave: 'nivel', etiqueta: 'inventario.columna.nivel', plantilla: this.plantillaNivel() },
    {
      clave: 'acciones',
      etiqueta: 'inventario.columna.acciones',
      plantilla: this.plantillaAcciones(),
      ancho: '8rem',
    },
  ]);

  constructor() {
    this.recargar();
  }

  recargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    this.servicio
      .stock(this.indicePagina() * TAMANO_PAGINA, TAMANO_PAGINA, this.soloAlertas())
      .subscribe({
        next: (pagina) => {
          // Última página vaciada: sin este retroceso el paginador deja al
          // usuario en una página que ya no existe (mismo patrón que Catálogo).
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
          // apaga el indicador y se deja salida: sin esto, spinner eterno.
          this.cargando.set(false);
          this.fallo.set(true);
        },
      });
  }

  alternarAlertas(solo: boolean): void {
    this.soloAlertas.set(solo);
    // Vuelta a la primera página: el conjunto filtrado cambia de tamaño.
    this.indicePagina.set(0);
    this.recargar();
  }

  alPaginar(evento: PageEvent): void {
    this.indicePagina.set(evento.pageIndex);
    this.recargar();
  }

  ajustar(producto: FilaStock): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    // El id se genera AL ABRIR: el reenvío del mismo formulario es el no-op
    // idempotente del servidor, no un ajuste duplicado (decisión 7).
    const id = crypto.randomUUID();
    const datos: DatosAjusteDialogo = { producto };
    this.dialogos
      .open<AjusteDialogoComponent, DatosAjusteDialogo, ResultadoAjuste | undefined>(
        AjusteDialogoComponent,
        { data: datos, width: '32rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargando.set(true);
        this.servicio.ajustar({ id, ...resultado }).subscribe({
          next: () => this.recargar(),
          // El interceptor ya avisó con el mensaje del backend.
          error: () => this.cargando.set(false),
        });
      });
  }

  registrarCompra(): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const id = crypto.randomUUID();
    // Recorte declarado (decisión 9): el selector ofrece la página de stock
    // ya cargada; la búsqueda en todo el catálogo es mejora posterior.
    const datos: DatosCompraDialogo = { productos: this.filas() };
    this.dialogos
      .open<CompraDialogoComponent, DatosCompraDialogo, ResultadoCompra | undefined>(
        CompraDialogoComponent,
        { data: datos, width: '40rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargando.set(true);
        this.servicio.registrarCompra({ id, ...resultado }).subscribe({
          next: () => this.recargar(),
          error: () => this.cargando.set(false),
        });
      });
  }

  varianteDeNivel(nivel: string): VarianteEstado {
    switch (nivel) {
      case 'agotado':
        return 'peligro';
      case 'critico':
        return 'aviso';
      case 'bajo':
        return 'info';
      default:
        return 'exito';
    }
  }

  /** Clave i18n del nivel; un nivel desconocido se pinta crudo, sin inventar. */
  etiquetaDeNivel(nivel: string): string {
    return NIVELES.includes(nivel as NivelStock) ? `inventario.nivel.${nivel}` : nivel;
  }
}
