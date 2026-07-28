import { Inject, Injectable, InjectionToken } from '@angular/core';
import Dexie, { Table } from 'dexie';
import type {
  ClienteLocal,
  EntradaMeta,
  OperacionEnCola,
  ProductoLocal,
  VentaLocal,
} from './modelos-locales';

/**
 * La base local del dispositivo: IndexedDB vía Dexie (ADR-017).
 *
 * Es el ÚNICO sitio del workspace donde `dexie` aparece (la frontera ESLint de
 * ADR-011 lo hace cumplir en todos los demás proyectos; `vendi-app` la gana en
 * la Tarea 9 de este plan). El esquema es la decisión 2 del plan:
 *
 *  - `productos` y `clientes`: datos de referencia (LWW por orden de recepción
 *    en el servidor; los clientes llegan online, D-28).
 *  - `ventas_locales`: la verdad local de las ventas, append-only.
 *  - `cola_sync`: el outbox local; la escritura de negocio y el encolado van en
 *    la misma transacción (eso lo garantizan los servicios, no este archivo).
 *  - `meta`: identidad del dispositivo, contadores y watermark del delta.
 *
 * Es inyectable (`providedIn: 'root'`) para que los specs puedan sustituirla
 * por una instancia con nombre propio sobre `fake-indexeddb`; el nombre viene
 * del token `VENDI_NOMBRE_DB` y el constructor lo admite por esa misma razón.
 */
export const VENDI_NOMBRE_DB = new InjectionToken<string>('VENDI_NOMBRE_DB', {
  providedIn: 'root',
  factory: () => 'vendi-offline',
});

@Injectable({ providedIn: 'root' })
export class VendiDb extends Dexie {
  productos!: Table<ProductoLocal, string>;
  clientes!: Table<ClienteLocal, string>;
  ventas_locales!: Table<VentaLocal, string>;
  cola_sync!: Table<OperacionEnCola, string>;
  meta!: Table<EntradaMeta, string>;

  // El nombre debe llegar a super() antes de `this` y los specs instancian la
  // base a mano, sin inyector: inject() no cubre este caso.
  // eslint-disable-next-line @angular-eslint/prefer-inject
  constructor(@Inject(VENDI_NOMBRE_DB) nombre = 'vendi-offline') {
    super(nombre);
    this.version(1).stores({
      productos: 'id, nombre, codigo_barras, categoria',
      clientes: 'id, nombre',
      ventas_locales: 'id, consecutivo_local, creada_en_cliente, estado',
      cola_sync: 'id, secuencia, estado',
      meta: 'clave',
    });
  }
}
