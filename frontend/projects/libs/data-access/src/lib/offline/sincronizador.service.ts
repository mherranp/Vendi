import { HttpContext } from '@angular/common/http';
import { Injectable, OnDestroy, inject, signal } from '@angular/core';
import { lastValueFrom } from 'rxjs';
import type { paths } from '../api-client';
import { ApiService } from '../api.service';
import { SILENCIAR_AVISO_ERROR } from '../interceptors/error.interceptor';
import { DispositivoService } from './dispositivo.service';
import type { OperacionEnCola } from './modelos-locales';
import { VendiDb } from './vendi.db';

type LoteSync = paths['/api/v1/sync/lotes']['post']['requestBody']['content']['application/json'];
type RespuestaLote =
  paths['/api/v1/sync/lotes']['post']['responses']['200']['content']['application/json'];

/** Tope del contrato: el lote acepta entre 1 y 200 operaciones. */
export const LOTE_MAXIMO = 200;
/** Backoff exponencial con tope (decisión 7 del plan): 5s, 10s, 20s, …, 5min. */
export const ESPERA_BASE_MS = 5_000;
export const ESPERA_MAXIMA_MS = 300_000;

export function esperaDeReintento(intentos: number): number {
  return Math.min(ESPERA_BASE_MS * 2 ** Math.max(0, intentos - 1), ESPERA_MAXIMA_MS);
}

/**
 * El motor de drenado de la cola (ADR-017).
 *
 * Reglas duras:
 *
 *  - FIFO por `secuencia`: el lote sale ordenado, porque la dependencia entre
 *    operaciones (`cliente.crear` antes que la venta fiada) es estructural.
 *  - La cola NUNCA se purga sin veredicto: una operación sale solo con
 *    `aceptada` o `duplicada`. La `rechazada` es dead-letter visible
 *    (decisión 5): queda en `error` con su motivo y no bloquea a las demás.
 *  - El backoff es por lote y ante fallo de transporte (red o 5xx): todas las
 *    operaciones del lote vuelven a `pendiente` con `intentos+1`. El reenvío
 *    es seguro porque el servidor es idempotente por PK (la re-aplicación
 *    responde `duplicada` y no re-emite eventos).
 *  - Los avisos globales de error se silencian en estas llamadas: la tienda
 *    no necesita un aviso por cada reintento de fondo; el estado lo da el
 *    contador de pendientes.
 */
@Injectable({ providedIn: 'root' })
export class SincronizadorService implements OnDestroy {
  private readonly db = inject(VendiDb);
  private readonly api = inject(ApiService);
  private readonly dispositivos = inject(DispositivoService);

  private readonly _pendientes = signal(0);
  readonly pendientes = this._pendientes.asReadonly();
  private readonly _enError = signal(0);
  readonly enError = this._enError.asReadonly();
  private readonly _sincronizando = signal(false);
  readonly sincronizando = this._sincronizando.asReadonly();

  private drenajeEnVuelo = false;
  private temporizador: ReturnType<typeof setTimeout> | null = null;
  private escuchando = false;

  /** Al destruir el inyector (apagar la app o el TestBed) no queda timer vivo. */
  ngOnDestroy(): void {
    if (this.temporizador) {
      clearTimeout(this.temporizador);
      this.temporizador = null;
    }
  }

  /** Dispara el drenado al volver la red. Idempotente (un solo listener). */
  escucharConectividad(): void {
    if (this.escuchando) {
      return;
    }
    this.escuchando = true;
    window.addEventListener('online', () => void this.sincronizar());
  }

  /** Cuenta pendientes y dead-letters para la barra del POS. */
  async refrescarContadores(): Promise<void> {
    this._pendientes.set(await this.db.cola_sync.where('estado').equals('pendiente').count());
    this._enError.set(await this.db.cola_sync.where('estado').equals('error').count());
  }

  /**
   * Las `enviando` huérfanas vuelven a `pendiente` (decisión 8): si la app
   * murió a mitad del drenado, el estado transitorio no es verdad — la cola
   * sí, y el reenvío es idempotente.
   */
  async recuperarEnviosInterrumpidos(): Promise<void> {
    await this.db.cola_sync.where('estado').equals('enviando').modify({ estado: 'pendiente' });
  }

  async sincronizar(): Promise<void> {
    if (this.drenajeEnVuelo) {
      return;
    }
    this.drenajeEnVuelo = true;
    this._sincronizando.set(true);
    try {
      const dispositivoId = await this.dispositivos.asegurarRegistro();
      let quedanPorDrenar = true;
      while (quedanPorDrenar) {
        quedanPorDrenar = await this.drenarLote(dispositivoId);
      }
    } catch (error) {
      // Sin red (en el registro o en el lote): se pospone con backoff y se
      // sigue vendiendo. La cola es la verdad; el aviso lo da el contador.
      console.warn('El drenado de la cola se pospone.', error);
      this.programarReintento();
    } finally {
      this.drenajeEnVuelo = false;
      this._sincronizando.set(false);
      await this.refrescarContadores().catch(() => {
        // La base se cerró (apagado de la app): no hay contadores que refrescar.
      });
    }
  }

  /** @returns `true` si pudo quedar otro lote detrás (este salió lleno). */
  private async drenarLote(dispositivoId: string): Promise<boolean> {
    const ahora = Date.now();
    const lote = (await this.db.cola_sync.where('estado').equals('pendiente').sortBy('secuencia'))
      .filter((op) => op.proximo_intento_en <= ahora)
      .slice(0, LOTE_MAXIMO);
    if (lote.length === 0) {
      this.programarReintento();
      return false;
    }

    await this.db.cola_sync
      .where('id')
      .anyOf(lote.map((op) => op.id))
      .modify({ estado: 'enviando' });

    const cuerpo: LoteSync = {
      dispositivo_id: dispositivoId,
      operaciones: lote.map(({ id, tipo, secuencia, datos }) => ({ id, tipo, secuencia, datos })),
    };

    try {
      const respuesta = await lastValueFrom(
        this.api.post<RespuestaLote>('/sync/lotes', cuerpo, {
          context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true),
        }),
      );
      await this.aplicarVeredictos(respuesta, lote);
    } catch (error) {
      await this.reprogramar(lote);
      throw error;
    }
    return lote.length === LOTE_MAXIMO;
  }

  private async aplicarVeredictos(
    respuesta: RespuestaLote,
    lote: OperacionEnCola[],
  ): Promise<void> {
    const porId = new Map(lote.map((op) => [op.id, op]));
    await this.db.transaction('rw', this.db.cola_sync, async () => {
      for (const resultado of respuesta.resultados) {
        const operacion = porId.get(resultado.id);
        if (!operacion) {
          // El servidor no inventa ids; si lo hiciera, no tocamos nada.
          continue;
        }
        if (resultado.resultado === 'aceptada' || resultado.resultado === 'duplicada') {
          await this.db.cola_sync.delete(operacion.id);
        } else {
          await this.db.cola_sync.update(operacion.id, {
            estado: 'error',
            ultimo_error: resultado.motivo ?? 'rechazada_sin_motivo',
          });
        }
      }
    });
  }

  private async reprogramar(lote: OperacionEnCola[]): Promise<void> {
    const ahora = Date.now();
    await this.db.transaction('rw', this.db.cola_sync, async () => {
      for (const operacion of lote) {
        const intentos = operacion.intentos + 1;
        await this.db.cola_sync.update(operacion.id, {
          estado: 'pendiente',
          intentos,
          proximo_intento_en: ahora + esperaDeReintento(intentos),
        });
      }
    });
  }

  /** Programa el próximo drenado para la pendiente más próxima, si la hay. */
  private programarReintento(): void {
    if (this.temporizador) {
      return;
    }
    void this.proximaPendiente()
      .then((instante) => {
        if (instante === null) {
          return;
        }
        this.temporizador = setTimeout(
          () => {
            this.temporizador = null;
            void this.sincronizar();
          },
          Math.max(0, instante - Date.now()),
        );
      })
      .catch(() => {
        // La base se cerró al apagar: el próximo disparador reprogramará.
      });
  }

  private async proximaPendiente(): Promise<number | null> {
    const pendientes = await this.db.cola_sync.where('estado').equals('pendiente').toArray();
    if (pendientes.length === 0) {
      return null;
    }
    return Math.min(...pendientes.map((op) => op.proximo_intento_en));
  }

  /** El botón manual del POS: adelanta las pendientes. Los dead-letters NO se reintentan (decisión 5). */
  async reintentar(): Promise<void> {
    await this.db.cola_sync
      .where('estado')
      .equals('pendiente')
      .modify({ proximo_intento_en: Date.now() });
    await this.sincronizar();
  }

  /** Lo llama el POS tras cada cobro: intento inmediato (si hay red, sube ya). */
  notificarVentaCobrada(): void {
    void this.refrescarContadores();
    void this.sincronizar();
  }
}
