import { expect, test, type CDPSession, type Page } from '@playwright/test';
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
  NEGOCIO_DEMO,
  RAIZ,
  REALM,
  URL_APP,
  URL_CUENTAS,
  USUARIO_DUENO,
  buscarUsuario,
  kcAdmin,
  limpiarBloqueo,
  requerido,
  tokenDeAdministracion,
} from './helpers/stack';

/**
 * Criterio 2 de cierre de la Fase 0: «login con passkey funcionando».
 *
 * Qué demuestra, de punta a punta y por el hostname real:
 *
 *   passkey → flujo `browser-passwordless` del realm `vendi-co` → token con
 *   claim `organization` → `tenant_id` → RLS → la fila del negocio,
 *   «Tienda Don Carlos», pintada en la pantalla «Mi negocio».
 *
 * Este spec sustituye al script suelto `scripts/verificar-passkey-tenant.mjs`
 * de la Etapa 4: la misma verificación, ahora dentro del harness que corre en
 * CI. `npm run verificar:passkey` lo ejecuta a solas.
 *
 * REQUISITOS: el stack de `infra/` levantado, `scripts/seed.sh` ejecutado y
 * las tres SPAs servidas por Traefik (servicios `portal`/`tenant`/`admin` del
 * compose). NO vale `ng serve`: lo que se verifica aquí es la integración con
 * Keycloak, y por un puerto pelado no se ejercita ni el enrutado de Traefik,
 * ni las cabeceras que inyecta, ni el TLS, ni la resolución de nombres.
 *
 * EL PASSKEY SE MATERIALIZA CON UN AUTENTICADOR VIRTUAL de Chrome (CDP,
 * dominio WebAuthn), que es el mecanismo que el plan admite explícitamente
 * para esta prueba: «authenticator virtual o huella real».
 *
 * POR QUÉ EL SPEC ES REENTRANTE (y tiene que serlo): la clave privada vive
 * DENTRO del autenticador virtual, que es efímero y muere con el navegador.
 * Un passkey registrado en una ejecución anterior existe en Keycloak pero ya
 * no tiene clave que lo respalde: el flujo caería a contraseña y la prueba
 * «pasaría» sin haber ejercitado ningún passkey. Por eso cada ejecución da de
 * baja los passkeys huérfanos y registra el suyo dentro de la misma sesión.
 * Es también lo que hace que `--repeat-each=5` sea honesto.
 */

/** Alta del autenticador virtual: residente y con verificación de usuario. */
async function crearAutenticadorVirtual(cdp: CDPSession): Promise<string> {
  await cdp.send('WebAuthn.enable');
  const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', {
    options: {
      protocol: 'ctap2',
      ctap2Version: 'ctap2_1',
      transport: 'internal',
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  return authenticatorId;
}

/**
 * Cierra la sesión en el IdP y borra las cookies del contexto.
 *
 * Las dos cosas: sin el `logout` de Keycloak queda la cookie de SSO del realm
 * y el siguiente `goto` volvería a la app sin pasar por ninguna pantalla de
 * autenticación — el spec «pasaría» sin haber usado el passkey.
 */
async function cerrarSesion(pagina: Page): Promise<void> {
  await pagina.goto(
    `${URL_CUENTAS}/realms/${REALM}/protocol/openid-connect/logout` +
      `?post_logout_redirect_uri=${encodeURIComponent(URL_APP)}&client_id=vendi-web`,
    { waitUntil: 'domcontentloaded' },
  );
  await pagina.context().clearCookies();
}

test.describe('Login con passkey en vendi-tenant', () => {
  test('registra un passkey y vuelve a entrar sin contraseña', async ({
    page,
    context,
  }, pruebas) => {
    const token = await tokenDeAdministracion();

    // --- Estado de partida --------------------------------------------------
    const usuario = await buscarUsuario(token, USUARIO_DUENO);
    await limpiarBloqueo(token, usuario.id);

    // La ruta correcta en Keycloak 26.6.4 es ésta.
    // `/users/{id}/organizations` NO existe y devuelve 404 siempre.
    const organizaciones = await kcAdmin<{ alias: string; name: string }[]>(
      token,
      `/organizations/members/${usuario.id}/organizations`,
    );
    expect(
      organizaciones?.length,
      `${USUARIO_DUENO} no pertenece a ninguna Organization: sin claim \`organization\` no hay tenant que resolver`,
    ).toBeGreaterThan(0);
    const alias = organizaciones![0].alias;

    const credencialesPrevias =
      (await kcAdmin<{ id: string; type: string }[]>(token, `/users/${usuario.id}/credentials`)) ??
      [];
    for (const credencial of credencialesPrevias.filter(
      (c) => c.type === 'webauthn-passwordless',
    )) {
      // Passkey huérfano de una ejecución anterior: ver la cabecera.
      await kcAdmin(token, `/users/${usuario.id}/credentials/${credencial.id}`, {
        method: 'DELETE',
      });
    }
    await kcAdmin(token, `/users/${usuario.id}`, {
      method: 'PUT',
      body: { ...usuario, requiredActions: ['webauthn-register-passwordless'] },
    });

    // --- Autenticador virtual ----------------------------------------------
    const cdp = await context.newCDPSession(page);
    const autenticador = await crearAutenticadorVirtual(cdp);

    // --- Alta del passkey: contraseña una sola vez, para registrarlo --------
    await page.goto(URL_APP, { waitUntil: 'domcontentloaded' });
    await page.waitForURL(/accounts\./, { timeout: 30_000 });

    // El flujo `browser-passwordless` pide primero el identificador y solo
    // después la credencial: son dos pantallas, no una.
    await page.fill('#username', USUARIO_DUENO);
    await page.click('#kc-login');
    await page.waitForSelector('#password', { timeout: 30_000 });
    // Única vez en todo el spec que se escribe la contraseña. El login que
    // verifica el criterio (más abajo) no la usa.
    await page.fill('#password', requerido('SEED_DUENO_PASSWORD'));
    await page.click('#kc-login');

    const botonRegistrar = page.locator('#registerWebAuthn');
    await botonRegistrar.waitFor({ timeout: 30_000 });
    await botonRegistrar.click();
    await page.waitForURL(new RegExp(`^${URL_APP}`), { timeout: 45_000 });

    // Se comprueba que la clave existe DENTRO del autenticador: si aquí
    // hubiera cero, el login siguiente caería a contraseña y estaríamos
    // «verificando» un login que no usa passkey.
    const { credentials } = await cdp.send('WebAuthn.getCredentials', {
      authenticatorId: autenticador,
    });
    const residentes = credentials.filter((c) => c.isResidentCredential);
    expect(
      residentes.length,
      'el autenticador virtual no acabó con ninguna clave residente',
    ).toBeGreaterThan(0);
    expect(residentes[0].rpId).toBe(new URL(URL_CUENTAS).hostname);

    await cerrarSesion(page);

    // --- El login que demuestra el criterio: SIN contraseña -----------------
    await page.goto(URL_APP, { waitUntil: 'domcontentloaded' });
    await page.waitForURL(/accounts\./, { timeout: 30_000 });

    const campoUsuario = page.locator('#username');
    if (await campoUsuario.count()) {
      await campoUsuario.fill(USUARIO_DUENO);
      await page.click('#kc-login');
    }

    // DEUDA CONOCIDA (configuración del realm, pista de infraestructura): el
    // subflujo `passkey-o-password` ofrece las dos credenciales como
    // ALTERNATIVE y hoy presenta la CONTRASEÑA por defecto; el passkey queda
    // detrás de «Pruebe de otra manera». Se elige explícitamente para que lo
    // que se verifica sea un login con passkey de verdad y no una contraseña
    // disfrazada. Cuando el orden del realm se invierta, esta rama
    // sencillamente no se ejecutará y el spec seguirá siendo válido.
    await page.waitForSelector('#password, #authenticateWebAuthnButton', { timeout: 30_000 });
    const otraManera = page.locator('#try-another-way');
    if (await otraManera.count()) {
      await otraManera.click();
      const opcionPasskey = page.locator(
        'button[name=authenticationExecution]:has-text("Passkey")',
      );
      await opcionPasskey.waitFor({ timeout: 20_000 });
      await opcionPasskey.click();
    }

    // La ceremonia WebAuthn la dispara el usuario: Keycloak sirve la pantalla
    // «Iniciar sesión con Passkey» y es ese botón el que llama a
    // `navigator.credentials.get()`.
    const botonPasskey = page.locator('#authenticateWebAuthnButton');
    await botonPasskey.waitFor({ timeout: 20_000 });
    await botonPasskey.click();

    await page.waitForURL(new RegExp(`^${URL_APP}`), { timeout: 45_000 }).catch(async () => {
      if (await page.locator('#password').count()) {
        throw new Error(
          'El flujo acabó pidiendo CONTRASEÑA: el passkey no resolvió la autenticación.',
        );
      }
      throw new Error(`El login con passkey no volvió a la app. URL: ${page.url()}`);
    });

    // --- La cadena de identidad llega hasta la fila del negocio -------------
    // Esto es lo que separa «Keycloak emitió un token» de «el sistema
    // funciona»: el claim `organization` se resolvió a un tenant, la API puso
    // el GUC, RLS dejó pasar UNA fila y la SPA la pintó.
    await page.waitForSelector('vd-mi-negocio', { timeout: 30_000 });
    await expect(page.getByText(NEGOCIO_DEMO)).toBeVisible({ timeout: 30_000 });

    // El shell saluda a quien entró. Parece cosmético y no lo es: el perfil se
    // leía solo de `loadUserProfile()`, que devuelve 401 porque el token de
    // Vendi no lleva la audiencia `account`, y el hueco quedaba VACÍO en las
    // cuatro apps. Ahora sale de los claims del propio token; esta aserción es
    // lo que impide que vuelva a quedarse mudo sin que nadie se entere.
    const nombreEsperado = `${usuario.firstName ?? ''} ${usuario.lastName ?? ''}`.trim();
    await expect(page.locator('.vd-shell__usuario')).toHaveText(nombreEsperado, {
      timeout: 30_000,
    });

    // Y el negocio que se ve es el del claim, no otro cualquiera:
    // `alias = str(tenant_id)` (verificado en el spike 1.1).
    const cuerpo = await page.innerText('body');
    expect(cuerpo).toContain(alias);

    // Confirmación por el lado del IdP de que el usuario acabó con passkey.
    const credencialesFinales =
      (await kcAdmin<{ type: string }[]>(token, `/users/${usuario.id}/credentials`)) ?? [];
    expect(credencialesFinales.map((c) => c.type)).toContain('webauthn-passwordless');

    // Evidencia. Siempre va adjunta al informe de Playwright, que es donde la
    // busca quien revisa una ejecución concreta. Y con VENDI_EVIDENCIA=1 se
    // refresca además `docs/evidencia-passkey-tenant.png`, la captura que
    // acompaña al criterio 2 en la documentación. Es opt-in a propósito: un
    // spec que escribe en `docs/` en cada ejecución deja el árbol sucio y
    // acaba metiendo ruido en cada rama.
    const captura = await page.screenshot({ fullPage: true });
    await pruebas.attach('mi-negocio-tras-login-con-passkey', {
      body: captura,
      contentType: 'image/png',
    });
    if (process.env['VENDI_EVIDENCIA'] === '1') {
      writeFileSync(resolve(RAIZ, 'docs/evidencia-passkey-tenant.png'), captura);
    }
  });
});
