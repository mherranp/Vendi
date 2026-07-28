import { HttpErrorResponse } from '@angular/common/http';
import { Component, TemplateRef, computed, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { PageEvent } from '@angular/material/paginator';
import { TranslateModule } from '@ngx-translate/core';
import { AuthService, HasPermissionDirective } from 'auth';
import { formatearPesos } from 'domain';
import {
  LoadingSpinnerComponent,
  PageHeaderComponent,
  StatusBadgeComponent,
  VarianteEstado,
} from 'ui-kit';
import { ColumnaTabla, DataTableComponent } from 'ui-kit/data-table';
import { CajaService } from './caja.service';
import { CerrarCajaDialogoComponent, DatosCerrarCaja } from './cerrar-caja-dialogo.component';
import { ArqueoConDesglose, ArqueoSalida, MovimientoSalida, SesionActualSalida } from './contrato';
import { MovimientoDialogoComponent, ResultadoMovimiento } from './movimiento-dialogo.component';

const TAMANO_PAGINA = 10;

/** Fila del historial: el arqueo más una clave fantasma para la diferencia. */
interface FilaArqueo extends ArqueoSalida {
  acciones?: never;
}

/**
 * Mi caja: la sesión del día, sus movimientos manuales y el arqueo.
 *
 * Lo que cada rol ve lo decide primero el backend: al cajero le llega
 * `efectivo_esperado: null` y un 403 si pide el historial; la pantalla solo
 * se lo ahorra (ADR-023). Quien cierra ve la cuenta completa: el esperado
 * vivo, el cierre con su diferencia y el historial congelado de arqueos.
 */
@Component({
  selector: 'vd-mi-caja',
  imports: [
    TranslateModule,
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatInputModule,
    HasPermissionDirective,
    PageHeaderComponent,
    LoadingSpinnerComponent,
    DataTableComponent,
    StatusBadgeComponent,
  ],
  templateUrl: './mi-caja.component.html',
  styleUrl: './mi-caja.component.scss',
})
export class MiCajaComponent {
  private readonly servicio = inject(CajaService);
  private readonly dialogos = inject(MatDialog);
  private readonly auth = inject(AuthService);

  /** null = no hay sesión abierta (el 404 silenciado del servicio). */
  readonly sesion = signal<SesionActualSalida | null>(null);
  readonly cargando = signal(true);
  readonly fallo = signal(false);

  /** Formulario de apertura (inline): la base en pesos y el id idempotente. */
  readonly basePesos = signal<number | null>(null);
  readonly idApertura = signal(crypto.randomUUID());
  readonly abriendo = signal(false);

  readonly movimientos = signal<MovimientoSalida[]>([]);
  readonly totalMovimientos = signal(0);
  readonly indiceMovimientos = signal(0);
  readonly cargandoMovimientos = signal(false);

  /** El arqueo recién hecho: la pantalla lo muestra hasta la próxima carga. */
  readonly arqueo = signal<ArqueoConDesglose | null>(null);

  readonly historial = signal<FilaArqueo[]>([]);
  readonly totalHistorial = signal(0);
  readonly indiceHistorial = signal(0);
  readonly cargandoHistorial = signal(false);

  readonly formatear = formatearPesos;
  readonly dialogoAbierto = signal(false);

  private readonly plantillaMonto =
    viewChild<TemplateRef<{ $implicit: MovimientoSalida }>>('celdaMonto');

  private readonly plantillaEsperado =
    viewChild<TemplateRef<{ $implicit: FilaArqueo }>>('celdaEsperado');

  private readonly plantillaContado =
    viewChild<TemplateRef<{ $implicit: FilaArqueo }>>('celdaContado');

  private readonly plantillaDiferencia =
    viewChild<TemplateRef<{ $implicit: FilaArqueo }>>('celdaDiferencia');

  readonly columnasMovimientos = computed<ColumnaTabla<MovimientoSalida>[]>(() => [
    { clave: 'created_at', etiqueta: 'caja.movimientos.columna.fecha' },
    { clave: 'tipo', etiqueta: 'caja.movimientos.columna.tipo' },
    { clave: 'categoria', etiqueta: 'caja.movimientos.columna.categoria' },
    { clave: 'motivo', etiqueta: 'caja.movimientos.columna.motivo' },
    {
      clave: 'monto',
      etiqueta: 'caja.movimientos.columna.monto',
      plantilla: this.plantillaMonto(),
      ancho: '8rem',
    },
  ]);

  readonly columnasHistorial = computed<ColumnaTabla<FilaArqueo>[]>(() => [
    { clave: 'abierta_en', etiqueta: 'caja.historial.abierta' },
    { clave: 'cerrada_por', etiqueta: 'caja.historial.cerrada_por' },
    {
      clave: 'efectivo_esperado',
      etiqueta: 'caja.historial.esperado',
      plantilla: this.plantillaEsperado(),
    },
    {
      clave: 'efectivo_contado',
      etiqueta: 'caja.historial.contado',
      plantilla: this.plantillaContado(),
    },
    {
      clave: 'acciones',
      etiqueta: 'caja.historial.diferencia',
      plantilla: this.plantillaDiferencia(),
      ancho: '8rem',
    },
  ]);

  constructor() {
    this.cargar();
  }

  cargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    this.servicio.sesionActual().subscribe({
      next: (sesion) => {
        this.sesion.set(sesion);
        this.cargando.set(false);
        if (sesion) {
          this.cargarMovimientos();
        }
        // El historial es de quien cierra, haya o no sesión abierta hoy.
        this.cargarHistorial();
      },
      error: () => {
        // El 404 ya es null en el servicio; llegar aquí es fallo de verdad.
        this.cargando.set(false);
        this.fallo.set(true);
      },
    });
  }

  abrirCaja(): void {
    const pesos = this.basePesos();
    if (this.abriendo() || pesos === null || pesos < 0) {
      return;
    }
    this.abriendo.set(true);
    this.servicio.abrir(this.idApertura(), Math.round(pesos * 100)).subscribe({
      next: () => this.recargarEstado(),
      error: (error: unknown) => {
        this.abriendo.set(false);
        // Otra caja abrió primero: la verdad está en el servidor, no aquí.
        if (codigoDe(error) === 'caja_ya_abierta') {
          this.recargarEstado();
        }
      },
    });
  }

  registrarMovimiento(): void {
    const sesion = this.sesion();
    if (!sesion || this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    // El id se genera AL ABRIR: el reenvío del mismo formulario es el no-op
    // idempotente del servidor, no un movimiento duplicado (decisión 7).
    const id = crypto.randomUUID();
    this.dialogos
      .open<MovimientoDialogoComponent, never, ResultadoMovimiento | undefined>(
        MovimientoDialogoComponent,
        { width: '32rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargandoMovimientos.set(true);
        this.servicio
          .registrarMovimiento({
            id,
            tipo: resultado.tipo,
            categoria: resultado.categoria,
            monto: resultado.montoCentavos,
            motivo: resultado.motivo,
          })
          .subscribe({
            next: () => {
              this.cargarMovimientos();
              this.refrescarSesion();
            },
            error: () => this.cargandoMovimientos.set(false),
          });
      });
  }

  cerrarCaja(): void {
    const sesion = this.sesion();
    if (!sesion || this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const datos: DatosCerrarCaja = { esperado: sesion.efectivo_esperado ?? null };
    this.dialogos
      .open<CerrarCajaDialogoComponent, DatosCerrarCaja, number | undefined>(
        CerrarCajaDialogoComponent,
        { data: datos, width: '32rem' },
      )
      .afterClosed()
      .subscribe((contado) => {
        this.dialogoAbierto.set(false);
        if (contado === undefined) {
          return;
        }
        this.servicio.cerrar(sesion.id, contado).subscribe({
          next: (arqueo) => {
            this.arqueo.set(arqueo);
            this.sesion.set(null);
            this.movimientos.set([]);
            this.totalMovimientos.set(0);
            this.idApertura.set(crypto.randomUUID());
            this.cargarHistorial();
          },
          error: (error: unknown) => {
            // Ya estaba cerrada (doble clic entre pestañas): refrescar.
            if (codigoDe(error) === 'caja_ya_cerrada') {
              this.recargarEstado();
            }
          },
        });
      });
  }

  alPaginarMovimientos(evento: PageEvent): void {
    this.indiceMovimientos.set(evento.pageIndex);
    this.cargarMovimientos();
  }

  alPaginarHistorial(evento: PageEvent): void {
    this.indiceHistorial.set(evento.pageIndex);
    this.cargarHistorial();
  }

  varianteDiferencia(diferencia: number | null | undefined): VarianteEstado {
    return diferencia ? 'peligro' : 'exito';
  }

  textoDiferencia(diferencia: number | null | undefined): string {
    if (diferencia === null || diferencia === undefined) {
      return '—';
    }
    const signo = diferencia < 0 ? '-' : '';
    return `${signo}${this.formatear(Math.abs(diferencia))}`;
  }

  textoMonto(movimiento: MovimientoSalida): string {
    const signo = movimiento.tipo === 'egreso' ? '-' : '';
    return `${signo}${this.formatear(movimiento.monto)}`;
  }

  private cargarMovimientos(): void {
    const sesion = this.sesion();
    if (!sesion) {
      return;
    }
    this.cargandoMovimientos.set(true);
    this.servicio
      .movimientos(sesion.id, this.indiceMovimientos() * TAMANO_PAGINA, TAMANO_PAGINA)
      .subscribe({
        next: (pagina) => {
          this.movimientos.set(pagina.items);
          this.totalMovimientos.set(pagina.total);
          this.cargandoMovimientos.set(false);
        },
        error: () => this.cargandoMovimientos.set(false),
      });
  }

  private cargarHistorial(): void {
    // Sin `caja:cerrar` el backend responde 403: ni se pide (decisión 4). La
    // directiva oculta la sección; esta guarda evita la petición huérfana.
    if (!this.auth.hasPermission('caja:cerrar')) {
      return;
    }
    this.cargandoHistorial.set(true);
    this.servicio.historial(this.indiceHistorial() * TAMANO_PAGINA, TAMANO_PAGINA).subscribe({
      next: (pagina) => {
        this.historial.set(pagina.items);
        this.totalHistorial.set(pagina.total);
        this.cargandoHistorial.set(false);
      },
      error: () => this.cargandoHistorial.set(false),
    });
  }

  /** Recarga sesión + tablas tras una escritura (el esperado vivo cambia). */
  private recargarEstado(): void {
    this.abriendo.set(false);
    this.cargar();
  }

  private refrescarSesion(): void {
    this.servicio.sesionActual().subscribe({
      next: (sesion) => this.sesion.set(sesion),
      error: () => undefined,
    });
  }
}

/** El `code` estable del sobre de error del backend (decisión 8 del plan). */
function codigoDe(error: unknown): string | null {
  if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
    const codigo = (error.error as { code?: unknown }).code;
    return typeof codigo === 'string' ? codigo : null;
  }
  return null;
}
