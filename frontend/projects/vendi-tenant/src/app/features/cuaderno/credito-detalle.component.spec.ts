import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { ActivatedRoute, provideRouter } from '@angular/router';
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

import detalleApp from '../../../../public/i18n/es.json';
import { CreditoDetalleSalida } from './contrato';
import { CreditoDetalleComponent } from './credito-detalle.component';

const BASE = 'https://api.vendi.co/api/v1';
const ID_CRED = '5f1d0e2a-0000-4000-8000-ffffffffffff';

const detalleBase: CreditoDetalleSalida = {
  id: ID_CRED,
  cliente_id: '5f1d0e2a-0000-4000-8000-dddddddddddd',
  cliente_nombre: 'Rosa Mejía',
  venta_id: '5f1d0e2a-0000-4000-8000-eeeeeeeeeeee',
  estado: 'vencido',
  monto_total: 5000000,
  saldo_pendiente: 4500000,
  fecha_vencimiento: '2026-07-25',
  created_at: '2026-07-10T00:00:00Z',
  abonos: [],
  whatsapp_url: 'https://wa.me/573001234567?text=Hola',
};

const ROLES_CAJERO = ['cajero', 'cliente:gestionar', 'fiado:crear', 'fiado:abonar'];

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, detalleApp as never) as unknown as TranslationObject,
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
  fixture: ComponentFixture<CreditoDetalleComponent>;
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
      // El id de la ruta, de mentira: más simple que levantar el harness para
      // un solo parámetro.
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => ID_CRED } } } },
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
    fixture: TestBed.createComponent(CreditoDetalleComponent),
    http: TestBed.inject(HttpTestingController),
    dialogos,
  };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

describe('CreditoDetalleComponent', () => {
  let m: Montaje;

  afterEach(() => {
    m.http.verify();
  });

  it('pinta saldo, vencimiento y el botón de WhatsApp con el wa.me del backend', async () => {
    m = await montar(ROLES_CAJERO);
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush(detalleBase);
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Rosa Mejía');
    expect(visible).toContain('45.000');
    const enlace = (m.fixture.nativeElement as HTMLElement).querySelector('a[href*="wa.me"]');
    expect(enlace?.getAttribute('href')).toBe(detalleBase.whatsapp_url);
    expect(enlace?.getAttribute('target')).toBe('_blank');
  });

  it('sin teléfono NO hay botón de WhatsApp (whatsapp_url llega null)', async () => {
    m = await montar(ROLES_CAJERO);
    m.http
      .expectOne(`${BASE}/fiado/creditos/${ID_CRED}`)
      .flush({ ...detalleBase, whatsapp_url: null });
    m.fixture.detectChanges();
    expect((m.fixture.nativeElement as HTMLElement).querySelector('a[href*="wa.me"]')).toBeNull();
  });

  it('crédito sin fecha lo declara en pantalla: sin fecha, sin recordatorio', async () => {
    m = await montar(ROLES_CAJERO);
    m.http
      .expectOne(`${BASE}/fiado/creditos/${ID_CRED}`)
      .flush({ ...detalleBase, fecha_vencimiento: null });
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain('Sin fecha de vencimiento');
  });

  it('el abono manda id, método y centavos, y recarga el detalle', async () => {
    m = await montar(ROLES_CAJERO);
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush(detalleBase);
    m.fixture.detectChanges();

    m.dialogos.resultados = [{ metodo_pago: 'efectivo', monto: 500000, nota: null }];
    m.fixture.componentInstance.registrarAbono();
    const req = m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}/abonos`);
    expect(req.request.body).toEqual({
      id: expect.any(String),
      metodo_pago: 'efectivo',
      monto: 500000,
      nota: null,
    });
    req.flush({ id: 'x' });
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush(detalleBase);
  });

  it('reprogramar a null manda la clave con null (nunca body vacío)', async () => {
    m = await montar(ROLES_CAJERO);
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush(detalleBase);
    m.fixture.detectChanges();

    m.fixture.componentInstance.quitarVencimiento();
    const req = m.http.expectOne({ method: 'PATCH', url: `${BASE}/fiado/creditos/${ID_CRED}` });
    expect(req.request.body).toEqual({ fecha_vencimiento: null });
    req.flush({ id: ID_CRED });
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush(detalleBase);
  });

  it('el historial de abonos se pinta con método y monto', async () => {
    m = await montar(ROLES_CAJERO);
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush({
      ...detalleBase,
      abonos: [
        {
          id: 'a1',
          credito_id: ID_CRED,
          monto: 300000,
          metodo_pago: 'efectivo',
          nota: null,
          registrado_por: 'ana',
          sesion_caja_id: null,
          created_at: '2026-07-20T10:00:00Z',
        },
      ],
    });
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('3.000');
    expect(visible).toContain('Efectivo');
  });
});
