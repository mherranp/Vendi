import { TestBed } from '@angular/core/testing';

import { Notificador } from './notificador.service';

function montar(): Notificador {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({ providers: [Notificador] });
  return TestBed.inject(Notificador);
}

describe('Notificador', () => {
  it('empieza vacío', () => {
    const n = montar();
    expect(n.avisos()).toEqual([]);
    expect(n.ultimo()).toBeNull();
  });

  it('apila los avisos del más reciente al más antiguo', () => {
    const n = montar();
    n.info('primero');
    n.error('segundo');
    expect(n.avisos().map((a) => a.mensaje)).toEqual(['segundo', 'primero']);
    expect(n.ultimo()?.tipo).toBe('error');
  });

  it('etiqueta cada aviso con su tipo', () => {
    const n = montar();
    n.exito('a');
    expect(n.ultimo()?.tipo).toBe('exito');
    n.advertencia('b');
    expect(n.ultimo()?.tipo).toBe('advertencia');
  });

  it('recorta la cola para que una tormenta de errores no crezca sin fin', () => {
    const n = montar();
    for (let i = 0; i < 50; i++) {
      n.error(`fallo ${i}`);
    }
    expect(n.avisos().length).toBe(20);
    expect(n.ultimo()?.mensaje).toBe('fallo 49');
  });

  it('descartar() quita solo el aviso indicado', () => {
    const n = montar();
    n.info('uno');
    n.info('dos');
    const id = n.avisos()[1].id;
    n.descartar(id);
    expect(n.avisos().map((a) => a.mensaje)).toEqual(['dos']);
  });

  it('limpiar() vacía la cola', () => {
    const n = montar();
    n.error('x');
    n.limpiar();
    expect(n.avisos()).toEqual([]);
  });
});
