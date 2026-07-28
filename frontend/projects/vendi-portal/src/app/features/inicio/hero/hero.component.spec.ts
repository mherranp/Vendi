import { TestBed } from '@angular/core/testing';

import { environment } from '../../../../environments/environment';
import { environment as entornoDesarrollo } from '../../../../environments/environment.development';
import { prepararPruebaI18n } from '../../../testing/i18n-prueba';
import { WHATSAPP_COMERCIAL } from '../whatsapp-comercial.token';
import { HeroComponent } from './hero.component';

describe('HeroComponent', () => {
  it('pinta la propuesta de valor y el enlace absoluto a la consola', () => {
    prepararPruebaI18n();
    const fixture = TestBed.createComponent(HeroComponent);
    fixture.detectChanges();
    const raiz = fixture.nativeElement as HTMLElement;
    expect(raiz.textContent).toContain('Del cuaderno al celular');
    expect(raiz.textContent).toContain('funciona sin internet');
    expect(raiz.textContent).toContain('fiado');
    // La consola es otro origen: href absoluto, nunca routerLink.
    const entrar = raiz.querySelector<HTMLAnchorElement>('a.hero__secundario');
    expect(entrar?.getAttribute('href')).toBe('https://app.vendi.co');
  });

  it('sin número comercial configurado NO pinta el CTA de WhatsApp', () => {
    prepararPruebaI18n([{ provide: WHATSAPP_COMERCIAL, useValue: '' }]);
    const fixture = TestBed.createComponent(HeroComponent);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('a.hero__cta')).toBeNull();
  });

  it('con número configurado pinta el wa.me con el mensaje prearmado codificado', () => {
    prepararPruebaI18n([{ provide: WHATSAPP_COMERCIAL, useValue: '573001234567' }]);
    const fixture = TestBed.createComponent(HeroComponent);
    fixture.detectChanges();
    const cta = (fixture.nativeElement as HTMLElement).querySelector<HTMLAnchorElement>(
      'a.hero__cta',
    );
    expect(cta?.getAttribute('href')).toBe(
      `https://wa.me/573001234567?text=${encodeURIComponent('Hola, quiero probar Vendi en mi tienda')}`,
    );
    expect(cta?.getAttribute('target')).toBe('_blank');
    expect(cta?.getAttribute('rel')).toContain('noopener');
  });

  it('el número del entorno, si existe, es apto para wa.me (solo dígitos)', () => {
    // Candado de formato: un '+' o un espacio rompe el enlace silenciosamente.
    expect(environment.whatsappComercial).toMatch(/^\d*$/);
  });

  it('el candado cubre TAMBIÉN el entorno de desarrollo (se prueba en local el mismo enlace)', () => {
    expect(entornoDesarrollo.whatsappComercial).toMatch(/^\d*$/);
  });

  it('la fábrica del token toma el número del entorno de producción, sin atajos', () => {
    prepararPruebaI18n();
    expect(TestBed.inject(WHATSAPP_COMERCIAL)).toBe(environment.whatsappComercial);
  });

  it('un número malformado («abc») produce un enlace wa.me roto: el candado del entorno es la ÚNICA defensa', () => {
    // Comportamiento actual, fijado a propósito como advertencia: el componente
    // confía en el token y NO valida. Si alguien debilita el candado del
    // entorno, este test es el que recuerda por qué importa.
    prepararPruebaI18n([{ provide: WHATSAPP_COMERCIAL, useValue: 'abc' }]);
    const fixture = TestBed.createComponent(HeroComponent);
    fixture.detectChanges();
    const cta = (fixture.nativeElement as HTMLElement).querySelector<HTMLAnchorElement>(
      'a.hero__cta',
    );
    expect(cta?.getAttribute('href')).toContain('wa.me/abc');
  });
});
