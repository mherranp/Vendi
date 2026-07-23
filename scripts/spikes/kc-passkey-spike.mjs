// =====================================================================
// kc-passkey-spike.mjs — Pregunta 10 del spike de Keycloak Organizations:
// ¿conviven las passkeys (WebAuthn passwordless) con Organizations?
//
// No se puede responder con curl: WebAuthn exige un autenticador real.
// Este script usa el autenticador VIRTUAL de Chrome vía CDP (el mismo
// mecanismo que chrome://webauthn-internals, pero automatizable).
//
// Requisitos:
//   npm i -D playwright && npx playwright install chromium
//   (o `npx playwright@1 install chromium` sin instalar nada en el repo)
//
// Uso — con el contenedor que deja vivo kc-orgs-spike.sh:
//   bash scripts/spikes/kc-orgs-spike.sh
//   node scripts/spikes/kc-passkey-spike.mjs
//
// Qué demuestra, en orden:
//   1. Registro de una passkey a través de la required action
//      `webauthn-register-passwordless`, entrando primero con contraseña.
//   2. Login SIN contraseña con esa passkey, sobre el flujo identity-first
//      que Organizations impone.
//   3. Que el token resultante trae el claim `organization` completo.
//   4. Que moviendo la passkey al primer puesto de las credenciales del
//      usuario (moveToFirst), la segunda pantalla ya no pide contraseña.
// =====================================================================
import { chromium } from 'playwright';

const KC = process.env.SPIKE_KC_URL ?? 'http://localhost:8089';
const REALM = 'vendi-co';
const CLIENT = 'vendi-web';
const REDIRECT = 'http://localhost/cb';
// PKCE fijo para que el spike sea reproducible: verifier = "a" * 64.
const VERIFIER = 'a'.repeat(64);
const CHALLENGE = '_-BU_nrgy23GXDr5th1SCfQ5hR20PQulmXM33xVGaOs';

const authUrl = () =>
  `${KC}/realms/${REALM}/protocol/openid-connect/auth` +
  `?client_id=${CLIENT}&response_type=code` +
  `&scope=${encodeURIComponent('openid organization:*')}` +
  `&redirect_uri=${encodeURIComponent(REDIRECT)}` +
  `&code_challenge=${CHALLENGE}&code_challenge_method=S256`;

const log = (...a) => console.log(...a);
const paso = (t) => console.log(`\n=== ${t} ===`);

async function tokenAdmin() {
  const r = await fetch(`${KC}/realms/master/protocol/openid-connect/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'password', client_id: 'admin-cli', username: 'admin', password: 'admin',
    }),
  });
  return (await r.json()).access_token;
}

async function admin(metodo, ruta, cuerpo) {
  const r = await fetch(`${KC}/admin/realms/${REALM}${ruta}`, {
    method: metodo,
    headers: {
      Authorization: `Bearer ${await tokenAdmin()}`,
      'Content-Type': 'application/json',
    },
    body: cuerpo ? JSON.stringify(cuerpo) : undefined,
  });
  const txt = await r.text();
  return { status: r.status, body: txt ? JSON.parse(txt) : null };
}

function claims(accessToken) {
  const p = accessToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
  return JSON.parse(Buffer.from(p, 'base64').toString('utf8'));
}

async function canjearCodigo(code) {
  const r = await fetch(`${KC}/realms/${REALM}/protocol/openid-connect/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: CLIENT,
      code,
      redirect_uri: REDIRECT,
      code_verifier: VERIFIER,
    }),
  });
  return await r.json();
}

const codigoDeUrl = (url) => new URL(url).searchParams.get('code');

async function main() {
  const navegador = await chromium.launch();
  const contexto = await navegador.newContext();
  const pagina = await contexto.newPage();

  // Autenticador virtual: passkey de plataforma con verificación de usuario
  // siempre satisfecha (equivale a Face ID / huella siempre OK).
  const cdp = await contexto.newCDPSession(pagina);
  await cdp.send('WebAuthn.enable', { enableUI: false });
  const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', {
    options: {
      protocol: 'ctap2',
      ctap2Version: 'ctap2_1',
      transport: 'internal',
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
      backupEligibility: true,
      backupState: true,
    },
  });
  log(`Autenticador virtual: ${authenticatorId}`);

  // -------------------------------------------------------------------
  paso('1. Registro de la passkey (entrando con contraseña)');
  pagina.on('dialog', (d) => d.accept('Passkey del spike'));
  await pagina.goto(authUrl());
  log('pantalla 1 — campos:', await pagina.$$eval('input', (e) => e.map((x) => `${x.name}:${x.type}`)));
  await pagina.fill('#username', 'cajera1');
  await pagina.click('#kc-login');
  await pagina.waitForTimeout(1500);
  log('pantalla 2 — campos:', await pagina.$$eval('input', (e) => e.map((x) => `${x.name}:${x.type}`)));
  await pagina.fill('#password', 'spike');
  await pagina.click('#kc-login');
  await pagina.waitForTimeout(2000);
  log('pantalla 3 — texto:', (await pagina.innerText('body')).slice(0, 200).replace(/\n/g, ' | '));
  await pagina.click('#registerWebAuthn');
  await pagina.waitForURL(/\/cb\?/, { timeout: 20000 });
  log('registro completado, redirigido a:', pagina.url().slice(0, 90) + '...');

  const cred = await admin('GET', `/users/${await idDe('cajera1')}/credentials`);
  log('credenciales del usuario:', cred.body.map((c) => `${c.type}(${c.userLabel ?? '-'})`).join(', '));

  // -------------------------------------------------------------------
  paso('2. Login SIN contraseña con la passkey');
  await contexto.clearCookies();
  await pagina.goto(authUrl());
  await pagina.fill('#username', 'cajera1');
  await pagina.click('#kc-login');
  await pagina.waitForTimeout(1500);
  log('pantalla 2 — pide contraseña:', !!(await pagina.$('#password')));
  if (await pagina.$('#password')) {
    log('   → Keycloak ofrece primero la credencial por defecto del usuario;');
    log('     se cambia con "Try Another Way".');
    await pagina.click('#try-another-way, a:has-text("Try Another Way")');
    await pagina.waitForTimeout(800);
    log('opciones:', (await pagina.innerText('body')).slice(0, 300).replace(/\n/g, ' | '));
    await pagina.click('text=Passkey');
    await pagina.waitForTimeout(1200);
  }
  await pagina.evaluate(() => document.getElementById('authenticateWebAuthnButton').click());
  await pagina.waitForURL(/\/cb\?/, { timeout: 20000 });
  const tok = await canjearCodigo(codigoDeUrl(pagina.url()));
  const c = claims(tok.access_token);
  log('LOGIN PASSWORDLESS OK · claims relevantes:');
  log(JSON.stringify({ scope: c.scope, acr: c.acr, organization: c.organization }, null, 2));

  // -------------------------------------------------------------------
  paso('3. Passkey como credencial por defecto (moveToFirst)');
  const uid = await idDe('cajera1');
  const creds = (await admin('GET', `/users/${uid}/credentials`)).body;
  const pk = creds.find((x) => x.type === 'webauthn-passwordless');
  const mv = await admin('POST', `/users/${uid}/credentials/${pk.id}/moveToFirst`);
  log('moveToFirst →', mv.status);
  await contexto.clearCookies();
  await pagina.goto(authUrl());
  await pagina.fill('#username', 'cajera1');
  await pagina.click('#kc-login');
  await pagina.waitForTimeout(1800);
  log('pantalla 2 — pide contraseña:', !!(await pagina.$('#password')));
  log('pantalla 2 — ofrece passkey:', !!(await pagina.$('#authenticateWebAuthnButton')));
  await pagina.evaluate(() => document.getElementById('authenticateWebAuthnButton').click());
  await pagina.waitForURL(/\/cb\?/, { timeout: 20000 });
  const tok2 = await canjearCodigo(codigoDeUrl(pagina.url()));
  const c2 = claims(tok2.access_token);
  log('LOGIN PASSWORDLESS DIRECTO OK · organization:', JSON.stringify(c2.organization));

  await navegador.close();

  async function idDe(username) {
    const r = await admin('GET', `/users?username=${username}&exact=true`);
    return r.body[0].id;
  }
}

main().catch((e) => {
  console.error('FALLÓ:', e);
  process.exit(1);
});
