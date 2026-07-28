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
import { formatearPesos } from 'domain';
import { Observable, of } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import catalogoApp from '../../../../public/i18n/es.json';
import {
  AbonoDialogoComponent,
  DatosAbonoDialogo,
  ResultadoAbono,
} from './abono-dialogo.component';

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

interface Montaje {
  componente: AbonoDialogoComponent;
  cerrar: ReturnType<typeof vi.fn>;
}

/**
 * QA adversarial del abono (ADR-022): el monto entra en pesos y sale en
 * centavos enteros; cero y negativos no salen del diálogo; la nota vacía
 * viaja null. El tope contra el saldo NO se valida aquí a propósito — lo
 * impone el servidor—, así que un abono mayor que el saldo SÍ sale del
 * diálogo: este candado fija que nadie "arregle" eso por la UI.
 */
describe('AbonoDialogoComponent — conversiones y rechazos del borde', () => {
  let m: Montaje;

  beforeEach(() => {
    TestBed.resetTestingModule();
    const cerrar = vi.fn();
    const datos: DatosAbonoDialogo = { saldoPendiente: 4500000 };
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
    m = { componente: TestBed.createComponent(AbonoDialogoComponent).componentInstance, cerrar };
  });

  it('el monto en pesos sale en centavos enteros; la nota vacía viaja null', () => {
    m.componente.alEnviar({ monto_pesos: 5000.5, metodo_pago: 'efectivo', nota: '   ' });
    expect(m.cerrar).toHaveBeenCalledWith({
      metodo_pago: 'efectivo',
      monto: 500050,
      nota: null,
    } satisfies ResultadoAbono);
  });

  it('un abono mayor que el saldo SÍ sale del diálogo: el tope es del servidor', () => {
    m.componente.alEnviar({ monto_pesos: 999999, metodo_pago: 'efectivo', nota: '' });
    expect(m.cerrar).toHaveBeenCalledWith(
      expect.objectContaining({ monto: 99999900 }) as ResultadoAbono,
    );
  });

  it('un abono de cero no sale del diálogo', () => {
    m.componente.alEnviar({ monto_pesos: 0, metodo_pago: 'efectivo', nota: '' });
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('un abono negativo no sale del diálogo', () => {
    m.componente.alEnviar({ monto_pesos: -100, metodo_pago: 'efectivo', nota: '' });
    expect(m.cerrar).not.toHaveBeenCalled();
    expect(m.componente.errorFormulario()).toBe(true);
  });

  it('el saldo se muestra formateado en pesos, nunca en centavos crudos', () => {
    expect(m.componente.saldoFormateado).toBe(formatearPesos(4500000));
  });

  it('el segundo envío es un no-op (candado de doble clic sobre el cobro)', () => {
    m.componente.alEnviar({ monto_pesos: 5000, metodo_pago: 'efectivo', nota: '' });
    m.componente.alEnviar({ monto_pesos: 5000, metodo_pago: 'efectivo', nota: '' });
    expect(m.cerrar).toHaveBeenCalledTimes(1);
  });
});
