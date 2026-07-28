import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { TranslateModule } from '@ngx-translate/core';
import { formatearPesos } from 'domain';
import { LoadingSpinnerComponent, PageHeaderComponent } from 'ui-kit';
import { ForecastSalida, LineaDeDinero, PeriodoPyl, PyLSalida } from './contrato';
import { NumerosService } from './numeros.service';

/**
 * Mis números (ADR-006): el P&L del período y el forecast a 30 días.
 *
 * Dos reglas del ADR hechas pantalla: nada aquí pide datos nuevos al tendero
 * (todo sale de lo ya registrado), y cada bloque muestra sus `fuentes` —
 * «proyección explicada, no promesa». Las compras del período son línea
 * informativa que NO se resta del resultado, y la etiqueta lo dice.
 */
@Component({
  selector: 'vd-numeros',
  imports: [
    TranslateModule,
    MatButtonModule,
    MatButtonToggleModule,
    MatCardModule,
    PageHeaderComponent,
    LoadingSpinnerComponent,
  ],
  templateUrl: './numeros.component.html',
  styleUrl: './numeros.component.scss',
})
export class NumerosComponent {
  private readonly servicio = inject(NumerosService);

  readonly periodo = signal<PeriodoPyl>('dia');
  readonly pyl = signal<PyLSalida | null>(null);
  readonly forecast = signal<ForecastSalida | null>(null);
  readonly cargando = signal(true);
  readonly fallo = signal(false);

  readonly formatear = formatearPesos;

  /** Las líneas del P&L en el orden en que la tienda las cuenta. */
  readonly lineasPyl = computed<LineaDeDinero[]>(() => {
    const p = this.pyl();
    if (!p) {
      return [];
    }
    return [
      { clave: 'numeros.pyl.ventas_netas', centavos: p.ventas_netas_centavos },
      { clave: 'numeros.pyl.ventas_efectivo', centavos: p.ventas_efectivo_centavos },
      { clave: 'numeros.pyl.ventas_fiado', centavos: p.ventas_fiado_centavos },
      { clave: 'numeros.pyl.ventas_anuladas', centavos: p.ventas_anuladas_centavos },
      { clave: 'numeros.pyl.costo_vendido', centavos: p.costo_de_lo_vendido_centavos },
      { clave: 'numeros.pyl.margen_bruto', centavos: p.margen_bruto_centavos },
      { clave: 'numeros.pyl.ingresos_caja', centavos: p.ingresos_caja_centavos },
      { clave: 'numeros.pyl.egresos_caja', centavos: p.egresos_caja_centavos },
      { clave: 'numeros.pyl.compras', centavos: p.compras_proveedores_centavos },
      { clave: 'numeros.pyl.resultado', centavos: p.resultado_operativo_centavos },
    ];
  });

  readonly lineasForecast = computed<LineaDeDinero[]>(() => {
    const f = this.forecast();
    if (!f) {
      return [];
    }
    return [
      { clave: 'numeros.forecast.saldo_actual', centavos: f.saldo_actual_centavos },
      { clave: 'numeros.forecast.ventas', centavos: f.ventas_proyectadas_centavos },
      { clave: 'numeros.forecast.cobros', centavos: f.cobros_fiado_proyectados_centavos },
      { clave: 'numeros.forecast.egresos', centavos: f.egresos_proyectados_centavos },
      { clave: 'numeros.forecast.saldo_proyectado', centavos: f.saldo_proyectado_centavos },
    ];
  });

  constructor() {
    this.cargar();
  }

  cargar(): void {
    // Invalida cualquier `cambiarPeriodo` en vuelo: su respuesta ya es vieja.
    this.secuenciaPyl += 1;
    this.cargando.set(true);
    this.fallo.set(false);
    let pendientes = 2;
    const alTerminar = (error: boolean) => {
      pendientes -= 1;
      if (error) {
        this.fallo.set(true);
      }
      if (pendientes === 0) {
        this.cargando.set(false);
      }
    };
    this.servicio.pyl(this.periodo()).subscribe({
      next: (pyl) => {
        this.pyl.set(pyl);
        alTerminar(false);
      },
      error: () => alTerminar(true),
    });
    this.servicio.forecast().subscribe({
      next: (forecast) => {
        this.forecast.set(forecast);
        alTerminar(false);
      },
      error: () => alTerminar(true),
    });
  }

  /**
   * Secuencia de peticiones de P&L: crece con cada `cargar`/`cambiarPeriodo`
   * y una respuesta solo se aplica si sigue siendo la última — dos toques
   * rápidos del toggle no pueden dejar «Mes» pintado con datos de «Semana».
   */
  private secuenciaPyl = 0;

  cambiarPeriodo(periodo: PeriodoPyl): void {
    if (periodo === this.periodo()) {
      return;
    }
    this.periodo.set(periodo);
    const secuencia = ++this.secuenciaPyl;
    this.servicio.pyl(periodo).subscribe({
      next: (pyl) => {
        if (secuencia === this.secuenciaPyl) {
          this.pyl.set(pyl);
        }
      },
      error: () => {
        if (secuencia === this.secuenciaPyl) {
          this.fallo.set(true);
        }
      },
    });
  }

  /** Las fuentes como lista clave-valor, en el orden en que llegan. */
  fuentesDe(mapa: Record<string, string> | undefined): { nombre: string; texto: string }[] {
    return Object.entries(mapa ?? {}).map(([nombre, texto]) => ({ nombre, texto }));
  }
}
