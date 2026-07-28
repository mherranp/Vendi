import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { API_BASE_URL } from 'data-access';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ForecastSalida, PyLSalida } from './contrato';
import { NumerosService } from './numeros.service';

const BASE = 'https://api.vendi.co/api/v1';

const pylBase: PyLSalida = {
  periodo: 'dia',
  desde: '2026-07-29T05:00:00Z',
  hasta: '2026-07-30T04:59:59Z',
  ventas_netas_centavos: 18000000,
  ventas_efectivo_centavos: 12000000,
  ventas_fiado_centavos: 6000000,
  ventas_anuladas_centavos: 0,
  costo_de_lo_vendido_centavos: 11000000,
  margen_bruto_centavos: 7000000,
  ingresos_caja_centavos: 0,
  egresos_caja_centavos: 1500000,
  compras_proveedores_centavos: 8000000,
  resultado_operativo_centavos: 5500000,
  fuentes: {
    costo_de_lo_vendido: 'Costeado con el último costo actual de cada producto',
    compras_proveedores: 'Compras del período, informativas: no se restan del resultado',
  },
};

const forecastBase: ForecastSalida = {
  dias: 30,
  dias_con_datos: 12,
  saldo_actual_centavos: 230000,
  ventas_proyectadas_centavos: 40000000,
  cobros_fiado_proyectados_centavos: 9000000,
  egresos_proyectados_centavos: 15000000,
  saldo_proyectado_centavos: 34230000,
  fuentes: {
    cobros_fiado: 'Créditos con vencimiento en los próximos 30 días; los sin fecha no entran',
    ventas: 'Promedio de ventas en efectivo de los últimos 30 días',
  },
};

function configurar(): { servicio: NumerosService; http: HttpTestingController } {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
    ],
  });
  return {
    servicio: TestBed.inject(NumerosService),
    http: TestBed.inject(HttpTestingController),
  };
}

describe('NumerosService — contrato con la API', () => {
  let c: { servicio: NumerosService; http: HttpTestingController };

  beforeEach(() => {
    c = configurar();
  });

  afterEach(() => {
    c.http.verify();
  });

  it('el P&L se pide por período', () => {
    c.servicio.pyl('semana').subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`);
    expect(req.request.params.get('periodo')).toBe('semana');
    req.flush(pylBase);
  });

  it('el forecast no lleva parámetros', () => {
    c.servicio.forecast().subscribe();
    const req = c.http.expectOne(`${BASE}/reportes/forecast`);
    expect([...req.request.params.keys()].length).toBe(0);
    req.flush(forecastBase);
  });
});
