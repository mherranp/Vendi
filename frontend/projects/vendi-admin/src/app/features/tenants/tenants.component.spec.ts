import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import {
  API_BASE_URL,
  CATALOGO_MINIMO_ES,
  Notificador,
  errorInterceptor,
  fusionarCatalogos,
} from 'data-access';
import { Observable, of } from 'rxjs';

import catalogoApp from '../../../../public/i18n/es.json';
import { TenantsComponent } from './tenants.component';

const BASE = 'https://api.vendi.co/api/v1';
const LISTADO = `${BASE}/platform/tenants`;
const ID_A = '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e';
const ID_B = '2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f';

/**
 * Catálogo real de la app fusionado sobre el empotrado — exactamente lo que
 * hace `CargadorDeTraduccionesResiliente` en producción. Así, si a un texto
 * nuevo se le olvida la entrada en `es.json`, el spec pinta la clave cruda y
 * los asertos de texto fallan aquí, no en la pantalla de un usuario.
 */
class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

/**
 * Doble de `MatDialog`.
 *
 * Los diálogos reales de Material montan un overlay y esperan animaciones; lo
 * que este spec necesita comprobar no es el overlay sino la coreografía: qué se
 * abre, con qué datos, y qué llamada HTTP sale cuando se cierra con un
 * resultado u otro.
 */
class DialogoFalso {
  /** Resultados a devolver, en orden de apertura. */
  resultados: unknown[] = [];
  /** Registro de aperturas: componente y datos con los que se abrió. */
  readonly aperturas: { componente: unknown; datos: unknown }[] = [];

  open(componente: unknown, config?: { data?: unknown }) {
    this.aperturas.push({ componente, datos: config?.data });
    const resultado = this.resultados.shift();
    return { afterClosed: () => of(resultado) };
  }
}

interface Montaje {
  fixture: ComponentFixture<TenantsComponent>;
  http: HttpTestingController;
  dialogos: DialogoFalso;
  notificador: Notificador;
}

function montar(): Montaje {
  TestBed.resetTestingModule();
  const dialogos = new DialogoFalso();
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      // El interceptor de errores va cableado a propósito: la ruta "la API
      // falla → el usuario lee un mensaje en español" es parte de lo que hay
      // que demostrar, y solo existe si el interceptor está en la cadena.
      provideHttpClient(withInterceptors([errorInterceptor])),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
      { provide: MatDialog, useValue: dialogos },
      ...provideTranslateService({
        lang: 'es',
        fallbackLang: 'es',
        loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
      }),
    ],
  });
  TestBed.inject(TranslateService).use('es');
  return {
    fixture: TestBed.createComponent(TenantsComponent),
    http: TestBed.inject(HttpTestingController),
    dialogos,
    notificador: TestBed.inject(Notificador),
  };
}

function pagina(items: unknown[], total = items.length, skip = 0, limit = 10) {
  return { items, total, skip, limit };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

describe('TenantsComponent — listar', () => {
  let m: Montaje;

  beforeEach(() => {
    m = montar();
  });

  afterEach(() => {
    m.http.verify();
  });

  it('pide la primera página al construirse y pinta las filas', () => {
    m.fixture.detectChanges();
    const req = m.http.expectOne((r) => r.url === LISTADO);
    expect(req.request.params.get('skip')).toBe('0');
    expect(req.request.params.get('limit')).toBe('10');
    req.flush(
      pagina([
        { id: ID_A, nombre: 'Tienda Don Carlos', estado: 'activo' },
        { id: ID_B, nombre: 'Panadería La Espiga', estado: 'suspendido' },
      ]),
    );
    m.fixture.detectChanges();

    const visible = texto(m.fixture);
    expect(visible).toContain('Tienda Don Carlos');
    expect(visible).toContain('Panadería La Espiga');
    // El estado se pinta traducido, no como el literal del cable.
    expect(visible).toContain('Activo');
    expect(visible).toContain('Suspendido');
    expect(m.fixture.componentInstance.cargando()).toBe(false);
  });

  it('con cero negocios enseña el estado vacío, no una tabla rota', () => {
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === LISTADO).flush(pagina([], 0));
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain('Todavía no hay negocios');
  });

  it('el interruptor de eliminados recarga desde la primera página', () => {
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === LISTADO).flush(pagina([], 30));
    // El usuario se va a la página 3…
    m.fixture.componentInstance.alPaginar({ pageIndex: 2, pageSize: 10, length: 30 });
    m.http
      .expectOne((r) => r.url === LISTADO)
      // La página 3 trae filas: si viniera vacía con total > 0, el componente
      // retrocedería de página (ver el spec de «la última página se vacía») y
      // este caso estaría probando otra cosa.
      .flush(pagina([{ id: ID_A, nombre: 'Tienda Don Carlos', estado: 'activo' }], 30, 20));

    // …y entonces activa "ver eliminados": el conjunto cambia, así que hay que
    // volver a la primera página o se queda mirando una tabla vacía.
    m.fixture.componentInstance.alternarEliminados(true);
    const req = m.http.expectOne((r) => r.url === LISTADO);
    expect(req.request.params.get('incluir_eliminados')).toBe('true');
    expect(req.request.params.get('skip')).toBe('0');
    expect(m.fixture.componentInstance.indicePagina()).toBe(0);
    req.flush(pagina([{ id: ID_B, nombre: 'Cerrada', estado: 'eliminado' }], 31));
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain('Eliminado');
  });

  it('cambiar de página vuelve a pedir con el skip correspondiente', () => {
    // El ataque de QA "paginación con 201 tenants": la página 3 de 10 en 10
    // tiene que pedir skip=20, no filtrar en memoria.
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === LISTADO).flush(pagina([], 201));

    m.fixture.componentInstance.alPaginar({ pageIndex: 2, pageSize: 10, length: 201 });
    const req = m.http.expectOne((r) => r.url === LISTADO);
    expect(req.request.params.get('skip')).toBe('20');
    req.flush(pagina([{ id: ID_A, nombre: 'Tienda Don Carlos', estado: 'activo' }], 201, 20));
    expect(m.fixture.componentInstance.total()).toBe(201);
  });

  it('si la última página se vacía, retrocede una página en vez de mentir', () => {
    // El caso real: el usuario está en la página 3, da de baja el único
    // negocio que quedaba en ella y el servidor devuelve cero filas con un
    // total que dice que sí hay negocios. Sin corrección, la pantalla enseña
    // «Todavía no hay negocios» —una afirmación falsa sobre la plataforma
    // entera— y el paginador deja al usuario encallado en una página que ya no
    // existe.
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === LISTADO).flush(pagina([], 21));

    m.fixture.componentInstance.alPaginar({ pageIndex: 2, pageSize: 10, length: 21 });
    const enLaPagina3 = m.http.expectOne((r) => r.url === LISTADO);
    expect(enLaPagina3.request.params.get('skip')).toBe('20');
    // El negocio que quedaba se dio de baja: la página 3 ya no tiene nada.
    enLaPagina3.flush(pagina([], 20, 20));

    const reintento = m.http.expectOne((r) => r.url === LISTADO);
    expect(reintento.request.params.get('skip')).toBe('10');
    expect(m.fixture.componentInstance.indicePagina()).toBe(1);
    reintento.flush(
      pagina([{ id: ID_B, nombre: 'Panadería La Espiga', estado: 'activo' }], 20, 10),
    );
    m.fixture.detectChanges();

    expect(texto(m.fixture)).toContain('Panadería La Espiga');
    expect(texto(m.fixture)).not.toContain('Todavía no hay negocios');
    expect(m.fixture.componentInstance.cargando()).toBe(false);
  });

  it('la primera página vacía NO retrocede: es el estado vacío legítimo', () => {
    // El guardia del retroceso es `indicePagina() > 0`. Sin él, un listado
    // realmente vacío entraría en un bucle de recargas.
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === LISTADO).flush(pagina([], 0));
    m.fixture.detectChanges();

    expect(m.fixture.componentInstance.indicePagina()).toBe(0);
    expect(texto(m.fixture)).toContain('Todavía no hay negocios');
  });
});

describe('TenantsComponent — crear', () => {
  let m: Montaje;

  beforeEach(() => {
    m = montar();
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === LISTADO).flush(pagina([]));
  });

  afterEach(() => {
    m.http.verify();
  });

  it('crea el negocio y recarga el listado', () => {
    m.dialogos.resultados = [{ nombre: 'Tienda Don Carlos' }];
    m.fixture.componentInstance.crear();

    const alta = m.http.expectOne(LISTADO);
    expect(alta.request.method).toBe('POST');
    expect(alta.request.body).toEqual({ nombre: 'Tienda Don Carlos' });
    alta.flush({ id: ID_A, nombre: 'Tienda Don Carlos', estado: 'activo' });

    // Recarga: el total del paginador lo tiene el servidor, no el cliente.
    m.http
      .expectOne((r) => r.url === LISTADO && r.method === 'GET')
      .flush(pagina([{ id: ID_A, nombre: 'Tienda Don Carlos', estado: 'activo' }]));
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain('Tienda Don Carlos');
  });

  it('cancelar el diálogo no llama a la API', () => {
    m.dialogos.resultados = [undefined];
    m.fixture.componentInstance.crear();
    // `http.verify()` del afterEach es el aserto: si hubiera salido un POST,
    // fallaría por petición no esperada.
    expect(m.dialogos.aperturas.length).toBe(1);
  });

  it('doble clic en «Nuevo negocio» no abre dos diálogos ni crea dos negocios', () => {
    // Ataque explícito de la sección de QA de la Etapa 4.
    const pendiente: { cerrar?: (v: unknown) => void } = {};
    const dialogoLento = {
      open: (componente: unknown) => {
        m.dialogos.aperturas.push({ componente, datos: undefined });
        return {
          afterClosed: () =>
            new Observable<unknown>((observador) => {
              pendiente.cerrar = (v) => {
                observador.next(v);
                observador.complete();
              };
            }),
        };
      },
    };
    // Se sustituye el doble por uno que NO cierra solo: reproduce el diálogo
    // real, que sigue abierto mientras el usuario hace el segundo clic.
    const instancia = m.fixture.componentInstance as unknown as { dialogos: unknown };
    instancia.dialogos = dialogoLento;

    m.fixture.componentInstance.crear();
    m.fixture.componentInstance.crear();
    expect(m.dialogos.aperturas.length).toBe(1);

    pendiente.cerrar?.({ nombre: 'Uno solo' });
    const alta = m.http.expectOne(LISTADO);
    expect(alta.request.method).toBe('POST');
    alta.flush({ id: ID_A, nombre: 'Uno solo', estado: 'activo' });
    m.http.expectOne((r) => r.url === LISTADO && r.method === 'GET').flush(pagina([]));
  });
});

describe('TenantsComponent — suspender, reactivar y eliminar', () => {
  let m: Montaje;
  const TENANT = { id: ID_A, nombre: 'Tienda Don Carlos', estado: 'activo' as const };

  beforeEach(() => {
    m = montar();
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === LISTADO).flush(pagina([TENANT]));
  });

  afterEach(() => {
    m.http.verify();
  });

  it('suspender pide confirmación antes de tocar la API', () => {
    m.dialogos.resultados = [false];
    m.fixture.componentInstance.suspender(TENANT);
    expect(m.dialogos.aperturas.length).toBe(1);
    // Confirmación rechazada ⇒ ninguna petición. Lo verifica el afterEach.
  });

  it('confirmando, manda PATCH {estado: suspendido} y recarga', () => {
    m.dialogos.resultados = [true];
    m.fixture.componentInstance.suspender(TENANT);

    const req = m.http.expectOne(`${LISTADO}/${ID_A}`);
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ estado: 'suspendido' });
    req.flush({ ...TENANT, estado: 'suspendido' });

    m.http
      .expectOne((r) => r.url === LISTADO && r.method === 'GET')
      .flush(pagina([{ ...TENANT, estado: 'suspendido' }]));
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain('Suspendido');
  });

  it('eliminar es destructivo y se anuncia como tal', () => {
    m.dialogos.resultados = [true];
    m.fixture.componentInstance.eliminar(TENANT);
    const datos = m.dialogos.aperturas[0].datos as { peligroso?: boolean };
    expect(datos.peligroso).toBe(true);

    const req = m.http.expectOne(`${LISTADO}/${ID_A}`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });
    m.http.expectOne((r) => r.url === LISTADO && r.method === 'GET').flush(pagina([]));
  });

  it('las acciones disponibles dependen del estado', () => {
    const componente = m.fixture.componentInstance;
    expect(componente.puedeSuspender(TENANT)).toBe(true);
    expect(componente.puedeReactivar(TENANT)).toBe(false);

    const suspendido = { ...TENANT, estado: 'suspendido' };
    expect(componente.puedeSuspender(suspendido)).toBe(false);
    expect(componente.puedeReactivar(suspendido)).toBe(true);

    const eliminado = { ...TENANT, estado: 'eliminado' };
    expect(componente.puedeEliminar(eliminado)).toBe(false);
  });
});

describe('TenantsComponent — cuando la API falla', () => {
  let m: Montaje;

  beforeEach(() => {
    m = montar();
  });

  afterEach(() => {
    m.http.verify();
  });

  it('un 500 deja un mensaje en español y una salida, no un spinner eterno', () => {
    m.fixture.detectChanges();
    m.http
      .expectOne((r) => r.url === LISTADO)
      .flush({ message: 'boom' }, { status: 500, statusText: 'Server Error' });
    m.fixture.detectChanges();

    // 1. El usuario lee algo comprensible, y no el inglés del backend.
    expect(m.notificador.ultimo()?.mensaje).toBe(
      'Tuvimos un problema. Vuelve a intentarlo en un momento.',
    );
    // 2. La pantalla no se queda cargando para siempre.
    expect(m.fixture.componentInstance.cargando()).toBe(false);
    // 3. Y hay por dónde salir.
    expect(m.fixture.componentInstance.fallo()).toBe(true);
    expect(texto(m.fixture)).toContain('Reintentar');
  });

  it('un 403 se cuenta como error de permisos, con su propio texto', () => {
    m.fixture.detectChanges();
    m.http
      .expectOne((r) => r.url === LISTADO)
      .flush({ message: '' }, { status: 403, statusText: 'Forbidden' });
    expect(m.notificador.ultimo()?.mensaje).toBe('No tienes permiso para hacer esto.');
  });

  it('reintentar vuelve a pedir el listado', () => {
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === LISTADO).error(new ProgressEvent('error'));
    expect(m.fixture.componentInstance.fallo()).toBe(true);

    m.fixture.componentInstance.recargar();
    m.http.expectOne((r) => r.url === LISTADO).flush(pagina([]));
    expect(m.fixture.componentInstance.fallo()).toBe(false);
  });

  it('sin red el mensaje habla de conexión, no de "error desconocido"', () => {
    // `status 0` es el caso frecuente en una tienda: portal cautivo, wifi que
    // se cae. El texto genérico de servidor sería engañoso.
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === LISTADO).error(new ProgressEvent('error'));
    expect(m.notificador.ultimo()?.mensaje).toBe(
      'Sin conexión. Revisa tu red e inténtalo de nuevo.',
    );
  });
});
