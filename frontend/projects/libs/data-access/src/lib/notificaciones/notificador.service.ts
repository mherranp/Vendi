import { Injectable, computed, signal } from '@angular/core';

export type TipoDeAviso = 'exito' | 'info' | 'advertencia' | 'error';

export interface Aviso {
  id: string;
  tipo: TipoDeAviso;
  /** Texto ya traducido y listo para pintar. */
  mensaje: string;
  /** Milisegundos desde epoch en que se emitió. */
  instante: number;
}

/** Máximo de avisos retenidos: evita que una tormenta de errores crezca sin fin. */
const MAXIMO_AVISOS = 20;

/**
 * Cola de avisos para el usuario, como señal.
 *
 * Sustituye al `NotificationService` de BaseSaaS, que no se cosecha tal cual
 * por dos motivos:
 *
 *  1. Dependía de `WebSocketService`, que el plan excluye explícitamente de la
 *     cosecha (Tarea 3.12, Paso 1).
 *  2. Inyectaba `MatSnackBar`, es decir, metía Angular Material dentro de la
 *     capa HTTP. Aquí el servicio solo **acumula** avisos; quien los pinta es
 *     la app (un host de snackbar en su shell), de modo que `data-access` no
 *     conoce la UI y sigue siendo probable sin TestBed de Material.
 *
 * Una app que prefiera pintarlos con `MatSnackBar` sustituye la clase entera
 * por DI: `{ provide: Notificador, useClass: NotificadorConSnackBar }`.
 */
@Injectable({ providedIn: 'root' })
export class Notificador {
  private readonly _avisos = signal<Aviso[]>([]);

  /** Avisos vivos, del más reciente al más antiguo. */
  readonly avisos = this._avisos.asReadonly();

  /** Último aviso emitido, o `null` si no hay ninguno. */
  readonly ultimo = computed<Aviso | null>(() => this._avisos()[0] ?? null);

  exito(mensaje: string): void {
    this.emitir('exito', mensaje);
  }

  info(mensaje: string): void {
    this.emitir('info', mensaje);
  }

  advertencia(mensaje: string): void {
    this.emitir('advertencia', mensaje);
  }

  error(mensaje: string): void {
    this.emitir('error', mensaje);
  }

  /** Descarta un aviso concreto (el usuario lo cerró o expiró su temporizador). */
  descartar(id: string): void {
    this._avisos.update((previos) => previos.filter((a) => a.id !== id));
  }

  limpiar(): void {
    this._avisos.set([]);
  }

  private emitir(tipo: TipoDeAviso, mensaje: string): void {
    const aviso: Aviso = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      tipo,
      mensaje,
      instante: Date.now(),
    };
    this._avisos.update((previos) => [aviso, ...previos].slice(0, MAXIMO_AVISOS));
  }
}
