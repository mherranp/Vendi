import { Injectable, inject } from '@angular/core';
import { ApiService } from 'data-access';
import type { components } from 'data-access';
import { Observable } from 'rxjs';

export type TenantMioSalida = components['schemas']['TenantMioSalida'];

/**
 * Cliente de `GET /api/v1/tenants/mios` (Tarea 1 del plan): los negocios del
 * token con nombre. Es la única llamada de la consola que sale SIN
 * `X-Tenant-Id` — el usuario todavía no ha elegido; el backend la sirve con
 * el token validado gracias a la excepción del middleware.
 */
@Injectable({ providedIn: 'root' })
export class ElegirNegocioService {
  private readonly api = inject(ApiService);

  mios(): Observable<TenantMioSalida[]> {
    return this.api.get<TenantMioSalida[]>('/tenants/mios');
  }
}
