import type { components, paths } from 'data-access';
import type { EstadoTenant, PagedList, TenantDeApi } from 'domain';
import type { CambiosDeTenant } from './tenants.service';

/*
 * Amarre en tiempo de compilación entre los tipos que usa esta app y el esquema
 * OpenAPI que publica la API.
 *
 * Los componentes siguen hablando en el lenguaje de `domain` (`TenantDeApi`,
 * `PagedList`, `EstadoTenant`) y no en el del generador —que emite nombres como
 * `PagedList_TenantSalida_` y obliga a escribir
 * `components['schemas']['TenantSalida']` en cada firma—. Este archivo es el
 * puente: no genera código ni se ejecuta, pero si el backend cambia el
 * contrato, `ng build` de esta app falla con el campo exacto que dejó de
 * cuadrar.
 *
 * Sin esto, "el cliente está generado" sería un hecho decorativo: el cliente
 * viviría en `data-access` sin que nada de la aplicación lo mirara, y la deriva
 * entre frontend y API solo aparecería en tiempo de ejecución.
 *
 * Para regenerar el cliente:
 *
 *     bash scripts/codegen-api-client.sh            # contra la API viva
 *     CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh
 */

type TenantSalidaDelEsquema = components['schemas']['TenantSalida'];
type TenantCrearDelEsquema = components['schemas']['TenantCrear'];
type TenantActualizarDelEsquema = components['schemas']['TenantActualizar'];
type PaginaDelEsquema = components['schemas']['PagedList_TenantSalida_'];
type EstadoDelEsquema = components['schemas']['EstadoTenant'];

/** Falla la compilación si `T` no es asignable a `Esperado`. */
type Conforma<T extends Esperado, Esperado> = T;

// --- Lo que la API devuelve encaja en lo que la app espera leer -------------
//
// La dirección importa: el esquema tiene que ser asignable a nuestro tipo, no
// al revés. `TenantSalida` trae además `kc_org_id` y `created_at`, que esta
// pantalla todavía no pinta; campos de más no rompen a nadie, campos de menos
// sí.
export type _RespuestaDeTenantEsLegible = Conforma<TenantSalidaDelEsquema, TenantDeApi>;
export type _PaginaEsLegible = Conforma<PaginaDelEsquema, PagedList<TenantDeApi>>;

// --- Lo que la app envía encaja en lo que la API acepta ---------------------
//
// Aquí la dirección se invierte: nuestro cuerpo de petición tiene que ser
// asignable al del esquema. Si el backend añade un campo obligatorio a
// `TenantCrear`, esta línea deja de compilar.
export type _AltaEsAceptable = Conforma<{ nombre: string }, TenantCrearDelEsquema>;
export type _CambioEsAceptable = Conforma<CambiosDeTenant, TenantActualizarDelEsquema>;

// --- Los estados son exactamente los mismos, en ambos sentidos -------------
//
// Doble comprobación a propósito: si el backend añadiera `en_mora` sin que este
// frontend lo conozca, la segunda línea falla y avisa de que hay que decidir
// cómo se pinta. Nótese que **no** rompe en tiempo de ejecución: la interfaz ya
// degrada un estado desconocido a neutro (ver `estados.ts`). Esto es el aviso
// temprano, no la red de seguridad.
export type _EstadoConocidoPorLaApi = Conforma<EstadoTenant, EstadoDelEsquema>;
export type _EstadoConocidoPorLaApp = Conforma<EstadoDelEsquema, EstadoTenant>;

// --- Las rutas existen y con los métodos que usa el servicio ---------------
//
// Un cambio de `/platform/tenants` a `/platform/negocios` en el backend no
// tiene por qué romper ningún tipo: las URLs son cadenas dentro del servicio.
// Estas líneas las convierten en algo que el compilador comprueba.
export type _RutaDeColeccion = paths['/api/v1/platform/tenants']['get'];
export type _RutaDeAlta = paths['/api/v1/platform/tenants']['post'];
export type _RutaDeElemento = paths['/api/v1/platform/tenants/{tenant_id}']['patch'];
export type _RutaDeBaja = paths['/api/v1/platform/tenants/{tenant_id}']['delete'];
