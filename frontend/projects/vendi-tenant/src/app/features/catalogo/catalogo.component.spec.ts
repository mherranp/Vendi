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
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';

import catalogoApp from '../../../../public/i18n/es.json';
import { CatalogoComponent } from './catalogo.component';
import { ProductoSalida } from './contrato';

const BASE = 'https://api.vendi.co/api/v1';

const productoBase: ProductoSalida = {
  id: '5f1d0e2a-0000-4000-8000-cccccccccccc',
  nombre: 'Arroz blanco x kg',
  categoria: 'Granos',
  codigo_barras: null,
  precio_venta: 420000,
  unidad_medida: 'kg',
  iva_pct: '0',
  stock_actual: '12.500',
  stock_minimo: '5.000',
  ultimo_costo: null,
  padre_id: null,
  created_at: '2026-07-01T00:00:00Z',
};

const ROLES_ALMACENISTA = [
  'almacenista',
  'producto:leer',
  'producto:editar',
  'inventario:ajustar',
  'compra:crear',
];
const ROLES_CAJERO = ['cajero', 'producto:leer'];

function pagina(items: ProductoSalida[], total = items.length, skip = 0, limit = 10) {
  return { items, total, skip, limit };
}

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
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
  fixture: ComponentFixture<CatalogoComponent>;
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
    fixture: TestBed.createComponent(CatalogoComponent),
    http: TestBed.inject(HttpTestingController),
    dialogos,
  };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

describe('CatalogoComponent — lectura', () => {
  let m: Montaje;

  afterEach(() => {
    m.http.verify();
  });

  it('pide la primera página y pinta precio formateado y unidad', async () => {
    m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http
      .expectOne((r) => r.url === `${BASE}/productos`)
      .flush(pagina([{ ...productoBase, nombre: 'Arroz blanco x kg' }]));
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Arroz blanco x kg');
    expect(visible).toContain('4.200'); // $42,00/kg → 420000 centavos
  });

  it('la búsqueda vuelve a la primera página y manda q', async () => {
    m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([]));
    m.fixture.componentInstance.consulta.set('arroz');
    m.fixture.componentInstance.buscar();
    const req = m.http.expectOne((r) => r.url === `${BASE}/productos`);
    expect(req.request.params.get('q')).toBe('arroz');
    expect(req.request.params.get('skip')).toBe('0');
    req.flush(pagina([]));
  });

  it('el cajero no ve los botones de editar ni el de nuevo producto', async () => {
    m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([productoBase]));
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).not.toContain('Nuevo producto');
    expect(visible).not.toContain('Editar');
  });
});

describe('CatalogoComponent — escritura', () => {
  let m: Montaje;

  beforeEach(async () => {
    m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
  });

  afterEach(() => {
    m.http.verify();
  });

  it('crear convierte pesos y granel en el borde y recarga', async () => {
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([]));

    m.dialogos.resultados = [
      {
        nombre: 'Arroz blanco x kg',
        categoria: 'Granos',
        codigo_barras: null,
        precio_venta: 420000,
        unidad_medida: 'kg',
        iva_pct: 0,
        stock_minimo: '5.000',
      },
    ];
    m.fixture.componentInstance.crear();
    const alta = m.http.expectOne((r) => r.url === `${BASE}/productos` && r.method === 'POST');
    expect((alta.request.body as { id: string }).id).toBeTruthy();
    expect((alta.request.body as { stock_minimo: string }).stock_minimo).toBe('5.000');
    alta.flush(productoBase);
    m.http
      .expectOne((r) => r.url === `${BASE}/productos` && r.method === 'GET')
      .flush(pagina([productoBase]));
  });

  it('eliminar pide confirmación marcada como peligrosa y manda DELETE', async () => {
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([productoBase]));

    m.dialogos.resultados = [true];
    m.fixture.componentInstance.eliminar(productoBase);
    expect((m.dialogos.aperturas[0].datos as { peligroso?: boolean }).peligroso).toBe(true);
    const baja = m.http.expectOne(`${BASE}/productos/${productoBase.id}`);
    expect(baja.request.method).toBe('DELETE');
    baja.flush(null, { status: 204, statusText: 'No Content' });
    m.http.expectOne((r) => r.url === `${BASE}/productos` && r.method === 'GET').flush(pagina([]));
  });

  it('un EAN duplicado (409) no cierra la pantalla ni pierde el listado', async () => {
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([productoBase]));

    m.dialogos.resultados = [
      {
        nombre: 'Otro',
        categoria: null,
        codigo_barras: '7701234567890',
        precio_venta: 1000,
        unidad_medida: 'unidad',
        iva_pct: 19,
        stock_minimo: '0.000',
      },
    ];
    m.fixture.componentInstance.crear();
    m.http
      .expectOne((r) => r.url === `${BASE}/productos` && r.method === 'POST')
      .flush(
        {
          message: 'Ya existe un producto con ese código de barras.',
          code: 'codigo_barras_duplicado',
        },
        { status: 409, statusText: 'Conflict' },
      );
    // El interceptor ya avisó con el mensaje del backend; la tabla sigue viva.
    expect(m.fixture.componentInstance.cargando()).toBe(false);
    m.fixture.componentInstance.recargar();
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([productoBase]));
  });
});
