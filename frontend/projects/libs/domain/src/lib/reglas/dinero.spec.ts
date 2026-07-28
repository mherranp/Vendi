import {
  MILI_POR_UNIDAD,
  LineaTicket,
  formatearPesos,
  miliDeCantidad,
  textoDeCantidad,
  totalLineaCentavos,
  totalTicketCentavos,
} from './dinero';

/**
 * La aritmética del dinero del POS. El servidor NO recalcula el total (el
 * contrato congela lo que manda el dispositivo), así que estas funciones son
 * la regla — y por eso esta tabla de casos es larga a propósito.
 */
describe('dinero (ADR-018: enteros, nunca flotantes)', () => {
  it('convierte cantidades del tendero a mili-unidades enteras', () => {
    expect(miliDeCantidad(1)).toBe(MILI_POR_UNIDAD);
    expect(miliDeCantidad(1.5)).toBe(1500);
    expect(miliDeCantidad(0.333)).toBe(333);
    expect(miliDeCantidad(2.75)).toBe(2750);
  });

  it('rechaza cantidades que no son vendibles', () => {
    expect(() => miliDeCantidad(0)).toThrow();
    expect(() => miliDeCantidad(-1)).toThrow();
    expect(() => miliDeCantidad(Number.NaN)).toThrow();
    expect(() => miliDeCantidad(Number.POSITIVE_INFINITY)).toThrow();
  });

  it('serializa la cantidad como string de 3 decimales (lo que el backend cuantiza)', () => {
    expect(textoDeCantidad(1500)).toBe('1.500');
    expect(textoDeCantidad(333)).toBe('0.333');
    expect(textoDeCantidad(25)).toBe('0.025');
  });

  it('total de línea exacto en centavos, con redondeo half-up', () => {
    // 3 unidades de $50,00
    expect(totalLineaCentavos(5000, 3000)).toBe(15000);
    // 0,333 kg a $10,00/kg = 333 centavos exactos
    expect(totalLineaCentavos(1000, 333)).toBe(333);
    // 2,5 kg a $19,99/kg = 4997,5 → 4998 (half-up, nunca hacia abajo)
    expect(totalLineaCentavos(1999, 2500)).toBe(4998);
    // 100 g a $10,07/kg = 100,7 → 101
    expect(totalLineaCentavos(1007, 100)).toBe(101);
  });

  it('no arrastra el error binario de los flotantes (el caso 0.1 + 0.2)', () => {
    // Tres líneas de 0,1 kg a $10,07/kg: cada una redondea a 101 y el total
    // es 303 — determinista, sin la deriva de 0.30000000000000004.
    const lineas: LineaTicket[] = [0, 1, 2].map((n) => ({
      producto_id: `p-${n}`,
      nombre: 'Arroz',
      cantidad_mili: 100,
      precio_unitario_centavos: 1007,
    }));
    expect(totalTicketCentavos(lineas)).toBe(303);
  });

  it('el total del ticket es la suma de las líneas YA redondeadas', () => {
    const lineas: LineaTicket[] = [
      { producto_id: 'a', nombre: 'A', cantidad_mili: 2500, precio_unitario_centavos: 1999 },
      { producto_id: 'b', nombre: 'B', cantidad_mili: 1000, precio_unitario_centavos: 5000 },
    ];
    expect(totalTicketCentavos(lineas)).toBe(4998 + 5000);
  });

  it('aguanta valores grandes sin perder enteros', () => {
    // $9.999.999,99 el kilo, 999,999 kg: por debajo de 2^53, exacto.
    expect(totalLineaCentavos(999_999_999, 999_999)).toBe(999_998_999_000);
  });

  it('formatea pesos colombianos sin decimales', () => {
    expect(formatearPesos(125000)).toContain('1.250');
    expect(formatearPesos(0)).toContain('0');
  });

  it('formatea millones con separador de miles (el total de una semana buena)', () => {
    expect(formatearPesos(123_456_700)).toContain('1.234.567');
  });
});
