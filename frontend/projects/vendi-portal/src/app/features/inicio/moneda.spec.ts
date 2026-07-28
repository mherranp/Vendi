import { formatearPesos, pesosPorDia } from './moneda';

describe('formatearPesos', () => {
  it('el cero se muestra sin separadores', () => {
    expect(formatearPesos(0)).toBe('$0');
  });

  it('menos de mil no lleva separador', () => {
    expect(formatearPesos(999)).toBe('$999');
  });

  it('los miles llevan punto, a la colombiana', () => {
    expect(formatearPesos(1_300)).toBe('$1.300');
  });

  it('los dos precios firmados en ADR-010', () => {
    expect(formatearPesos(19_500)).toBe('$19.500');
    expect(formatearPesos(40_000)).toBe('$40.000');
  });

  it('millones con todos los separadores', () => {
    expect(formatearPesos(1_000_000)).toBe('$1.000.000');
  });

  it('rechaza lo que no es un entero en pesos', () => {
    expect(() => formatearPesos(-1)).toThrow();
    expect(() => formatearPesos(19.5)).toThrow();
    expect(() => formatearPesos(Number.NaN)).toThrow();
  });

  it('aguanta el rango completo de precios razonables sin desbordar', () => {
    // La landing formatea lo que `planes.ts` diga; si un día Pro sube al tope
    // del rango firmado ($60.000) o más, el formato no se rompe.
    expect(formatearPesos(60_000)).toBe('$60.000');
    expect(formatearPesos(99_999_999)).toBe('$99.999.999');
  });
});

describe('pesosPorDia', () => {
  it('el plan gratis no tiene ancla por día', () => {
    expect(pesosPorDia(0)).toBe(0);
  });

  it('redondea estrictamente AL ALZA al múltiplo de 50: nunca prometer de menos', () => {
    // 19.500/30 = 650 exactos: «menos de $650» sería FALSO. Sube a 700.
    expect(pesosPorDia(19_500)).toBe(700);
    // 40.000/30 = 1.333,33…: sube a 1.350.
    expect(pesosPorDia(40_000)).toBe(1_350);
  });

  it('la promesa «menos de» es CIERTA en un barrido de precios (invariante, no ejemplos)', () => {
    // Para cualquier precio: el ancla diaria × 30 cubre el mes con creces
    // (estrictamente mayor) y es un múltiplo de $50 presentable.
    for (let precio = 1; precio <= 200_000; precio += 97) {
      expect(pesosPorDia(precio) * 30).toBeGreaterThan(precio);
      expect(pesosPorDia(precio) % 50).toBe(0);
    }
  });
});
