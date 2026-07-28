import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { API_BASE_URL } from 'data-access';
import { afterEach, describe, expect, it } from 'vitest';
import { CatalogoService } from './catalogo.service';

const BASE = 'https://api.vendi.co/api/v1';
const ID_OP = '5f1d0e2a-0000-4000-8000-bbbbbbbbbbbb';
const ID_PROD = '5f1d0e2a-0000-4000-8000-cccccccccccc';

function configurar(): { servicio: CatalogoService; http: HttpTestingController } {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
    ],
  });
  return { servicio: TestBed.inject(CatalogoService), http: TestBed.inject(HttpTestingController) };
}

describe('CatalogoService — contrato con la API', () => {
  let c: { servicio: CatalogoService; http: HttpTestingController };

  beforeEach(() => {
    c = configurar();
  });

  afterEach(() => {
    c.http.verify();
  });

  it('lista con búsqueda y paginación del servidor', () => {
    c.servicio.listar(20, 10, 'arroz').subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/productos`);
    expect(req.request.params.get('q')).toBe('arroz');
    expect(req.request.params.get('skip')).toBe('20');
    expect(req.request.params.get('limit')).toBe('10');
    req.flush({ items: [], total: 0, skip: 20, limit: 10 });
  });

  it('la búsqueda vacía NO manda el parámetro q', () => {
    c.servicio.listar(0, 10, '').subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/productos`);
    expect(req.request.params.has('q')).toBe(false);
    req.flush({ items: [], total: 0, skip: 0, limit: 10 });
  });

  it('crear manda el id idempotente, el precio en centavos y el mínimo como string de 3 decimales', () => {
    c.servicio
      .crear({
        id: ID_OP,
        nombre: 'Arroz blanco x kg',
        categoria: 'Granos',
        codigo_barras: null,
        precio_venta: 420000,
        unidad_medida: 'kg',
        iva_pct: 0,
        stock_minimo: '5.000',
      })
      .subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/productos` && r.method === 'POST');
    expect(req.request.body).toEqual({
      id: ID_OP,
      nombre: 'Arroz blanco x kg',
      categoria: 'Granos',
      codigo_barras: null,
      precio_venta: 420000,
      unidad_medida: 'kg',
      iva_pct: 0,
      stock_minimo: '5.000',
    });
    req.flush({ id: ID_OP });
  });

  it('actualizar manda solo los campos del formulario (nunca stock ni costo)', () => {
    c.servicio.actualizar(ID_PROD, { nombre: 'Nuevo nombre', precio_venta: 500000 }).subscribe();
    const req = c.http.expectOne(`${BASE}/productos/${ID_PROD}`);
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ nombre: 'Nuevo nombre', precio_venta: 500000 });
    req.flush({ id: ID_PROD });
  });

  it('eliminar es un DELETE sin cuerpo', () => {
    c.servicio.eliminar(ID_PROD).subscribe();
    const req = c.http.expectOne(`${BASE}/productos/${ID_PROD}`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });
  });
});
