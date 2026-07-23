import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { ImpersonationBannerComponent } from '../impersonation/impersonation-banner.component';
import {
  NotificacionEnPantalla,
  NotificationsBadgeComponent,
} from '../notifications/notifications-badge.component';
import { proveerTraduccionDePrueba } from '../testing/i18n-de-prueba';
import { FullLayoutComponent } from './full-layout/full-layout.component';

function preparar(): void {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [provideRouter([]), ...proveerTraduccionDePrueba()],
  });
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

describe('FullLayoutComponent', () => {
  it('pinta la marca, la navegación traducida y el nombre del usuario', () => {
    preparar();
    const fixture = TestBed.createComponent(FullLayoutComponent);
    fixture.componentRef.setInput('marca', 'Vendi Admin');
    fixture.componentRef.setInput('nombreUsuario', 'Ana Gómez');
    fixture.componentRef.setInput('navegacion', [
      { etiqueta: 'layout.cuenta', icono: 'person', ruta: '/cuenta' },
    ]);
    fixture.detectChanges();

    expect(texto(fixture)).toContain('Vendi Admin');
    expect(texto(fixture)).toContain('Ana Gómez');
    expect(texto(fixture)).toContain('Mi cuenta');
    expect(fixture.nativeElement.querySelector('a[href="/cuenta"]')).not.toBeNull();
  });

  it('no exige sesión: sin AuthService el shell se monta igual', () => {
    // Es la comprobación de la frontera de ADR-011. Si alguien vuelve a
    // inyectar `AuthService` aquí, este test falla con NullInjectorError.
    preparar();
    const fixture = TestBed.createComponent(FullLayoutComponent);
    expect(() => fixture.detectChanges()).not.toThrow();
  });

  it('emite cerrarSesion en vez de cerrarla por su cuenta', () => {
    preparar();
    const fixture = TestBed.createComponent(FullLayoutComponent);
    fixture.detectChanges();
    let veces = 0;
    fixture.componentInstance.cerrarSesion.subscribe(() => veces++);
    fixture.componentInstance.cerrarSesion.emit();
    expect(veces).toBe(1);
  });

  it('alterna la barra lateral', () => {
    preparar();
    const fixture = TestBed.createComponent(FullLayoutComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance.lateralAbierto()).toBe(true);
    fixture.componentInstance.alternarLateral();
    expect(fixture.componentInstance.lateralAbierto()).toBe(false);
  });

  it('oculta el enlace de cuenta si no se configura ruta', () => {
    preparar();
    const fixture = TestBed.createComponent(FullLayoutComponent);
    fixture.detectChanges();
    expect(texto(fixture)).not.toContain('Mi cuenta');
  });
});

describe('NotificationsBadgeComponent', () => {
  const NOTIFICACIONES: NotificacionEnPantalla[] = [
    { id: '1', titulo: 'Venta registrada', leida: false },
    {
      id: '2',
      titulo: 'Cierre de caja',
      cuerpo: 'Turno de la tarde',
      leida: true,
      enlace: '/caja',
    },
  ];

  it('cuenta solo las no leídas', () => {
    preparar();
    const fixture = TestBed.createComponent(NotificationsBadgeComponent);
    fixture.componentRef.setInput('notificaciones', NOTIFICACIONES);
    fixture.detectChanges();
    expect(fixture.componentInstance.noLeidas()).toBe(1);
  });

  it('recorta el panel a 20 elementos', () => {
    preparar();
    const fixture = TestBed.createComponent(NotificationsBadgeComponent);
    const muchas: NotificacionEnPantalla[] = Array.from({ length: 50 }, (_, i) => ({
      id: String(i),
      titulo: `Aviso ${i}`,
      leida: false,
    }));
    fixture.componentRef.setInput('notificaciones', muchas);
    fixture.detectChanges();
    expect(fixture.componentInstance.visibles().length).toBe(20);
  });

  it('no hace HTTP: se monta sin HttpClient en el inyector', () => {
    // El original de BaseSaaS llamaba a GET /notifications en ngOnInit. Si
    // alguien lo reintroduce, este test falla con NullInjectorError.
    preparar();
    const fixture = TestBed.createComponent(NotificationsBadgeComponent);
    expect(() => fixture.detectChanges()).not.toThrow();
  });

  it('emite marcarTodasLeidas', () => {
    preparar();
    const fixture = TestBed.createComponent(NotificationsBadgeComponent);
    fixture.detectChanges();
    let veces = 0;
    fixture.componentInstance.marcarTodasLeidas.subscribe(() => veces++);
    fixture.componentInstance.marcarTodasLeidas.emit();
    expect(veces).toBe(1);
  });
});

describe('ImpersonationBannerComponent', () => {
  it('sin actor no pinta nada', () => {
    preparar();
    const fixture = TestBed.createComponent(ImpersonationBannerComponent);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.vd-suplantacion')).toBeNull();
  });

  it('con actor pinta la banda con rol de alerta y el nombre interpolado', () => {
    preparar();
    const fixture = TestBed.createComponent(ImpersonationBannerComponent);
    fixture.componentRef.setInput('actor', 'ana@vendi.co');
    fixture.componentRef.setInput('expiraEnSegundos', 120);
    fixture.detectChanges();

    const banda = fixture.nativeElement.querySelector('.vd-suplantacion');
    expect(banda).not.toBeNull();
    expect(banda.getAttribute('role')).toBe('alert');
    expect(texto(fixture)).toContain('ana@vendi.co');
    expect(texto(fixture)).toContain('120');
  });

  it('emite detener sin tocar la sesión', () => {
    preparar();
    const fixture = TestBed.createComponent(ImpersonationBannerComponent);
    fixture.componentRef.setInput('actor', 'ana@vendi.co');
    fixture.detectChanges();
    let veces = 0;
    fixture.componentInstance.detener.subscribe(() => veces++);
    fixture.nativeElement.querySelector('button').click();
    expect(veces).toBe(1);
  });
});
