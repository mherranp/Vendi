/**
 * Tipos de la verdad local del dispositivo (ADR-017/ADR-018).
 *
 * Son los contratos internos de `data-access`: lo que el POS lee y escribe en
 * IndexedDB. No son los contratos de la API —los del lote de sync se arman en
 * el momento de encolar— aunque se parezcan a propósito.
 */

/** Estados de una operación en la cola de sincronización. */
export type EstadoOperacion = 'pendiente' | 'enviando' | 'error';

/**
 * Operaciones que el dispositivo sabe encolar. `venta.anular` entra cuando la
 * UI de anulación llegue (decisión 12 del plan); el tipo se deja cerrado a
 * propósito: añadir una operación es una decisión, no un string suelto.
 */
export type TipoOperacion = 'venta.crear' | 'cliente.crear';

/** Producto del catálogo local (lo que baja el delta de ADR-017). */
export interface ProductoLocal {
  id: string;
  nombre: string;
  categoria: string | null;
  codigo_barras: string | null;
  /** Centavos enteros (ADR-018). */
  precio_venta: number;
  unidad_medida: string;
  /** Decimal de la API como string (granel); es dato de exhibición, no se opera. */
  stock_actual: string;
}

/**
 * Cliente conocido por el dispositivo. `origen: 'local'` lo creó este
 * dispositivo (sube como `cliente.crear`); `'servidor'` se asimiló online por
 * `GET /clientes` (no hay delta de clientes — D-28).
 */
export interface ClienteLocal {
  id: string;
  nombre: string;
  telefono: string | null;
  limite_credito: number | null;
  origen: 'local' | 'servidor';
}

/** Línea de una venta local: el precio y el nombre se congelan en la venta. */
export interface LineaVentaLocal {
  producto_id: string;
  /** Desnormalizado: el ticket no cambia aunque el catálogo cambie después. */
  nombre: string;
  /** Mili-unidades enteras: 1500 = 1,5 kg (granel de 3 decimales). */
  cantidad_mili: number;
  precio_unitario_centavos: number;
  total_linea_centavos: number;
}

/** La venta append-only tal como la creó el dispositivo (ADR-018). */
export interface VentaLocal {
  id: string;
  /** El número que ve el tendero; monotónico por dispositivo. */
  consecutivo_local: number;
  estado: 'completada' | 'anulada';
  medio_pago: 'efectivo' | 'fiado';
  total_centavos: number;
  cliente_id: string | null;
  /** Desnormalizado: el historial se lee sin red y sin joins. */
  cliente_nombre: string | null;
  /** `YYYY-MM-DD` o null; solo fiado. */
  fecha_vencimiento: string | null;
  /** ISO 8601 con zona; marca del reloj del dispositivo: dato, no árbitro. */
  creada_en_cliente: string;
  items: LineaVentaLocal[];
}

/**
 * Operación encolada para el lote de sync. `id` ES la PK de la entidad que
 * creó (la venta o el cliente): la idempotencia del servidor es por esa PK
 * (ADR-017). `datos` lleva el shape exacto del schema del módulo dueño de la
 * operación (`VentaCrearSync`, `ClienteCrearSync`).
 */
export interface OperacionEnCola {
  id: string;
  tipo: TipoOperacion;
  /** Orden FIFO por dispositivo; monotónica, sin huecos garantizados. */
  secuencia: number;
  datos: Record<string, unknown>;
  estado: EstadoOperacion;
  intentos: number;
  /** Epoch ms a partir del cual se puede reintentar; 0 = ya. */
  proximo_intento_en: number;
  /** Motivo estable del servidor cuando `estado` es `error` (dead-letter). */
  ultimo_error: string | null;
  creada_en: number;
}

/** Claves de la tabla `meta` (configuración y contadores del dispositivo). */
export type ClaveMeta =
  | 'dispositivo_id'
  | 'nombre_dispositivo'
  | 'dispositivo_registrado'
  | 'ultima_secuencia'
  | 'consecutivo_local'
  | 'delta_hasta';

export interface EntradaMeta {
  clave: ClaveMeta;
  valor: string | number | boolean;
}
