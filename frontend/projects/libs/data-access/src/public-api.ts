/*
 * Public API Surface of data-access
 *
 * Persistencia local (Dexie/IndexedDB como fuente de verdad offline),
 * cola de sincronización y cliente de la API.
 * El acceso a plataforma va por native.
 */

// --- Cliente HTTP ---------------------------------------------------------
export { API_BASE_URL, ApiService } from './lib/api.service';
export type { OpcionesDeLlamada } from './lib/api.service';

// --- Interceptores --------------------------------------------------------
export { correlationIdInterceptor } from './lib/interceptors/correlation-id.interceptor';
export {
  SILENCIAR_AVISO_ERROR,
  claveDeError,
  errorInterceptor,
  extraerMensajeDeError,
} from './lib/interceptors/error.interceptor';

// --- Avisos al usuario ----------------------------------------------------
export { Notificador } from './lib/notificaciones/notificador.service';
export type { Aviso, TipoDeAviso } from './lib/notificaciones/notificador.service';

// --- i18n -----------------------------------------------------------------
export { CATALOGO_MINIMO_ES, textoDeRespaldo } from './lib/i18n/catalogo-minimo';
export type { CatalogoTraducciones } from './lib/i18n/catalogo-minimo';
export { traducir } from './lib/i18n/traduccion';
export {
  CATALOGO_DE_RESPALDO,
  CargadorDeTraduccionesResiliente,
  ESPERA_MAXIMA_CATALOGO_MS,
  IDIOMA_POR_DEFECTO,
  fusionarCatalogos,
  proveerI18nVendi,
} from './lib/i18n/i18n.provider';

// --- Servicios ------------------------------------------------------------
export { FeatureFlagsService } from './lib/services/feature-flags.service';

// --- Offline (ADR-017/ADR-018): IndexedDB como verdad local ----------------
export { VendiDb } from './lib/offline/vendi.db';
export { VentasOfflineService } from './lib/offline/ventas-offline.service';
export type { EntradaCobro } from './lib/offline/ventas-offline.service';
export type {
  ClaveMeta,
  ClienteLocal,
  EntradaMeta,
  EstadoOperacion,
  LineaVentaLocal,
  OperacionEnCola,
  ProductoLocal,
  TipoOperacion,
  VentaLocal,
} from './lib/offline/modelos-locales';

// --- Cliente generado desde el OpenAPI de la API --------------------------
export * from './lib/api-client';
