import type { components } from 'data-access';

export type PyLSalida = components['schemas']['PyLSalida'];
export type ForecastSalida = components['schemas']['ForecastSalida'];

export type PeriodoPyl = 'dia' | 'semana' | 'mes';

/** Una línea de dinero del reporte: clave i18n y valor en centavos. */
export interface LineaDeDinero {
  clave: string;
  centavos: number;
}
