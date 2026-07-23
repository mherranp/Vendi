import { Injectable, inject } from '@angular/core';
import { ApiService } from 'data-access';
import { TenantDeApi } from 'domain';
import { Observable } from 'rxjs';

/**
 * Cliente de `GET /api/v1/tenants/me`.
 *
 * Es una sola llamada y **sin parámetros**, y eso es lo importante: el tenant
 * lo resuelve el backend del claim `organization` del token, no de nada que
 * mande este cliente. La cabecera `X-Tenant-Id` que añade `authInterceptor`
 * solo desambigua entre los negocios que YA están en el token cuando el usuario
 * pertenece a varios; no es una credencial y el backend no la trata como tal.
 *
 * Consecuencia práctica: no existe forma, desde esta app, de pedir el negocio
 * de otro. No hay ningún identificador que manipular en la URL.
 *
 * Como el resto de la pista frontend, se escribe a mano contra el contrato de
 * la Tarea 4.2 mientras `docs/api/openapi-fase0.json` no exista; el spec de al
 * lado lo fija.
 */
@Injectable({ providedIn: 'root' })
export class MiNegocioService {
  private readonly api = inject(ApiService);

  obtener(): Observable<TenantDeApi> {
    return this.api.get<TenantDeApi>('/tenants/me');
  }
}
