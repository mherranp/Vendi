import { provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import { CATALOGO_MINIMO_ES, fusionarCatalogos } from 'data-access';
import { Observable, of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';

import catalogoApp from '../../../../public/i18n/es.json';
import { CerrarCajaDialogoComponent, DatosCerrarCaja } from './cerrar-caja-dialogo.component';

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

interface Montaje {
  fixture: ComponentFixture<CerrarCajaDialogoComponent>;
  cerrar: ReturnType<typeof vi.fn>;
}

function montar(datos: DatosCerrarCaja): Montaje {
  TestBed.resetTestingModule();
  const cerrar = vi.fn();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      { provide: MatDialogRef, useValue: { close: cerrar } },
      { provide: MAT_DIALOG_DATA, useValue: datos },
      ...provideTranslateService({
        lang: 'es',
        fallbackLang: 'es',
        loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
      }),
    ],
  });
  TestBed.inject(TranslateService).use('es');
  return { fixture: TestBed.createComponent(CerrarCajaDialogoComponent), cerrar };
}

/**
 * QA adversarial del arqueo (ADR-021): el contado entra en pesos y sale en
 * centavos enteros; cero es un contado legítimo (gaveta vacía); y el esperado
 * solo se revela cuando el backend lo mandó — nunca se pinta un cero inventado.
 */
describe('CerrarCajaDialogoComponent — conversiones y revelación del esperado', () => {
  it('el contado en pesos sale en centavos enteros', () => {
    const m = montar({ esperado: 230000 });
    m.fixture.componentInstance.alEnviar({ contado_pesos: 2250 });
    expect(m.cerrar).toHaveBeenCalledWith(225000);
  });

  it('contar cero es legítimo: cierra con 0, no con undefined', () => {
    const m = montar({ esperado: 230000 });
    m.fixture.componentInstance.alEnviar({ contado_pesos: 0 });
    expect(m.cerrar).toHaveBeenCalledWith(0);
  });

  it('un contado negativo no sale del diálogo', () => {
    const m = montar({ esperado: 230000 });
    m.fixture.componentInstance.alEnviar({ contado_pesos: -5 });
    expect(m.cerrar).not.toHaveBeenCalled();
  });

  it('un contado ilegible no sale del diálogo', () => {
    const m = montar({ esperado: 230000 });
    m.fixture.componentInstance.alEnviar({ contado_pesos: 'abc' });
    expect(m.cerrar).not.toHaveBeenCalled();
  });

  it('el segundo envío es un no-op (candado de doble clic sobre el arqueo)', () => {
    const m = montar({ esperado: 230000 });
    m.fixture.componentInstance.alEnviar({ contado_pesos: 2250 });
    m.fixture.componentInstance.alEnviar({ contado_pesos: 2250 });
    expect(m.cerrar).toHaveBeenCalledTimes(1);
  });

  it('con esperado del backend se muestra formateado en pesos', () => {
    const m = montar({ esperado: 230000 });
    m.fixture.detectChanges();
    const visible = (m.fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(visible).toContain('2.300');
  });

  it('sin esperado (null) NO se pinta la cifra — ni siquiera un cero', () => {
    const m = montar({ esperado: null });
    m.fixture.detectChanges();
    const visible = (m.fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(visible).not.toContain('Esperado');
    expect(visible).not.toContain('$');
  });
});
