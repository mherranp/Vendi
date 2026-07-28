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
import { formatearPesos } from 'domain';

import catalogoApp from '../../../../public/i18n/es.json';
import { MiCajaComponent } from './mi-caja.component';

const BASE = 'https://api.vendi.co/api/v1';
const SESION = '5f1d0e2a-0000-4000-8000-aaaaaaaaaaaa';

const ROLES_DUENO = [
  'dueno',
  'caja:leer',
  'caja:abrir',
  'caja:cerrar',
  'caja:movimiento',
  'reporte:leer',
];
const ROLES_CAJERO = ['cajero', 'caja:leer', 'caja:abrir', 'caja:movimiento'];

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
  fixture: ComponentFixture<MiCajaComponent>;
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
    fixture: TestBed.createComponent(MiCajaComponent),
    http: TestBed.inject(HttpTestingController),
    dialogos,
  };
}

function sesion(esperado: number | null) {
  return {
    id: SESION,
    estado: 'abierta',
    abierta_en: '2026-07-29T08:00:00-05:00',
    abierta_por: 'ana',
    base_inicial: 50000,
    efectivo_esperado: esperado,
  };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

/** Responde el arranque "sin sesión" (404 silenciado → null). */
function arrancarSinSesion(m: Montaje): void {
  m.fixture.detectChanges();
  m.http
    .expectOne(`${BASE}/caja/sesiones/actual`)
    .flush({ message: 'no hay' }, { status: 404, statusText: 'Not Found' });
  // El historial se pide igual (es de quien cierra, haya o no sesión hoy).
  m.http
    .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'GET')
    .flush({ items: [], total: 0, skip: 0, limit: 10 });
  m.fixture.detectChanges();
}

/** Responde el arranque con sesión abierta (y sus movimientos e historial). */
function arrancarConSesion(m: Montaje, esperado: number | null, conHistorial: boolean): void {
  m.fixture.detectChanges();
  m.http.expectOne(`${BASE}/caja/sesiones/actual`).flush(sesion(esperado));
  m.http
    .expectOne((r) => r.url === `${BASE}/caja/movimientos`)
    .flush({ items: [], total: 0, skip: 0, limit: 10 });
  if (conHistorial) {
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'GET')
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
  }
  m.fixture.detectChanges();
}

describe('MiCajaComponent — sin sesión', () => {
  let m: Montaje;

  beforeEach(async () => {
    m = await montar(ROLES_DUENO);
    arrancarSinSesion(m);
  });

  afterEach(() => {
    m.http.verify();
  });

  it('ofrece abrir la caja con base inicial', () => {
    expect(texto(m.fixture)).toContain('Abrir caja');
  });

  it('abrir manda la base en centavos y recarga el estado', () => {
    m.fixture.componentInstance.basePesos.set(500);
    m.fixture.componentInstance.abrirCaja();
    const apertura = m.http.expectOne(
      (r) => r.url === `${BASE}/caja/sesiones` && r.method === 'POST',
    );
    expect(apertura.request.body).toEqual({
      id: m.fixture.componentInstance.idApertura(),
      base_inicial: 50000,
    });
    apertura.flush(sesion(null));
    m.http.expectOne(`${BASE}/caja/sesiones/actual`).flush(sesion(50000));
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/movimientos`)
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'GET')
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    expect(m.fixture.componentInstance.sesion()?.id).toBe(SESION);
  });

  it('un 409 caja_ya_abierta (otra caja abrió primero) refresca el estado en vez de morir', () => {
    m.fixture.componentInstance.basePesos.set(500);
    m.fixture.componentInstance.abrirCaja();
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'POST')
      .flush(
        { message: 'Ya hay una caja abierta', code: 'caja_ya_abierta' },
        { status: 409, statusText: 'Conflict' },
      );
    m.http.expectOne(`${BASE}/caja/sesiones/actual`).flush(sesion(50000));
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/movimientos`)
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'GET')
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    m.fixture.detectChanges();
    expect(m.fixture.componentInstance.sesion()?.estado).toBe('abierta');
  });
});

describe('MiCajaComponent — con sesión abierta', () => {
  afterEach(() => {
    TestBed.inject(HttpTestingController).verify();
  });

  it('el dueño ve el esperado; el backend se lo manda', async () => {
    const m = await montar(ROLES_DUENO);
    arrancarConSesion(m, 230000, true);
    // Sin asertar el símbolo exacto: Intl puede meter un espacio duro tras
    // el "$" según la versión de ICU. Lo que importa es la cifra.
    expect(texto(m.fixture)).toContain('2.300');
  });

  it('el cajero NO ve la cifra: llega null y no se pinta (ni como cero)', async () => {
    const m = await montar(ROLES_CAJERO);
    arrancarConSesion(m, null, false);
    const visible = texto(m.fixture);
    expect(visible).not.toContain('Esperado en gaveta');
    expect(visible).not.toContain('Historial de arqueos');
    // Y nunca pidió el historial: http.verify() del afterEach lo garantiza.
  });

  it('registrar un movimiento manda motivo, categoría y monto en centavos con id estable', async () => {
    const m = await montar(ROLES_DUENO);
    arrancarConSesion(m, 230000, true);
    m.dialogos.resultados = [
      { tipo: 'egreso', categoria: 'arriendo', montoCentavos: 150000, motivo: 'Arriendo de junio' },
    ];
    m.fixture.componentInstance.registrarMovimiento();
    const req = m.http.expectOne(
      (r) => r.url === `${BASE}/caja/movimientos` && r.method === 'POST',
    );
    expect(req.request.body).toEqual({
      id: expect.any(String),
      tipo: 'egreso',
      categoria: 'arriendo',
      monto: 150000,
      motivo: 'Arriendo de junio',
    });
    req.flush({ id: 'x' });
    // La escritura recarga movimientos y refresca la sesión (esperado vivo).
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/movimientos` && r.method === 'GET')
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    m.http.expectOne(`${BASE}/caja/sesiones/actual`).flush(sesion(230000));
  });

  it('cerrar pide el contado y muestra la diferencia del arqueo', async () => {
    const m = await montar(ROLES_DUENO);
    arrancarConSesion(m, 230000, true);
    expect(m.dialogos.aperturas.length).toBe(0);
    m.dialogos.resultados = [225000];
    m.fixture.componentInstance.cerrarCaja();
    expect((m.dialogos.aperturas[0].datos as { esperado: number | null }).esperado).toBe(230000);

    const cierre = m.http.expectOne(`${BASE}/caja/sesiones/${SESION}/cerrar`);
    expect(cierre.request.body).toEqual({ contado: 225000 });
    cierre.flush({
      ...sesion(null),
      estado: 'cerrada',
      cerrada_en: '2026-07-29T20:00:00-05:00',
      cerrada_por: 'ana',
      efectivo_esperado: 230000,
      efectivo_contado: 225000,
      diferencia: -5000,
      desglose: {
        base_inicial: 50000,
        ventas_efectivo: 180000,
        abonos_efectivo: 0,
        ingresos: 0,
        egresos: 0,
        devoluciones: 0,
        esperado: 230000,
      },
    });
    // Tras cerrar, el historial se recarga solo.
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'GET')
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    m.fixture.detectChanges();

    const visible = texto(m.fixture);
    expect(visible).toContain('Diferencia');
    expect(m.fixture.componentInstance.textoDiferencia(-5000)).toBe(`-${formatearPesos(5000)}`);
    expect(m.fixture.componentInstance.sesion()).toBeNull();
  });

  it('un fallo de red deja la pantalla en estado de reintento, no en spinner eterno', async () => {
    const m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne(`${BASE}/caja/sesiones/actual`).error(new ProgressEvent('error'));
    m.fixture.detectChanges();
    expect(m.fixture.componentInstance.fallo()).toBe(true);
    expect(texto(m.fixture)).toContain('Reintentar');
  });
});
