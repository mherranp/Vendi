import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import { CATALOGO_MINIMO_ES, fusionarCatalogos } from 'data-access';
import { Observable, of } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import catalogoApp from '../../../../public/i18n/es.json';
import {
  AjusteDialogoComponent,
  DatosAjusteDialogo,
  ResultadoAjuste,
} from './ajuste-dialogo.component';

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

const PRODUCTO = {
  producto_id: '5f1d0e2a-0000-4000-8000-bbbbbbbbbbbb',
  nombre: 'Arroz por kilo',
  stock_actual: '5.000',
  stock_minimo: '1.000',
  nivel: 'ok',
} as DatosAjusteDialogo['producto'];

interface Montaje {
  componente: AjusteDialogoComponent;
  cerrar: ReturnType<typeof vi.fn>;
}

/**
 * QA adversarial del ajuste de inventario (ADR-020): las conversiones del
 * borde (coma/punto, mili-unidades) y los rechazos que no deben producir un
 * payload inválido. Se conduce `alEnviar` en directo: lo que se defiende es
 * el contrato que sale del diálogo, no el pintado del formulario.
 */
describe('AjusteDialogoComponent — conversiones y rechazos del borde', () => {
  let m: Montaje;

  beforeEach(() => {
    TestBed.resetTestingModule();
    const cerrar = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        { provide: MatDialogRef, useValue: { close: cerrar } },
        { provide: MAT_DIALOG_DATA, useValue: { producto: PRODUCTO } },
        ...provideTranslateService({
          lang: 'es',
          fallbackLang: 'es',
          loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
        }),
      ],
    });
    TestBed.inject(TranslateService).use('es');
    m = { componente: TestBed.createComponent(AjusteDialogoComponent).componentInstance, cerrar };
  });

  it('el conteo manda stock_contado como texto de 3 decimales, nunca la cantidad', () => {
    m.componente.alEnviar({ tipo: 'ajuste', cantidad: '14', motivo: 'Conteo de cierre' });
    expect(m.cerrar).toHaveBeenCalledWith({
      tipo: 'ajuste',
      producto_id: PRODUCTO.producto_id,
      motivo: 'Conteo de cierre',
      stock_contado: '14.000',
    } satisfies ResultadoAjuste);
  });

  it('la merma manda cantidad y NUNCA stock_contado (el check del backend lo exige)', () => {
    m.componente.alEnviar({ tipo: 'merma', cantidad: '2', motivo: 'Se dañó con la nevera' });
    const resultado = m.cerrar.mock.calls[0][0] as ResultadoAjuste;
    expect(resultado).toEqual({
      tipo: 'merma',
      producto_id: PRODUCTO.producto_id,
      motivo: 'Se dañó con la nevera',
      cantidad: '2.000',
    });
    expect('stock_contado' in resultado).toBe(false);
  });

  it('la cantidad con coma ("1,5") se entiende como 1.500, la regla del granel', () => {
    m.componente.alEnviar({ tipo: 'merma', cantidad: '1,5', motivo: 'Roto en transporte' });
    expect(m.cerrar).toHaveBeenCalledWith(
      expect.objectContaining({ cantidad: '1.500' }) as ResultadoAjuste,
    );
  });

  it('una cantidad por debajo del mili (0.0004) no sale del diálogo', () => {
    m.componente.alEnviar({ tipo: 'merma', cantidad: '0.0004', motivo: 'Casi nada' });
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('el conteo CERO sale del diálogo («no queda nada» es un conteo legítimo, ge=0 del backend)', () => {
    m.componente.alEnviar({ tipo: 'ajuste', cantidad: '0', motivo: 'No queda ninguna' });
    expect(m.cerrar).toHaveBeenCalledWith({
      tipo: 'ajuste',
      producto_id: PRODUCTO.producto_id,
      motivo: 'No queda ninguna',
      stock_contado: '0.000',
    } satisfies ResultadoAjuste);
  });

  it('una merma de cero no sale del diálogo (merma cero no existe)', () => {
    m.componente.alEnviar({ tipo: 'merma', cantidad: '0', motivo: 'Prueba de cero' });
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('una cantidad ilegible ("abc") no sale del diálogo', () => {
    m.componente.alEnviar({ tipo: 'ajuste', cantidad: 'abc', motivo: 'Texto basura' });
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('un ajuste sin motivo real no sale del diálogo', () => {
    m.componente.alEnviar({ tipo: 'ajuste', cantidad: '14', motivo: '  x ' });
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('el segundo envío del mismo formulario es un no-op (candado de doble clic)', () => {
    m.componente.alEnviar({ tipo: 'ajuste', cantidad: '14', motivo: 'Conteo de cierre' });
    m.componente.alEnviar({ tipo: 'ajuste', cantidad: '14', motivo: 'Conteo de cierre' });
    expect(m.cerrar).toHaveBeenCalledTimes(1);
  });
});
