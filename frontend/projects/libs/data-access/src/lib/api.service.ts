import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Injectable, InjectionToken, inject } from '@angular/core';
import { Observable } from 'rxjs';

/**
 * URL base de la API. Cada app la provee desde su `environment`
 * (`{ provide: API_BASE_URL, useValue: environment.apiUrl }`).
 *
 * El valor por defecto `/api/v1` sirve para tests y para un despliegue donde
 * Traefik enruta la API bajo el mismo origen que el frontend.
 */
export const API_BASE_URL = new InjectionToken<string>('API_BASE_URL');

/**
 * Opciones por llamada.
 *
 * Hoy solo se honra `context`, que usan las peticiones de fondo para activar
 * `SILENCIAR_AVISO_ERROR` y que el interceptor global no saque un aviso:
 *
 *   import { HttpContext } from '@angular/common/http';
 *   import { SILENCIAR_AVISO_ERROR } from 'data-access';
 *   this.api.get('/tenants', undefined, {
 *     context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true),
 *   });
 */
export interface OpcionesDeLlamada {
  context?: HttpContext;
}

/**
 * Cliente HTTP delgado sobre `HttpClient`.
 *
 * Cosechado sin cambios de fondo de `ui-core/src/lib/services/api.service.ts`
 * de BaseSaaS. Deliberadamente no sabe de tenants: la cabecera `X-Tenant-Id` y
 * el `Authorization: Bearer` los pone `auth.interceptor` (librería `auth`), que
 * es quien conoce la sesión. La frontera de ADR-011 va `auth → data-access` y
 * no al revés; el lint de esta librería lo hace cumplir.
 */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL, { optional: true }) || '/api/v1';

  get<T>(
    path: string,
    params?: Record<string, string | number>,
    options?: OpcionesDeLlamada,
  ): Observable<T> {
    let httpParams = new HttpParams();
    if (params) {
      Object.entries(params).forEach(([clave, valor]) => {
        httpParams = httpParams.set(clave, String(valor));
      });
    }
    return this.http.get<T>(`${this.baseUrl}${path}`, {
      params: httpParams,
      context: options?.context,
    });
  }

  post<T>(path: string, body: unknown, options?: OpcionesDeLlamada): Observable<T> {
    return this.http.post<T>(`${this.baseUrl}${path}`, body, {
      context: options?.context,
    });
  }

  patch<T>(path: string, body: unknown, options?: OpcionesDeLlamada): Observable<T> {
    return this.http.patch<T>(`${this.baseUrl}${path}`, body, {
      context: options?.context,
    });
  }

  put<T>(path: string, body: unknown, options?: OpcionesDeLlamada): Observable<T> {
    return this.http.put<T>(`${this.baseUrl}${path}`, body, {
      context: options?.context,
    });
  }

  delete<T>(path: string, options?: OpcionesDeLlamada): Observable<T> {
    return this.http.delete<T>(`${this.baseUrl}${path}`, {
      context: options?.context,
    });
  }
}
