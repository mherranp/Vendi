import { esEstadoTenant } from 'domain';
import { VarianteEstado } from 'ui-kit';

/**
 * Traducción visual del estado de un negocio.
 *
 * El `default` **no** es decorativo: si el backend añade un estado que este
 * frontend no conoce (`en_mora`, por ejemplo), la alternativa a esta rama sería
 * que un `switch` cayera en "activo" y la consola dijera que un negocio moroso
 * está operando con normalidad. Un estado desconocido se pinta neutro y con su
 * texto crudo, que para quien administra la plataforma es información honesta.
 */
export function varianteDeEstado(estado: string): VarianteEstado {
  if (!esEstadoTenant(estado)) {
    return 'neutro';
  }
  switch (estado) {
    case 'activo':
      return 'exito';
    case 'suspendido':
      return 'aviso';
    case 'eliminado':
      return 'peligro';
  }
}

/**
 * Clave de traducción del estado, o el valor crudo si no lo conocemos.
 *
 * `vd-status-badge` pasa la etiqueta por `| translate`; ngx-translate devuelve
 * la entrada tal cual cuando no es una clave del catálogo, así que un estado
 * desconocido se enseña literal en vez de como `tenants.estado.en_mora`.
 */
export function etiquetaDeEstado(estado: string): string {
  return esEstadoTenant(estado) ? `tenants.estado.${estado}` : estado;
}
