import { HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { ApiService, SILENCIAR_AVISO_ERROR } from 'data-access';
import { PagedList } from 'domain';
import { Observable } from 'rxjs';
import {
  AbonoNuevo,
  AbonoSalida,
  CambiosDeCliente,
  ClienteConSaldo,
  ClienteNuevo,
  CreditoDetalleSalida,
  CreditoResumenSalida,
} from './contrato';

/**
 * Cliente del cuaderno (ADR-009/ADR-022). El cupo se muestra, nunca bloquea;
 * el abono se registra contra el crédito que el usuario tocó.
 */
@Injectable({ providedIn: 'root' })
export class CuadernoService {
  private readonly api = inject(ApiService);

  clientes(skip: number, limit: number, consulta = ''): Observable<PagedList<ClienteConSaldo>> {
    const params: Record<string, string | number> = { skip, limit };
    const q = consulta.trim();
    if (q.length > 0) {
      params['q'] = q;
    }
    return this.api.get<PagedList<ClienteConSaldo>>('/clientes', params);
  }

  crearCliente(cliente: ClienteNuevo): Observable<ClienteConSaldo> {
    return this.api.post<ClienteConSaldo>('/clientes', cliente);
  }

  editarCliente(id: string, cambios: CambiosDeCliente): Observable<ClienteConSaldo> {
    return this.api.patch<ClienteConSaldo>(`/clientes/${id}`, cambios);
  }

  /** `estado` null = el filtro por defecto del backend (vigente + vencido). */
  creditos(
    estado: string | null,
    skip: number,
    limit: number,
  ): Observable<PagedList<CreditoResumenSalida>> {
    const params: Record<string, string | number> = { skip, limit };
    if (estado) {
      params['estado'] = estado;
    }
    return this.api.get<PagedList<CreditoResumenSalida>>('/fiado/creditos', params);
  }

  credito(id: string): Observable<CreditoDetalleSalida> {
    return this.api.get<CreditoDetalleSalida>(`/fiado/creditos/${id}`);
  }

  /**
   * El total de vencidos para la tira de cobro (una página de un ítem: solo
   * importa `total`). Viaja silenciada: si falla, la tira no sale y ya está;
   * un aviso de error por un conteo de fondo sería ruido.
   */
  vencidos(): Observable<PagedList<CreditoResumenSalida>> {
    return this.api.get<PagedList<CreditoResumenSalida>>(
      '/fiado/creditos',
      { estado: 'vencido', skip: 0, limit: 1 },
      { context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true) },
    );
  }

  abonar(creditoId: string, abono: AbonoNuevo): Observable<AbonoSalida> {
    return this.api.post<AbonoSalida>(`/fiado/creditos/${creditoId}/abonos`, abono);
  }

  /** `null` explícito = sin fecha (y sin recordatorio, declarado en pantalla). */
  reprogramar(creditoId: string, fecha: string | null): Observable<CreditoResumenSalida> {
    return this.api.patch<CreditoResumenSalida>(`/fiado/creditos/${creditoId}`, {
      fecha_vencimiento: fecha,
    });
  }
}
