/*
 * El tenant: un negocio dentro de la región.
 *
 * Alineado con el contrato de la Tarea 4.2 del plan:
 *   POST   /api/v1/platform/tenants {nombre} → 201 {id, nombre, estado}
 *   GET    /api/v1/platform/tenants?skip&limit → PagedList<Tenant>
 *   PATCH  /api/v1/platform/tenants/{id} {nombre?, estado?}
 *   GET    /api/v1/tenants/me → {id, nombre, estado}
 *
 * El `id` es además el alias de la Organization de Keycloak
 * (`alias = str(tenant_id)`), así que este mismo valor es el que viaja en el
 * claim `organization` del token.
 */

/**
 * Estado del tenant. La suspensión es **app-level**: con realm único,
 * deshabilitar la Organization de Keycloak no bloquea el login (hallazgo del
 * spike 1.1), así que quien corta el acceso es la API leyendo esta columna.
 *
 * - `activo`: opera con normalidad.
 * - `suspendido`: autentica, pero la API responde 403 `tenant_suspendido` en
 *   las rutas de tenant. Los datos siguen ahí.
 * - `eliminado`: baja lógica; no debería aparecer en listados por defecto.
 */
export type EstadoTenant = 'activo' | 'suspendido' | 'eliminado';

/** Lista cerrada de estados, para validar entrada externa en tiempo de ejecución. */
export const ESTADOS_TENANT: readonly EstadoTenant[] = ['activo', 'suspendido', 'eliminado'];

export interface Tenant {
  /** UUID. Es también el alias de la Organization en Keycloak. */
  id: string;
  /** Nombre comercial del negocio, tal como lo escribió el dueño. */
  nombre: string;
  estado: EstadoTenant;
  /**
   * Plan de suscripción.
   *
   * Discrepancia con el plan, deliberada: la Tarea 3.9 pide `plan` en el
   * modelo, pero el contrato de la Tarea 4.2 devuelve solo `{id, nombre,
   * estado}` — la monetización está fuera del alcance de Fase 0 (subproyecto
   * 4). Se declara **opcional** para que el día que la API lo emita el tipo ya
   * lo admita, y para que hoy nadie escriba `tenant.plan` creyendo que llega.
   */
  plan?: string | null;
}

/**
 * El tenant **tal como llega por el cable**, con `estado` sin estrechar.
 *
 * Existe porque `Tenant.estado` es una unión cerrada y el JSON de la API no lo
 * es: el día que el backend añada `en_mora`, un `as Tenant` haría que
 * TypeScript jurara que el valor es uno de los tres conocidos y el `switch` de
 * la insignia caería en una rama equivocada sin que nadie se entere.
 *
 * La regla en las apps: se recibe `TenantDeApi`, y solo se estrecha a
 * `EstadoTenant` pasando por `esEstadoTenant()`. Un estado desconocido se
 * pinta en neutro con su texto crudo —que es información útil para quien
 * administra— en vez de disfrazarse de "activo".
 */
export interface TenantDeApi extends Omit<Tenant, 'estado'> {
  estado: string;
}

/**
 * ¿El estado recibido por HTTP es uno de los que conocemos?
 *
 * Guarda de tipo para no confiar en que el backend y el frontend evolucionen a
 * la vez: un estado nuevo (`en_mora`, por ejemplo) llegaría como string y sin
 * esta comprobación se colaría en un `switch` como si fuera conocido.
 */
export function esEstadoTenant(valor: unknown): valor is EstadoTenant {
  return typeof valor === 'string' && (ESTADOS_TENANT as readonly string[]).includes(valor);
}
