import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { API_BASE_URL } from 'data-access';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { InventarioService } from './inventario.service';

const BASE = 'https://api.vendi.co/api/v1';
const ID_OP = '5f1d0e2a-0000-4000-8000-bbbbbbbbbbbb';
const ID_PROD = '5f1d0e2a-0000-4000-8000-cccccccccccc';

function configurar(): { servicio: InventarioService; http: HttpTestingController } {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
    ],
  });
  return {
    servicio: TestBed.inject(InventarioService),
    http: TestBed.inject(HttpTestingController),
  };
}

describe('InventarioService — contrato con la API', () => {
  let c: { servicio: InventarioService; http: HttpTestingController };

  beforeEach(() => {
    c = configurar();
  });

  afterEach(() => {
    c.http.verify();
  });

  it('el estado de stock pagina y filtra por alertas en el servidor', () => {
    c.servicio.stock(10, 10, true).subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/inventario/stock`);
    expect(req.request.params.get('solo_alertas')).toBe('true');
    expect(req.request.params.get('skip')).toBe('10');
    req.flush({ items: [], total: 0, skip: 10, limit: 10 });
  });

  it('el ajuste por conteo manda stock_contado y NO cantidad', () => {
    c.servicio
      .ajustar({
        id: ID_OP,
        tipo: 'ajuste',
        producto_id: ID_PROD,
        motivo: 'Conteo del lunes',
        stock_contado: '14.000',
      })
      .subscribe();
    const req = c.http.expectOne(
      (r) => r.url === `${BASE}/inventario/ajustes` && r.method === 'POST',
    );
    expect(req.request.body).toEqual({
      id: ID_OP,
      tipo: 'ajuste',
      producto_id: ID_PROD,
      motivo: 'Conteo del lunes',
      stock_contado: '14.000',
    });
    expect(req.request.body['cantidad']).toBeUndefined();
    req.flush({ id: ID_OP });
  });

  it('la merma manda cantidad y NO stock_contado', () => {
    c.servicio
      .ajustar({
        id: ID_OP,
        tipo: 'merma',
        producto_id: ID_PROD,
        motivo: 'Se dañó',
        cantidad: '0.500',
      })
      .subscribe();
    const req = c.http.expectOne(
      (r) => r.url === `${BASE}/inventario/ajustes` && r.method === 'POST',
    );
    expect(req.request.body['cantidad']).toBe('0.500');
    expect(req.request.body['stock_contado']).toBeUndefined();
    req.flush({ id: ID_OP });
  });

  it('la compra viaja con id, proveedor e ítems en centavos y 3 decimales (sin total)', () => {
    c.servicio
      .registrarCompra({
        id: ID_OP,
        proveedor_nombre: 'Distribuidora La 33',
        items: [{ producto_id: ID_PROD, cantidad: '10.000', costo_unitario_centavos: 350000 }],
      })
      .subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/compras` && r.method === 'POST');
    expect(req.request.body).toEqual({
      id: ID_OP,
      proveedor_nombre: 'Distribuidora La 33',
      items: [{ producto_id: ID_PROD, cantidad: '10.000', costo_unitario_centavos: 350000 }],
    });
    req.flush({ id: ID_OP, total_centavos: 3500000 });
  });
});
