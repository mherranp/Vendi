/**
 * Formato de dinero de la landing, en pesos colombianos.
 *
 * No usa `Intl.NumberFormat`: la salida de ICU varía entre versiones de Node
 * y navegadores (espacio duro, símbolo con o sin separación), y el precio de
 * la página pública tiene que verse IDÉNTICO en el test, en CI y en el
 * celular del tendero. Los precios son enteros de pesos —Colombia no usa
 * centavos en el habla— así que el formateador es una agrupación de miles.
 */

/**
 * `$` + miles con punto: 19_500 → `$19.500`.
 *
 * @throws si el valor no es un entero no negativo: un precio con decimales o
 *   negativo en la landing es un error de datos, no algo que maquillar.
 */
export function formatearPesos(valor: number): string {
  if (!Number.isInteger(valor) || valor < 0) {
    throw new Error(`formatearPesos espera un entero de pesos no negativo; recibió: ${valor}`);
  }
  return '$' + String(valor).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

/**
 * El ancla «menos de X al día», redondeada estrictamente AL ALZA al múltiplo
 * de $50 siguiente.
 *
 * «Menos de» es una promesa: si el cociente exacto cae en un múltiplo de 50
 * (19.500/30 = 650), decir «menos de $650» es falso — es exactamente $650—.
 * Por eso el redondeo es `floor + 50`, no `ceil`. El plan gratis no tiene
 * ancla: devuelve 0 y la plantilla no la pinta.
 */
export function pesosPorDia(precioMensual: number): number {
  if (precioMensual <= 0) {
    return 0;
  }
  return Math.floor(precioMensual / 30 / 50) * 50 + 50;
}
