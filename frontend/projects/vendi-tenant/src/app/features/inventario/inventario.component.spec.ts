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
import { API_BASE_URL, CATALOGO_MINIMO_ES, errorInterceptor, fusionarCatalogos } from 'data-access';
import { Observable, of } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';

import inventarioApp from '../../../../public/i18n/es.json';
import { StockSalida } from './contrato';
import { InventarioComponent } from './inventario.component';

const BASE = 'https://api.vendi.co/api/v1';
const ID_PROD = '5f1d0e2a-0000-4000-8000-cccccccccccc';
const ID_PROD_2 = '5f1d0e2a-0000-4000-8000-dddddddddddd';

const stockBase: StockSalida = {
  producto_id: ID_PROD,
  nombre: 'Arroz',
  stock_actual: '12.500',
  stock_minimo: '5.000',
  nivel: 'ok',
};

const ROLES_ALMACENISTA = [
  'almacenista',
  'producto:leer',
  'producto:editar',
  'inventario:ajustar',
  'compra:crear',
];
const ROLES_CAJERO = ['cajero', 'producto:leer'];

function pagina(items: StockSalida[], total = items.length, skip = 0, limit = 10) {
  return { items, total, skip, limit };
}

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, inventarioApp as never) as unknown as TranslationObject,
    );
  }
}

class DialogoFalso {
  resultados: unknown[] = [];
  readonly aperturas: { componente: unknown; datos: unknown }[] = [];
  open(componente: unknown, config?: { data?: unknown }) {
    this.aperturas.push({ componente, datos: config?.data });
    return { afterClosed: () => of(this.resultados.shift()) };
  }
}

interface Montaje {
  fixture: ComponentFixture<InventarioComponent>;
  http: HttpTestingController;
  dialogos: DialogoFalso;
}

async function montar(roles: string[]): Promise<Montaje> {
  TestBed.resetTestingModule();
  KeycloakFake.reiniciar();
  const dialogos = new DialogoFalso();
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      provideHttpClient(withInterceptors([errorInterceptor])),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
      { provide: MatDialog, useValue: dialogos },
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
    fixture: TestBed.createComponent(InventarioComponent),
    http: TestBed.inject(HttpTestingController),
    dialogos,
  };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

describe('InventarioComponent — stock y alertas', () => {
  let m: Montaje;

  afterEach(() => {
    m.http.verify();
  });

  it('pinta el nivel como badge y el stock negativo como dato, no como error', async () => {
    m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http
      .expectOne((r) => r.url === `${BASE}/inventario/stock`)
      .flush(
        pagina([
          {
            producto_id: ID_PROD,
            nombre: 'Arroz',
            stock_actual: '-2.000',
            stock_minimo: '5.000',
            nivel: 'agotado',
          },
          {
            producto_id: ID_PROD_2,
            nombre: 'Aceite',
            stock_actual: '8.000',
            stock_minimo: '10.000',
            nivel: 'bajo',
          },
        ]),
      );
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('-2.000'); // vendiste de más según el sistema: información
    expect(visible).toContain('Agotado');
    expect(visible).toContain('Bajo');
  });

  it('el interruptor de alertas recarga con solo_alertas=true desde la primera página', async () => {
    m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([], 30));
    m.fixture.componentInstance.alternarAlertas(true);
    const req = m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`);
    expect(req.request.params.get('solo_alertas')).toBe('true');
    expect(req.request.params.get('skip')).toBe('0');
    req.flush(pagina([]));
  });

  it('el cajero no ve los botones de ajustar ni de registrar compra', async () => {
    m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([stockBase]));
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).not.toContain('Registrar compra');
    expect(visible).not.toContain('Ajustar');
  });
});

describe('InventarioComponent — ajuste y compra', () => {
  let m: Montaje;

  afterEach(() => {
    m.http.verify();
  });

  it('el ajuste por conteo manda stock_contado, motivo y el id generado al abrir', async () => {
    m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([stockBase]));

    m.dialogos.resultados = [
      { tipo: 'ajuste', producto_id: ID_PROD, motivo: 'Conteo del lunes', stock_contado: '14.000' },
    ];
    m.fixture.componentInstance.ajustar(stockBase);
    const req = m.http.expectOne(
      (r) => r.url === `${BASE}/inventario/ajustes` && r.method === 'POST',
    );
    expect(req.request.body).toEqual({
      id: expect.any(String),
      tipo: 'ajuste',
      producto_id: ID_PROD,
      motivo: 'Conteo del lunes',
      stock_contado: '14.000',
    });
    req.flush({ id: 'x', nivel: 'ok' });
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([stockBase]));
  });

  it('la compra manda los ítems convertidos y recarga el stock', async () => {
    m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([stockBase]));

    m.dialogos.resultados = [
      {
        proveedor_nombre: 'Distribuidora La 33',
        items: [{ producto_id: ID_PROD, cantidad: '10.000', costo_unitario_centavos: 350000 }],
      },
    ];
    m.fixture.componentInstance.registrarCompra();
    const req = m.http.expectOne((r) => r.url === `${BASE}/compras` && r.method === 'POST');
    expect((req.request.body as { id: string }).id).toBeTruthy();
    req.flush({ id: 'x', total_centavos: 3500000 });
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([stockBase]));
  });

  it('un fallo de red deja reintento, no spinner eterno', async () => {
    m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).error(new ProgressEvent('error'));
    m.fixture.detectChanges();
    expect(m.fixture.componentInstance.fallo()).toBe(true);
    expect(texto(m.fixture)).toContain('Reintentar');
  });
});
