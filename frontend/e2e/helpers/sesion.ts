import { expect, type Page } from '@playwright/test';

/**
 * Inicio de sesión con contraseña contra el flujo `browser-passwordless` del
 * realm `vendi-co`.
 *
 * Se conduce el formulario real de Keycloak en vez de inyectar un token en
 * `sessionStorage` porque `keycloak-js` —que es quien gobierna la sesión en
 * las cuatro apps— espera haber ejecutado su propio intercambio PKCE: un token
 * sintético no satisface el contrato de su `init()` y la app arrancaría
 * creyéndose sin sesión. Cuesta unos segundos por login; a cambio, lo que se
 * prueba es el camino real.
 *
 * POR QUÉ SON DOS PANTALLAS: `browser-passwordless` pide primero el
 * identificador y solo después la credencial. Un helper escrito para el flujo
 * clásico (usuario + contraseña en la misma pantalla) falla aquí con un
 * «elemento no encontrado» que despista.
 *
 * Este helper se usa SOLO en el spec de tenants, donde el sujeto de la prueba
 * es el CRUD y no la autenticación. El criterio de passkey lo demuestra
 * `login-passkey.spec.ts`, que no usa contraseña.
 */
export async function iniciarSesionConContrasena(
  pagina: Page,
  opciones: { urlApp: string; usuario: string; contrasena: string },
): Promise<void> {
  await pagina.goto(opciones.urlApp, { waitUntil: 'domcontentloaded' });
  await pagina.waitForURL(/accounts\./, { timeout: 30_000 });

  const campoUsuario = pagina.locator('#username');
  await campoUsuario.waitFor({ state: 'visible', timeout: 30_000 });
  await campoUsuario.fill(opciones.usuario);
  // Se comprueba el valor antes de enviar: bajo carga, el JS del tema de
  // Keycloak puede rebindear el campo justo después del `fill` y llegar vacío
  // al submit. El síntoma sería «credenciales inválidas» con las credenciales
  // correctas, que manda a depurar el sitio equivocado.
  await expect(campoUsuario).toHaveValue(opciones.usuario);
  await pagina.click('#kc-login');

  const campoContrasena = pagina.locator('#password');
  await campoContrasena.waitFor({ state: 'visible', timeout: 30_000 });
  await campoContrasena.fill(opciones.contrasena);
  await expect(campoContrasena).toHaveValue(opciones.contrasena);
  await pagina.click('#kc-login');

  await pagina.waitForURL(new RegExp(`^${opciones.urlApp}`), { timeout: 45_000 });
}

/**
 * Sufijo corto y difícil de colisionar para los recursos que crea un spec.
 *
 * Que cada ejecución use un nombre nuevo es lo que hace el spec reentrante:
 * el alta de un negocio crea además una Organization en Keycloak, y reutilizar
 * el nombre chocaría con la de la ejecución anterior. Además deja los restos
 * fáciles de encontrar (`grep e2e-`) si alguna vez una limpieza falla.
 */
export function sufijoUnico(prefijo = 'e2e'): string {
  return `${prefijo}-${Math.random().toString(36).slice(2, 8)}`;
}
