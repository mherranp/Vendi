import { TestBed } from '@angular/core/testing';

import { prepararPruebaI18n } from '../../../testing/i18n-prueba';
import { pesosPorDia } from '../moneda';
import { TIERS } from '../planes';
import { PreciosComponent } from './precios.component';

describe('PreciosComponent', () => {
  function crear(): HTMLElement {
    prepararPruebaI18n();
    const fixture = TestBed.createComponent(PreciosComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('muestra los tres tiers con los precios reales de ADR-010', () => {
    const raiz = crear();
    expect(raiz.textContent).toContain('Gratis');
    expect(raiz.textContent).toContain('Light');
    expect(raiz.textContent).toContain('Pro');
    expect(raiz.textContent).toContain('$0');
    expect(raiz.textContent).toContain('$19.500');
    expect(raiz.textContent).toContain('$40.000');
  });

  it('ancla el precio al día sin prometer de menos (redondeo estricto al alza)', () => {
    const raiz = crear();
    // 19.500/30 = 650 exactos: «menos de $650» sería falso; la regla sube a 700.
    expect(raiz.textContent).toContain('menos de $700 al día');
    // 40.000/30 = 1.333,33…: sube a 1.350.
    expect(raiz.textContent).toContain('menos de $1.350 al día');
  });

  it('el trial es el sello estrella: 1 mes de Pro, sin tarjeta', () => {
    const raiz = crear();
    expect(raiz.textContent).toContain('1 mes de Pro gratis');
    expect(raiz.textContent).toContain('sin tarjeta');
  });

  it('el add-on DIAN está marcado como próximamente y SIN precio', () => {
    const raiz = crear();
    expect(raiz.textContent).toContain('Facturación electrónica DIAN');
    expect(raiz.textContent).toContain('Próximamente');
    const dian = raiz.querySelector('.precios__dian');
    expect(dian?.textContent).not.toContain('$');
  });

  it('los límites de ADR-010 están en la comparativa, como texto legible', () => {
    const raiz = crear();
    for (const esperado of ['100', '500', 'Ilimitado', 'Incluido', '30 consultas al día']) {
      expect(raiz.textContent).toContain(esperado);
    }
    // Nada de ✓/✗ mudas: un lector de pantalla tiene que poder leer la tabla.
    expect(raiz.textContent).toContain('No incluido');
  });

  it('la comparativa fija celda a celda los límites de ADR-010 (no solo «aparecen por ahí»)', () => {
    prepararPruebaI18n();
    const componente = TestBed.createComponent(PreciosComponent).componentInstance;
    const fila = (sufijo: string) =>
      componente.filas.find((f) => f.clave === `portal.precios.${sufijo}`)?.valores;
    expect(fila('fila_productos')).toEqual(['100', '500', 'ilimitado']);
    expect(fila('fila_usuarios')).toEqual(['1', '2', '3']);
    expect(fila('fila_fiado')).toEqual(['no', 'si', 'si']);
    expect(fila('fila_asistente')).toEqual(['asistente_5_mes', 'asistente_30_dia', 'ilimitado']);
    expect(fila('fila_reportes')).toEqual(['no', 'reportes_briefing', 'reportes_completos']);
    // Toda fila tiene exactamente una celda por tier: una de más o de menos
    // descuadra la comparativa entera silenciosamente.
    for (const f of componente.filas) {
      expect(f.valores).toHaveLength(TIERS.length);
    }
  });

  it('el ancla «menos de» es cierta para cada tier de pago: cubre el mes entero', () => {
    for (const tier of TIERS.filter((t) => t.precioMensualPesos > 0)) {
      expect(pesosPorDia(tier.precioMensualPesos) * 30).toBeGreaterThan(tier.precioMensualPesos);
    }
  });

  it('el plan gratis NO muestra ancla por día ni precio distinto de $0', () => {
    const raiz = crear();
    const gratis = Array.from(raiz.querySelectorAll('.precios__tier')).find((t) =>
      t.querySelector('h3')?.textContent?.includes('Gratis'),
    );
    expect(gratis).toBeDefined();
    expect(gratis?.querySelector('.precios__dia')).toBeNull();
    expect(gratis?.textContent).toContain('$0');
    expect(gratis?.textContent).not.toContain('al día');
  });
});
