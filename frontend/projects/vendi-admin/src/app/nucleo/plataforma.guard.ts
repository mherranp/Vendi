import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from 'auth';

/**
 * Permiso que habilita la consola de plataforma. Viaja como rol de realm.
 *
 * Se declara aquí y no en la librería `auth` porque es una regla **de esta
 * app**: `vendi-tenant` y `vendi-app` no saben nada de él.
 */
export const PERMISO_PLATAFORMA = 'platform:admin';

/**
 * Deja pasar solo a quien administra la plataforma.
 *
 * Tres desenlaces, y los tres importan:
 *
 *  1. Sin sesión → al login. No es un error, es que aún no se ha identificado.
 *  2. Con sesión y sin el permiso → `/sin-acceso`, una pantalla que **explica**
 *     lo que pasa. El requisito del plan (Tarea 4.5, Paso 2) es explícito:
 *     "usuario sin `platform:admin` ve pantalla de 'sin acceso', no una consola
 *     vacía". Una consola vacía es peor que un error: el dueño de un negocio
 *     que entre por error creería que la plataforma perdió sus datos.
 *  3. Con el permiso → pasa.
 *
 * Usa `hasPermission()` y no `hasAnyRole()` a propósito: el primero honra el
 * comodín `*`, que es como se representa "puede todo" en el realm.
 *
 * Esto es una comodidad de interfaz, no seguridad. Quien decide de verdad es la
 * API: aunque alguien fabricara una navegación a `/negocios`, cada petición al
 * endpoint de plataforma se valida en el backend.
 */
export const guardPlataforma: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (!auth.authenticated()) {
    auth.login();
    return false;
  }

  if (auth.hasPermission(PERMISO_PLATAFORMA)) {
    return true;
  }

  return router.createUrlTree(['/sin-acceso']);
};
