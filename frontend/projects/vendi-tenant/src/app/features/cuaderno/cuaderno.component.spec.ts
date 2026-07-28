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

import cuadernoApp from '../../../../public/i18n/es.json';
import { ClienteConSaldo, CreditoResumenSalida } from './contrato';
import { CuadernoComponent } from './cuaderno.component';

const BASE = 'https://api.vendi.co/api/v1';
const ID_CRED = '5f1d0e2a-0000-4000-8000-ffffffffffff';

const clienteBase: ClienteConSaldo = {
  id: '5f1d0e2a-0000-4000-8000-dddddddddddd',
  nombre: 'Rosa Mejía',
  telefono: '3001234567',
  nota: null,
  limite_credito: 20000000,
  saldo_pendiente_total: 4500000,
  cupo_excedido: false,
  created_at: '2026-07-01T00:00:00Z',
};

const creditoBase: CreditoResumenSalida = {
  id: ID_CRED,
  cliente_id: clienteBase.id,
  cliente_nombre: 'Rosa Mejía',
  venta_id: '5f1d0e2a-0000-4000-8000-eeeeeeeeeeee',
  estado: 'vencido',
  monto_total: 5000000,
  saldo_pendiente: 4500000,
  fecha_vencimiento: '2026-07-25',
  created_at: '2026-07-10T00:00:00Z',
};

const ROLES_CAJERO = ['cajero', 'cliente:gestionar', 'fiado:crear', 'fiado:abonar'];
const ROLES_ALMACENISTA = [
  'almacenista',
  'producto:leer',
  'producto:editar',
  'inventario:ajustar',
  'compra:crear',
];

function pagina<T>(items: T[], total = items.length, skip = 0, limit = 10) {
  return { items, total, skip, limit };
}

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, cuadernoApp as never) as unknown as TranslationObject,
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
  fixture: ComponentFixture<CuadernoComponent>;
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
    fixture: TestBed.createComponent(CuadernoComponent),
    http: TestBed.inject(HttpTestingController),
    dialogos,
  };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

const esClientes = (r: { url: string }) => r.url === `${BASE}/clientes`;
const esCreditosPorCobrar = (r: { url: string; params: { has: (k: string) => boolean } }) =>
  r.url === `${BASE}/fiado/creditos` && !r.params.has('estado');
const esCreditosVencidos = (r: { url: string; params: { get: (k: string) => string | null } }) =>
  r.url === `${BASE}/fiado/creditos` && r.params.get('estado') === 'vencido';

/** Responde las tres peticiones de la carga inicial: clientes, por cobrar y conteo de vencidos. */
function flushCargaInicial(
  m: Montaje,
  clientes = pagina<ClienteConSaldo>([]),
  porCobrar = pagina<CreditoResumenSalida>([]),
  vencidos = pagina<CreditoResumenSalida>([], 0),
): void {
  m.http.expectOne(esClientes).flush(clientes);
  m.http.expectOne(esCreditosPorCobrar).flush(porCobrar);
  m.http.expectOne(esCreditosVencidos).flush(vencidos);
}

describe('CuadernoComponent — clientes', () => {
  let m: Montaje;

  afterEach(() => {
    m.http.verify();
  });

  it('pinta saldo formateado y el badge de cupo excedido como advertencia', async () => {
    m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    flushCargaInicial(
      m,
      pagina([
        {
          ...clienteBase,
          nombre: 'Rosa Mejía',
          saldo_pendiente_total: 4500000,
          cupo_excedido: true,
        },
      ]),
    );
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Rosa Mejía');
    expect(visible).toContain('45.000');
    expect(visible).toContain('Cupo excedido');
  });

  it('avisa cuántos créditos vencidos hay (el cuaderno cobra, no esconde)', async () => {
    m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    flushCargaInicial(m, pagina([]), pagina([]), pagina([creditoBase], 3));
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain('3 créditos vencidos');
  });

  it('el filtro de vencidos pide estado=vencido al servidor', async () => {
    m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    flushCargaInicial(m);
    m.fixture.componentInstance.filtrarEstado('vencido');
    const req = m.http.expectOne(esCreditosVencidos);
    expect(req.request.params.get('estado')).toBe('vencido');
    req.flush(pagina([]));
  });

  it('crear cliente manda el payload convertido y recarga', async () => {
    m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    flushCargaInicial(m);

    m.dialogos.resultados = [
      { nombre: 'Rosa Mejía', telefono: '3001234567', limite_credito: 20000000, nota: null },
    ];
    m.fixture.componentInstance.crearCliente();
    const alta = m.http.expectOne((r) => r.url === `${BASE}/clientes` && r.method === 'POST');
    expect((alta.request.body as { id: string }).id).toBeTruthy();
    expect((alta.request.body as { limite_credito: number }).limite_credito).toBe(20000000);
    alta.flush(clienteBase);
    m.http
      .expectOne((r) => r.url === `${BASE}/clientes` && r.method === 'GET')
      .flush(pagina([clienteBase]));
    m.http.expectOne(esCreditosPorCobrar).flush(pagina([]));
    m.http.expectOne(esCreditosVencidos).flush(pagina([], 0));
  });

  it('el almacenista no ve el botón de nuevo cliente (la ruta ni siquiera se le ofrece)', async () => {
    m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    flushCargaInicial(m, pagina([clienteBase]));
    m.fixture.detectChanges();
    expect(texto(m.fixture)).not.toContain('Nuevo cliente');
  });
});
