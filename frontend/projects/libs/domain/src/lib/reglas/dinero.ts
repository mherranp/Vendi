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
 * nadie sin revisarla: el servidor verifica la coherencia total/ítems con la
 * MISMA regla —cada línea redondeada a centavos enteros (ROUND_HALF_UP) y
 * luego sumada—, así que la consistencia entre el ticket del tendero y la
 * caja del negocio depende de que estas funciones sean deterministas.
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
 * ticket. Más de 3 decimales se redondean half-up al mili (la MISMA regla
 * ROUND_HALF_UP del backend: cliente y servidor cuantizan igual).
 *
 * Y lanza también cuando la positiva cuantiza a 0 mili (BUG-B del QA): una
 * línea de 0.000 kg vale $0 en el ticket y el servidor la rechaza como dato
 * inválido, envenenando la venta entera. El conteo 0 solo existe en ajustes
 * de inventario; en ventas no hay cantidad vendible menor que 0,001.
 */
export function miliDeCantidad(cantidad: number): number {
  if (!Number.isFinite(cantidad) || cantidad <= 0) {
    throw new Error(`Cantidad no vendible: ${cantidad}`);
  }
  const mili = Math.round(cantidad * MILI_POR_UNIDAD);
  if (mili === 0) {
    throw new Error(`Cantidad menor que 0,001: ${cantidad}`);
  }
  return mili;
}

/**
 * Convierte el CONTEO físico del almacenista a mili-unidades enteras.
 *
 * Espejo de `_cuantizar_conteo` del backend (`inventario/schemas.py`): el
 * cero es un conteo VÁLIDO («no queda ninguna», el schema lo admite con
 * `ge=0`), así que solo lanzan los negativos y lo ilegible. Una fracción
 * sub-mili cuantiza a 0 mili y se acepta, exactamente como hace el servidor
 * (ROUND_HALF_UP sin rechazo del cero). No confundir con `miliDeCantidad`:
 * ventas y mermas exigen `> 0`; el conteo no es una cantidad vendible.
 */
export function miliDeConteo(conteo: number): number {
  if (!Number.isFinite(conteo) || conteo < 0) {
    throw new Error(`Conteo ilegible: ${conteo}`);
  }
  return Math.round(conteo * MILI_POR_UNIDAD);
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
