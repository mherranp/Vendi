import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';

/**
 * Guard de rutas por permiso de dominio (ADR-023).
 *
 * Es el hermano de `roleGuard` para los permisos `recurso:accion`: usa
 * `hasPermission`, que honra el comodín `*` (cosa que `hasAnyRole`, y por
 * tanto `roleGuard`, no hace a propósito). Semántica OR: basta UN permiso.
 *
 * Sin permiso redirige a `/sin-permiso`: la app que lo use debe proveer esa
 * ruta (igual que `tenantGuard` exige `/elegir-negocio`). No es una frontera
 * de seguridad —eso es el backend—: solo ahorra el 403.
 */
export const permisoGuard = (...permisos: string[]): CanActivateFn => {
  return () => {
    const auth = inject(AuthService);
    const router = inject(Router);

    if (!auth.authenticated()) {
      auth.login();
      return false;
    }
    if (permisos.length === 0 || permisos.some((permiso) => auth.hasPermission(permiso))) {
      return true;
    }
    return router.createUrlTree(['/sin-permiso']);
  };
};
