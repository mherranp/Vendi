import { Injectable, inject } from '@angular/core';
import { LineaTicket, textoDeCantidad, totalLineaCentavos, totalTicketCentavos } from 'domain';
import type { ClaveMeta, ClienteLocal, OperacionEnCola, VentaLocal } from './modelos-locales';
import { VendiDb } from './vendi.db';

/** Entrada del cobro: lo que la UI del POS ya validó visualmente. */
export interface EntradaCobro {
  lineas: readonly LineaTicket[];
  medio_pago: 'efectivo' | 'fiado';
  cliente: ClienteLocal | null;
  /** `YYYY-MM-DD`; solo fiado. Esta entrega siempre la manda en null (decisión 4). */
  fecha_vencimiento: string | null;
}

/**
 * El outbox local del POS (ADR-017 en espejo del backend).
 *
 * Cobra SIN RED: la venta, su operación en `cola_sync` y el avance de los dos
 * contadores (`consecutivo_local` —el número del ticket— y `ultima_secuencia`
 * —el orden FIFO de la cola, que también cuentan los `cliente.crear`—)
 * confirman o revientan JUNTOS en una transacción Dexie. No existe ningún
 * camino que escriba la venta sin encolarla.
 *
 * La venta es append-only (ADR-018): nace `completada` con el id que el
 * dispositivo le puso (ese id ES la PK en el servidor y el `id` de la
 * operación del lote: la idempotencia es estructural).
 */
@Injectable({ providedIn: 'root' })
export class VentasOfflineService {
  private readonly db = inject(VendiDb);

  async cobrar(entrada: EntradaCobro): Promise<VentaLocal> {
    if (entrada.lineas.length === 0) {
      throw new Error('El ticket no tiene líneas.');
    }
    if (entrada.medio_pago === 'fiado' && !entrada.cliente) {
      // El cuaderno se lleva por persona (ADR-009): fiado sin cliente no existe.
      throw new Error('El fiado exige un cliente.');
    }
    if (entrada.medio_pago === 'efectivo' && entrada.fecha_vencimiento) {
      throw new Error('La fecha de vencimiento solo aplica al fiado.');
    }
    const ahora = new Date();

    return this.db.transaction(
      'rw',
      [this.db.ventas_locales, this.db.cola_sync, this.db.meta],
      async () => {
        const consecutivo = (await this.numeroMeta('consecutivo_local')) + 1;
        const secuencia = (await this.numeroMeta('ultima_secuencia')) + 1;
        const venta: VentaLocal = {
          id: crypto.randomUUID(),
          consecutivo_local: consecutivo,
          estado: 'completada',
          medio_pago: entrada.medio_pago,
          total_centavos: totalTicketCentavos(entrada.lineas),
          cliente_id: entrada.cliente?.id ?? null,
          cliente_nombre: entrada.cliente?.nombre ?? null,
          fecha_vencimiento: entrada.fecha_vencimiento,
          creada_en_cliente: ahora.toISOString(),
          items: entrada.lineas.map((linea) => ({
            producto_id: linea.producto_id,
            nombre: linea.nombre,
            cantidad_mili: linea.cantidad_mili,
            precio_unitario_centavos: linea.precio_unitario_centavos,
            total_linea_centavos: totalLineaCentavos(
              linea.precio_unitario_centavos,
              linea.cantidad_mili,
            ),
          })),
        };
        // Shape EXACTO de VentaCrearSync (ventas/schemas.py): la cantidad es
        // string de 3 decimales, el formato que el backend cuantiza.
        const datos: Record<string, unknown> = {
          consecutivo_local: venta.consecutivo_local,
          estado: venta.estado,
          medio_pago: venta.medio_pago,
          total_centavos: venta.total_centavos,
          cliente_id: venta.cliente_id,
          fecha_vencimiento: venta.fecha_vencimiento,
          creada_en_cliente: venta.creada_en_cliente,
          items: venta.items.map((item) => ({
            producto_id: item.producto_id,
            cantidad: textoDeCantidad(item.cantidad_mili),
            precio_unitario_centavos: item.precio_unitario_centavos,
          })),
        };
        await this.db.ventas_locales.add(venta);
        await this.db.cola_sync.add(
          this.operacion(venta.id, 'venta.crear', secuencia, datos, ahora),
        );
        await this.ponerMeta('consecutivo_local', consecutivo);
        await this.ponerMeta('ultima_secuencia', secuencia);
        return venta;
      },
    );
  }

  /**
   * Alta de cliente en el dispositivo: la venta fiada sin red lo referencia y
   * el servidor lo adopta como PK (operación `cliente.crear`, cierre de D-10
   * por adopción). El FIFO por `secuencia` garantiza que esta operación sube
   * ANTES que la venta que fía: la dependencia es estructural.
   */
  async crearClienteLocal(entrada: {
    nombre: string;
    telefono: string | null;
  }): Promise<ClienteLocal> {
    const nombre = entrada.nombre.trim();
    if (nombre.length < 2) {
      // Mismo piso que ClienteCrearSync (min 2): rechazar aquí evita una
      // `rechazada` segura en el servidor y una venta fiada huérfana detrás.
      throw new Error('El nombre del cliente necesita al menos 2 letras.');
    }
    if (nombre.length > 160) {
      // BUG-E del QA: ClienteCrearSync también tiene max 160 y sin el tope
      // local el `cliente.crear` moría como dead-letter — y la venta fiada
      // detrás, en cascada, con `cliente_no_encontrado`.
      throw new Error('El nombre del cliente no puede pasar de 160 letras.');
    }
    const ahora = new Date();
    return this.db.transaction(
      'rw',
      [this.db.clientes, this.db.cola_sync, this.db.meta],
      async () => {
        const secuencia = (await this.numeroMeta('ultima_secuencia')) + 1;
        const cliente: ClienteLocal = {
          id: crypto.randomUUID(),
          nombre,
          telefono: entrada.telefono,
          limite_credito: null,
          origen: 'local',
        };
        await this.db.clientes.add(cliente);
        // ClienteCrearSync tiene extra="forbid": solo estos dos campos viajan.
        await this.db.cola_sync.add(
          this.operacion(
            cliente.id,
            'cliente.crear',
            secuencia,
            { nombre: cliente.nombre, telefono: cliente.telefono },
            ahora,
          ),
        );
        await this.ponerMeta('ultima_secuencia', secuencia);
        return cliente;
      },
    );
  }

  /** El historial local, del más reciente al más antiguo. */
  historial(limite = 50): Promise<VentaLocal[]> {
    return this.db.ventas_locales.orderBy('consecutivo_local').reverse().limit(limite).toArray();
  }

  private operacion(
    id: string,
    tipo: OperacionEnCola['tipo'],
    secuencia: number,
    datos: Record<string, unknown>,
    ahora: Date,
  ): OperacionEnCola {
    return {
      id,
      tipo,
      secuencia,
      datos,
      estado: 'pendiente',
      intentos: 0,
      proximo_intento_en: 0,
      ultimo_error: null,
      creada_en: ahora.getTime(),
    };
  }

  private async numeroMeta(clave: 'consecutivo_local' | 'ultima_secuencia'): Promise<number> {
    const entrada = await this.db.meta.get(clave);
    return typeof entrada?.valor === 'number' ? entrada.valor : 0;
  }

  private async ponerMeta(clave: ClaveMeta, valor: string | number | boolean): Promise<void> {
    await this.db.meta.put({ clave, valor });
  }
}
