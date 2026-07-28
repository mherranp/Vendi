import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { TranslateService, provideTranslateService } from '@ngx-translate/core';
import { beforeEach, describe, expect, it } from 'vitest';
import { AvisoEnPantalla, AvisosComponent } from './avisos.component';

class SnackBarFalso {
  readonly aperturas: { mensaje: string; accion: string; config: unknown }[] = [];
  open(mensaje: string, accion: string, config: unknown): void {
    this.aperturas.push({ mensaje, accion, config });
  }
}

function montar(): { snack: SnackBarFalso } {
  TestBed.resetTestingModule();
  const snack = new SnackBarFalso();
  TestBed.configureTestingModule({
    providers: [
      { provide: MatSnackBar, useValue: snack },
      ...provideTranslateService({ fallbackLang: 'es', lang: 'es' }),
    ],
  });
  TestBed.inject(TranslateService).setTranslation('es', { comun: { cerrar: 'Cerrar' } });
  return { snack };
}

function aviso(id: string, tipo: string): AvisoEnPantalla {
  return { id, tipo, mensaje: `mensaje ${id}` };
}

describe('AvisosComponent (anfitrión de avisos por input)', () => {
  let snack: SnackBarFalso;

  beforeEach(() => {
    ({ snack } = montar());
  });

  it('sin aviso no abre nada', () => {
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.detectChanges();
    expect(snack.aperturas.length).toBe(0);
  });

  it('abre la barra con el mensaje y la acción traducida', () => {
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.componentRef.setInput('aviso', aviso('a1', 'info'));
    fixture.detectChanges();
    expect(snack.aperturas.length).toBe(1);
    expect(snack.aperturas[0].mensaje).toBe('mensaje a1');
    expect(snack.aperturas[0].accion).toBe('Cerrar');
  });

  it('un error no se cierra solo; un éxito dura 3 s', () => {
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.componentRef.setInput('aviso', aviso('a1', 'error'));
    fixture.detectChanges();
    expect((snack.aperturas[0].config as { duration: number }).duration).toBe(0);

    fixture.componentRef.setInput('aviso', aviso('a2', 'exito'));
    fixture.detectChanges();
    expect((snack.aperturas[1].config as { duration: number }).duration).toBe(3_000);
  });

  it('el mismo aviso no se repinta aunque el input se reemplace por otro igual', () => {
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.componentRef.setInput('aviso', aviso('a1', 'info'));
    fixture.detectChanges();
    fixture.componentRef.setInput('aviso', aviso('a1', 'info'));
    fixture.detectChanges();
    expect(snack.aperturas.length).toBe(1);
  });

  it('dos avisos con distinto id se pintan los dos', () => {
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.componentRef.setInput('aviso', aviso('a1', 'info'));
    fixture.detectChanges();
    fixture.componentRef.setInput('aviso', aviso('a2', 'advertencia'));
    fixture.detectChanges();
    expect(snack.aperturas.length).toBe(2);
  });
});
