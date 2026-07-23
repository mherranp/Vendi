import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';

/**
 * Exige sesión. Si no la hay, manda al login de Keycloak.
 *
 * Cosechado sin cambios de fondo de `ui-core/src/lib/auth/auth.guard.ts`,
 * quitando la inyección de `Router` que allí estaba declarada y no se usaba.
 */
export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);

  if (auth.authenticated()) {
    return true;
  }

  auth.login();
  return false;
};

/**
 * Exige sesión **y** al menos uno de los roles indicados.
 *
 * Sin el rol, redirige a `/sin-permiso` en vez de dejar la ruta a medias. La
 * ruta de destino debe existir en la app que use el guard.
 */
export const roleGuard = (...roles: string[]): CanActivateFn => {
  return () => {
    const auth = inject(AuthService);
    const router = inject(Router);

    if (!auth.authenticated()) {
      auth.login();
      return false;
    }

    if (auth.hasAnyRole(...roles)) {
      return true;
    }

    return router.createUrlTree(['/sin-permiso']);
  };
};

/**
 * Exige que haya un tenant activo.
 *
 * Un usuario con varios negocios no tiene tenant hasta que elige uno; sin este
 * guard, sus peticiones saldrían sin `X-Tenant-Id` y el backend respondería
 * 403. Redirige al selector de negocio, que es lo que el usuario necesita.
 */
export const tenantGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (!auth.authenticated()) {
    auth.login();
    return false;
  }

  if (auth.tenantId()) {
    return true;
  }

  return router.createUrlTree(['/elegir-negocio']);
};
