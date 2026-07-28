import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { API_BASE_URL, SILENCIAR_AVISO_ERROR } from 'data-access';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { CreditoDetalleSalida } from './contrato';
import { CuadernoService } from './cuaderno.service';

const BASE = 'https://api.vendi.co/api/v1';
const ID_OP = '5f1d0e2a-0000-4000-8000-bbbbbbbbbbbb';
const ID_CRED = '5f1d0e2a-0000-4000-8000-ffffffffffff';

function configurar(): { servicio: CuadernoService; http: HttpTestingController } {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
    ],
  });
  return {
    servicio: TestBed.inject(CuadernoService),
    http: TestBed.inject(HttpTestingController),
  };
}

describe('CuadernoService — contrato con la API', () => {
  let c: { servicio: CuadernoService; http: HttpTestingController };

  beforeEach(() => {
    c = configurar();
  });

  afterEach(() => {
    c.http.verify();
  });

  it('los clientes se buscan con q y paginan en el servidor', () => {
    c.servicio.clientes(10, 10, 'rosa').subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/clientes`);
    expect(req.request.params.get('q')).toBe('rosa');
    expect(req.request.params.get('skip')).toBe('10');
    req.flush({ items: [], total: 0, skip: 10, limit: 10 });
  });

  it('crear cliente manda el id idempotente y el límite en centavos', () => {
    c.servicio
      .crearCliente({
        id: ID_OP,
        nombre: 'Rosa Mejía',
        telefono: '3001234567',
        limite_credito: 20000000,
        nota: null,
      })
      .subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/clientes` && r.method === 'POST');
    expect(req.request.body).toEqual({
      id: ID_OP,
      nombre: 'Rosa Mejía',
      telefono: '3001234567',
      limite_credito: 20000000,
      nota: null,
    });
    req.flush({ id: ID_OP });
  });

  it('los créditos se filtran por estado (vencido, todos)', () => {
    c.servicio.creditos('vencido', 0, 10).subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/fiado/creditos`);
    expect(req.request.params.get('estado')).toBe('vencido');
    req.flush({ items: [], total: 0, skip: 0, limit: 10 });
  });

  it('sin filtro de estado NO se manda el parámetro (el backend aplica vigente+vencido)', () => {
    c.servicio.creditos(null, 0, 10).subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/fiado/creditos`);
    expect(req.request.params.has('estado')).toBe(false);
    req.flush({ items: [], total: 0, skip: 0, limit: 10 });
  });

  it('el detalle del crédito trae abonos y el wa.me', () => {
    let detalle: CreditoDetalleSalida | undefined;
    c.servicio.credito(ID_CRED).subscribe((d) => (detalle = d));
    c.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush({
      id: ID_CRED,
      whatsapp_url: 'https://wa.me/573001234567?text=...',
      abonos: [],
    });
    expect(detalle?.whatsapp_url).toContain('wa.me');
  });

  it('el abono viaja con id, método y monto en centavos', () => {
    c.servicio
      .abonar(ID_CRED, { id: ID_OP, metodo_pago: 'efectivo', monto: 500000, nota: null })
      .subscribe();
    const req = c.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}/abonos`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      id: ID_OP,
      metodo_pago: 'efectivo',
      monto: 500000,
      nota: null,
    });
    req.flush({ id: ID_OP });
  });

  it('reprogramar manda SIEMPRE la clave fecha_vencimiento (body {} es 422)', () => {
    c.servicio.reprogramar(ID_CRED, null).subscribe();
    const req = c.http.expectOne({ method: 'PATCH', url: `${BASE}/fiado/creditos/${ID_CRED}` });
    expect(req.request.body).toEqual({ fecha_vencimiento: null });
    req.flush({ id: ID_CRED });

    c.servicio.reprogramar(ID_CRED, '2026-08-15').subscribe();
    const conFecha = c.http.expectOne({
      method: 'PATCH',
      url: `${BASE}/fiado/creditos/${ID_CRED}`,
    });
    expect(conFecha.request.body).toEqual({ fecha_vencimiento: '2026-08-15' });
    conFecha.flush({ id: ID_CRED });
  });

  it('el conteo de vencidos pide estado=vencido con limit=1 y viaja silenciado', () => {
    c.servicio.vencidos().subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/fiado/creditos`);
    expect(req.request.params.get('estado')).toBe('vencido');
    expect(req.request.params.get('limit')).toBe('1');
    // La tira de cobro es un gesto de fondo: si falla, simplemente no sale;
    // no debe estampar un aviso de error sobre la pantalla.
    expect(req.request.context.get(SILENCIAR_AVISO_ERROR)).toBe(true);
    req.flush({ items: [], total: 0, skip: 0, limit: 1 });
  });
});
