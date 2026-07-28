import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { HasPermissionDirective } from 'auth';
import { formatearPesos } from 'domain';
import { LoadingSpinnerComponent, StatusBadgeComponent, VarianteEstado } from 'ui-kit';
import {
  AbonoDialogoComponent,
  DatosAbonoDialogo,
  ResultadoAbono,
} from './abono-dialogo.component';
import { CreditoDetalleSalida } from './contrato';
import { CuadernoService } from './cuaderno.service';

/**
 * La pantalla del fiado (ADR-022): su historial de pagos, el cobro por
 * WhatsApp con el `wa.me` prearmado del backend (null sin teléfono) y la
 * reprogramación del vencimiento — `null` explícito es «sin fecha», y la
 * pantalla lo declara: sin fecha no hay recordatorio.
 */
@Component({
  selector: 'vd-credito-detalle',
  imports: [
    TranslateModule,
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    HasPermissionDirective,
    LoadingSpinnerComponent,
    StatusBadgeComponent,
  ],
  templateUrl: './credito-detalle.component.html',
  styleUrl: './credito-detalle.component.scss',
})
export class CreditoDetalleComponent {
  private readonly servicio = inject(CuadernoService);
  private readonly dialogos = inject(MatDialog);
  private readonly ruta = inject(ActivatedRoute);

  readonly credito = signal<CreditoDetalleSalida | null>(null);
  readonly cargando = signal(true);
  readonly fallo = signal(false);
  /** Nueva fecha del input tipo date (`YYYY-MM-DD`); vacío = sin cambiar. */
  readonly nuevaFecha = signal('');
  private readonly dialogoAbierto = signal(false);

  readonly formatear = formatearPesos;
  private readonly id = this.ruta.snapshot.paramMap.get('id') ?? '';

  constructor() {
    this.cargar();
  }

  cargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    this.servicio.credito(this.id).subscribe({
      next: (credito) => {
        this.credito.set(credito);
        this.nuevaFecha.set(credito.fecha_vencimiento ?? '');
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.fallo.set(true);
      },
    });
  }

  registrarAbono(): void {
    const credito = this.credito();
    if (!credito || this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    // El id se genera AL ABRIR: el reenvío del mismo abono es el no-op
    // idempotente del servidor, no un doble cobro (decisión 7).
    const id = crypto.randomUUID();
    const datos: DatosAbonoDialogo = { saldoPendiente: credito.saldo_pendiente };
    this.dialogos
      .open<AbonoDialogoComponent, DatosAbonoDialogo, ResultadoAbono | undefined>(
        AbonoDialogoComponent,
        { data: datos, width: '32rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.servicio.abonar(credito.id, { id, ...resultado }).subscribe({
          next: () => this.cargar(),
          // 422 abono_excede_saldo, 409 credito_no_abonable o
          // caja_sin_sesion_abierta: el interceptor ya mostró el mensaje del
          // backend; no hay nada que la pantalla pueda corregir sola.
          error: () => undefined,
        });
      });
  }

  guardarVencimiento(): void {
    const fecha = this.nuevaFecha().trim();
    if (!fecha) {
      return;
    }
    this.servicio.reprogramar(this.id, fecha).subscribe({
      next: () => this.cargar(),
      error: () => undefined,
    });
  }

  quitarVencimiento(): void {
    this.servicio.reprogramar(this.id, null).subscribe({
      next: () => this.cargar(),
      error: () => undefined,
    });
  }

  varianteDeEstado(estado: string): VarianteEstado {
    switch (estado) {
      case 'vencido':
        return 'peligro';
      case 'vigente':
        return 'info';
      case 'saldado':
        return 'exito';
      default:
        return 'neutro';
    }
  }

  /**
   * `dd/MM/yyyy` a partir del ISO del servidor. No se usa `DatePipe`: un pipe
   * de `@angular/common` en una feature perezosa obliga a retener el módulo
   * común (~10 kB) en el chunk inicial, que ya va apretado de budget.
   */
  fechaDeAbono(iso: string | null | undefined): string {
    const [anio, mes, dia] = (iso ?? '').slice(0, 10).split('-');
    return anio && mes && dia ? `${dia}/${mes}/${anio}` : '';
  }
}
