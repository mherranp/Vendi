import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { TranslateService } from '@ngx-translate/core';

import { CATALOGO_MINIMO_ES, CatalogoTraducciones, textoDeRespaldo } from './catalogo-minimo';

/** Lee una clave con notación de punto de un catálogo ya fusionado. */
function enRuta(catalogo: CatalogoTraducciones, clave: string): string | null {
  let nodo: string | CatalogoTraducciones | undefined = catalogo;
  for (const parte of clave.split('.')) {
    if (typeof nodo !== 'object' || nodo === null) return null;
    nodo = nodo[parte];
  }
  return typeof nodo === 'string' ? nodo : null;
}

import {
  CargadorDeTraduccionesResiliente,
  fusionarCatalogos,
  proveerI18nVendi,
} from './i18n.provider';
import { SILENCIAR_AVISO_ERROR } from '../interceptors/error.interceptor';
import { traducir } from './traduccion';

describe('textoDeRespaldo', () => {
  it('resuelve claves anidadas con notación de punto', () => {
    expect(textoDeRespaldo('errores.sin_conexion')).toBe(
      'Sin conexión. Revisa tu red e inténtalo de nuevo.',
    );
    expect(textoDeRespaldo('comun.cancelar')).toBe('Cancelar');
  });

  it('devuelve null para claves ausentes o para nodos intermedios', () => {
    expect(textoDeRespaldo('errores.inventado')).toBeNull();
    expect(textoDeRespaldo('errores')).toBeNull();
    expect(textoDeRespaldo('a.b.c.d')).toBeNull();
    expect(textoDeRespaldo('')).toBeNull();
  });
});

describe('CargadorDeTraduccionesResiliente', () => {
  let http: HttpTestingController;
  let cargador: CargadorDeTraduccionesResiliente;

  beforeEach(() => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        CargadorDeTraduccionesResiliente,
      ],
    });
    http = TestBed.inject(HttpTestingController);
    cargador = TestBed.inject(CargadorDeTraduccionesResiliente);
  });

  it('pide el catálogo en /i18n/<idioma>.json y lo fusiona sobre el empotrado', () => {
    let recibido: CatalogoTraducciones = {};
    cargador.getTranslation('es').subscribe((c) => (recibido = c as CatalogoTraducciones));
    const req = http.expectOne('/i18n/es.json');
    expect(req.request.method).toBe('GET');
    req.flush({ app: { titulo: 'Vendi POS' } });

    // Lo que trae el remoto manda…
    expect(enRuta(recibido, 'app.titulo')).toBe('Vendi POS');
    // …y lo que omite lo cubre el empotrado, en vez de desaparecer.
    expect(enRuta(recibido, 'comun.reintentar')).toBe('Reintentar');
    expect(enRuta(recibido, 'ui.validacion.requerido')).toBe('Este campo es obligatorio');
  });

  it('la fusión no muta el catálogo empotrado (es una constante compartida)', () => {
    cargador.getTranslation('es').subscribe();
    http.expectOne('/i18n/es.json').flush({ app: { titulo: 'Otro' }, nuevo: { clave: 'x' } });

    expect(enRuta(CATALOGO_MINIMO_ES, 'app.titulo')).toBe('Vendi');
    expect(CATALOGO_MINIMO_ES['nuevo']).toBeUndefined();
  });

  it('la petición del catálogo no dispara el aviso global de error', () => {
    cargador.getTranslation('es').subscribe();
    const req = http.expectOne('/i18n/es.json');
    // Sin esto, un 404 del asset le saca al usuario un aviso rojo por algo que
    // la app resuelve sola cayendo al catálogo empotrado.
    expect(req.request.context.get(SILENCIAR_AVISO_ERROR)).toBe(true);
    req.flush({});
  });

  it('ante un error de red devuelve el catálogo empotrado en vez de fallar', () => {
    // Éste es el escenario del POS instalado sin conexión: sin este respaldo,
    // el APP_INITIALIZER rechaza y Angular aborta el bootstrap.
    let recibido: unknown;
    let fallo: unknown;
    cargador.getTranslation('es').subscribe({
      next: (c) => (recibido = c),
      error: (e) => (fallo = e),
    });
    http.expectOne('/i18n/es.json').error(new ProgressEvent('error'));

    expect(fallo).toBeUndefined();
    expect(recibido).toEqual(CATALOGO_MINIMO_ES);
  });

  it('ante un 404 (despliegue sin el asset) también devuelve el empotrado', () => {
    let recibido: unknown;
    cargador.getTranslation('es').subscribe((c) => (recibido = c));
    http.expectOne('/i18n/es.json').flush('no such file', { status: 404, statusText: 'Not Found' });
    expect(recibido).toEqual(CATALOGO_MINIMO_ES);
  });
});

describe('fusionarCatalogos', () => {
  it('lo de encima gana clave a clave y lo de abajo rellena', () => {
    const base = { a: '1', anidado: { x: 'base-x', y: 'base-y' } };
    const encima = { anidado: { y: 'nuevo-y', z: 'nuevo-z' } };
    expect(fusionarCatalogos(base, encima)).toEqual({
      a: '1',
      anidado: { x: 'base-x', y: 'nuevo-y', z: 'nuevo-z' },
    });
  });

  it('no muta ninguno de los dos operandos', () => {
    const base = { anidado: { x: 'base-x' } };
    const encima = { anidado: { y: 'nuevo-y' } };
    fusionarCatalogos(base, encima);
    expect(base).toEqual({ anidado: { x: 'base-x' } });
    expect(encima).toEqual({ anidado: { y: 'nuevo-y' } });
  });

  it('un catálogo remoto vacío deja el empotrado intacto', () => {
    expect(fusionarCatalogos({ a: '1' }, {})).toEqual({ a: '1' });
  });
});

describe('proveerI18nVendi', () => {
  it('arranca la app aunque el catálogo no se pueda descargar', async () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), ...proveerI18nVendi()],
    });

    // Inyectar TranslateService dispara el inicializador registrado.
    const traductor = TestBed.inject(TranslateService);
    const http = TestBed.inject(HttpTestingController);
    const arranque = TestBed.inject(TranslateService).use('es');

    http.match('/i18n/es.json').forEach((req) => req.error(new ProgressEvent('error')));
    await new Promise<void>((resolve) => arranque.subscribe(() => resolve()));

    // La app está viva y con textos usables, no con claves crudas.
    expect(traducir(traductor, 'errores.sin_conexion')).toBe(
      'Sin conexión. Revisa tu red e inténtalo de nuevo.',
    );
    http.verify();
  });
});

describe('el catálogo empotrado cubre lo que se pinta con el pipe | translate', () => {
  /*
   * `traducir()` sabe caer al catálogo empotrado, pero solo lo llama
   * `error.interceptor.ts`. Todos los componentes de `ui-kit` usan el pipe
   * `| translate` directo, y ngx-translate devuelve **la clave** cuando no la
   * encuentra. Por eso el respaldo tiene que ser completo, no "mínimo": si le
   * faltan claves, la PWA sin red arranca pintando `ui.404.titulo` y
   * `ui.validacion.requerido` en pantalla.
   *
   * Este test ejerce la misma ruta que el pipe (`TranslateService.instant`)
   * después de un arranque degradado.
   */
  const CLAVES_DE_UI_KIT = [
    'comun.aceptar',
    'comun.cancelar',
    'comun.guardar',
    'layout.menu',
    'layout.cuenta',
    'layout.cerrar_sesion',
    'layout.cargando',
    'notificaciones.titulo',
    'notificaciones.marcar_leidas',
    'notificaciones.vacio',
    'suplantacion.titulo',
    'suplantacion.expira_en',
    'suplantacion.detener',
    'ui.vacio.titulo',
    'ui.tabla.vacia',
    'ui.archivos.suelta_aqui',
    'ui.archivos.buscar',
    'ui.404.titulo',
    'ui.404.descripcion',
    'ui.404.volver',
    'ui.validacion.requerido',
    'ui.validacion.correo',
    'ui.validacion.minimo',
    'ui.validacion.maximo',
    'ui.validacion.muy_corto',
    'ui.validacion.muy_largo',
    'ui.validacion.formato',
    'ui.validacion.invalido',
  ];

  it('instant() devuelve texto, no la clave, tras un arranque sin catálogo', async () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), ...proveerI18nVendi()],
    });
    const traductor = TestBed.inject(TranslateService);
    const http = TestBed.inject(HttpTestingController);
    const arranque = traductor.use('es');
    http.match('/i18n/es.json').forEach((req) => req.error(new ProgressEvent('error')));
    await new Promise<void>((resolve) => arranque.subscribe(() => resolve()));

    const crudas = CLAVES_DE_UI_KIT.filter((clave) => traductor.instant(clave) === clave);
    expect(crudas).toEqual([]);
    http.verify();
  });
});

describe('traducir', () => {
  it('no devuelve nunca la clave cruda', () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), ...proveerI18nVendi()],
    });
    const traductor = TestBed.inject(TranslateService);

    // Clave que no está ni en el catálogo cargado ni en el mínimo.
    expect(traducir(traductor, 'seccion.inexistente', 'respaldo explícito')).toBe(
      'respaldo explícito',
    );
    // Sin respaldo explícito, cadena vacía — nunca "seccion.inexistente".
    expect(traducir(traductor, 'seccion.inexistente')).toBe('');
  });
});
