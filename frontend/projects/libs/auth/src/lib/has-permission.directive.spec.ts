import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { AuthService } from './auth.service';
import { HasPermissionDirective } from './has-permission.directive';

@Component({
  imports: [HasPermissionDirective],
  template: `
    <span id="con" *vdHasPermission="'tenant:create'">crear</span>
    <span id="sin" *vdHasPermission="'permiso:inexistente'">nunca</span>
    <span id="varios" *vdHasPermission="['no:existe', 'tenant:create']">alguno</span>
    <span id="ninguno" *vdHasPermission="[]">siempre</span>
    <span id="nulo" *vdHasPermission="null">siempre</span>
  `,
})
class AnfitrionDePrueba {}

function montar(permisos: string[]) {
  const roles = signal(permisos);
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      {
        provide: AuthService,
        useValue: {
          hasPermission: (p: string) => roles().includes('*') || roles().includes(p),
        } as Partial<AuthService>,
      },
    ],
  });
  const fixture = TestBed.createComponent(AnfitrionDePrueba);
  fixture.detectChanges();
  return fixture;
}

function existe(fixture: ReturnType<typeof montar>, id: string): boolean {
  return fixture.nativeElement.querySelector(`#${id}`) !== null;
}

describe('HasPermissionDirective', () => {
  it('pinta cuando el usuario tiene el permiso', () => {
    const fixture = montar(['tenant:create']);
    expect(existe(fixture, 'con')).toBe(true);
  });

  it('con un permiso inexistente no pinta y no explota', () => {
    const fixture = montar(['tenant:create']);
    expect(existe(fixture, 'sin')).toBe(false);
  });

  it('basta con tener alguno de la lista', () => {
    const fixture = montar(['tenant:create']);
    expect(existe(fixture, 'varios')).toBe(true);
  });

  it('sin permisos exigidos (lista vacía o null) pinta siempre', () => {
    const fixture = montar([]);
    expect(existe(fixture, 'ninguno')).toBe(true);
    expect(existe(fixture, 'nulo')).toBe(true);
  });

  it('un usuario sin ningún rol no ve nada de lo protegido', () => {
    const fixture = montar([]);
    expect(existe(fixture, 'con')).toBe(false);
    expect(existe(fixture, 'varios')).toBe(false);
  });
});
