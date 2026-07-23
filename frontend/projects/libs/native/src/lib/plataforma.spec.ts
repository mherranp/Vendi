import { esPlataformaNativa, nombreDePlataforma } from './plataforma';

describe('fachada de plataforma', () => {
  it('reporta "no nativa" cuando corre en un navegador (jsdom)', () => {
    expect(esPlataformaNativa()).toBe(false);
  });

  it('reporta la plataforma "web" cuando corre en un navegador (jsdom)', () => {
    expect(nombreDePlataforma()).toBe('web');
  });
});
