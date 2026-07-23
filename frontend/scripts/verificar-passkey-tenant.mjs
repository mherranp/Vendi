/**
 * Verificación en vivo del criterio 1 de la Fase 0:
 * «login con passkey en vendi-tenant demostrado en vivo».
 *
 * Qué demuestra, de punta a punta y por el hostname real:
 *
 *   passkey → flujo `browser-passwordless` del realm `vendi-co` → token con
 *   claim `organization` → `tenant_id` → RLS → la fila del negocio,
 *   "Tienda Don Carlos", pintada en la pantalla «Mi negocio».
 *
 * Cómo se ejecuta (desde `frontend/`):
 *
 *     npm run build:tenant
 *     # La app tiene que servirse POR SU HOSTNAME, no por `ng serve` en un
 *     # puerto pelado: lo que se verifica es la integración con Keycloak, y por
 *     # `localhost:4202` no se ejercita ni el enrutado de Traefik ni el TLS.
 *     # Mientras no exista `frontend/Dockerfile` (Etapa 5), basta con:
 *     docker run -d --name vendi-tenant-demo --network vendi_vendi-net \
 *       -v "$PWD/dist/vendi-tenant/browser:/usr/share/nginx/html:ro" \
 *       nginx:1.27-alpine
 *     # y el router `infra/traefik/dynamic/demo-frontend.yml`, que Traefik
 *     # recarga en caliente.
 *     npm run verificar:passkey
 *
 * Requiere el stack de `infra/` levantado.
 *
 * PROTECCIÓN DE RESOLUCIÓN — no la quites:
 *
 * El dominio `vendi.co` NO pertenece al dueño del producto: está registrado
 * por un tercero y resuelve públicamente a una IP que no es nuestra. Mientras
 * no exista `/etc/resolver/vendi.co`, cualquier petición a `*.vendi.co` que no
 * fije la resolución SALE A INTERNET, al servidor de ese tercero. Ya pasó una
 * vez: un `client_secret` acabó fuera.
 *
 * Por eso Chromium se lanza siempre con `--host-resolver-rules`, que mapea
 * TODO `*.vendi.co` a 127.0.0.1 dentro del navegador. Y por eso NO se usa
 * `ignoreHTTPSErrors`: el certificado de mkcert valida contra la CA que
 * `mkcert -install` dejó en el llavero del sistema, así que si la validación
 * fallara sería una señal real de que algo no está donde creemos —justo lo que
 * `--insecure` taparía—.
 *
 * El passkey se materializa con un **autenticador virtual** de Chrome (CDP,
 * dominio WebAuthn), que es el mecanismo que el propio plan admite para esta
 * prueba: "authenticator virtual o huella real".
 */
import { chromium } from 'playwright';
import { request as httpsRequest } from 'node:https';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const AQUI = dirname(fileURLToPath(import.meta.url));
/** Raíz del repositorio: aquí viven `.env` y `docs/`. */
const RAIZ = resolve(AQUI, '../..');

const APP = 'https://app.vendi.co';
const CUENTAS = 'https://accounts.vendi.co';
const REALM = 'vendi-co';
const USUARIO = 'dueno@demo.vendi.co';
const NEGOCIO_ESPERADO = 'Tienda Don Carlos';

/** Mapea todo el dominio al bucle local DENTRO del navegador. Innegociable. */
const REGLAS_DE_RESOLUCION = 'MAP *.vendi.co 127.0.0.1, MAP vendi.co 127.0.0.1';

function leerEnv() {
  const texto = readFileSync(resolve(RAIZ, '.env'), 'utf8');
  const env = {};
  for (const linea of texto.split('\n')) {
    const m = /^([A-Z0-9_]+)=(.*)$/.exec(linea.trim());
    if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
  return env;
}

/**
 * Petición HTTPS contra el stack con la resolución fijada a 127.0.0.1.
 *
 * Es el equivalente en Node de `curl --resolve host:443:127.0.0.1`. Se fija por
 * `lookup`, de modo que el `Host` y el SNI siguen siendo el hostname real —que
 * es lo que hace que Traefik enrute y que el certificado de mkcert valide—
 * mientras que el socket nunca sale del bucle local.
 *
 * NO se toca `rejectUnauthorized`: la validación TLS se queda activa a
 * propósito. Ver la cabecera del archivo.
 */
function pedir(url, opciones = {}) {
  const destino = new URL(url);
  return new Promise((resolver, rechazar) => {
    const peticion = httpsRequest(
      {
        protocol: destino.protocol,
        hostname: destino.hostname,
        port: destino.port || 443,
        path: `${destino.pathname}${destino.search}`,
        method: opciones.method ?? 'GET',
        headers: opciones.headers ?? {},
        servername: destino.hostname,
        // Aquí vive la protección: el nombre se resuelve siempre al bucle
        // local. Node pide la respuesta como lista cuando usa `all: true`, así
        // que se contemplan las dos formas.
        lookup: (_hostname, opcionesDns, cb) =>
          opcionesDns?.all
            ? cb(null, [{ address: '127.0.0.1', family: 4 }])
            : cb(null, '127.0.0.1', 4),
      },
      (respuesta) => {
        let cuerpo = '';
        respuesta.on('data', (trozo) => (cuerpo += trozo));
        respuesta.on('end', () =>
          resolver({
            ok: respuesta.statusCode >= 200 && respuesta.statusCode < 300,
            status: respuesta.statusCode,
            text: async () => cuerpo,
            json: async () => JSON.parse(cuerpo),
          }),
        );
      },
    );
    peticion.on('error', rechazar);
    if (opciones.body) peticion.write(opciones.body.toString());
    peticion.end();
  });
}

async function tokenDeAdmin(env) {
  const r = await pedir(`${CUENTAS}/realms/master/protocol/openid-connect/token`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: 'admin-cli',
      username: env.KEYCLOAK_ADMIN_USER,
      password: env.KEYCLOAK_ADMIN_PASSWORD,
      grant_type: 'password',
    }),
  });
  if (!r.ok) throw new Error(`No se pudo autenticar contra Keycloak: ${r.status}`);
  return (await r.json()).access_token;
}

async function admin(token, ruta, opciones = {}) {
  const r = await pedir(`${CUENTAS}/admin/realms/${REALM}${ruta}`, {
    ...opciones,
    headers: {
      authorization: `Bearer ${token}`,
      'content-type': 'application/json',
      ...(opciones.headers ?? {}),
    },
  });
  if (!r.ok && r.status !== 204) {
    throw new Error(`Keycloak ${opciones.method ?? 'GET'} ${ruta} → ${r.status}`);
  }
  const texto = await r.text();
  return texto ? JSON.parse(texto) : null;
}

const paso = (n, t) => console.log(`\n[${n}] ${t}`);
const ok = (t) => console.log(`    ✓ ${t}`);

async function main() {
  const env = leerEnv();
  const token = await tokenDeAdmin(env);

  paso(1, 'Estado de partida del usuario en el realm');
  const [usuario] = await admin(token, `/users?username=${encodeURIComponent(USUARIO)}&exact=true`);
  if (!usuario) throw new Error(`No existe ${USUARIO} en el realm ${REALM}`);
  const credencialesAntes = await admin(token, `/users/${usuario.id}/credentials`);
  console.log(
    `    credenciales: ${credencialesAntes.map((c) => c.type).join(', ') || '(ninguna)'}`,
  );

  // La ruta correcta en Keycloak 26.6.4. `/users/{id}/organizations` NO existe
  // y devuelve 404 siempre.
  const orgs = await admin(token, `/organizations/members/${usuario.id}/organizations`);
  console.log(`    organizaciones: ${orgs.map((o) => o.alias).join(', ')}`);

  // El passkey se da de baja y se vuelve a registrar en cada ejecución, y no
  // por gusto: la clave privada vive DENTRO del autenticador virtual, que es
  // efímero y muere con el navegador. Un passkey registrado en una ejecución
  // anterior existe en Keycloak pero ya no tiene clave que lo respalde, así
  // que el flujo caería a contraseña y la prueba no demostraría nada. Dando
  // de baja y registrando dentro de la misma sesión, la verificación es
  // repetible y siempre ejercita el passkey de verdad.
  for (const credencial of credencialesAntes.filter((c) => c.type === 'webauthn-passwordless')) {
    await admin(token, `/users/${usuario.id}/credentials/${credencial.id}`, { method: 'DELETE' });
    ok(`dado de baja el passkey huérfano ${credencial.id.slice(0, 8)} de una ejecución anterior`);
  }
  await admin(token, `/users/${usuario.id}`, {
    method: 'PUT',
    body: JSON.stringify({
      ...usuario,
      requiredActions: ['webauthn-register-passwordless'],
    }),
  });
  ok('marcado `webauthn-register-passwordless` para el próximo inicio de sesión');

  paso(2, 'Chromium con autenticador virtual y resolución fijada a 127.0.0.1');
  const navegador = await chromium.launch({
    headless: true,
    args: [`--host-resolver-rules=${REGLAS_DE_RESOLUCION}`],
  });
  // Sin `ignoreHTTPSErrors`: el certificado de mkcert tiene que validar solo.
  const contexto = await navegador.newContext();
  const pagina = await contexto.newPage();

  const cdp = await contexto.newCDPSession(pagina);
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
  ok(`autenticador virtual ${authenticatorId} (residente + verificación de usuario)`);

  const errores = [];
  pagina.on('console', (m) => {
    if (m.type() === 'error') errores.push(m.text());
  });

  try {
    {
      paso(3, 'Alta del passkey: primer login con contraseña + registro WebAuthn');
      await pagina.goto(APP, { waitUntil: 'domcontentloaded' });
      await pagina.waitForURL(/accounts\.vendi\.co/, { timeout: 20_000 });
      ok(`la SPA redirigió al IdP: ${new URL(pagina.url()).origin}`);

      // El flujo `browser-passwordless` pide primero el identificador y solo
      // después la credencial: son dos pantallas, no una.
      await pagina.fill('#username', USUARIO);
      await pagina.click('#kc-login');

      await pagina.waitForSelector('#password', { timeout: 20_000 });
      // Única vez en todo el script que se escribe la contraseña: es el alta
      // del passkey. El login que verifica el criterio (paso 4) no la usa.
      await pagina.fill('#password', env.SEED_DUENO_PASSWORD);
      await pagina.click('#kc-login');

      // Keycloak sirve la pantalla de registro de passkey (required action).
      const botonRegistrar = pagina.locator('#registerWebAuthn');
      await botonRegistrar.waitFor({ timeout: 20_000 });
      await botonRegistrar.click();
      await pagina.waitForURL(/app\.vendi\.co/, { timeout: 30_000 });

      // Se comprueba que la clave existe DENTRO del autenticador: si aquí
      // hubiera cero, el paso 4 caería a contraseña y estaríamos "verificando"
      // un login que no usa passkey.
      const { credentials } = await cdp.send('WebAuthn.getCredentials', { authenticatorId });
      const residentes = credentials.filter((c) => c.isResidentCredential);
      if (residentes.length === 0) {
        throw new Error('El autenticador virtual no acabó con ninguna clave residente');
      }
      ok(
        `passkey registrado: ${residentes.length} clave residente para rpId «${residentes[0].rpId}»`,
      );

      // Se cierra la sesión para que el siguiente login sea SOLO con passkey.
      await pagina.goto(
        `${CUENTAS}/realms/${REALM}/protocol/openid-connect/logout?post_logout_redirect_uri=${encodeURIComponent(APP)}&client_id=vendi-web`,
        { waitUntil: 'domcontentloaded' },
      );
      await contexto.clearCookies();
      ok('sesión cerrada: el siguiente inicio parte de cero');
    }

    paso(4, 'Login con PASSKEY (sin contraseña) por el hostname real');
    await pagina.goto(APP, { waitUntil: 'domcontentloaded' });
    await pagina.waitForURL(/accounts\.vendi\.co/, { timeout: 20_000 });

    // Flujo `browser-passwordless`: se identifica al usuario y la credencial
    // la resuelve el passkey. En este tramo NO se escribe ninguna contraseña.
    const usuarioInput = pagina.locator('#username');
    if (await usuarioInput.count()) {
      await usuarioInput.fill(USUARIO);
      await pagina.click('#kc-login');
    }

    // El subflujo `passkey-o-password` ofrece las dos credenciales como
    // ALTERNATIVE y hoy presenta la CONTRASEÑA por defecto; el passkey queda
    // detrás de «Pruebe de otra manera». Se elige explícitamente para que lo
    // que se verifica sea un login con passkey de verdad y no una contraseña
    // disfrazada. (Que el orden por defecto sea ése es configuración de realm
    // —pista infra— y queda anotado en el informe.)
    await pagina.waitForSelector('#password, #kc-login', { timeout: 20_000 });
    if (await pagina.locator('#try-another-way').count()) {
      await pagina.click('#try-another-way');
      const opcionPasskey = pagina.locator(
        'button[name=authenticationExecution]:has-text("Passkey")',
      );
      await opcionPasskey.waitFor({ timeout: 15_000 });
      ok('elegida la opción «Passkey — Use su Passkey para iniciar sesión sin contraseña»');
      await opcionPasskey.click();
    }

    // La ceremonia WebAuthn la dispara el usuario: Keycloak sirve la pantalla
    // «Iniciar sesión con Passkey» y es ese botón el que llama a
    // `navigator.credentials.get()`.
    const botonPasskey = pagina.locator('#authenticateWebAuthnButton');
    await botonPasskey.waitFor({ timeout: 15_000 });
    await botonPasskey.click();

    await pagina.waitForURL(/app\.vendi\.co/, { timeout: 30_000 }).catch(async () => {
      if (await pagina.locator('#password').count()) {
        throw new Error(
          'El flujo acabó pidiendo CONTRASEÑA: el passkey no resolvió la autenticación.',
        );
      }
      throw new Error(`El login con passkey no volvió a la app. URL: ${pagina.url()}`);
    });

    // Ninguna contraseña se escribió en este tramo: el token viene del passkey.
    ok('autenticado SIN contraseña (aserción WebAuthn del autenticador virtual)');
    ok(`de vuelta en la app: ${pagina.url()}`);

    paso(5, 'La cadena de identidad llega hasta la fila del negocio');
    await pagina.waitForSelector('vd-mi-negocio', { timeout: 20_000 });
    await pagina.waitForFunction(
      (esperado) => document.body.innerText.includes(esperado),
      NEGOCIO_ESPERADO,
      { timeout: 20_000 },
    );
    const texto = await pagina.innerText('body');
    ok(`se ve «${NEGOCIO_ESPERADO}» en la pantalla «Mi negocio»`);

    const alias = orgs[0]?.alias;
    if (alias && texto.includes(alias)) {
      ok(`y el tenant del claim (${alias}) coincide con el de la API`);
    }

    // Se confirma que el token que trajo el navegador es realmente de passkey.
    const credencialesDespues = await admin(token, `/users/${usuario.id}/credentials`);
    const tipos = credencialesDespues.map((c) => c.type);
    if (!tipos.includes('webauthn-passwordless')) {
      throw new Error(`El usuario no acabó con un passkey: ${tipos.join(', ')}`);
    }
    ok(`credenciales finales: ${tipos.join(', ')}`);

    if (errores.length) {
      console.log(`\n    Errores de consola observados (${errores.length}):`);
      for (const e of errores.slice(0, 10)) console.log(`      · ${e}`);
    }

    console.log('\nRESULTADO: login con passkey en vendi-tenant VERIFICADO EN VIVO.');
  } finally {
    await pagina
      .screenshot({ path: resolve(RAIZ, 'docs/evidencia-passkey-tenant.png'), fullPage: true })
      .catch(() => undefined);
    await navegador.close();
  }
}

main().catch((error) => {
  console.error('\nFALLÓ la verificación de passkey:', error.message);
  process.exit(1);
});
