import { HttpInterceptorFn } from '@angular/common/http';

/**
 * Genera un identificador de correlación. Usa `crypto.randomUUID()` cuando
 * existe y cae a una implementación manual en contextos donde no está
 * disponible (WebView antiguo de Android, origen no seguro).
 */
function uuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Añade `X-Correlation-ID` a toda petición saliente.
 *
 * Es la contraparte del middleware `CorrelationIdMiddleware` del backend: el
 * mismo identificador aparece en los logs de la API, en los eventos de
 * auditoría y en el mensaje del outbox, de modo que un incidente se sigue de
 * punta a punta. Si quien llama ya puso la cabecera (p. ej. un reintento que
 * quiere conservar la traza), se respeta su valor.
 */
export const correlationIdInterceptor: HttpInterceptorFn = (req, next) => {
  const id = req.headers.get('X-Correlation-ID') ?? uuid();
  return next(req.clone({ setHeaders: { 'X-Correlation-ID': id } }));
};
