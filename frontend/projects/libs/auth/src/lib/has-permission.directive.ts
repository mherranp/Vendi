import { Directive, Input, TemplateRef, ViewContainerRef, inject } from '@angular/core';
import { AuthService } from './auth.service';

/**
 * Directiva estructural que pinta su plantilla solo si el usuario tiene
 * **alguno** de los permisos indicados (o si no se exige ninguno).
 *
 * Uso: `<button *vdHasPermission="'tenant:create'">Nuevo negocio</button>`
 * o:   `<a *vdHasPermission="['tenant:update','tenant:delete']">…</a>`
 *
 * Lee `realm_access.roles` del JWT a través de `AuthService.hasPermission()`.
 * Cosechada de BaseSaaS con el prefijo de selector cambiado de `bs` a `vd`.
 *
 * Nota de seguridad: esto es cosmética. Ocultar un botón no protege nada; quien
 * autoriza es la API. La directiva existe para no ofrecer acciones que van a
 * rebotar con 403.
 */
@Directive({
  selector: '[vdHasPermission]',
})
export class HasPermissionDirective {
  private readonly auth = inject(AuthService);
  private readonly tpl = inject(TemplateRef<unknown>);
  private readonly vc = inject(ViewContainerRef);

  private pintado = false;

  @Input({ required: true }) set vdHasPermission(permisos: string | string[] | undefined | null) {
    const requeridos = Array.isArray(permisos) ? permisos : permisos ? [permisos] : [];
    const permitido = requeridos.length === 0 || requeridos.some((p) => this.auth.hasPermission(p));
    if (permitido && !this.pintado) {
      this.vc.createEmbeddedView(this.tpl);
      this.pintado = true;
    } else if (!permitido && this.pintado) {
      this.vc.clear();
      this.pintado = false;
    }
  }
}
