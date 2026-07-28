import { PRECIO_LIGHT_PESOS_MES, PRECIO_PRO_PESOS_MES, TIERS } from './planes';

// Este spec es un CANDADO, no un detalle: ADR-010 firma los precios y los
// etiqueta como hipótesis de piloto. Cambiarlos es una decisión de negocio,
// y esta suite es donde esa decisión tiene que pasar y explicarse.
describe('TIERS (ADR-010)', () => {
  it('son tres, en orden Gratis → Light → Pro, con los precios firmados', () => {
    expect(TIERS.map((t) => t.id)).toEqual(['gratis', 'light', 'pro']);
    expect(TIERS.map((t) => t.precioMensualPesos)).toEqual([0, 19_500, 40_000]);
  });

  it('Pro es el tier destacado, y solo él', () => {
    expect(TIERS.filter((t) => t.destacado).map((t) => t.id)).toEqual(['pro']);
  });

  it('los precios son enteros de pesos (nunca centavos ni flotantes)', () => {
    expect(Number.isInteger(PRECIO_LIGHT_PESOS_MES)).toBe(true);
    expect(Number.isInteger(PRECIO_PRO_PESOS_MES)).toBe(true);
    for (const tier of TIERS) {
      expect(Number.isInteger(tier.precioMensualPesos)).toBe(true);
      expect(tier.precioMensualPesos).toBeGreaterThanOrEqual(0);
    }
  });
});
