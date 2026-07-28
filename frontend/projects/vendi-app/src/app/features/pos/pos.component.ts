import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import {
  CatalogoLocalService,
  ClienteLocal,
  Notificador,
  ProductoLocal,
  SincronizadorService,
  VentaLocal,
  VentasOfflineService,
} from 'data-access';
import {
  LineaTicket,
  MILI_POR_UNIDAD,
  formatearPesos,
  miliDeCantidad,
  totalLineaCentavos,
  totalTicketCentavos,
} from 'domain';

/**
 * El punto de venta: la pantalla por la que existe esta app.
 *
 * Todo lo que hace el tendero aquí funciona SIN RED: el catálogo se lee del
 * IndexedDB (lo siembra el delta), el cobro escribe en la base local y encola
 * en la misma transacción (el outbox de `VentasOfflineService`), y el estado
 * de la cola se ve siempre arriba: «N por sincronizar» es la promesa visible
 * de que nada se pierde. La red solo se nota en que el contador baja solo.
 */
@Component({
  selector: 'vd-pos',
  imports: [TranslateModule, FormsModule, MatButtonModule, MatIconModule],
  templateUrl: './pos.component.html',
  styleUrl: './pos.component.scss',
})
export class PosComponent implements OnInit {
  private readonly catalogo = inject(CatalogoLocalService);
  private readonly ventas = inject(VentasOfflineService);
  private readonly sincronizador = inject(SincronizadorService);
  private readonly notificador = inject(Notificador);
  private readonly traductor = inject(TranslateService);

  readonly consulta = signal('');
  readonly resultados = signal<ProductoLocal[]>([]);
  readonly lineas = signal<LineaTicket[]>([]);
  readonly total = computed(() => totalTicketCentavos(this.lineas()));

  readonly pendientes = this.sincronizador.pendientes;
  readonly enError = this.sincronizador.enError;
  readonly sincronizando = this.sincronizador.sincronizando;

  readonly catalogoVacio = signal(false);
  readonly medioPago = signal<'efectivo' | 'fiado'>('efectivo');
  readonly consultaCliente = signal('');
  readonly clientes = signal<ClienteLocal[]>([]);
  readonly cliente = signal<ClienteLocal | null>(null);
  readonly ultimaVenta = signal<VentaLocal | null>(null);
  readonly cobrando = signal(false);

  readonly formatear = formatearPesos;

  /** Total de línea con la misma regla del dominio: nunca la fórmula cruda en plantilla. */
  totalDeLinea(linea: LineaTicket): string {
    return formatearPesos(totalLineaCentavos(linea.precio_unitario_centavos, linea.cantidad_mili));
  }

  /**
   * La promesa del arranque completo. Angular ignora lo que devuelve
   * `ngOnInit`, así que se guarda aquí: el `catch` la deja siempre observada
   * y el spec la espera para no cerrar la base de pruebas a mitad del ciclo.
   */
  arranque: Promise<void> = Promise.resolve();

  ngOnInit(): void {
    this.sincronizador.escucharConectividad();
    this.arranque = this.arrancarDatos().catch((error) => {
      // Sin base local no hay POS offline: se avisa y la pantalla queda viva.
      console.error('El arranque del POS falló.', error);
      this.notificador.error(this.traductor.instant('layout.error_inesperado'));
    });
  }

  private async arrancarDatos(): Promise<void> {
    await this.sincronizador.recuperarEnviosInterrumpidos();
    await this.refrescarDatos();
  }

  /** El delta y los clientes bajan si hay red; si no, se trabaja con lo local. */
  private async refrescarDatos(): Promise<void> {
    try {
      await this.catalogo.refrescarDelta();
      await this.catalogo.cargarClientes();
    } catch {
      // Sin red: el catálogo y los clientes locales son la verdad de hoy.
    }
    this.catalogoVacio.set((await this.catalogo.contar()) === 0);
    await this.buscar('');
    await this.sincronizador.sincronizar();
  }

  async buscar(consulta: string): Promise<void> {
    this.consulta.set(consulta);
    this.resultados.set(await this.catalogo.buscar(consulta));
  }

  agregar(producto: ProductoLocal): void {
    this.lineas.update((lineas) => {
      const existente = lineas.find((l) => l.producto_id === producto.id);
      if (existente) {
        return lineas.map((l) =>
          l.producto_id === producto.id
            ? { ...l, cantidad_mili: l.cantidad_mili + MILI_POR_UNIDAD }
            : l,
        );
      }
      return [
        ...lineas,
        {
          producto_id: producto.id,
          nombre: producto.nombre,
          cantidad_mili: MILI_POR_UNIDAD,
          precio_unitario_centavos: producto.precio_venta,
        },
      ];
    });
  }

  /** Acepta coma o punto (el teclado de la tienda tiene las dos). */
  fijarCantidad(productoId: string, valor: string): void {
    const cantidad = Number(valor.replace(',', '.'));
    if (!Number.isFinite(cantidad) || cantidad <= 0) {
      return;
    }
    const mili = miliDeCantidad(cantidad);
    this.lineas.update((lineas) =>
      lineas.map((l) => (l.producto_id === productoId ? { ...l, cantidad_mili: mili } : l)),
    );
  }

  quitar(productoId: string): void {
    this.lineas.update((lineas) => lineas.filter((l) => l.producto_id !== productoId));
  }

  elegirMedioPago(medio: 'efectivo' | 'fiado'): void {
    this.medioPago.set(medio);
  }

  async buscarCliente(consulta: string): Promise<void> {
    this.consultaCliente.set(consulta);
    this.clientes.set(await this.catalogo.buscarClientes(consulta));
  }

  elegirCliente(cliente: ClienteLocal): void {
    this.cliente.set(cliente);
  }

  /** Alta en el mostrador: el cliente nace local y sube por la cola (FIFO). */
  async crearCliente(): Promise<void> {
    const nombre = this.consultaCliente().trim();
    if (nombre.length < 2) {
      return;
    }
    const cliente = await this.ventas.crearClienteLocal({ nombre, telefono: null });
    this.cliente.set(cliente);
    await this.buscarCliente('');
  }

  async cobrar(): Promise<void> {
    if (this.lineas().length === 0 || this.cobrando()) {
      return;
    }
    if (this.medioPago() === 'fiado' && !this.cliente()) {
      this.notificador.advertencia(this.traductor.instant('pos.fiado_sin_cliente'));
      return;
    }
    this.cobrando.set(true);
    try {
      const venta = await this.ventas.cobrar({
        lineas: this.lineas(),
        medio_pago: this.medioPago(),
        cliente: this.cliente(),
        fecha_vencimiento: null,
      });
      this.ultimaVenta.set(venta);
      this.lineas.set([]);
      this.cliente.set(null);
      this.medioPago.set('efectivo');
      this.notificador.exito(
        this.traductor.instant('pos.cobrada', { numero: venta.consecutivo_local }),
      );
      this.sincronizador.notificarVentaCobrada();
    } catch (error) {
      // Un fallo de Dexie aquí significa que la venta NO quedó registrada:
      // hay que decirlo en voz alta, no dejar la promesa sin observar.
      console.error('El cobro falló antes de escribir la venta local.', error);
      this.notificador.error(this.traductor.instant('pos.error_cobro'));
    } finally {
      this.cobrando.set(false);
    }
  }

  async reintentar(): Promise<void> {
    try {
      await this.sincronizador.reintentar();
    } catch (error) {
      // El backoff del sincronizador lo volverá a intentar solo; el aviso es
      // para que el tendero sepa que el gesto manual no surtió efecto.
      console.error('El reintento manual del drenado falló.', error);
      this.notificador.error(this.traductor.instant('pos.error_reintento'));
    }
  }
}
