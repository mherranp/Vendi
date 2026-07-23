import { HttpContextToken, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { TranslateService } from '@ngx-translate/core';
import { catchError, throwError } from 'rxjs';
import { traducir } from '../i18n/traduccion';
import { Notificador } from '../notificaciones/notificador.service';

/**
 * Bandera de contexto por petición. Las peticiones de fondo (sondeos, refresco
 * silencioso) la activan para que el interceptor no saque un aviso; quien llama
 * sigue recibiendo el error por el observable y decide qué hacer.
 *
 *   http.get(url, { context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true) });
 */
export const SILENCIAR_AVISO_ERROR = new HttpContextToken<boolean>(() => false);

/**
 * Extrae, con el mejor esfuerzo, un mensaje legible del cuerpo de un error HTTP.
 *
 * Cubre las tres formas que produce el backend:
 *   - Envoltura de error de la API:  `{ message: "...", code: "..." }`
 *   - `HTTPException` de FastAPI:    `{ detail: "..." }`
 *   - Validación de Pydantic:        `{ detail: [{ loc, msg, type }] }`
 *
 * Devuelve cadena vacía si no hay nada aprovechable. **Nunca** devuelve
 * `[object Object]`: cualquier valor que no sea string usable se descarta y es
 * quien llama el que pone un texto traducido genérico. Esto importa porque el
 * cuerpo de un error de red (`status 0`) es un `ProgressEvent`, y el de un 502
 * de Traefik es HTML.
 */
export function extraerMensajeDeError(err: HttpErrorResponse): string {
  const cuerpo = err.error as { message?: unknown; detail?: unknown } | string | null | undefined;

  if (cuerpo == null) {
    return '';
  }

  // Un cuerpo string es HTML (página de error del proxy) o texto plano. El HTML
  // no se enseña jamás; el texto corto sí puede servir.
  if (typeof cuerpo === 'string') {
    const limpio = cuerpo.trim();
    if (limpio.length === 0 || limpio.startsWith('<') || limpio.length > 200) {
      return '';
    }
    return limpio;
  }

  if (typeof cuerpo !== 'object') {
    return '';
  }

  if (typeof cuerpo.message === 'string' && cuerpo.message.length > 0) {
    return cuerpo.message;
  }

  if (typeof cuerpo.detail === 'string' && cuerpo.detail.length > 0) {
    return cuerpo.detail;
  }

  if (Array.isArray(cuerpo.detail)) {
    // Array de validación de Pydantic → "campo: mensaje" unidos por "; ".
    const partes = (cuerpo.detail as { loc?: unknown; msg?: unknown }[])
      .map((d) => {
        const campo = Array.isArray(d.loc)
          ? d.loc
              .slice(1) // se descarta el segmento inicial 'body' / 'query'
              .map(String)
              .join('.')
          : '';
        const msg = typeof d.msg === 'string' ? d.msg : '';
        return campo ? `${campo}: ${msg}` : msg;
      })
      .filter((s) => s.length > 0);
    if (partes.length > 0) {
      return partes.join('; ');
    }
  }

  return '';
}

/**
 * Traduce un error HTTP a la clave del catálogo que le corresponde.
 *
 * `status === 0` es el caso que más importa en un POS: no hay respuesta porque
 * no hay red (o CORS la bloqueó). BaseSaaS lo dejaba caer en el `>= 400` y
 * acababa enseñando el `err.message` de Angular en inglés.
 */
export function claveDeError(status: number): string {
  if (status === 0) return 'errores.sin_conexion';
  if (status === 401) return 'errores.sesion_expirada';
  if (status === 403) return 'errores.sin_permiso';
  if (status === 404) return 'errores.no_encontrado';
  if (status >= 500) return 'errores.servidor';
  return 'errores.solicitud';
}

/**
 * Interceptor global de errores: convierte cualquier fallo HTTP en un aviso en
 * español y vuelve a lanzar el error para que quien llamó decida.
 *
 * Reglas:
 *  - 5xx y errores de red: mensaje genérico traducido. No se enseña el detalle
 *    del servidor (suele ser un traceback o HTML del proxy, y siempre en
 *    inglés).
 *  - 4xx: se prefiere el mensaje del backend —que ya viene en español, es quien
 *    conoce la regla de negocio violada— y se cae al genérico si no hay ninguno
 *    aprovechable.
 */
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const notificador = inject(Notificador);
  const traductor = inject(TranslateService);
  const silenciar = req.context.get(SILENCIAR_AVISO_ERROR);

  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      if (silenciar) {
        return throwError(() => err);
      }

      const clave = claveDeError(err.status);
      const generico = traducir(traductor, clave);
      const delBackend = extraerMensajeDeError(err);

      const esRecuperableDelBackend = err.status >= 400 && err.status < 500 && err.status !== 401;
      const mensaje = esRecuperableDelBackend && delBackend ? delBackend : generico;

      if (err.status === 401 || err.status === 403) {
        notificador.advertencia(mensaje);
      } else {
        notificador.error(mensaje);
      }

      return throwError(() => err);
    }),
  );
};
