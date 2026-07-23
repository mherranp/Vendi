import { expect, test } from '@playwright/test';

import { iniciarSesionConContrasena, sufijoUnico } from './helpers/sesion';
import {
  URL_ADMIN,
  USUARIO_PLATAFORMA,
  buscarUsuario,
  limpiarBloqueo,
  requerido,
  tokenDeAdministracion,
} from './helpers/stack';

/**
 * Criterio 3 de cierre de la Fase 0: «CRUD de tenant funcionando», visto desde
 * la consola de plataforma (`vendi-admin`, https://admin.vendi.co).
 *
 * El recorrido es el del plan: crear → suspender → eliminar, comprobando el
 * estado en la interfaz después de cada paso. Se añade un cuarto tramo que el
 * plan no pide y que importa: tras la baja lógica el negocio DESAPARECE del
 * listado por defecto y solo reaparece al activar «Ver también los
 * eliminados». Una baja que borrase la fila de verdad también pasaría los tres
 * primeros pasos, y no es lo que hace —ni debe hacer— el sistema: los datos se
 * conservan para auditoría.
 *
 * Lo que este spec demuestra por debajo de la UI: el alta crea la fila y su
 * Organization en Keycloak, el `PATCH` de estado viaja y persiste, y el
 * listado paginado del servidor devuelve lo que la pantalla pinta.
 *
 * REENTRANTE: cada ejecución usa un nombre distinto (`sufijoUnico`) y termina
 * dejando su negocio dado de baja. No hay estado compartido entre ejecuciones,
 * así que `--repeat-each=5` es honesto.
 */
test.describe('CRUD de negocios en la consola de plataforma', () => {
  test('crea, suspende y elimina un negocio', async ({ page }) => {
    const token = await tokenDeAdministracion();
    const usuario = await buscarUsuario(token, USUARIO_PLATAFORMA);
    // Un fallo de una ejecución anterior deja armado el contador de fuerza
    // bruta y el login siguiente falla con credenciales correctas.
    await limpiarBloqueo(token, usuario.id);

    await iniciarSesionConContrasena(page, {
      urlApp: URL_ADMIN,
      usuario: USUARIO_PLATAFORMA,
      contrasena: requerido('SEED_ADMIN_PASSWORD'),
    });

    // La consola redirige a `/negocios`. Si el usuario no tuviera el permiso
    // `platform:admin` aterrizaría en `/sin-acceso`: comprobarlo aquí evita
    // que un fallo de permisos se disfrace de «no encuentro el botón».
    await expect(page).toHaveURL(/\/negocios/);
    await expect(page.getByRole('heading', { name: 'Negocios' })).toBeVisible();

    // El shell saluda a quien entró: el perfil sale de los claims del token y
    // no de `loadUserProfile()`, que devuelve 401 con este token. Ver el
    // comentario de `AuthService.cargarPerfil()`.
    const nombreEsperado = `${usuario.firstName ?? ''} ${usuario.lastName ?? ''}`.trim();
    await expect(page.locator('.vd-shell__usuario')).toHaveText(nombreEsperado);

    const nombre = `Tienda ${sufijoUnico()}`;
    const fila = page.getByRole('row').filter({ hasText: nombre });

    // --- Alta ---------------------------------------------------------------
    await page.getByRole('button', { name: 'Nuevo negocio' }).click();
    const dialogo = page.getByRole('dialog');
    await expect(dialogo).toBeVisible();
    await dialogo.getByLabel('Nombre del negocio').fill(nombre);
    await dialogo.getByRole('button', { name: 'Guardar' }).click();

    // El listado del servidor ordena por fecha de creación descendente, así
    // que el recién creado entra en la primera página sin tener que paginar.
    await expect(fila).toBeVisible({ timeout: 30_000 });
    await expect(fila).toContainText('Activo');

    // El identificador que pinta la tabla es el `tenant_id`, que es también el
    // alias de la Organization en Keycloak (`alias = str(tenant_id)`, spike
    // 1.1). Que sea un UUID es la señal de que el alta llegó hasta el IdP.
    const textoFila = await fila.innerText();
    const identificador = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/.exec(
      textoFila,
    );
    expect(
      identificador,
      `la fila no muestra un identificador de negocio: ${textoFila}`,
    ).not.toBeNull();

    // --- Suspensión ---------------------------------------------------------
    await fila.getByRole('button', { name: 'Acciones del negocio' }).click();
    await page.getByRole('menuitem', { name: 'Suspender' }).click();
    await page.getByRole('button', { name: 'Suspender', exact: true }).click();
    await expect(fila).toContainText('Suspendido', { timeout: 30_000 });

    // --- Baja lógica --------------------------------------------------------
    await fila.getByRole('button', { name: 'Acciones del negocio' }).click();
    await page.getByRole('menuitem', { name: 'Eliminar' }).click();
    await page.getByRole('button', { name: 'Eliminar', exact: true }).click();

    // Desaparece del listado por defecto: la operación diaria no debe ver
    // negocios dados de baja.
    await expect(fila).toHaveCount(0, { timeout: 30_000 });

    // --- Pero sigue ahí, para auditoría -------------------------------------
    await page.getByRole('switch', { name: 'Ver también los eliminados' }).click();
    await expect(fila).toBeVisible({ timeout: 30_000 });
    await expect(fila).toContainText('Eliminado');

    // Y un negocio ya dado de baja no ofrece volver a borrarse.
    await fila.getByRole('button', { name: 'Acciones del negocio' }).click();
    await expect(page.getByRole('menuitem', { name: 'Eliminar' })).toHaveCount(0);
    await page.keyboard.press('Escape');
  });
});
