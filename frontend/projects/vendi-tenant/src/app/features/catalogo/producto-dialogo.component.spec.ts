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
import { ProductoNuevo, ProductoSalida } from './contrato';
import { DatosProductoDialogo, ProductoDialogoComponent } from './producto-dialogo.component';

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

type ResultadoDialogo = Omit<ProductoNuevo, 'id'>;

interface Montaje {
  componente: ProductoDialogoComponent;
  cerrar: ReturnType<typeof vi.fn>;
}

function montar(datos?: DatosProductoDialogo): Montaje {
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
  return {
    componente: TestBed.createComponent(ProductoDialogoComponent).componentInstance,
    cerrar,
  };
}

const VALORES_VALIDOS = {
  nombre: 'Arroz 500g',
  categoria: 'Granos',
  codigo_barras: '7701234567890',
  precio_pesos: 2500,
  unidad_medida: 'unidad',
  iva_pct: 0,
  stock_minimo: '0',
};

/**
 * QA adversarial del alta/edición de producto (ADR-019): el precio entra en
 * pesos y sale en centavos enteros, el stock mínimo respeta la regla del
 * granel (coma o punto, 3 decimales, cero legítimo) y un EAN con espacios no
 * viaja sucio — el duplicado de EAN se detecta por igualdad en el servidor,
 * así que la normalización del borde es parte de la defensa.
 */
describe('ProductoDialogoComponent — conversiones y rechazos del borde', () => {
  let m: Montaje;

  beforeEach(() => {
    m = montar();
  });

  it('el precio en pesos sale en centavos enteros, redondeado al centavo', () => {
    m.componente.alEnviar({ ...VALORES_VALIDOS, precio_pesos: 2500.505 });
    expect(m.cerrar).toHaveBeenCalledWith(
      expect.objectContaining({ precio_venta: 250051 }) as ResultadoDialogo,
    );
  });

  it('el EAN viaja recortado; vacío viaja null (nunca cadena con espacios)', () => {
    m.componente.alEnviar({ ...VALORES_VALIDOS, codigo_barras: '  7701234567890  ' });
    expect(m.cerrar).toHaveBeenCalledWith(
      expect.objectContaining({ codigo_barras: '7701234567890' }) as ResultadoDialogo,
    );
    // Instancia nueva: el candado de doble envío bloquea un segundo alEnviar.
    const otro = montar();
    otro.componente.alEnviar({ ...VALORES_VALIDOS, codigo_barras: '   ' });
    expect(otro.cerrar).toHaveBeenCalledWith(
      expect.objectContaining({ codigo_barras: null }) as ResultadoDialogo,
    );
  });

  it('el stock mínimo cero ES legítimo (sin alertas) y viaja como "0.000"', () => {
    m.componente.alEnviar({ ...VALORES_VALIDOS, stock_minimo: '0' });
    expect(m.cerrar).toHaveBeenCalledWith(
      expect.objectContaining({ stock_minimo: '0.000' }) as ResultadoDialogo,
    );
  });

  it('el stock mínimo con coma ("1,5") viaja como "1.500"', () => {
    m.componente.alEnviar({ ...VALORES_VALIDOS, stock_minimo: '1,5' });
    expect(m.cerrar).toHaveBeenCalledWith(
      expect.objectContaining({ stock_minimo: '1.500' }) as ResultadoDialogo,
    );
  });

  it('un stock mínimo por debajo del mili ("0.0004") no sale del diálogo', () => {
    m.componente.alEnviar({ ...VALORES_VALIDOS, stock_minimo: '0.0004' });
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('un stock mínimo negativo no sale del diálogo', () => {
    m.componente.alEnviar({ ...VALORES_VALIDOS, stock_minimo: '-2' });
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('un precio negativo no sale del diálogo', () => {
    m.componente.alEnviar({ ...VALORES_VALIDOS, precio_pesos: -1 });
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('un nombre de una letra no sale del diálogo', () => {
    m.componente.alEnviar({ ...VALORES_VALIDOS, nombre: ' a ' });
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('la categoría vacía viaja null, no cadena vacía', () => {
    m.componente.alEnviar({ ...VALORES_VALIDOS, categoria: '   ' });
    expect(m.cerrar).toHaveBeenCalledWith(
      expect.objectContaining({ categoria: null }) as ResultadoDialogo,
    );
  });

  it('el segundo envío del mismo formulario es un no-op (candado de doble clic)', () => {
    m.componente.alEnviar(VALORES_VALIDOS);
    m.componente.alEnviar(VALORES_VALIDOS);
    expect(m.cerrar).toHaveBeenCalledTimes(1);
  });

  it('en edición el precio se precarga en PESOS (centavos / 100), no en centavos', () => {
    const producto = {
      id: 'p1',
      nombre: 'Arroz 500g',
      precio_venta: 250050,
      iva_pct: '19',
      unidad_medida: 'unidad',
      stock_minimo: '1.500',
    } as ProductoSalida;
    const edicion = montar({ producto });
    expect(edicion.componente.esEdicion).toBe(true);
    const campos = edicion.componente.configuracion.campos;
    expect(campos.find((c) => c.clave === 'precio_pesos')?.valorPorDefecto).toBe(2500.5);
    expect(campos.find((c) => c.clave === 'stock_minimo')?.valorPorDefecto).toBe('1.500');
    expect(campos.find((c) => c.clave === 'iva_pct')?.valorPorDefecto).toBe(19);
  });
});
