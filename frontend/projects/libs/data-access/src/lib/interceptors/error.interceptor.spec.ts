import {
  HttpContext,
  HttpErrorResponse,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import { Observable, of } from 'rxjs';

import { ApiService } from '../api.service';
import { CATALOGO_MINIMO_ES, CatalogoTraducciones } from '../i18n/catalogo-minimo';
import { Notificador } from '../notificaciones/notificador.service';
import {
  SILENCIAR_AVISO_ERROR,
  claveDeError,
  errorInterceptor,
  extraerMensajeDeError,
} from './error.interceptor';

// --- unitario: extracción del mensaje del cuerpo -----------------------------

function errorCon(cuerpo: unknown, status = 400): HttpErrorResponse {
  return new HttpErrorResponse({ error: cuerpo, status, statusText: 'Error', url: '/x' });
}

describe('extraerMensajeDeError', () => {
  it('devuelve el `message` de la envoltura de error de la API', () => {
    expect(
      extraerMensajeDeError(errorCon({ message: 'Tenant suspendido', code: 'TENANT_SUSPENDIDO' })),
    ).toBe('Tenant suspendido');
  });

  it('devuelve el `detail` string de HTTPException de FastAPI', () => {
    expect(extraerMensajeDeError(errorCon({ detail: 'Filtro de acción inválido' }))).toBe(
      'Filtro de acción inválido',
    );
  });

  it('aplana el array de validación de Pydantic en pares "campo: mensaje"', () => {
    const cuerpo = {
      detail: [
        { loc: ['body', 'email'], msg: 'no es un correo válido', type: 'value_error' },
        { loc: ['body', 'roles', 0], msg: 'el rol debe ser texto', type: 'type_error' },
      ],
    };
    expect(extraerMensajeDeError(errorCon(cuerpo))).toBe(
      'email: no es un correo válido; roles.0: el rol debe ser texto',
    );
  });

  it('NO devuelve [object Object] cuando el cuerpo no tiene nada aprovechable', () => {
    // Éste es el modo de fallo que buscaba el QA: un cuerpo objeto sin claves
    // conocidas jamás debe acabar interpolado en una plantilla.
    const salida = extraerMensajeDeError(errorCon({ foo: { bar: 1 } }));
    expect(salida).toBe('');
    expect(salida).not.toContain('[object Object]');
  });

  it('descarta el cuerpo de un error de red (ProgressEvent) en vez de imprimirlo', () => {
    const evento = new ProgressEvent('error');
    expect(extraerMensajeDeError(errorCon(evento, 0))).toBe('');
  });

  it('descarta el HTML de la página de error del proxy', () => {
    expect(extraerMensajeDeError(errorCon('<html><body>502 Bad Gateway</body></html>', 502))).toBe(
      '',
    );
  });

  it('acepta un cuerpo de texto plano corto', () => {
    expect(extraerMensajeDeError(errorCon('Cuota agotada', 429))).toBe('Cuota agotada');
  });

  it('ignora un `message` que no es string', () => {
    expect(extraerMensajeDeError(errorCon({ message: 123, detail: 'respaldo' }))).toBe('respaldo');
  });

  it('tolera cuerpo nulo', () => {
    expect(extraerMensajeDeError(errorCon(null, 500))).toBe('');
  });
});

describe('claveDeError', () => {
  it('mapea cada familia de estado a su clave', () => {
    expect(claveDeError(0)).toBe('errores.sin_conexion');
    expect(claveDeError(401)).toBe('errores.sesion_expirada');
    expect(claveDeError(403)).toBe('errores.sin_permiso');
    expect(claveDeError(404)).toBe('errores.no_encontrado');
    expect(claveDeError(500)).toBe('errores.servidor');
    expect(claveDeError(503)).toBe('errores.servidor');
    expect(claveDeError(422)).toBe('errores.solicitud');
  });
});

// --- integración: petición real a través del interceptor ---------------------

class CargadorDePrueba extends TranslateLoader {
  constructor(private readonly catalogo: CatalogoTraducciones) {
    super();
  }
  override getTranslation(): Observable<TranslationObject> {
    return of(this.catalogo as TranslationObject);
  }
}

function montar(catalogo: CatalogoTraducciones = CATALOGO_MINIMO_ES): {
  api: ApiService;
  http: HttpTestingController;
  notificador: Notificador;
} {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withInterceptors([errorInterceptor])),
      provideHttpClientTesting(),
      ...provideTranslateService({
        fallbackLang: 'es',
        lang: 'es',
        loader: { provide: TranslateLoader, useFactory: () => new CargadorDePrueba(catalogo) },
      }),
      ApiService,
      Notificador,
    ],
  });
  // El cargador es síncrono, así que al volver de `use()` el catálogo ya está.
  TestBed.inject(TranslateService).use('es').subscribe();
  return {
    api: TestBed.inject(ApiService),
    http: TestBed.inject(HttpTestingController),
    notificador: TestBed.inject(Notificador),
  };
}

describe('errorInterceptor', () => {
  it('un 500 produce un aviso en español, no [object Object] ni el estado crudo', () => {
    const { api, http, notificador } = montar();
    api.get('/tenants/me').subscribe({ error: () => undefined });
    http
      .expectOne('/api/v1/tenants/me')
      .flush({ foo: 'bar' }, { status: 500, statusText: 'Internal Server Error' });

    const aviso = notificador.ultimo();
    expect(aviso?.tipo).toBe('error');
    expect(aviso?.mensaje).toBe('Tuvimos un problema. Vuelve a intentarlo en un momento.');
    expect(aviso?.mensaje).not.toContain('[object Object]');
    expect(aviso?.mensaje).not.toContain('errores.');
  });

  it('un error de red (status 0) produce el mensaje de sin conexión', () => {
    const { api, http, notificador } = montar();
    api.get('/tenants/me').subscribe({ error: () => undefined });
    http.expectOne('/api/v1/tenants/me').error(new ProgressEvent('error'));

    const aviso = notificador.ultimo();
    expect(aviso?.mensaje).toBe('Sin conexión. Revisa tu red e inténtalo de nuevo.');
    expect(aviso?.mensaje).not.toContain('Http failure');
  });

  it('un 4xx prefiere el mensaje del backend, que ya viene en español', () => {
    const { api, http, notificador } = montar();
    api.post('/platform/tenants', { nombre: '' }).subscribe({ error: () => undefined });
    http
      .expectOne('/api/v1/platform/tenants')
      .flush(
        { message: 'Ya existe un negocio con ese nombre' },
        { status: 409, statusText: 'Conflict' },
      );

    expect(notificador.ultimo()?.mensaje).toBe('Ya existe un negocio con ese nombre');
  });

  it('un 403 se avisa como advertencia con el texto de permisos', () => {
    const { api, http, notificador } = montar();
    api.get('/platform/tenants').subscribe({ error: () => undefined });
    http
      .expectOne('/api/v1/platform/tenants')
      .flush(null, { status: 403, statusText: 'Forbidden' });

    expect(notificador.ultimo()?.tipo).toBe('advertencia');
    expect(notificador.ultimo()?.mensaje).toBe('No tienes permiso para hacer esto.');
  });

  it('un 401 ignora el detalle técnico del backend y usa el texto de sesión expirada', () => {
    const { api, http, notificador } = montar();
    api.get('/tenants/me').subscribe({ error: () => undefined });
    http
      .expectOne('/api/v1/tenants/me')
      .flush(
        { detail: 'Signature verification failed' },
        { status: 401, statusText: 'Unauthorized' },
      );

    expect(notificador.ultimo()?.mensaje).toBe('Tu sesión expiró. Vuelve a iniciar sesión.');
  });

  it('SILENCIAR_AVISO_ERROR evita el aviso pero deja pasar el error a quien llamó', () => {
    const { api, http, notificador } = montar();
    let recibido: unknown;
    api
      .get('/tenant/features', undefined, {
        context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true),
      })
      .subscribe({ error: (e) => (recibido = e) });
    http.expectOne('/api/v1/tenant/features').flush(null, { status: 404, statusText: 'Not Found' });

    expect(notificador.avisos().length).toBe(0);
    expect(recibido).toBeInstanceOf(HttpErrorResponse);
  });

  it('con el catálogo vacío cae al texto empotrado, nunca a la clave cruda', () => {
    // Simula la app arrancada sin conexión: el catálogo remoto no llegó.
    const { api, http, notificador } = montar({});
    api.get('/tenants/me').subscribe({ error: () => undefined });
    http.expectOne('/api/v1/tenants/me').flush(null, { status: 500, statusText: 'ISE' });

    expect(notificador.ultimo()?.mensaje).toBe(
      'Tuvimos un problema. Vuelve a intentarlo en un momento.',
    );
  });
});
