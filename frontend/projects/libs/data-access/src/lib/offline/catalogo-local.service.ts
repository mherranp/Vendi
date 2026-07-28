import { HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { lastValueFrom } from 'rxjs';
import type { paths } from '../api-client';
import { ApiService } from '../api.service';
import { SILENCIAR_AVISO_ERROR } from '../interceptors/error.interceptor';
import type { ClienteLocal, ProductoLocal } from './modelos-locales';
import { VendiDb } from './vendi.db';

type DeltaSalida =
  paths['/api/v1/sync/delta']['get']['responses']['200']['content']['application/json'];
type PaginaClientes =
  paths['/api/v1/clientes']['get']['responses']['200']['content']['application/json'];

/**
 * Marca inicial del delta: «desde el principio de los tiempos». El servidor
 * responde con todo el catálogo vivo y su marca `hasta`.
 */
const MARCA_INICIAL = '1970-01-01T00:00:00.000Z';

const LIMITE_BUSQUEDA = 20;

/**
 * El catálogo local del POS (ADR-017).
 *
 * El delta baja los cambios del servidor al IndexedDB: productos vivos
 * (upsert — el LWW lo arbitra el orden de recepción en el servidor, nunca el
 * reloj del dispositivo) y tumbas (borrados). El watermark `hasta` del
 * servidor se guarda en `meta` y se devuelve como próximo `desde`: es marca
 * del SERVIDOR, no del reloj local.
 *
 * Los clientes NO tienen delta (D-28): se asimilan online por
 * `GET /clientes` en el mismo gesto de refresco. Offline, el dispositivo ve
 * los que él mismo creó (decisión 4 del plan).
 */
@Injectable({ providedIn: 'root' })
export class CatalogoLocalService {
  private readonly db = inject(VendiDb);
  private readonly api = inject(ApiService);

  /** Baja el delta al IndexedDB y avanza el watermark, en una transacción. */
  async refrescarDelta(): Promise<{ recibidos: number; eliminados: number }> {
    const desde = (await this.leerWatermark()) ?? MARCA_INICIAL;
    const delta = await lastValueFrom(
      this.api.get<DeltaSalida>(
        '/sync/delta',
        { desde },
        { context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true) },
      ),
    );
    await this.db.transaction('rw', [this.db.productos, this.db.meta], async () => {
      await this.db.productos.bulkPut(delta.productos.map(mapearProducto));
      await this.db.productos.bulkDelete(delta.eliminados);
      await this.db.meta.put({ clave: 'delta_hasta', valor: delta.hasta });
    });
    return { recibidos: delta.productos.length, eliminados: delta.eliminados.length };
  }

  /**
   * Búsqueda del POS: subcadena de nombre (sin distinguir mayúsculas) o
   * código de barras EXACTO — un lector de código «teclea» el código entero.
   * Todo local: sin red no hay búsqueda contra la API que valga.
   */
  buscar(consulta: string): Promise<ProductoLocal[]> {
    const limpia = consulta.trim();
    if (limpia.length === 0) {
      return this.db.productos.orderBy('nombre').limit(LIMITE_BUSQUEDA).toArray();
    }
    const minusculas = limpia.toLowerCase();
    return this.db.productos
      .filter(
        (producto) =>
          producto.nombre.toLowerCase().includes(minusculas) || producto.codigo_barras === limpia,
      )
      .limit(LIMITE_BUSQUEDA)
      .toArray();
  }

  contar(): Promise<number> {
    return this.db.productos.count();
  }

  /** Asimila los clientes del servidor (rodeo de D-28; solo con red). */
  async cargarClientes(): Promise<number> {
    const pagina = await lastValueFrom(
      this.api.get<PaginaClientes>(
        '/clientes',
        { limit: 200 },
        { context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true) },
      ),
    );
    const asimilados: ClienteLocal[] = pagina.items.map((cliente) => ({
      id: cliente.id,
      nombre: cliente.nombre,
      telefono: cliente.telefono ?? null,
      limite_credito: cliente.limite_credito ?? null,
      origen: 'servidor',
    }));
    await this.db.clientes.bulkPut(asimilados);
    return asimilados.length;
  }

  buscarClientes(consulta: string): Promise<ClienteLocal[]> {
    const limpia = consulta.trim().toLowerCase();
    if (limpia.length === 0) {
      return this.db.clientes.orderBy('nombre').limit(LIMITE_BUSQUEDA).toArray();
    }
    return this.db.clientes
      .filter((cliente) => cliente.nombre.toLowerCase().includes(limpia))
      .limit(LIMITE_BUSQUEDA)
      .toArray();
  }

  private async leerWatermark(): Promise<string | null> {
    const entrada = await this.db.meta.get('delta_hasta');
    return typeof entrada?.valor === 'string' ? entrada.valor : null;
  }
}

function mapearProducto(producto: DeltaSalida['productos'][number]): ProductoLocal {
  return {
    id: producto.id,
    nombre: producto.nombre,
    categoria: producto.categoria ?? null,
    codigo_barras: producto.codigo_barras ?? null,
    precio_venta: producto.precio_venta,
    unidad_medida: producto.unidad_medida,
    stock_actual: producto.stock_actual,
  };
}
