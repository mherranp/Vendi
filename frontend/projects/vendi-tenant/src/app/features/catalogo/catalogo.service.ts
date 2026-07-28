import { Injectable, inject } from '@angular/core';
import { ApiService } from 'data-access';
import { PagedList } from 'domain';
import { Observable } from 'rxjs';
import { CambiosDeProducto, ProductoNuevo, ProductoSalida } from './contrato';

const RUTA = '/productos';

/** Cliente del catálogo (ADR-019). El stock no se edita aquí: ADR-020. */
@Injectable({ providedIn: 'root' })
export class CatalogoService {
  private readonly api = inject(ApiService);

  listar(skip: number, limit: number, consulta = ''): Observable<PagedList<ProductoSalida>> {
    const params: Record<string, string | number> = { skip, limit };
    const q = consulta.trim();
    if (q.length > 0) {
      params['q'] = q;
    }
    return this.api.get<PagedList<ProductoSalida>>(RUTA, params);
  }

  crear(producto: ProductoNuevo): Observable<ProductoSalida> {
    return this.api.post<ProductoSalida>(RUTA, producto);
  }

  actualizar(id: string, cambios: CambiosDeProducto): Observable<ProductoSalida> {
    return this.api.patch<ProductoSalida>(`${RUTA}/${id}`, cambios);
  }

  /** Borrado lógico: el producto desaparece de las listas y su EAN queda libre. */
  eliminar(id: string): Observable<void> {
    return this.api.delete<void>(`${RUTA}/${id}`);
  }
}
