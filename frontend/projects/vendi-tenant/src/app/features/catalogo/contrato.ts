import type { components } from 'data-access';

export type ProductoSalida = components['schemas']['ProductoSalida'];

/** Unidades del catálogo (ADR-019): el granel se vende por peso o volumen. */
export const UNIDADES_DE_MEDIDA = ['unidad', 'kg', 'g', 'lt', 'ml'] as const;
export type UnidadDeMedida = (typeof UNIDADES_DE_MEDIDA)[number];

/** IVA como dato, no módulo fiscal (ADR-019): los tres valores de Colombia. */
export const TASAS_IVA = [0, 5, 19] as const;

/** Lo que el formulario de producto produce; números ya en unidades del cable. */
export interface ProductoNuevo {
  id: string;
  nombre: string;
  categoria: string | null;
  codigo_barras: string | null;
  /** Centavos enteros. */
  precio_venta: number;
  unidad_medida: UnidadDeMedida;
  iva_pct: number;
  /** String de 3 decimales (`"5.000"`): el granel no cabe en un entero. */
  stock_minimo: string;
}

/** PATCH: todo opcional; lo que no se toca no viaja. */
export type CambiosDeProducto = Partial<Omit<ProductoNuevo, 'id'>>;
