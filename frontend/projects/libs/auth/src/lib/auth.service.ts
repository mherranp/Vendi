import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FeatureFlagsService } from 'data-access';
import type { UserProfile } from 'domain';
import Keycloak from 'keycloak-js';
import { Subscription, timer } from 'rxjs';
import { VendiTokenParsed, aliasDeOrganizaciones, rolesDeRealm } from './token';

// Programación del refresco (valores conservadores, ajustables):
const RETRASO_MINIMO_MS = 5_000; // nunca antes de 5 segundos
const RETRASO_MAXIMO_MS = 300_000; // nunca después de 5 minutos
const VALIDEZ_MINIMA_SEG = 60; // se refresca cuando quedan ≤60s de validez

/**
 * Scope que piden **siempre** las cuatro apps.
 *
 * No es configurable a propósito. Medido en el informe de verificación de
 * Organizations (Pregunta 3): con el usuario en **dos** organizaciones, pedir
 * `organization` a secas —o no pedir nada y confiar en que va como default
 * client scope— devuelve el claim **ausente**. Solo `organization:*` trae
 * todas. Dejarlo como parámetro por app es garantizar que alguna se olvide y
 * que el segundo negocio del mismo dueño deje de funcionar sin ruido.
 */
export const SCOPE_ORGANIZACIONES = 'organization:*';

export interface ConfiguracionAuth {
  url: string;
  realm: string;
  clientId: string;
  onLoad?: 'login-required' | 'check-sso';
}

/**
 * Sesión de Keycloak como señales.
 *
 * Cosechado de `ui-core/src/lib/auth/auth.service.ts` de BaseSaaS. Se mantienen
 * intactos los dos candados que allí ya estaban resueltos y que son fáciles de
 * romper al reescribir: el guard de refresco re-entrante y el guard de logout
 * doble.
 *
 * Lo que cambia es la resolución del tenant: BaseSaaS leía del token un slug
 * de tenant (tenía un realm por tenant); Vendi lee el claim `organization` de
 * un realm único, cuyo alias es el `tenant_id`.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly destroyRef = inject(DestroyRef);
  // Las banderas de funcionalidad son "del tenant activo" y `data-access` no
  // puede conocer la sesión (ADR-011). Desde aquí sí se ve el cambio de tenant,
  // así que aquí es donde se invalida su caché.
  private readonly banderas = inject(FeatureFlagsService);

  private keycloak: Keycloak | null = null;

  // Guard de re-entrada del refresco: si `updateToken(60)` tarda más que el
  // intervalo, el siguiente tick correría contra el que está en vuelo y podría
  // pisar `_token.set(...)` con un valor viejo (o abrir dos llamadas
  // simultáneas a Keycloak sobre la misma sesión).
  private refrescando = false;
  // `logout()` acaba navegando fuera, pero la redirección es asíncrona
  // (keycloak-js construye la URL y asigna `window.location`). Una ráfaga de
  // fallos en ticks consecutivos podría llamarlo dos veces.
  private cerrandoSesion = false;

  private _suscripcionRefresco: Subscription | null = null;

  private readonly _authenticated = signal(false);
  private readonly _user = signal<UserProfile | null>(null);
  private readonly _token = signal<string>('');
  private readonly _organizaciones = signal<string[]>([]);
  private readonly _seleccion = signal<string | null>(null);
  // Fuente única de los roles: el token vigente, releído en cada refresco.
  // Antes había dos autoridades —`_user().roles`, congelado en el perfil que se
  // leyó en `init()`, y `tokenParsed` que sí leía `hasPermission()`— así que
  // tras un refresco que cambiara los roles, `roleGuard` y `*vdHasPermission`
  // podían decidir distinto sobre el mismo permiso.
  private readonly _roles = signal<string[]>([]);

  readonly authenticated = this._authenticated.asReadonly();
  readonly user = this._user.asReadonly();
  readonly token = this._token.asReadonly();

  /** Alias (= `tenant_id`) de todas las organizaciones del token. */
  readonly organizaciones = this._organizaciones.asReadonly();

  /**
   * Tenant activo.
   *
   * - Una sola organización → esa, sin que nadie elija.
   * - Ninguna → `null` (usuario de plataforma, o token sin el scope correcto).
   * - Varias → `null` **hasta** que se llame a `selectTenant(alias)`. Elegir
   *   por su cuenta "la primera" sería adivinar con qué negocio quiere trabajar
   *   el dueño, y adivinar en algo que decide qué datos se ven no es aceptable.
   */
  readonly tenantId = computed<string | null>(() => {
    const seleccion = this._seleccion();
    if (seleccion) {
      return seleccion;
    }
    const orgs = this._organizaciones();
    return orgs.length === 1 ? orgs[0] : null;
  });

  /** Roles de realm del token vigente. */
  readonly roles = this._roles.asReadonly();

  /** `true` cuando el usuario pertenece a más de un negocio y debe elegir. */
  readonly requiereSeleccionDeTenant = computed(
    () => this._organizaciones().length > 1 && this._seleccion() === null,
  );

  readonly displayName = computed(() => {
    const u = this._user();
    if (!u) return '';
    return `${u.firstName} ${u.lastName}`.trim() || u.username;
  });

  async init(config: ConfiguracionAuth): Promise<boolean> {
    this.keycloak = new Keycloak({
      url: config.url,
      realm: config.realm,
      clientId: config.clientId,
    });

    const autenticado = await this.keycloak.init({
      onLoad: config.onLoad || 'login-required',
      pkceMethod: 'S256',
      checkLoginIframe: false,
      // Ver SCOPE_ORGANIZACIONES: sin esto, un usuario con dos negocios llega
      // sin claim `organization` y se queda sin tenant.
      scope: SCOPE_ORGANIZACIONES,
    });

    if (autenticado) {
      this._authenticated.set(true);
      this._token.set(this.keycloak.token || '');
      this.leerDelToken();
      await this.cargarPerfil();
      this.programarSiguienteRefresco();
    }

    return autenticado;
  }

  /**
   * Fija el tenant activo entre los del token.
   *
   * Solo acepta un alias que **venga en el propio token**: la selección es una
   * preferencia de interfaz, no una credencial. Así la cabecera `X-Tenant-Id`
   * nunca puede llevar un tenant que el usuario no tenga, ni siquiera si un
   * componente le pasa un valor arbitrario. El backend, además, resuelve el
   * tenant del token y no confía en la cabecera.
   *
   * @returns `true` si se aplicó; `false` si el alias no pertenece al usuario.
   */
  selectTenant(alias: string): boolean {
    if (!this._organizaciones().includes(alias)) {
      console.error(
        `[auth] Se intentó seleccionar el tenant "${alias}", que no está en el token del usuario. Selección ignorada.`,
      );
      return false;
    }
    const anterior = this.tenantId();
    this._seleccion.set(alias);
    this.invalidarCachesPorTenant(anterior);
    return true;
  }

  /** Deshace la selección explícita (volver al selector de negocio). */
  limpiarSeleccionDeTenant(): void {
    const anterior = this.tenantId();
    this._seleccion.set(null);
    this.invalidarCachesPorTenant(anterior);
  }

  /**
   * Tira todo lo cacheado que dependa del tenant si el tenant efectivo cambió.
   *
   * Se llama en los tres puntos que pueden moverlo: `selectTenant()`,
   * `limpiarSeleccionDeTenant()` y la relectura del token tras un refresco (una
   * baja de negocio descarta la selección). Sin esto, un dueño con dos negocios
   * que cambiara de uno a otro seguía viendo las banderas del anterior, sin
   * petición HTTP nueva y sin ninguna señal de que algo iba mal.
   */
  private invalidarCachesPorTenant(anterior: string | null): void {
    if (this.tenantId() === anterior) {
      return;
    }
    this.banderas.invalidar();
  }

  hasRole(rol: string): boolean {
    return this.roles().includes(rol);
  }

  hasAnyRole(...roles: string[]): boolean {
    const propios = this.roles();
    return roles.some((r) => propios.includes(r));
  }

  /**
   * ¿El usuario tiene el permiso indicado?
   *
   * Los permisos viajan como roles de realm. `*` es el comodín de plataforma.
   * A diferencia de BaseSaaS **no** se honra ningún `is_superuser` del token:
   * ese claim no existe en el realm `vendi-co`, y dejar el atajo escrito
   * invitaría a inventarlo.
   */
  hasPermission(permiso: string): boolean {
    // Misma fuente que `hasRole()`/`hasAnyRole()`: `_roles`, que se resiembra
    // del token en cada refresco. Que este método leyera `tokenParsed` y los
    // otros dos el perfil congelado era precisamente la incoherencia.
    const roles = this.roles();
    return roles.includes('*') || roles.includes(permiso);
  }

  login(): void {
    // Sin `scope` explícito: keycloak-js aplica el de `init()`
    // (`KeycloakInitOptions.scope` es el scope por defecto del endpoint de
    // login), y pasarlo dos veces solo abriría la puerta a que diverjan.
    this.keycloak?.login();
  }

  logout(): void {
    // Idempotente: la redirección de Keycloak es asíncrona, así que una ráfaga
    // de fallos de refresco podría reentrar antes de que el navegador navegue.
    if (this.cerrandoSesion) return;
    this.cerrandoSesion = true;
    this.keycloak?.logout({ redirectUri: window.location.origin });
  }

  getToken(): string {
    return this._token();
  }

  /**
   * Resiembra del token todo lo que decide autorización: roles y organizaciones.
   * Se llama en `init()` y en cada refresco efectivo.
   */
  private leerDelToken(): void {
    const parsed = this.keycloak?.tokenParsed as VendiTokenParsed | undefined;
    this._roles.set(rolesDeRealm(parsed));
    const alias = aliasDeOrganizaciones(parsed?.organization);
    this._organizaciones.set(alias);
    // Si la selección previa ya no está en el token (el dueño dejó de ser
    // miembro de ese negocio), se descarta en vez de arrastrarla.
    const seleccion = this._seleccion();
    if (seleccion && !alias.includes(seleccion)) {
      this._seleccion.set(null);
    }
  }

  private async cargarPerfil(): Promise<void> {
    if (!this.keycloak) return;

    try {
      const perfil = await this.keycloak.loadUserProfile();
      const parsed = this.keycloak.tokenParsed as VendiTokenParsed | undefined;

      this._user.set({
        id: parsed?.sub || '',
        username: perfil.username || '',
        email: perfil.email || '',
        firstName: perfil.firstName || '',
        lastName: perfil.lastName || '',
        roles: this.roles(),
        tenantId: this.tenantId(),
      });
    } catch (error) {
      console.error('No se pudo cargar el perfil del usuario', error);
    }
  }

  private programarSiguienteRefresco(): void {
    this._suscripcionRefresco?.unsubscribe();
    const token = this.keycloak?.tokenParsed as VendiTokenParsed | undefined;
    if (!token?.exp) return;
    const expiraEnMs = token.exp * 1000 - Date.now();
    let retraso = expiraEnMs - VALIDEZ_MINIMA_SEG * 1000;
    retraso = Math.max(RETRASO_MINIMO_MS, Math.min(RETRASO_MAXIMO_MS, retraso));
    this._suscripcionRefresco = timer(retraso)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        void this.refrescar();
      });
  }

  /**
   * Fuerza un refresco del token.
   *
   * Se expone además de programarse sola porque la app móvil la necesita al
   * volver de segundo plano: el temporizador de `rxjs` no corre mientras el
   * WebView está suspendido, así que al reanudar puede haber un token vencido.
   *
   * Es re-entrante-segura: si ya hay un refresco en vuelo, no lanza otro.
   */
  async refrescar(): Promise<void> {
    if (!this.keycloak || this.refrescando) return;
    this.refrescando = true;
    try {
      const tenantAntesDelRefresco = this.tenantId();
      const refrescado = await this.keycloak.updateToken(VALIDEZ_MINIMA_SEG);
      if (refrescado) {
        this._token.set(this.keycloak.token || '');
        // Las organizaciones pueden haber cambiado entre tokens (alta o baja
        // de un negocio). Releerlas es barato y evita operar con un tenant que
        // ya no está en el token.
        this.leerDelToken();
        this.invalidarCachesPorTenant(tenantAntesDelRefresco);
        // `_user` es una foto del perfil; se rearma con lo que acaba de salir
        // del token nuevo para que no quede como segunda fuente de verdad.
        this._user.update((u) =>
          u ? { ...u, roles: this.roles(), tenantId: this.tenantId() } : u,
        );
      }
      // Se reprograma siempre: aunque este tick no refrescara, hay que fijar la
      // siguiente comprobación según la expiración vigente.
      this.programarSiguienteRefresco();
    } catch (err) {
      console.error('Falló el refresco del token', err);
      this.logout();
    } finally {
      this.refrescando = false;
    }
  }
}
