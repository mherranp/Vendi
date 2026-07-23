/**
 * Doble de pruebas de la clase `Keycloak` que exporta `keycloak-js`.
 *
 * Se enchufa en los specs con:
 *
 *     vi.mock('keycloak-js', () => ({ default: KeycloakFake }));
 *
 * El adaptador real abre un iframe, habla con el IdP, escucha mensajes y
 * arranca un temporizador: nada de eso puede correr en un test unitario. Este
 * doble sustituye cada método que `AuthService` toca por un equivalente
 * controlable, de modo que un spec pueda comprobar cosas como "si el refresco
 * falla, se cierra sesión" sin simular la red.
 *
 * Cosechado de BaseSaaS y adaptado al claim `organization`: el token por
 * defecto trae una organización cuyo alias es un UUID, que es lo que produce el
 * realm `vendi-co` (`alias = str(tenant_id)`).
 */
import type { KeycloakTokenParsed } from 'keycloak-js';
import type { ClaimOrganizacion, VendiTokenParsed } from './token';

export interface PerfilFalso {
  username?: string;
  email?: string;
  firstName?: string;
  lastName?: string;
}

/** Alias de organización usado por defecto en los tests. Es un UUID válido. */
export const ORG_POR_DEFECTO = '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e';

/**
 * Clase mínima compatible con Keycloak. Lleva contadores para que un spec
 * pueda afirmar `instancia.logoutCalls === 1`.
 */
export class KeycloakFake {
  /**
   * Última instancia construida.
   *
   * `AuthService` crea el `Keycloak` por dentro, así que un spec no tiene otra
   * forma de llegar a él. Guardarlo aquí evita que cada test tenga que envolver
   * el prototipo solo para capturar `this`.
   */
  static ultimaInstancia: KeycloakFake | undefined = undefined;

  // ---------- Superficie que lee AuthService ----------
  authenticated = false;
  token = '';
  tokenParsed: VendiTokenParsed | undefined = undefined;

  // ---------- Mandos del test ----------
  /** Lo que devuelve `init()`. `false` simula "el usuario no ha iniciado sesión". */
  initReturns = true;
  /** Error a lanzar desde `init()` (IdP inalcanzable). */
  initThrows: Error | null = null;
  /** Opciones con las que se llamó a `init()`, para poder afirmar el `scope`. */
  ultimasOpcionesDeInit: Record<string, unknown> | undefined = undefined;

  /** Lo que devuelve `updateToken()`: `true` = hubo refresco, `false` = seguía válido. */
  updateReturns = true;
  /** Error a lanzar desde `updateToken()` (dispara el logout de AuthService). */
  updateThrows: Error | null = null;
  /** Token que publica el doble tras un refresco con éxito. */
  nextToken = 'token-refrescado';
  /**
   * Si es `true`, `updateToken()` devuelve una promesa que **no** se resuelve
   * hasta que el spec llame a `resolverUpdatePendiente()`. Es lo que permite
   * comprobar el guard de refresco re-entrante.
   */
  updateManual = false;
  private resolverPendiente: ((v: boolean) => void) | null = null;

  /** Perfil que devuelve `loadUserProfile()`. */
  profile: PerfilFalso = {
    username: 'dueno',
    email: 'dueno@demo.vendi.co',
    firstName: 'Ana',
    lastName: 'Gómez',
  };

  // ---------- Contadores ----------
  initCalls = 0;
  loadProfileCalls = 0;
  updateCalls = 0;
  loginCalls = 0;
  logoutCalls = 0;

  /** Configuración con la que se construyó (url, realm, clientId). */
  readonly configuracion: unknown;

  /** Validez mínima con la que se llamó a `updateToken()` por última vez. */
  ultimaValidezMinima: number | undefined = undefined;

  /** Opciones con las que se llamó a `logout()` por última vez. */
  ultimasOpcionesDeLogout: unknown = undefined;

  constructor(configuracion: unknown) {
    // El constructor real guarda configuración y no hace E/S: se imita.
    this.configuracion = configuracion;
    KeycloakFake.ultimaInstancia = this;
  }

  async init(opts: Record<string, unknown>): Promise<boolean> {
    this.initCalls += 1;
    this.ultimasOpcionesDeInit = opts;
    if (this.initThrows) throw this.initThrows;
    this.authenticated = this.initReturns;
    if (this.initReturns) {
      // Se emula lo que el adaptador real deja tras un init con éxito.
      this.token = this.token || 'token-inicial';
      this.tokenParsed = this.tokenParsed ?? this.tokenPorDefecto();
    }
    return this.initReturns;
  }

  async loadUserProfile(): Promise<PerfilFalso> {
    this.loadProfileCalls += 1;
    return this.profile;
  }

  async updateToken(validezMinima: number): Promise<boolean> {
    this.updateCalls += 1;
    this.ultimaValidezMinima = validezMinima;
    if (this.updateThrows) throw this.updateThrows;
    if (this.updateManual) {
      return new Promise<boolean>((resolve) => {
        this.resolverPendiente = resolve;
      });
    }
    return this.completarUpdate();
  }

  /** Resuelve el `updateToken()` que quedó pendiente con `updateManual`. */
  resolverUpdatePendiente(): void {
    const resolver = this.resolverPendiente;
    this.resolverPendiente = null;
    resolver?.(this.completarUpdate());
  }

  login(): void {
    this.loginCalls += 1;
  }

  logout(opts: unknown): void {
    this.logoutCalls += 1;
    this.ultimasOpcionesDeLogout = opts;
    this.authenticated = false;
    this.token = '';
  }

  // ---------- Ayudas ----------

  /** Reemplaza `tokenParsed` por uno que expira dentro de N segundos. */
  setTokenExpiringInSeconds(segundos: number, extras: Partial<VendiTokenParsed> = {}): void {
    const exp = Math.floor(Date.now() / 1000) + segundos;
    this.tokenParsed = { ...this.tokenPorDefecto(), ...extras, exp };
  }

  /** Fija el claim `organization` en la forma que se quiera probar. */
  setOrganizaciones(claim: ClaimOrganizacion | undefined): void {
    this.tokenParsed = { ...(this.tokenParsed ?? this.tokenPorDefecto()), organization: claim };
  }

  /** Fija los roles de realm del token. */
  setRoles(roles: string[]): void {
    this.tokenParsed = {
      ...(this.tokenParsed ?? this.tokenPorDefecto()),
      realm_access: { roles },
    };
  }

  private completarUpdate(): boolean {
    if (this.updateReturns) {
      this.token = this.nextToken;
    }
    return this.updateReturns;
  }

  private tokenPorDefecto(): VendiTokenParsed {
    return {
      exp: Math.floor(Date.now() / 1000) + 600,
      iat: Math.floor(Date.now() / 1000),
      sub: 'usuario-falso',
      realm_access: { roles: ['dueno'] },
      // Forma **por defecto** del claim en Keycloak 26.6.4: lista de alias.
      organization: [ORG_POR_DEFECTO],
    } as KeycloakTokenParsed & VendiTokenParsed;
  }
}
