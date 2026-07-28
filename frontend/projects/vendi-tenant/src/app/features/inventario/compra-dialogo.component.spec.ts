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
  CompraDialogoComponent,
  DatosCompraDialogo,
  ResultadoCompra,
} from './compra-dialogo.component';

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

const DATOS: DatosCompraDialogo = {
  productos: [
    { producto_id: 'p1', nombre: 'Arroz', stock_actual: '5.000' },
    { producto_id: 'p2', nombre: 'Aceite', stock_actual: '3.000' },
  ] as DatosCompraDialogo['productos'],
};

interface Montaje {
  componente: CompraDialogoComponent;
  cerrar: ReturnType<typeof vi.fn>;
}

/**
 * QA adversarial del registro de compra (ADR-020): el costo entra en pesos y
 * sale en centavos enteros, la cantidad sale como texto de 3 decimales y una
 * línea inválida envenena el envío entero (el diálogo no cierra con basura).
 */
describe('CompraDialogoComponent — conversiones y rechazos del borde', () => {
  let m: Montaje;

  beforeEach(() => {
    TestBed.resetTestingModule();
    const cerrar = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        { provide: MatDialogRef, useValue: { close: cerrar } },
        { provide: MAT_DIALOG_DATA, useValue: DATOS },
        ...provideTranslateService({
          lang: 'es',
          fallbackLang: 'es',
          loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
        }),
      ],
    });
    TestBed.inject(TranslateService).use('es');
    m = { componente: TestBed.createComponent(CompraDialogoComponent).componentInstance, cerrar };
  });

  function rellenarCabecera(proveedor = 'Distribuidora La 33'): void {
    m.componente.formulario.controls['proveedor_nombre'].setValue(proveedor);
  }

  function rellenarItem(indice: number, valor: object): void {
    m.componente.items.at(indice).setValue(valor);
  }

  it('costo en pesos → centavos enteros y cantidad → texto de 3 decimales', () => {
    rellenarCabecera();
    rellenarItem(0, { producto_id: 'p1', cantidad: '1,5', costo_pesos: 1250.5 });
    m.componente.agregarItem();
    rellenarItem(1, { producto_id: 'p2', cantidad: '2', costo_pesos: 10 });
    m.componente.alEnviar();
    expect(m.cerrar).toHaveBeenCalledWith({
      proveedor_nombre: 'Distribuidora La 33',
      items: [
        { producto_id: 'p1', cantidad: '1.500', costo_unitario_centavos: 125050 },
        { producto_id: 'p2', cantidad: '2.000', costo_unitario_centavos: 1000 },
      ],
    } satisfies ResultadoCompra);
  });

  it('dos líneas del mismo producto salen al servidor: el 422 por duplicado es del backend', () => {
    rellenarCabecera();
    rellenarItem(0, { producto_id: 'p1', cantidad: '1', costo_pesos: 100 });
    m.componente.agregarItem();
    rellenarItem(1, { producto_id: 'p1', cantidad: '2', costo_pesos: 100 });
    m.componente.alEnviar();
    const resultado = m.cerrar.mock.calls[0][0] as ResultadoCompra;
    expect(resultado.items.map((item) => item.producto_id)).toEqual(['p1', 'p1']);
  });

  it('una cantidad de cero envenena el envío entero: el diálogo no cierra', () => {
    rellenarCabecera();
    rellenarItem(0, { producto_id: 'p1', cantidad: '0', costo_pesos: 100 });
    m.componente.alEnviar();
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('una cantidad ilegible ("abc") envenena el envío entero', () => {
    rellenarCabecera();
    rellenarItem(0, { producto_id: 'p1', cantidad: 'abc', costo_pesos: 100 });
    m.componente.alEnviar();
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('con el formulario incompleto no cierra y lo marca todo como tocado', () => {
    m.componente.alEnviar();
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
    expect(m.componente.formulario.touched).toBe(true);
  });

  it('no deja quitar la última línea: una compra sin ítems no existe', () => {
    expect(m.componente.items.length).toBe(1);
    m.componente.quitarItem(0);
    expect(m.componente.items.length).toBe(1);
  });

  it('el segundo envío del mismo formulario es un no-op (candado de doble clic)', () => {
    rellenarCabecera();
    rellenarItem(0, { producto_id: 'p1', cantidad: '1', costo_pesos: 100 });
    m.componente.alEnviar();
    m.componente.alEnviar();
    expect(m.cerrar).toHaveBeenCalledTimes(1);
  });
});
