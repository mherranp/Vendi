import { TestBed } from '@angular/core/testing';

import { prepararPruebaI18n } from '../../../testing/i18n-prueba';
import { ConfianzaComponent } from './confianza.component';

describe('ConfianzaComponent', () => {
  it('pinta las tres pruebas de confianza', () => {
    prepararPruebaI18n();
    const fixture = TestBed.createComponent(ConfianzaComponent);
    fixture.detectChanges();
    const raiz = fixture.nativeElement as HTMLElement;
    expect(raiz.textContent).toContain('Hecho para la tienda de barrio');
    expect(raiz.textContent).toContain('Funciona sin internet');
    expect(raiz.textContent).toContain('Tus datos son de tu negocio');
    expect(raiz.textContent).toContain('mostrador');
  });

  it('tiene su propio ancla para la barra de navegación', () => {
    prepararPruebaI18n();
    const fixture = TestBed.createComponent(ConfianzaComponent);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('#confianza')).not.toBeNull();
  });
});
