import type { components } from 'data-access';

export type StockSalida = components['schemas']['StockSalida'];
export type AjusteCreado = components['schemas']['AjusteCreado'];
export type CompraDetalleSalida = components['schemas']['CompraDetalleSalida'];

/** Niveles que documenta el backend (`nivel` llega como string libre). */
export type NivelStock = 'agotado' | 'critico' | 'bajo' | 'ok';

/**
 * El ajuste (ADR-020): `stock_contado` para el conteo, `cantidad` para la
 * merma; nunca los dos. `motivo` obligatorio — un ajuste sin justificación
 * es un desfalco con buenos modales. Online-obligatorio: el delta lo calcula
 * el servidor contra SU stock del momento.
 */
export interface AjusteNuevo {
  id: string;
  tipo: 'ajuste' | 'merma';
  producto_id: string;
  motivo: string;
  stock_contado?: string;
  cantidad?: string;
}

export interface ItemCompra {
  producto_id: string;
  /** String de 3 decimales. */
  cantidad: string;
  costo_unitario_centavos: number;
}

/** El total NO viaja: lo calcula el servidor (ADR-020, decisión 7 del módulo). */
export interface CompraNueva {
  id: string;
  proveedor_nombre: string;
  items: ItemCompra[];
}
