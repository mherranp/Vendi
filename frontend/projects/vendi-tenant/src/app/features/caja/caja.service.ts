import { HttpContext, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { ApiService, SILENCIAR_AVISO_ERROR } from 'data-access';
import { PagedList } from 'domain';
import { Observable, catchError, of, throwError } from 'rxjs';
import {
  ArqueoConDesglose,
  ArqueoSalida,
  MovimientoNuevo,
  MovimientoSalida,
  SesionActualSalida,
  SesionSalida,
} from './contrato';

const RUTA = '/caja';

/**
 * Cliente del módulo de caja (ADR-021).
 *
 * Solo `sesionActual` va silenciada: su 404 es «no hay caja abierta», un
 * estado normal de la pantalla, no un fallo que avisar. Todo lo demás deja
 * que `errorInterceptor` avise con el mensaje del backend, y la pantalla
 * reacciona al `code` cuando el flujo lo necesita (decisión 8 del plan).
 */
@Injectable({ providedIn: 'root' })
export class CajaService {
  private readonly api = inject(ApiService);

  /** La sesión abierta con su esperado vivo (null en el campo sin `caja:cerrar`), o null si no hay. */
  sesionActual(): Observable<SesionActualSalida | null> {
    return this.api
      .get<SesionActualSalida>(`${RUTA}/sesiones/actual`, undefined, {
        context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true),
      })
      .pipe(
        catchError((error: unknown) => {
          if (error instanceof HttpErrorResponse && error.status === 404) {
            return of(null);
          }
          return throwError(() => error);
        }),
      );
  }

  /** Apertura con `id` del cliente: el reenvío es un no-op (ADR-017). */
  abrir(id: string, baseInicial: number): Observable<SesionSalida> {
    return this.api.post<SesionSalida>(`${RUTA}/sesiones`, { id, base_inicial: baseInicial });
  }

  movimientos(
    sesionId: string,
    skip: number,
    limit: number,
  ): Observable<PagedList<MovimientoSalida>> {
    return this.api.get<PagedList<MovimientoSalida>>(`${RUTA}/movimientos`, {
      sesion_id: sesionId,
      skip,
      limit,
    });
  }

  registrarMovimiento(movimiento: MovimientoNuevo): Observable<MovimientoSalida> {
    return this.api.post<MovimientoSalida>(`${RUTA}/movimientos`, movimiento);
  }

  /** El arqueo: el servidor calcula y CONGELA esperado y diferencia. */
  cerrar(sesionId: string, contado: number): Observable<ArqueoConDesglose> {
    return this.api.post<ArqueoConDesglose>(`${RUTA}/sesiones/${sesionId}/cerrar`, { contado });
  }

  /** Historial de arqueos: exige `caja:cerrar` en el backend. */
  historial(skip: number, limit: number): Observable<PagedList<ArqueoSalida>> {
    return this.api.get<PagedList<ArqueoSalida>>(`${RUTA}/sesiones`, { skip, limit });
  }
}
