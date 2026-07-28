/**
 * Amarre compile-time con el cliente generado (patrón `contrato.ts` de
 * vendi-admin): los nombres son los del OpenAPI, no se redeclaran. Si el
 * backend cambia el contrato, esto deja de compilar — que es su trabajo.
 */
import type { components } from 'data-access';

export type SesionActualSalida = components['schemas']['SesionActualSalida'];
export type SesionSalida = components['schemas']['SesionSalida'];
export type MovimientoSalida = components['schemas']['MovimientoSalida'];
export type ArqueoSalida = components['schemas']['ArqueoSalida'];
export type ArqueoConDesglose = components['schemas']['ArqueoConDesglose'];

/** Lista cerrada del backend (migración 0008, ADR-021). */
export type TipoMovimiento = 'ingreso' | 'egreso';
export type CategoriaMovimiento = 'arriendo' | 'servicios' | 'retiro_dueno' | 'otro';

/** Cuerpo de `POST /caja/movimientos`; `id` es la ancla de idempotencia. */
export interface MovimientoNuevo {
  id: string;
  tipo: TipoMovimiento;
  categoria: CategoriaMovimiento;
  /** Centavos enteros. */
  monto: number;
  motivo: string;
}
