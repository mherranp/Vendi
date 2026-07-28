/**
 * Los datos comerciales de la landing, fijados por ADR-010.
 *
 * Los precios son una hipótesis firmada (el propio ADR los etiqueta como
 * supuestos a validar en el piloto): cambiarlos es una decisión de negocio,
 * no un retoque, y por eso `planes.spec.ts` los bloquea — quien mueva un
 * número rompe el test y tiene que decirlo.
 *
 * Pro se publica en $40.000, el borde inferior del rango firmado
 * ($40.000–$60.000): una landing no puede mostrar un rango sin mentir, y el
 * piso es el coherente con la sensibilidad de precio del segmento y con el
 * escalón Light «precio de un café». Subirlo después es decisión de negocio
 * protegida por el spec.
 */

/** Precio mensual del tier Light, en pesos colombianos (ADR-010). */
export const PRECIO_LIGHT_PESOS_MES = 19_500;

/** Precio mensual del tier Pro, en pesos colombianos (ADR-010, borde inferior del rango). */
export const PRECIO_PRO_PESOS_MES = 40_000;

export interface TierComercial {
  readonly id: 'gratis' | 'light' | 'pro';
  readonly precioMensualPesos: number;
  /**
   * Pro es la recomendación visual: es el tier que el trial deja probar un
   * mes y al que se degrada después — la comparación honesta ya la vivió el
   * tendero.
   */
  readonly destacado: boolean;
}

/** Los tres tiers de ADR-010, en el orden en que se muestran. */
export const TIERS: readonly TierComercial[] = [
  { id: 'gratis', precioMensualPesos: 0, destacado: false },
  { id: 'light', precioMensualPesos: PRECIO_LIGHT_PESOS_MES, destacado: false },
  { id: 'pro', precioMensualPesos: PRECIO_PRO_PESOS_MES, destacado: true },
];
