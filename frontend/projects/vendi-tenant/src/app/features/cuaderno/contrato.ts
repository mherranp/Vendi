import type { components } from 'data-access';

export type ClienteConSaldo = components['schemas']['ClienteConSaldo'];
export type CreditoResumenSalida = components['schemas']['CreditoResumenSalida'];
export type CreditoDetalleSalida = components['schemas']['CreditoDetalleSalida'];
export type AbonoSalida = components['schemas']['AbonoSalida'];

/** Estados del crédito (ADR-022): un saldado nunca vuelve a vigente. */
export type EstadoCredito = 'vigente' | 'vencido' | 'saldado' | 'anulado';

export interface ClienteNuevo {
  id: string;
  nombre: string;
  telefono: string | null;
  /** Centavos; null = sin cupo. */
  limite_credito: number | null;
  nota: string | null;
}

/** Edición parcial; `null` explícito BORRA el valor en el backend. */
export type CambiosDeCliente = Partial<Omit<ClienteNuevo, 'id'>>;

export interface AbonoNuevo {
  id: string;
  metodo_pago: 'efectivo' | 'transferencia' | 'otro';
  /** Centavos. */
  monto: number;
  nota: string | null;
}
