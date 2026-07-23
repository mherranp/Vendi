import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { FeatureFlagsService } from 'data-access';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Se sustituye keycloak-js por el doble ANTES de que AuthService se cargue.
// vitest eleva `vi.mock` al principio del archivo, así que la fábrica no puede
// depender de imports de nivel superior: se carga el doble de forma perezosa.
vi.mock('keycloak-js', async () => {
  const mod = await import('./keycloak.fake');
  return { default: mod.KeycloakFake };
});

import { AuthService, SCOPE_ORGANIZACIONES } from './auth.service';
import { KeycloakFake, ORG_POR_DEFECTO } from './keycloak.fake';

const ORG_B = '2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f';

const CONFIG = {
  url: 'https://accounts.vendi.co',
  realm: 'vendi-co',
  clientId: 'vendi-web',
} as const;

function crearServicio(): AuthService {
  TestBed.resetTestingModule();
  // `AuthService` invalida la caché de banderas al cambiar de tenant, así que
  // arrastra `FeatureFlagsService` → `ApiService` → `HttpClient`.
  TestBed.configureTestingModule({ providers: [provideHttpClient(), AuthService] });
  return TestBed.runInInjectionContext(() => TestBed.inject(AuthService));
}

/** La instancia de Keycloak que `AuthService` construyó por dentro. */
function doble(): KeycloakFake {
  const instancia = KeycloakFake.ultimaInstancia;
  if (!instancia) throw new Error('AuthService no construyó ningún Keycloak');
  return instancia;
}

type EnvoltorioInit = (opciones: Record<string, unknown>, fake: KeycloakFake) => void;

/**
 * Arranca `AuthService` interceptando el `init()` del doble.
 *
 * El doble se construye dentro de `AuthService.init()`, así que éste es el
 * único punto donde un spec puede tocar la instancia antes de que se lea el
 * claim (fijar `tokenParsed`, capturar el `scope`, activar `updateManual`…).
 */
async function iniciar(auth: AuthService, antes?: EnvoltorioInit): Promise<boolean> {
  const ctor = KeycloakFake as unknown as {
    prototype: { init: (o: Record<string, unknown>) => Promise<boolean> };
  };
  const original = ctor.prototype.init;
  ctor.prototype.init = async function (opciones: Record<string, unknown>) {
    const fake = doble();
    antes?.(opciones, fake);
    return original.call(fake, opciones);
  };
  try {
    return await auth.init({ ...CONFIG });
  } finally {
    ctor.prototype.init = original;
  }
}

/** Atajo: arranca fijando el `tokenParsed` que necesita el caso. */
function conToken(token: Record<string, unknown>): EnvoltorioInit {
  return (_opciones, fake) => {
    fake.tokenParsed = token as never;
  };
}

function tokenBase(extras: Record<string, unknown>): Record<string, unknown> {
  return {
    exp: Math.floor(Date.now() / 1000) + 600,
    iat: Math.floor(Date.now() / 1000),
    sub: 'u1',
    realm_access: { roles: ['dueno'] },
    ...extras,
  };
}

describe('AuthService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
    KeycloakFake.ultimaInstancia = undefined;
  });

  it('arranca sin sesión: token vacío, sin usuario y sin tenant', () => {
    const auth = crearServicio();
    expect(auth.authenticated()).toBe(false);
    expect(auth.token()).toBe('');
    expect(auth.user()).toBeNull();
    expect(auth.tenantId()).toBeNull();
    expect(auth.organizaciones()).toEqual([]);
    expect(auth.displayName()).toBe('');
  });

  it('init() pide SIEMPRE scope=organization:*', async () => {
    // Hallazgo del spike 1.1: con dos organizaciones, `organization` a secas
    // devuelve el claim ausente. Si esta prueba falla, el segundo negocio del
    // mismo dueño deja de funcionar sin ningún error visible.
    const auth = crearServicio();
    await iniciar(auth);

    const opciones = doble().ultimasOpcionesDeInit;
    expect(opciones?.['scope']).toBe('organization:*');
    expect(SCOPE_ORGANIZACIONES).toBe('organization:*');
    expect(opciones?.['pkceMethod']).toBe('S256');
    expect(opciones?.['checkLoginIframe']).toBe(false);
  });

  it('init() con sesión puebla las señales y resuelve el tenant de la única organización', async () => {
    const auth = crearServicio();
    const ok = await auth.init({ ...CONFIG, onLoad: 'check-sso' });

    expect(ok).toBe(true);
    expect(auth.authenticated()).toBe(true);
    expect(auth.token()).toBe('token-inicial');
    expect(auth.user()?.username).toBe('dueno');
    expect(auth.displayName()).toBe('Ana Gómez');
    expect(auth.organizaciones()).toEqual([ORG_POR_DEFECTO]);
    expect(auth.tenantId()).toBe(ORG_POR_DEFECTO);
    expect(auth.user()?.tenantId).toBe(ORG_POR_DEFECTO);
    expect(auth.requiereSeleccionDeTenant()).toBe(false);
  });

  it('init() devolviendo false no toca ninguna señal', async () => {
    const auth = crearServicio();
    const ctor = (await import('keycloak-js')).default as unknown as typeof KeycloakFake;
    const spy = vi.spyOn(ctor.prototype, 'init').mockResolvedValueOnce(false);
    const ok = await auth.init({ ...CONFIG });
    expect(ok).toBe(false);
    expect(auth.authenticated()).toBe(false);
    expect(auth.user()).toBeNull();
    expect(auth.token()).toBe('');
    expect(auth.tenantId()).toBeNull();
    spy.mockRestore();
  });

  it('lee el claim en forma de LISTA (la forma por defecto de Keycloak 26)', async () => {
    const auth = crearServicio();
    await iniciar(auth, conToken(tokenBase({ organization: [ORG_POR_DEFECTO] })));
    expect(auth.organizaciones()).toEqual([ORG_POR_DEFECTO]);
    expect(auth.tenantId()).toBe(ORG_POR_DEFECTO);
  });

  it('lee el claim en forma de MAPA (addOrganizationId=true)', async () => {
    const auth = crearServicio();
    await iniciar(
      auth,
      conToken(tokenBase({ organization: { [ORG_POR_DEFECTO]: { id: 'kc-org-1' } } })),
    );
    expect(auth.organizaciones()).toEqual([ORG_POR_DEFECTO]);
    expect(auth.tenantId()).toBe(ORG_POR_DEFECTO);
  });

  it('con DOS organizaciones el tenant es null hasta selectTenant()', async () => {
    const auth = crearServicio();
    await iniciar(auth, conToken(tokenBase({ organization: [ORG_POR_DEFECTO, ORG_B] })));

    expect(auth.organizaciones()).toEqual([ORG_POR_DEFECTO, ORG_B]);
    expect(auth.tenantId()).toBeNull();
    expect(auth.requiereSeleccionDeTenant()).toBe(true);

    expect(auth.selectTenant(ORG_B)).toBe(true);
    expect(auth.tenantId()).toBe(ORG_B);
    expect(auth.requiereSeleccionDeTenant()).toBe(false);

    auth.limpiarSeleccionDeTenant();
    expect(auth.tenantId()).toBeNull();
  });

  it('selectTenant() rechaza un alias que no está en el token', async () => {
    const auth = crearServicio();
    await iniciar(auth);
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    expect(auth.selectTenant(ORG_B)).toBe(false);
    // Sigue valiendo el único del token: la selección inválida no lo pisó.
    expect(auth.tenantId()).toBe(ORG_POR_DEFECTO);
    expect(error).toHaveBeenCalled();
    error.mockRestore();
  });

  it('sin claim organization no hay tenant, pero la sesión es válida', async () => {
    const auth = crearServicio();
    await iniciar(
      auth,
      conToken(tokenBase({ sub: 'admin', realm_access: { roles: ['platform:admin'] } })),
    );
    expect(auth.authenticated()).toBe(true);
    expect(auth.tenantId()).toBeNull();
    expect(auth.hasRole('platform:admin')).toBe(true);
  });

  it('un alias no-UUID se descarta en vez de convertirse en tenant', async () => {
    const auth = crearServicio();
    await iniciar(auth, conToken(tokenBase({ organization: ['acme'] })));
    expect(auth.organizaciones()).toEqual([]);
    expect(auth.tenantId()).toBeNull();
  });

  it('hasRole / hasAnyRole reflejan los roles del token', async () => {
    const auth = crearServicio();
    await iniciar(auth);
    expect(auth.roles()).toEqual(['dueno']);
    expect(auth.hasRole('dueno')).toBe(true);
    expect(auth.hasRole('cajero')).toBe(false);
    expect(auth.hasAnyRole('cajero', 'dueno')).toBe(true);
    expect(auth.hasAnyRole('cajero', 'almacenista')).toBe(false);
  });

  it('hasPermission honra el comodín *', async () => {
    const auth = crearServicio();
    await iniciar(auth, conToken(tokenBase({ realm_access: { roles: ['*'] } })));
    expect(auth.hasPermission('lo:que:sea')).toBe(true);
  });

  it('hasPermission NO honra is_superuser (claim que no existe en vendi-co)', async () => {
    const auth = crearServicio();
    await iniciar(
      auth,
      conToken(tokenBase({ realm_access: { roles: ['dueno'] }, is_superuser: true })),
    );
    // BaseSaaS daba pase libre con este claim; Vendi no lo reconoce.
    expect(auth.hasPermission('tenant:delete')).toBe(false);
    expect(auth.hasPermission('dueno')).toBe(true);
  });

  it('hasPermission con un permiso inexistente devuelve false sin explotar', () => {
    const auth = crearServicio();
    expect(auth.hasPermission('permiso:que:no:existe')).toBe(false);
  });

  it('logout() es idempotente ante una ráfaga de llamadas', async () => {
    const auth = crearServicio();
    await iniciar(auth);
    auth.logout();
    auth.logout();
    auth.logout();
    expect(doble().logoutCalls).toBe(1);
  });

  it('el refresco re-entrante no dispara dos updateToken concurrentes', async () => {
    // Escenario del QA: el token expira durante la navegación y algo fuerza un
    // segundo refresco antes de que el primero responda.
    const auth = crearServicio();
    await iniciar(auth, (_opciones, fake) => {
      fake.updateManual = true;
    });

    const primero = auth.refrescar();
    const segundo = auth.refrescar(); // reentra con el primero en vuelo
    expect(doble().updateCalls).toBe(1);

    doble().resolverUpdatePendiente();
    await Promise.all([primero, segundo]);

    expect(doble().updateCalls).toBe(1);
    expect(auth.token()).toBe('token-refrescado');
  });

  it('un refresco con éxito relee las organizaciones del token nuevo', async () => {
    const auth = crearServicio();
    await iniciar(auth);
    expect(auth.tenantId()).toBe(ORG_POR_DEFECTO);

    // El dueño abre un segundo negocio: el token refrescado trae dos orgs.
    doble().setOrganizaciones([ORG_POR_DEFECTO, ORG_B]);
    await auth.refrescar();

    expect(auth.organizaciones()).toEqual([ORG_POR_DEFECTO, ORG_B]);
    expect(auth.tenantId()).toBeNull();
    expect(auth.requiereSeleccionDeTenant()).toBe(true);
  });

  it('si el refresco falla se cierra la sesión', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const auth = crearServicio();
    await iniciar(auth);
    doble().updateThrows = new Error('refresh token vencido');

    await auth.refrescar();

    expect(doble().logoutCalls).toBe(1);
    error.mockRestore();
  });

  it('la selección se descarta si el token nuevo ya no incluye ese negocio', async () => {
    const auth = crearServicio();
    await iniciar(auth, conToken(tokenBase({ organization: [ORG_POR_DEFECTO, ORG_B] })));
    auth.selectTenant(ORG_B);
    expect(auth.tenantId()).toBe(ORG_B);

    // Al dueño lo sacan del segundo negocio.
    doble().setOrganizaciones([ORG_POR_DEFECTO]);
    await auth.refrescar();

    expect(auth.tenantId()).toBe(ORG_POR_DEFECTO);
  });

  it('un refresco relee los roles: hasRole() y hasPermission() no divergen', async () => {
    // Antes había dos autoridades sobre los roles: `roles()`/`hasRole()` leían
    // el perfil congelado en `init()` y `hasPermission()` leía `tokenParsed`.
    // Tras un refresco que cambiara los roles, `roleGuard` y
    // `*vdHasPermission` decidían distinto sobre el mismo permiso.
    const auth = crearServicio();
    await iniciar(auth, conToken(tokenBase({ realm_access: { roles: ['dueno'] } })));
    expect(auth.roles()).toEqual(['dueno']);
    expect(auth.hasRole('dueno')).toBe(true);
    expect(auth.hasPermission('dueno')).toBe(true);
    expect(auth.hasPermission('ventas:leer')).toBe(false);

    // Al usuario le quitan `dueno` y le dan `ventas:leer`.
    doble().setRoles(['ventas:leer']);
    await auth.refrescar();

    expect(auth.roles()).toEqual(['ventas:leer']);
    expect(auth.hasRole('dueno')).toBe(false);
    expect(auth.hasPermission('dueno')).toBe(false);
    expect(auth.hasAnyRole('dueno', 'ventas:leer')).toBe(true);
    expect(auth.hasPermission('ventas:leer')).toBe(true);
    // Y el perfil deja de ser una segunda fuente de verdad.
    expect(auth.user()?.roles).toEqual(['ventas:leer']);
  });

  it('cambiar de negocio invalida la caché de banderas del tenant', async () => {
    // Sin esto, un dueño con dos negocios seguía leyendo indefinidamente las
    // banderas del negocio anterior, y sin ninguna petición HTTP nueva.
    const auth = crearServicio();
    const banderas = TestBed.inject(FeatureFlagsService);
    await iniciar(auth, conToken(tokenBase({ organization: [ORG_POR_DEFECTO, ORG_B] })));
    auth.selectTenant(ORG_POR_DEFECTO);

    const invalidar = vi.spyOn(banderas, 'invalidar');
    auth.selectTenant(ORG_B);
    expect(invalidar).toHaveBeenCalledTimes(1);

    // Reelegir el mismo negocio no tira nada: no cambió el tenant efectivo.
    auth.selectTenant(ORG_B);
    expect(invalidar).toHaveBeenCalledTimes(1);

    // Volver al selector sí, porque el tenant efectivo pasa a null.
    auth.limpiarSeleccionDeTenant();
    expect(invalidar).toHaveBeenCalledTimes(2);
  });

  it('getToken() devuelve lo que tiene la señal token()', async () => {
    const auth = crearServicio();
    expect(auth.getToken()).toBe('');
    await iniciar(auth);
    expect(auth.getToken()).toBe(auth.token());
    expect(auth.getToken()).toBe('token-inicial');
  });
});
