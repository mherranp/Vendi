import { HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { ApiService, SILENCIAR_AVISO_ERROR } from 'data-access';
import { EstadoTenant, PagedList, TenantDeApi } from 'domain';
import { Observable, map } from 'rxjs';

/**
 * Ruta base del módulo de plataforma. `API_BASE_URL` ya incluye `/api/v1`, así
 * que aquí solo va lo que cuelga de él.
 */
const RUTA = '/platform/tenants';

/**
 * Límite de caracteres del nombre de un negocio.
 *
 * No es un capricho de UI: el alta crea además una Organization en Keycloak con
 * este nombre, y las columnas de texto de Keycloak son `varchar(255)` —el spike
 * de la Etapa 3 documentó que pasarse revienta el import con un 500 de JDBC—.
 * 120 deja margen de sobra para cualquier razón social real y garantiza que el
 * error, si lo hay, sea un mensaje en español del formulario y no un 500 opaco
 * a mitad del aprovisionamiento.
 */
export const MAXIMO_NOMBRE = 120;

/** Cuerpo de `PATCH /platform/tenants/{id}`. Ambos campos son opcionales. */
export interface CambiosDeTenant {
  nombre?: string;
  estado?: EstadoTenant;
}

/**
 * Cliente del módulo `tenants` de plataforma.
 *
 * ## Relación con el cliente generado
 *
 * `openapi-typescript` genera **tipos**, no un cliente ejecutable: emite
 * `paths` y `components`, y quien hace las peticiones sigue siendo `ApiService`.
 * Así que "construir la feature sobre el cliente generado" (Tarea 4.5, Paso 1)
 * se materializa en dos piezas:
 *
 *  1. Este servicio, que habla el lenguaje de `domain` (`TenantDeApi`,
 *     `PagedList`) y no el del generador —que llama a las cosas
 *     `PagedList_TenantSalida_` y obliga a escribir
 *     `components['schemas']['TenantSalida']` en cada firma—.
 *  2. `contrato.ts`, que amarra esos tipos a los generados con aserciones de
 *     tipo. Si el backend cambia el esquema, `ng build vendi-admin` falla
 *     señalando el campo exacto. Sin ese archivo, el cliente generado sería
 *     decorativo: viviría en `data-access` sin que nada de la app lo mirara.
 *
 * Los specs de al lado cierran lo que los tipos no pueden ver: la URL, el
 * método y la forma del cuerpo que realmente sale por el cable.
 *
 * ## Por qué `TenantDeApi` y no `Tenant`
 *
 * `Tenant.estado` es una unión cerrada de tres literales; el JSON que llega no
 * lo es. Castear a `Tenant` haría que TypeScript jurara que un `en_mora` futuro
 * es uno de los tres conocidos. Se recibe con el estado sin estrechar y se
 * estrecha, donde importa, con `esEstadoTenant()`.
 */
@Injectable({ providedIn: 'root' })
export class TenantsService {
  private readonly api = inject(ApiService);

  /**
   * Página de negocios. `skip`/`limit` es la paginación del backend (ver
   * `PagedList`), no un filtro en memoria: con RLS, la cuenta de filas la tiene
   * el servidor.
   */
  listar(
    skip: number,
    limit: number,
    incluirEliminados = false,
  ): Observable<PagedList<TenantDeApi>> {
    return this.api
      .get<Partial<PagedList<TenantDeApi>>>(RUTA, {
        skip,
        limit,
        // El parámetro se manda siempre y explícito. El backend lo tiene por
        // defecto en `false`, pero depender de un valor por defecto ajeno para
        // decidir si se muestran negocios dados de baja es confiar en algo que
        // no controlamos y que además no se ve al leer esta llamada.
        incluir_eliminados: String(incluirEliminados),
      })
      .pipe(map((bruto) => normalizarPagina(bruto, skip, limit)));
  }

  /** Alta de un negocio. El backend crea además su Organization en Keycloak. */
  crear(nombre: string): Observable<TenantDeApi> {
    return this.api.post<TenantDeApi>(RUTA, { nombre: nombre.trim() });
  }

  /** Renombrado y cambio de estado comparten endpoint. */
  actualizar(id: string, cambios: CambiosDeTenant): Observable<TenantDeApi> {
    return this.api.patch<TenantDeApi>(`${RUTA}/${id}`, cambios);
  }

  /** Baja lógica: el backend marca `eliminado` y deshabilita la organización. */
  eliminar(id: string): Observable<void> {
    return this.api.delete<void>(`${RUTA}/${id}`);
  }

  /**
   * Sondeo silencioso usado por la recarga de fondo: el interceptor global no
   * saca aviso y es la pantalla la que decide qué enseñar.
   */
  listarEnSilencio(skip: number, limit: number): Observable<PagedList<TenantDeApi>> {
    return this.api
      .get<Partial<PagedList<TenantDeApi>>>(
        RUTA,
        { skip, limit },
        {
          context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true),
        },
      )
      .pipe(map((bruto) => normalizarPagina(bruto, skip, limit)));
  }
}

/**
 * Endurece la respuesta de listado.
 *
 * Una página sin `items` (204 mal formado, respuesta de un proxy, endpoint que
 * cambia de forma) no puede convertirse en `undefined.length` dentro de la
 * tabla: eso es una pantalla rota. Se degrada a "página vacía", que la interfaz
 * ya sabe pintar.
 *
 * `total` se toma del servidor incluso cuando no coincide con `items.length`:
 * son cosas distintas —el total es sin paginar— y "arreglarlo" aquí rompería el
 * paginador con más de una página.
 */
function normalizarPagina(
  bruto: Partial<PagedList<TenantDeApi>> | null | undefined,
  skip: number,
  limit: number,
): PagedList<TenantDeApi> {
  const items = Array.isArray(bruto?.items) ? bruto.items : [];
  return {
    items,
    total: typeof bruto?.total === 'number' && bruto.total >= 0 ? bruto.total : items.length,
    skip: typeof bruto?.skip === 'number' ? bruto.skip : skip,
    limit: typeof bruto?.limit === 'number' ? bruto.limit : limit,
  };
}
