import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from './auth.service';

/**
 * Añade la credencial a cada petición saliente.
 *
 *  - `Authorization: Bearer <token>` siempre que haya sesión.
 *  - `X-Tenant-Id: <uuid>` cuando hay un tenant activo.
 *
 * Sobre `X-Tenant-Id`: **no es una credencial y el backend no la trata como
 * tal**. El tenant se resuelve del claim `organization` del token; la cabecera
 * solo desambigua cuál eligió el usuario cuando pertenece a varios negocios.
 * Su valor sale siempre de `AuthService.tenantId()`, que a su vez solo admite
 * alias presentes en el token, así que no hay forma de pedir un tenant ajeno
 * desde el cliente — y aunque la hubiera, RLS en PostgreSQL sigue siendo el que
 * decide qué filas existen.
 *
 * Sustituye a la cabecera `X-Organization` con el slug del tenant que usaba
 * BaseSaaS: ya no hay slugs, y el nombre `X-Tenant-Id` dice exactamente lo que
 * viaja.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const token = auth.getToken();

  if (!token) {
    return next(req);
  }

  const cabeceras: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };

  const tenantId = auth.tenantId();
  if (tenantId) {
    cabeceras['X-Tenant-Id'] = tenantId;
  }

  return next(req.clone({ setHeaders: cabeceras }));
};
