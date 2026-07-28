import { Injectable, inject } from '@angular/core';
import { ApiService } from 'data-access';
import { PagedList } from 'domain';
import { Observable } from 'rxjs';
import {
  AjusteCreado,
  AjusteNuevo,
  CompraDetalleSalida,
  CompraNueva,
  StockSalida,
} from './contrato';

/** Cliente de inventario y compras (ADR-020). */
@Injectable({ providedIn: 'root' })
export class InventarioService {
  private readonly api = inject(ApiService);

  stock(skip: number, limit: number, soloAlertas: boolean): Observable<PagedList<StockSalida>> {
    return this.api.get<PagedList<StockSalida>>('/inventario/stock', {
      skip,
      limit,
      solo_alertas: String(soloAlertas),
    });
  }

  ajustar(ajuste: AjusteNuevo): Observable<AjusteCreado> {
    return this.api.post<AjusteCreado>('/inventario/ajustes', ajuste);
  }

  registrarCompra(compra: CompraNueva): Observable<CompraDetalleSalida> {
    return this.api.post<CompraDetalleSalida>('/compras', compra);
  }
}
