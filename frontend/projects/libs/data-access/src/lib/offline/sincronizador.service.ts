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
 *  - Tras CADA drenado se programa el próximo intento de lo que quedó
 *    pendiente (BUG-C del QA): ninguna pendiente con espera queda huérfana de
 *    temporizador. Y una operación que el servidor OMITE de `resultados`
 *    (fuera de contrato) se marca dead-letter visible: jamás `enviando`
 *    eterna.
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
  private fallosRegistro = 0;
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
      let dispositivoId: string;
      try {
        dispositivoId = await this.dispositivos.asegurarRegistro();
        this.fallosRegistro = 0;
      } catch (error) {
        // BUG-D del QA: un registro que falla sin red con pendientes frescas
        // (`proximo_intento_en = 0`) armaba un setTimeout(0) — el mínimo crudo
        // de la cola — y martilleaba el registro 102 veces en 100 ms (medido
        // con fake timers): CPU, batería y red quemados sin que `intentos`
        // crezca jamás. El reintento del registro lleva SU PROPIO backoff,
        // con el mismo patrón exponencial de los lotes.
        this.fallosRegistro += 1;
        console.warn('El registro del dispositivo se pospone.', error);
        this.programarReintento(Date.now() + esperaDeReintento(this.fallosRegistro));
        return;
      }
      let quedanPorDrenar = true;
      while (quedanPorDrenar) {
        quedanPorDrenar = await this.drenarLote(dispositivoId);
      }
      // BUG-C del QA: un drenado parcial exitoso dejaba pendientes con
      // `proximo_intento_en` futuro SIN temporizador (el backoff solo se
      // armaba con la cola vacía o al reventar el transporte), y esa operación
      // no subía sola jamás. Al salir del while se programa SIEMPRE: si no
      // queda nada, `proximaPendiente` devuelve null y no pasa nada.
      this.programarReintento();
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
        porId.delete(resultado.id);
        if (resultado.resultado === 'aceptada' || resultado.resultado === 'duplicada') {
          await this.db.cola_sync.delete(operacion.id);
        } else {
          await this.db.cola_sync.update(operacion.id, {
            estado: 'error',
            ultimo_error: resultado.motivo ?? 'rechazada_sin_motivo',
          });
        }
      }
      // Defensa ante un servidor FUERA DE CONTRATO: una operación que no
      // viene en `resultados` no puede quedar `enviando` para siempre —
      // invisible para los contadores, congelada en caliente hasta el próximo
      // arranque. Se marca dead-letter visible con su motivo.
      for (const omitida of porId.values()) {
        await this.db.cola_sync.update(omitida.id, {
          estado: 'error',
          ultimo_error: 'omitida_en_resultados',
        });
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

  /**
   * Programa el próximo drenado para la pendiente más próxima, si la hay.
   * `noAntesDe` es el piso del backoff propio del registro (BUG-D): sin red,
   * la pendiente más próxima es 0 y sin ese piso el registro se martillea.
   */
  private programarReintento(noAntesDe: number | null = null): void {
    if (this.temporizador) {
      return;
    }
    void this.proximaPendiente()
      .then((instante) => {
        if (instante === null) {
          return;
        }
        const objetivo = noAntesDe === null ? instante : Math.max(instante, noAntesDe);
        this.temporizador = setTimeout(
          () => {
            this.temporizador = null;
            void this.sincronizar();
          },
          Math.max(0, objetivo - Date.now()),
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
