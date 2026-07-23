import { HttpContext } from '@angular/common/http';
import { Injectable, Signal, computed, inject, signal } from '@angular/core';
import { Observable, catchError, of, shareReplay, tap } from 'rxjs';
import { ApiService } from '../api.service';
import { SILENCIAR_AVISO_ERROR } from '../interceptors/error.interceptor';

/**
 * Caché de banderas de funcionalidad del tenant activo, como señal.
 *
 * Cosechado de `ui-core/src/lib/services/feature-flags.service.ts` con un solo
 * cambio de fondo: la petición viaja con `SILENCIAR_AVISO_ERROR`. En Fase 0 el
 * módulo `feature_flags` del backend **no existe** (queda como backlog en
 * `docs/ARCHITECTURE.md`), así que `/tenant/features` responde 404; sin
 * silenciarlo, cada arranque le enseñaría al usuario un aviso de error por una
 * llamada que a él no le importa.
 *
 * El fallo es cerrado: ante cualquier error el mapa queda vacío y toda bandera
 * se lee como desactivada. Nunca se habilita una funcionalidad por no poder
 * consultarla.
 */
@Injectable({ providedIn: 'root' })
export class FeatureFlagsService {
  private readonly api = inject(ApiService);

  private readonly _flags = signal<Record<string, boolean>>({});
  private readonly _cargado = signal(false);
  private _enVuelo$?: Observable<Record<string, boolean>>;

  /** Mapa reactivo `{clave: habilitada}`. Vacío hasta que `cargar()` resuelve. */
  readonly flags: Signal<Record<string, boolean>> = this._flags.asReadonly();
  /** `true` cuando ya se intentó cargar el catálogo (con éxito o sin él). */
  readonly cargado = this._cargado.asReadonly();

  /**
   * Lanza (o reutiliza) la única petición en vuelo. Es seguro llamarla desde
   * cada consumidor: los siguientes se suscriben al resultado cacheado.
   */
  cargar(): Observable<Record<string, boolean>> {
    if (this._enVuelo$) {
      return this._enVuelo$;
    }
    this._enVuelo$ = this.api
      .get<Record<string, boolean>>('/tenant/features', undefined, {
        context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true),
      })
      .pipe(
        tap((mapa) => {
          this._flags.set(mapa ?? {});
          this._cargado.set(true);
        }),
        catchError(() => {
          this._cargado.set(true);
          return of({} as Record<string, boolean>);
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    return this._enVuelo$;
  }

  /** Selector calculado, cómodo para enlazar en plantilla. */
  habilitada(clave: string): Signal<boolean> {
    return computed(() => !!this._flags()[clave]);
  }

  /** Lectura síncrona; solo es fiable después de que `cargado()` sea `true`. */
  estaHabilitada(clave: string): boolean {
    return !!this._flags()[clave];
  }

  /** Fuerza una recarga: descarta el observable cacheado. */
  recargar(): Observable<Record<string, boolean>> {
    this.invalidar();
    return this.cargar();
  }

  /**
   * Descarta la caché **sin** lanzar una petición nueva.
   *
   * Existe porque las banderas son "del tenant activo" y este servicio, por la
   * frontera de capas (ADR-011), no puede conocer la sesión: `data-access` no
   * importa `auth`. Sin esto, un dueño con dos negocios que llamara a
   * `selectTenant()` seguía leyendo indefinidamente las banderas del negocio
   * anterior, y sin ninguna petición HTTP que lo delatara. Quien sí sabe cuándo
   * cambia el tenant —`AuthService`— es quien tiene que invalidar; la dirección
   * auth → data-access sí está permitida.
   *
   * No recarga por su cuenta a propósito: tras cambiar de negocio la app suele
   * navegar, y la vista que necesite banderas llamará a `cargar()`. Hasta
   * entonces el mapa queda vacío, que es el fallo cerrado correcto (ninguna
   * funcionalidad habilitada por defecto).
   */
  invalidar(): void {
    this._enVuelo$ = undefined;
    this._flags.set({});
    this._cargado.set(false);
  }
}
