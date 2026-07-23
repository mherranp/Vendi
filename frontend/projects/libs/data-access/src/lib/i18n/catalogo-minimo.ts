/*
 * Catálogo de respaldo empotrado en el bundle.
 *
 * Existe por un motivo concreto: el arranque de i18n **no puede ser
 * fail-hard**. Si `/i18n/es.json` no se puede descargar —red caída, PWA
 * instalada sin conexión, caché del service worker vacía, 404 tras un despliegue
 * a medias— y el `APP_INITIALIZER` espera a esa promesa sin red de seguridad,
 * Angular aborta el bootstrap y el usuario ve una **pantalla en blanco**. Para
 * un punto de venta que promete funcionar sin conexión eso es inaceptable.
 *
 * Con este catálogo, el peor caso deja de ser "pantalla en blanco" y pasa a ser
 * "la app arranca en español, con todos sus textos".
 *
 * ## Por qué es COMPLETO y no "mínimo"
 *
 * La primera versión de este archivo solo traía `app`, `comun`, `layout` y
 * `errores`, con el argumento de que eran "las cadenas sin las cuales la
 * interfaz no se puede usar". Era un error de razonamiento, y el QA lo demostró
 * ejecutando la rama de respaldo: los componentes de `ui-kit` no llaman a
 * `traducir()` —que sí sabe caer aquí—, sino al pipe `| translate` directo, y
 * ngx-translate devuelve la clave cruda cuando no la encuentra. En el escenario
 * exacto que este archivo ataca (catálogo inaccesible, PWA sin red) la app
 * arrancaba pintando `ui.404.titulo`, `ui.vacio.titulo`, `ui.archivos.buscar` y
 * un `ui.validacion.requerido` debajo de cada campo obligatorio de cada
 * formulario. "Arranca con identificadores técnicos en pantalla" no es mejor
 * que la pantalla en blanco: es peor, porque parece que funciona.
 *
 * La regla, por tanto: **toda clave que un componente de `ui-kit` o un layout de
 * una app pueda pintar tiene que estar aquí**. El coste es unos cientos de bytes
 * en el bundle; el beneficio es que la promesa "nunca se pinta una clave cruda"
 * es cierta.
 *
 * El catálogo de `ui-kit/testing` (`CATALOGO_DE_PRUEBA`) reexporta esta misma
 * constante justamente para que los specs de componentes se ejecuten contra la
 * ruta degradada de producción y cualquier clave nueva sin respaldo rompa la
 * suite en vez de llegar a un dispositivo.
 *
 * Se usa en dos sitios:
 *  - `CargadorDeTraduccionesResiliente`: respaldo cuando el HTTP falla.
 *  - `textoDeRespaldo()`: respaldo cuando la clave no está en el catálogo
 *    cargado, para no pintar nunca la clave cruda (`errores.servidor`).
 */

/** Estructura anidada de traducciones, tal como la consume ngx-translate. */
export interface CatalogoTraducciones {
  [clave: string]: string | CatalogoTraducciones;
}

export const CATALOGO_MINIMO_ES: CatalogoTraducciones = {
  // `app.titulo` lo sobrescribe cada app en su `public/i18n/es.json`; aquí va el
  // nombre del producto, que sirve para las cuatro.
  app: {
    titulo: 'Vendi',
    descripcion: 'Punto de venta e inventario',
  },
  comun: {
    aceptar: 'Aceptar',
    cancelar: 'Cancelar',
    guardar: 'Guardar',
    eliminar: 'Eliminar',
    buscar: 'Buscar',
    reintentar: 'Reintentar',
    cerrar: 'Cerrar',
  },
  layout: {
    cargando: 'Cargando…',
    reintentar: 'Reintentar',
    error_inesperado: 'Algo salió mal. Vuelve a intentarlo.',
    cuenta: 'Mi cuenta',
    cerrar_sesion: 'Cerrar sesión',
    menu: 'Menú',
  },
  errores: {
    sin_conexion: 'Sin conexión. Revisa tu red e inténtalo de nuevo.',
    sesion_expirada: 'Tu sesión expiró. Vuelve a iniciar sesión.',
    sin_permiso: 'No tienes permiso para hacer esto.',
    no_encontrado: 'No encontramos lo que buscabas.',
    servidor: 'Tuvimos un problema. Vuelve a intentarlo en un momento.',
    solicitud: 'No pudimos completar la operación.',
    tenant_suspendido: 'La cuenta del negocio está suspendida. Contáctanos para reactivarla.',
  },
  // -- Claves de los componentes de `ui-kit` ---------------------------------
  // Todas se pintan con `| translate` directo, sin red de seguridad: si faltan
  // aquí, en modo degradado salen crudas en pantalla.
  ui: {
    vacio: {
      titulo: 'Nada por aquí todavía',
    },
    tabla: {
      vacia: 'Sin registros',
    },
    archivos: {
      suelta_aqui: 'Suelta los archivos aquí',
      buscar: 'Buscar archivo',
    },
    '404': {
      titulo: 'No encontramos esta página',
      descripcion: 'La página que buscas no existe o cambió de sitio.',
      volver: 'Volver al inicio',
    },
    // `claveDelPrimerError()` (ui-kit/forms/validadores.ts) mapea cada error de
    // Angular a una de estas claves. Es lo que ve el usuario en cada `mat-error`
    // de cualquier formulario, también sin conexión.
    validacion: {
      requerido: 'Este campo es obligatorio',
      correo: 'Escribe un correo válido',
      minimo: 'El valor es muy pequeño',
      maximo: 'El valor es muy grande',
      muy_corto: 'Es demasiado corto',
      muy_largo: 'Es demasiado largo',
      formato: 'El formato no es válido',
      invalido: 'Valor inválido',
    },
  },
  notificaciones: {
    titulo: 'Notificaciones',
    marcar_leidas: 'Marcar todas como leídas',
    vacio: 'No hay notificaciones',
  },
  suplantacion: {
    titulo: 'Estás viendo la cuenta de {{usuario}}',
    expira_en: 'Expira en {{segundos}} s',
    detener: 'Salir de la suplantación',
  },
};

/**
 * Texto de respaldo para una clave con notación de punto (`errores.servidor`).
 * Devuelve `null` si la clave no está en el catálogo de respaldo.
 */
export function textoDeRespaldo(clave: string): string | null {
  const partes = clave.split('.');
  let nodo: string | CatalogoTraducciones | undefined = CATALOGO_MINIMO_ES;
  for (const parte of partes) {
    if (typeof nodo !== 'object' || nodo === null) {
      return null;
    }
    nodo = nodo[parte];
  }
  return typeof nodo === 'string' ? nodo : null;
}
