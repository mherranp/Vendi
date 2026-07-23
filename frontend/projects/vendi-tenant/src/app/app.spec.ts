import { TestBed } from '@angular/core/testing';
import { TranslateService, provideTranslateService } from '@ngx-translate/core';
import { App } from './app';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      // Sin `loader`: el catálogo se inyecta a mano con `setTranslation`, así el
      // test no depende de HTTP ni del archivo de assets.
      providers: [provideTranslateService({ fallbackLang: 'es', lang: 'es' })],
    }).compileComponents();

    TestBed.inject(TranslateService).setTranslation('es', {
      app: { titulo: 'Título de prueba', descripcion: 'Descripción de prueba' },
    });
  });

  it('debería crearse', () => {
    const fixture = TestBed.createComponent(App);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('no debería pintar claves crudas de i18n', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const texto = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(texto).toContain('Título de prueba');
    expect(texto).not.toContain('app.titulo');
    expect(texto).not.toContain('app.descripcion');
  });
});
