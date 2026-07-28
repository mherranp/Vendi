import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import { API_BASE_URL, CATALOGO_MINIMO_ES, errorInterceptor, fusionarCatalogos } from 'data-access';
import { Observable, of } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';

import numerosApp from '../../../../public/i18n/es.json';
import { ForecastSalida, PyLSalida } from './contrato';
import { NumerosComponent } from './numeros.component';

const BASE = 'https://api.vendi.co/api/v1';

const ROLES_DUENO = ['dueno', 'reporte:leer'];

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

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, numerosApp as never) as unknown as TranslationObject,
    );
  }
}

interface Montaje {
  fixture: ComponentFixture<NumerosComponent>;
  http: HttpTestingController;
}

async function montar(roles: string[]): Promise<Montaje> {
  TestBed.resetTestingModule();
  KeycloakFake.reiniciar();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withInterceptors([errorInterceptor])),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
      AuthService,
      ...provideTranslateService({
        lang: 'es',
        fallbackLang: 'es',
        loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
      }),
    ],
  });
  TestBed.inject(TranslateService).use('es');
  await arrancarSesionFalsa(TestBed.inject(AuthService), { roles });
  return {
    fixture: TestBed.createComponent(NumerosComponent),
    http: TestBed.inject(HttpTestingController),
  };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

describe('NumerosComponent', () => {
  let m: Montaje;

  afterEach(() => {
    m.http.verify();
  });

  it('pide P&L del día y forecast al entrar, y pinta los números formateados', async () => {
    m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).flush(pylBase);
    m.http.expectOne(`${BASE}/reportes/forecast`).flush(forecastBase);
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Ventas netas');
    expect(visible).toContain('180.000'); // ventas_netas_centavos = 18000000
    expect(visible).toContain('Saldo proyectado');
  });

  it('las fuentes se RENDERIZAN: la pantalla dice de qué datos sale (ADR-006)', async () => {
    m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).flush(pylBase);
    m.http.expectOne(`${BASE}/reportes/forecast`).flush(forecastBase);
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain(pylBase.fuentes['costo_de_lo_vendido']);
    expect(visible).toContain(forecastBase.fuentes['cobros_fiado']);
    expect(visible).toContain('12'); // dias_con_datos
  });

  it('cambiar a la semana vuelve a pedir solo el P&L', async () => {
    m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).flush(pylBase);
    m.http.expectOne(`${BASE}/reportes/forecast`).flush(forecastBase);

    m.fixture.componentInstance.cambiarPeriodo('semana');
    const req = m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`);
    expect(req.request.params.get('periodo')).toBe('semana');
    req.flush(pylBase);
    // No hay segunda petición de forecast: lo verifica http.verify().
  });

  it('dos cambios rápidos: la respuesta vieja se descarta aunque llegue ÚLTIMA', async () => {
    m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).flush(pylBase);
    m.http.expectOne(`${BASE}/reportes/forecast`).flush(forecastBase);

    m.fixture.componentInstance.cambiarPeriodo('semana');
    m.fixture.componentInstance.cambiarPeriodo('mes');
    const pendientes = m.http.match((r) => r.url === `${BASE}/reportes/pyl`);
    expect(pendientes.length).toBe(2);

    // Llega primero la del mes (la última pedida)...
    pendientes
      .find((r) => r.request.params.get('periodo') === 'mes')
      ?.flush({ ...pylBase, periodo: 'mes', ventas_netas_centavos: 222 });
    // ...y después la vieja de la semana: no debe pisar los datos del mes.
    pendientes
      .find((r) => r.request.params.get('periodo') === 'semana')
      ?.flush({ ...pylBase, periodo: 'semana', ventas_netas_centavos: 111 });

    expect(m.fixture.componentInstance.periodo()).toBe('mes');
    expect(m.fixture.componentInstance.pyl()?.ventas_netas_centavos).toBe(222);
  });

  it('las compras del período se muestran como línea informativa, no restada', async () => {
    m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).flush(pylBase);
    m.http.expectOne(`${BASE}/reportes/forecast`).flush(forecastBase);
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Compras a proveedores (informativo');
  });

  it('un fallo deja reintento, no spinner eterno', async () => {
    m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).error(new ProgressEvent('error'));
    m.http.expectOne(`${BASE}/reportes/forecast`).error(new ProgressEvent('error'));
    m.fixture.detectChanges();
    expect(m.fixture.componentInstance.fallo()).toBe(true);
    expect(texto(m.fixture)).toContain('Reintentar');
  });
});
