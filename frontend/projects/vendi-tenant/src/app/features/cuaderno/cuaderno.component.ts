import { Component, TemplateRef, computed, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { PageEvent } from '@angular/material/paginator';
import { MatSelectModule } from '@angular/material/select';
import { Router } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { HasPermissionDirective } from 'auth';
import { formatearPesos } from 'domain';
import { PageHeaderComponent, StatusBadgeComponent, VarianteEstado } from 'ui-kit';
import { ColumnaTabla, DataTableComponent } from 'ui-kit/data-table';
import {
  ClienteDialogoComponent,
  DatosClienteDialogo,
  ResultadoCliente,
} from './cliente-dialogo.component';
import { ClienteConSaldo, CreditoResumenSalida, EstadoCredito } from './contrato';
import { CuadernoService } from './cuaderno.service';

const TAMANO_PAGINA = 10;

interface FilaCliente extends ClienteConSaldo {
  acciones?: never;
}
interface FilaCredito extends CreditoResumenSalida {
  acciones?: never;
}

const ESTADOS: readonly EstadoCredito[] = ['vigente', 'vencido', 'saldado', 'anulado'];

/**
 * Mi cuaderno: los clientes con su deuda viva y los fiados (ADR-009/022).
 *
 * El cupo es advertencia, nunca bloqueo: `cupo_excedido` se pinta como badge
 * de aviso (aquí vive el aviso que el POS no muestra — decisión 10 del plan).
 * La tira de vencidos es el gesto de cobro del día: cuántos son y un filtro
 * para verlos. El detalle de cada crédito tiene su propia ruta.
 */
@Component({
  selector: 'vd-cuaderno',
  imports: [
    TranslateModule,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    HasPermissionDirective,
    PageHeaderComponent,
    DataTableComponent,
    StatusBadgeComponent,
  ],
  templateUrl: './cuaderno.component.html',
  styleUrl: './cuaderno.component.scss',
})
export class CuadernoComponent {
  private readonly servicio = inject(CuadernoService);
  private readonly dialogos = inject(MatDialog);
  private readonly router = inject(Router);

  readonly clientes = signal<FilaCliente[]>([]);
  readonly totalClientes = signal(0);
  readonly indiceClientes = signal(0);
  readonly consulta = signal('');
  readonly creditos = signal<FilaCredito[]>([]);
  readonly totalCreditos = signal(0);
  readonly indiceCreditos = signal(0);
  /** null = filtro por defecto del backend (vigente + vencido). */
  readonly estadoFiltro = signal<string | null>(null);
  /** Cuántos fiados vencidos esperan cobro; alimenta la tira. */
  readonly totalVencidos = signal(0);
  readonly cargando = signal(false);
  readonly fallo = signal(false);
  readonly tamanoPagina = TAMANO_PAGINA;
  private readonly dialogoAbierto = signal(false);

  readonly formatear = formatearPesos;

  // Las plantillas son consultas de vista: la primera pasada las ve como
  // `undefined` y la tabla cae a pintar el valor crudo; en cuanto se
  // resuelven, la señal notifica y el `computed` pasa a la plantilla
  // (mismo patrón que Catálogo e Inventario).
  private readonly plantillaSaldo =
    viewChild<TemplateRef<{ $implicit: FilaCliente }>>('celdaSaldo');
  private readonly plantillaAccionesCliente =
    viewChild<TemplateRef<{ $implicit: FilaCliente }>>('celdaAccionesCliente');
  private readonly plantillaMonto =
    viewChild<TemplateRef<{ $implicit: FilaCredito }>>('celdaMonto');
  private readonly plantillaDebe = viewChild<TemplateRef<{ $implicit: FilaCredito }>>('celdaDebe');
  private readonly plantillaEstado =
    viewChild<TemplateRef<{ $implicit: FilaCredito }>>('celdaEstado');
  private readonly plantillaAccionesCredito =
    viewChild<TemplateRef<{ $implicit: FilaCredito }>>('celdaAccionesCredito');

  readonly columnasClientes = computed<ColumnaTabla<FilaCliente>[]>(() => [
    { clave: 'nombre', etiqueta: 'cuaderno.columna.nombre' },
    { clave: 'telefono', etiqueta: 'cuaderno.columna.telefono' },
    {
      clave: 'saldo_pendiente_total',
      etiqueta: 'cuaderno.columna.saldo',
      plantilla: this.plantillaSaldo(),
    },
    {
      clave: 'acciones',
      etiqueta: 'cuaderno.columna.acciones',
      plantilla: this.plantillaAccionesCliente(),
      ancho: '7rem',
    },
  ]);

  readonly columnasCreditos = computed<ColumnaTabla<FilaCredito>[]>(() => [
    { clave: 'cliente_nombre', etiqueta: 'cuaderno.columna.cliente' },
    {
      clave: 'monto_total',
      etiqueta: 'cuaderno.columna.monto',
      plantilla: this.plantillaMonto(),
    },
    {
      clave: 'saldo_pendiente',
      etiqueta: 'cuaderno.columna.debe',
      plantilla: this.plantillaDebe(),
    },
    { clave: 'fecha_vencimiento', etiqueta: 'cuaderno.columna.vence' },
    { clave: 'estado', etiqueta: 'cuaderno.columna.estado', plantilla: this.plantillaEstado() },
    {
      clave: 'acciones',
      etiqueta: 'cuaderno.columna.acciones',
      plantilla: this.plantillaAccionesCredito(),
      ancho: '6rem',
    },
  ]);

  constructor() {
    this.recargar();
  }

  recargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    this.servicio
      .clientes(this.indiceClientes() * TAMANO_PAGINA, TAMANO_PAGINA, this.consulta())
      .subscribe({
        next: (pagina) => {
          this.clientes.set(pagina.items);
          this.totalClientes.set(pagina.total);
          this.cargarCreditos();
          this.cargarVencidos();
        },
        error: () => {
          this.cargando.set(false);
          this.fallo.set(true);
        },
      });
  }

  buscar(): void {
    this.indiceClientes.set(0);
    this.recargar();
  }

  filtrarEstado(estado: string | null): void {
    this.estadoFiltro.set(estado);
    this.indiceCreditos.set(0);
    this.cargarCreditos();
  }

  alPaginarClientes(evento: PageEvent): void {
    this.indiceClientes.set(evento.pageIndex);
    this.recargar();
  }

  alPaginarCreditos(evento: PageEvent): void {
    this.indiceCreditos.set(evento.pageIndex);
    this.cargarCreditos();
  }

  crearCliente(): void {
    this.abrirFormularioCliente({});
  }

  editarCliente(cliente: FilaCliente): void {
    this.abrirFormularioCliente({ cliente });
  }

  verCredito(credito: FilaCredito): void {
    this.router.navigate(['/cuaderno/creditos', credito.id]).catch((error: unknown) => {
      console.error('No se pudo abrir el detalle del crédito.', error);
    });
  }

  varianteDeEstado(estado: string): VarianteEstado {
    switch (estado) {
      case 'vencido':
        return 'peligro';
      case 'vigente':
        return 'info';
      case 'saldado':
        return 'exito';
      default:
        return 'neutro';
    }
  }

  /** Clave i18n del estado; uno desconocido se pinta crudo, sin inventar. */
  etiquetaDeEstado(estado: string): string {
    return ESTADOS.includes(estado as EstadoCredito) ? `cuaderno.estado.${estado}` : estado;
  }

  private cargarCreditos(): void {
    this.servicio
      .creditos(this.estadoFiltro(), this.indiceCreditos() * TAMANO_PAGINA, TAMANO_PAGINA)
      .subscribe({
        next: (pagina) => {
          this.creditos.set(pagina.items);
          this.totalCreditos.set(pagina.total);
          this.cargando.set(false);
        },
        error: () => {
          this.cargando.set(false);
          this.fallo.set(true);
        },
      });
  }

  private cargarVencidos(): void {
    this.servicio.vencidos().subscribe({
      next: (pagina) => this.totalVencidos.set(pagina.total),
      // La llamada viaja silenciada: si falla, la tira simplemente no sale.
      error: () => this.totalVencidos.set(0),
    });
  }

  private abrirFormularioCliente(datos: DatosClienteDialogo): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    // El id se genera AL ABRIR: el reenvío del mismo alta es el no-op
    // idempotente del servidor, no un cliente duplicado (decisión 7).
    const id = datos.cliente ? null : crypto.randomUUID();
    this.dialogos
      .open<ClienteDialogoComponent, DatosClienteDialogo, ResultadoCliente | undefined>(
        ClienteDialogoComponent,
        { data: datos, width: '32rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargando.set(true);
        const operacion = datos.cliente
          ? this.servicio.editarCliente(datos.cliente.id, resultado)
          : this.servicio.crearCliente({ id: id ?? crypto.randomUUID(), ...resultado });
        operacion.subscribe({
          next: () => this.recargar(),
          // El interceptor ya avisó con el mensaje del backend.
          error: () => this.cargando.set(false),
        });
      });
  }
}
