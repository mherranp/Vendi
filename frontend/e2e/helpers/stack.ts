/**
 * Utilidades compartidas por los specs de extremo a extremo.
 *
 * Aquí vive todo lo que habla con el stack POR FUERA del navegador: la lectura
 * de `.env`, las URLs de los servicios y el cliente de la API de
 * administración de Keycloak. Los specs solo describen el flujo del usuario.
 *
 * PROTECCIÓN DE RESOLUCIÓN — no la quites. El dominio `vendi.co` no es del
 * dueño del producto: está registrado por un tercero y resuelve públicamente a
 * una IP ajena. Mientras no exista `/etc/resolver/vendi.co`, toda petición a
 * `*.vendi.co` que no fije la resolución sale a internet, a un servidor que no
 * controlamos. `pedir()` fija el destino a 127.0.0.1 sin tocar el `Host` ni el
 * SNI; el navegador hace lo propio con `--host-resolver-rules` (ver
 * `playwright.config.ts`).
 */
import { readFileSync } from 'node:fs';
import { request as peticionHttps } from 'node:https';
import { resolve } from 'node:path';

// `__dirname` y no `import.meta.url`: `frontend/package.json` no declara
// `"type": "module"`, así que el transpilador de Playwright emite CommonJS y
// `import.meta` sería un error de sintaxis en tiempo de ejecución.
/** Raíz del repositorio: tres niveles por encima de `frontend/e2e/helpers`. */
export const RAIZ = resolve(__dirname, '../../..');

/**
 * Variables de entorno efectivas: las del proceso mandan sobre las del `.env`.
 *
 * Ese orden y no el contrario porque en CI no hay `.env` —los valores llegan
 * como secretos del workflow— y en el portátil sí lo hay. Si el `.env` ganara,
 * un desarrollador con el stack local levantado no podría apuntar las pruebas
 * a otro entorno ni con variables por delante del comando.
 */
function cargarEntorno(): Record<string, string> {
  const entorno: Record<string, string> = {};
  try {
    const texto = readFileSync(resolve(RAIZ, '.env'), 'utf8');
    for (const linea of texto.split('\n')) {
      const par = /^([A-Za-z0-9_]+)=(.*)$/.exec(linea.trim());
      if (par) entorno[par[1]] = par[2].replace(/^["']|["']$/g, '');
    }
  } catch {
    // Sin `.env` no pasa nada: es el caso de CI.
  }
  for (const [clave, valor] of Object.entries(process.env)) {
    if (valor !== undefined) entorno[clave] = valor;
  }
  return entorno;
}

export const ENTORNO = cargarEntorno();

/**
 * Lee una variable obligatoria y falla con un mensaje que dice qué hacer.
 *
 * Un `undefined` que se cuela hasta el formulario de Keycloak produce
 * «credenciales inválidas», que manda a depurar el sitio equivocado.
 */
export function requerido(clave: string): string {
  const valor = ENTORNO[clave];
  if (!valor) {
    throw new Error(
      `Falta la variable ${clave}. En local: copia .env.example a .env y levanta el stack de infra/. En CI: decláralo como secreto del workflow.`,
    );
  }
  return valor;
}

export const DOMINIO_BASE = ENTORNO['BASE_DOMAIN'] ?? 'vendi.co';

/** Regla de resolución para Chromium. La consume `playwright.config.ts`. */
export const REGLAS_DE_RESOLUCION = `MAP *.${DOMINIO_BASE} 127.0.0.1, MAP ${DOMINIO_BASE} 127.0.0.1`;

export const URL_PORTAL = `https://${DOMINIO_BASE}`;
/** `vendi-tenant`: la consola web del dueño del negocio. */
export const URL_APP = `https://app.${DOMINIO_BASE}`;
/** `vendi-admin`: la consola de plataforma (nosotros). */
export const URL_ADMIN = `https://admin.${DOMINIO_BASE}`;
export const URL_CUENTAS = `https://accounts.${DOMINIO_BASE}`;
export const REALM = 'vendi-co';

/** Usuario de plataforma sembrado por `scripts/seed.sh`. */
export const USUARIO_PLATAFORMA = 'admin@vendi.co';
/** Dueño del negocio de demostración, también de `seed.sh`. */
export const USUARIO_DUENO = 'dueno@demo.vendi.co';
/** Nombre comercial del negocio de demostración. */
export const NEGOCIO_DEMO = 'Tienda Don Carlos';

interface RespuestaSimple {
  ok: boolean;
  status: number;
  texto: string;
}

/**
 * Petición HTTPS contra el stack con la resolución fijada al bucle local.
 *
 * Es el equivalente en Node de `curl --resolve host:443:127.0.0.1`. El nombre
 * y el SNI siguen siendo los reales —Traefik enruta por `Host` y el
 * certificado de mkcert valida contra ellos—, pero el socket nunca sale de la
 * máquina.
 *
 * `rejectUnauthorized` NO se toca: la validación TLS se queda encendida a
 * propósito. Requiere que Node confíe en la CA de mkcert, que es lo que hace
 * `node --use-system-ca` (ver el script `e2e` de package.json).
 */
export function pedir(
  url: string,
  opciones: { method?: string; headers?: Record<string, string>; body?: string } = {},
): Promise<RespuestaSimple> {
  const destino = new URL(url);
  return new Promise((resolver, rechazar) => {
    const peticion = peticionHttps(
      {
        protocol: destino.protocol,
        hostname: destino.hostname,
        port: destino.port || 443,
        path: `${destino.pathname}${destino.search}`,
        method: opciones.method ?? 'GET',
        headers: opciones.headers ?? {},
        servername: destino.hostname,
        // Aquí vive la protección. Node pide la respuesta como lista cuando
        // usa `all: true`, así que se contemplan las dos formas.
        lookup: (
          _nombre: string,
          opcionesDns: { all?: boolean },
          cb: (
            err: NodeJS.ErrnoException | null,
            direccion: string | { address: string; family: number }[],
            familia?: number,
          ) => void,
        ) =>
          opcionesDns?.all
            ? cb(null, [{ address: '127.0.0.1', family: 4 }])
            : cb(null, '127.0.0.1', 4),
      },
      (respuesta) => {
        let cuerpo = '';
        respuesta.on('data', (trozo) => (cuerpo += trozo));
        respuesta.on('end', () =>
          resolver({
            ok: (respuesta.statusCode ?? 0) >= 200 && (respuesta.statusCode ?? 0) < 300,
            status: respuesta.statusCode ?? 0,
            texto: cuerpo,
          }),
        );
      },
    );
    peticion.on('error', rechazar);
    if (opciones.body) peticion.write(opciones.body);
    peticion.end();
  });
}

/**
 * Token de administración del realm `master`.
 *
 * Se usa `admin-cli` con contraseña (ROPC) porque es la credencial de
 * administración del propio Keycloak, no la de la aplicación: `vendi-web`
 * tiene ROPC APAGADO a propósito (deuda D-01 — con ROPC encendido se podía
 * obtener un token completo solo con contraseña, anulando la política de
 * passkey). Estas pruebas no lo reactivan ni dependen de que esté encendido.
 */
export async function tokenDeAdministracion(): Promise<string> {
  const respuesta = await pedir(`${URL_CUENTAS}/realms/master/protocol/openid-connect/token`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: 'admin-cli',
      username: requerido('KEYCLOAK_ADMIN_USER'),
      password: requerido('KEYCLOAK_ADMIN_PASSWORD'),
      grant_type: 'password',
    }).toString(),
  });
  if (!respuesta.ok) {
    throw new Error(
      `No se pudo autenticar contra Keycloak (${respuesta.status}). ¿Está el stack de infra/ levantado?`,
    );
  }
  return JSON.parse(respuesta.texto).access_token as string;
}

/** Llamada a la API de administración del realm `vendi-co`. */
export async function kcAdmin<T = unknown>(
  token: string,
  ruta: string,
  opciones: { method?: string; body?: unknown } = {},
): Promise<T | null> {
  const respuesta = await pedir(`${URL_CUENTAS}/admin/realms/${REALM}${ruta}`, {
    method: opciones.method,
    headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
    body: opciones.body === undefined ? undefined : JSON.stringify(opciones.body),
  });
  if (!respuesta.ok && respuesta.status !== 204) {
    throw new Error(
      `Keycloak ${opciones.method ?? 'GET'} ${ruta} → ${respuesta.status}: ${respuesta.texto.slice(0, 200)}`,
    );
  }
  return respuesta.texto ? (JSON.parse(respuesta.texto) as T) : null;
}

/**
 * Deja al usuario sin bloqueo por fuerza bruta antes de un login.
 *
 * Sin esto, un fallo de una ejecución anterior deja el contador armado y la
 * siguiente ejecución falla con «credenciales inválidas» aunque las
 * credenciales sean correctas: un flake que manda a depurar el sitio
 * equivocado. Es idempotente — si no estaba bloqueado, Keycloak responde 204.
 */
export async function limpiarBloqueo(token: string, idUsuario: string): Promise<void> {
  await kcAdmin(token, `/attack-detection/brute-force/users/${idUsuario}`, { method: 'DELETE' });
}

export interface UsuarioDeRealm {
  id: string;
  username: string;
  firstName?: string;
  lastName?: string;
  requiredActions?: string[];
}

/** Busca un usuario del realm por nombre de usuario exacto. */
export async function buscarUsuario(token: string, usuario: string): Promise<UsuarioDeRealm> {
  const encontrados = await kcAdmin<UsuarioDeRealm[]>(
    token,
    `/users?username=${encodeURIComponent(usuario)}&exact=true`,
  );
  const primero = encontrados?.[0];
  if (!primero) {
    throw new Error(
      `No existe ${usuario} en el realm ${REALM}. Ejecuta scripts/seed.sh antes de las pruebas.`,
    );
  }
  return primero;
}
