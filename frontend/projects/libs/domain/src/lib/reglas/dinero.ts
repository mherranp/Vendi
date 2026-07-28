/**
 * Aritmética del dinero y del granel del POS (ADR-018).
 *
 * Dos reglas duras:
 *
 *  - El dinero son centavos ENTEROS. Ningún flotante toca un precio, un total
 *    o un saldo.
 *  - Las cantidades son mili-unidades ENTERAS (1 kg = 1000), porque el granel
 *    se vende con 3 decimales (el backend cuantiza `cantidad` a 3) y la masa
 *    tampoco es un flotante.
 *
 * El único sitio donde existe un número fraccionario es el input del tendero,
 * y se convierte en el borde (`miliDeCantidad`).
 *
 * La regla de redondeo la fija el plan del POS (decisión 6) y no la mueve
 * nadie sin revisarla: el servidor NO recalcula el total —acepta el que manda
 * el dispositivo—, así que la consistencia entre el ticket del tendero y la
 * caja del negocio depende de que esta función sea determinista.
 */

/** Factor de la unidad de cantidad: 1 unidad = 1000 mili-unidades. */
export const MILI_POR_UNIDAD = 1000;

/** Línea del ticket en memoria: enteros por todas partes. */
export interface LineaTicket {
  producto_id: string;
  nombre: string;
  cantidad_mili: number;
  precio_unitario_centavos: number;
}

/**
 * Convierte la cantidad que tecleó el tendero a mili-unidades enteras.
 *
 * Lanza sobre lo no vendible (cero, negativos, NaN, infinito): quien llama
 * decide si ignora la tecla o avisa, pero ninguna de esas cantidades llega al
 * ticket. Más de 3 decimales se truncan al mili (el tendero no pesa
 * microgramos; el backend cuantiza igual).
 */
export function miliDeCantidad(cantidad: number): number {
  if (!Number.isFinite(cantidad) || cantidad <= 0) {
    throw new Error(`Cantidad no vendible: ${cantidad}`);
  }
  return Math.round(cantidad * MILI_POR_UNIDAD);
}

/**
 * Serializa la cantidad para el payload del sync: string de 3 decimales, el
 * formato exacto que el backend cuantiza (`Decimal`). Un número JSON
 * arrastraría binario (0.1 + 0.2) hacia el validador.
 */
export function textoDeCantidad(cantidadMili: number): string {
  return (cantidadMili / MILI_POR_UNIDAD).toFixed(3);
}

/**
 * Total de una línea en centavos, redondeo half-up al centavo.
 *
 * `Math.round` es half-up exacto para positivos (los precios y cantidades de
 * una venta siempre lo son). La línea es la unidad que ve el tendero: el
 * ticket cuadra línea a línea y el total es su suma.
 */
export function totalLineaCentavos(precioUnitarioCentavos: number, cantidadMili: number): number {
  return Math.round((precioUnitarioCentavos * cantidadMili) / MILI_POR_UNIDAD);
}

/** Total del ticket: suma de los totales de línea YA redondeados. */
export function totalTicketCentavos(lineas: readonly LineaTicket[]): number {
  return lineas.reduce(
    (total, linea) =>
      total + totalLineaCentavos(linea.precio_unitario_centavos, linea.cantidad_mili),
    0,
  );
}

/** Pesos colombianos para mostrar: enteros, con separador de miles. */
export function formatearPesos(centavos: number): string {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    maximumFractionDigits: 0,
  }).format(centavos / 100);
}
