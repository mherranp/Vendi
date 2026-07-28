import { Injectable, inject } from '@angular/core';
import { ApiService } from 'data-access';
import { Observable } from 'rxjs';
import { ForecastSalida, PeriodoPyl, PyLSalida } from './contrato';

/** Cliente de reportes (ADR-006): cada número declara su fuente. */
@Injectable({ providedIn: 'root' })
export class NumerosService {
  private readonly api = inject(ApiService);

  pyl(periodo: PeriodoPyl): Observable<PyLSalida> {
    return this.api.get<PyLSalida>('/reportes/pyl', { periodo });
  }

  forecast(): Observable<ForecastSalida> {
    return this.api.get<ForecastSalida>('/reportes/forecast');
  }
}
