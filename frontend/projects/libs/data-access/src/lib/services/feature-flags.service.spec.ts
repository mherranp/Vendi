import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ApiService } from '../api.service';
import { SILENCIAR_AVISO_ERROR } from '../interceptors/error.interceptor';
import { FeatureFlagsService } from './feature-flags.service';

function montar(): { flags: FeatureFlagsService; http: HttpTestingController } {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [provideHttpClient(), provideHttpClientTesting(), ApiService, FeatureFlagsService],
  });
  return {
    flags: TestBed.inject(FeatureFlagsService),
    http: TestBed.inject(HttpTestingController),
  };
}

describe('FeatureFlagsService', () => {
  it('empieza vacío y sin cargar', () => {
    const { flags, http } = montar();
    expect(flags.flags()).toEqual({});
    expect(flags.cargado()).toBe(false);
    http.verify();
  });

  it('carga el catálogo una sola vez aunque lo pidan varios consumidores', () => {
    const { flags, http } = montar();
    flags.cargar().subscribe();
    flags.cargar().subscribe();
    const req = http.expectOne('/api/v1/tenant/features');
    req.flush({ ventas_offline: true, informes: false });

    expect(flags.estaHabilitada('ventas_offline')).toBe(true);
    expect(flags.estaHabilitada('informes')).toBe(false);
    expect(flags.cargado()).toBe(true);
    http.verify();
  });

  it('la petición va silenciada: en Fase 0 el endpoint no existe y no debe avisar al usuario', () => {
    const { flags, http } = montar();
    flags.cargar().subscribe();
    const req = http.expectOne('/api/v1/tenant/features');
    expect(req.request.context.get(SILENCIAR_AVISO_ERROR)).toBe(true);
    req.flush(null, { status: 404, statusText: 'Not Found' });
    http.verify();
  });

  it('falla cerrado: ante un error toda bandera queda desactivada', () => {
    const { flags, http } = montar();
    flags.cargar().subscribe();
    http.expectOne('/api/v1/tenant/features').error(new ProgressEvent('error'));

    expect(flags.flags()).toEqual({});
    expect(flags.estaHabilitada('lo_que_sea')).toBe(false);
    expect(flags.cargado()).toBe(true);
    http.verify();
  });

  it('habilitada() expone la bandera como señal calculada', () => {
    const { flags, http } = montar();
    const señal = flags.habilitada('ventas_offline');
    expect(señal()).toBe(false);
    flags.cargar().subscribe();
    http.expectOne('/api/v1/tenant/features').flush({ ventas_offline: true });
    expect(señal()).toBe(true);
    http.verify();
  });

  it('recargar() vuelve a pedir el catálogo', () => {
    const { flags, http } = montar();
    flags.cargar().subscribe();
    http.expectOne('/api/v1/tenant/features').flush({ a: true });
    flags.recargar().subscribe();
    http.expectOne('/api/v1/tenant/features').flush({ a: false, b: true });

    expect(flags.estaHabilitada('a')).toBe(false);
    expect(flags.estaHabilitada('b')).toBe(true);
    http.verify();
  });
});
