import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { API_BASE_URL } from 'data-access';
import { afterEach, describe, expect, it } from 'vitest';
import { CajaService } from './caja.service';

const BASE = 'https://api.vendi.co/api/v1';
const SESION = '5f1d0e2a-0000-4000-8000-aaaaaaaaaaaa';
const ID_OP = '5f1d0e2a-0000-4000-8000-bbbbbbbbbbbb';

function configurar(): { servicio: CajaService; http: HttpTestingController } {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
    ],
  });
  return { servicio: TestBed.inject(CajaService), http: TestBed.inject(HttpTestingController) };
}

describe('CajaService — contrato con la API', () => {
  let c: { servicio: CajaService; http: HttpTestingController };

  beforeEach(() => {
    c = configurar();
  });

  afterEach(() => {
    c.http.verify();
  });

  it('la sesión actual se pide en silencio (el 404 es "sin sesión", no un error)', () => {
    let resultado: unknown = 'sin-respuesta';
    c.servicio.sesionActual().subscribe((s) => (resultado = s));
    const req = c.http.expectOne(`${BASE}/caja/sesiones/actual`);
    expect(req.request.method).toBe('GET');
    req.flush({ id: SESION, estado: 'abierta', base_inicial: 50000, efectivo_esperado: null });
    expect((resultado as { id: string }).id).toBe(SESION);
  });

  it('el 404 de la sesión actual se traduce a null, no a error', () => {
    let resultado: unknown = 'sin-respuesta';
    c.servicio
      .sesionActual()
      .subscribe({ next: (s) => (resultado = s), error: () => (resultado = 'error') });
    c.http
      .expectOne(`${BASE}/caja/sesiones/actual`)
      .flush({ message: 'no hay' }, { status: 404, statusText: 'Not Found' });
    expect(resultado).toBeNull();
  });

  it('otro error de la sesión actual SÍ se propaga', () => {
    let fallo = false;
    c.servicio.sesionActual().subscribe({ error: () => (fallo = true) });
    c.http.expectOne(`${BASE}/caja/sesiones/actual`).error(new ProgressEvent('error'));
    expect(fallo).toBe(true);
  });

  it('abrir manda id y base en centavos', () => {
    c.servicio.abrir(ID_OP, 50000).subscribe();
    const req = c.http.expectOne(`${BASE}/caja/sesiones`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ id: ID_OP, base_inicial: 50000 });
    req.flush({ id: SESION });
  });

  it('los movimientos se filtran por sesión y paginan en el servidor', () => {
    c.servicio.movimientos(SESION, 20, 10).subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/caja/movimientos`);
    expect(req.request.params.get('sesion_id')).toBe(SESION);
    expect(req.request.params.get('skip')).toBe('20');
    expect(req.request.params.get('limit')).toBe('10');
    req.flush({ items: [], total: 0, skip: 20, limit: 10 });
  });

  it('el movimiento viaja con su id de idempotencia, motivo y monto en centavos', () => {
    c.servicio
      .registrarMovimiento({
        id: ID_OP,
        tipo: 'egreso',
        categoria: 'arriendo',
        monto: 150000,
        motivo: 'Arriendo de junio',
      })
      .subscribe();
    const req = c.http.expectOne(`${BASE}/caja/movimientos`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      id: ID_OP,
      tipo: 'egreso',
      categoria: 'arriendo',
      monto: 150000,
      motivo: 'Arriendo de junio',
    });
    req.flush({ id: ID_OP });
  });

  it('cerrar manda solo el contado y devuelve el arqueo con desglose', () => {
    let arqueo: unknown = 'sin-respuesta';
    c.servicio.cerrar(SESION, 230000).subscribe((a) => (arqueo = a));
    const req = c.http.expectOne(`${BASE}/caja/sesiones/${SESION}/cerrar`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ contado: 230000 });
    req.flush({ id: SESION, estado: 'cerrada', diferencia: -5000, desglose: null });
    expect((arqueo as { diferencia?: number | null }).diferencia).toBe(-5000);
  });

  it('el historial de arqueos pagina en el servidor', () => {
    c.servicio.historial(10, 10).subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/caja/sesiones`);
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('skip')).toBe('10');
    req.flush({ items: [], total: 0, skip: 10, limit: 10 });
  });
});
