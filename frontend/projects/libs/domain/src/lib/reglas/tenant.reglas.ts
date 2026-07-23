/*
 * Reglas de negocio del tenant. Funciones puras: sin Angular, sin RxJS, sin
 * red. Son la parte que "decide" (la regla de oro de `domain`: el código
 * decide, la IA narra), y por eso viven donde se pueden probar sin arrancar
 * nada.
 */
import { EstadoTenant, Tenant } from '../models/tenant.model';

/**
 * Expresión de un UUID canónico (8-4-4-4-12, con guiones, sin llaves).
 *
 * No valida la versión ni el bit de variante a propósito: Keycloak devuelve el
 * alias literalmente como se creó, y el objetivo aquí es rechazar basura
 * (`'undefined'`, `'null'`, un slug heredado), no auditar RFC 4122.
 */
const RE_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * ¿El valor tiene forma de identificador de tenant?
 *
 * El alias de la Organization de Keycloak **es** el `tenant_id`
 * (`alias = str(tenant_id)`). El backend responde 401 si el alias del claim no
 * es un UUID, en vez de dejar que reviente como error de casteo en PostgreSQL
 * (deuda D-06 de la Etapa 1). El frontend aplica el mismo filtro antes de
 * tratar un alias como tenant: si Keycloak devolviera un alias no-UUID, la
 * consecuencia debe ser "no hay tenant seleccionado", no una cabecera
 * `X-Tenant-Id` con basura.
 */
export function esIdDeTenant(valor: unknown): boolean {
  return typeof valor === 'string' && RE_UUID.test(valor);
}

/**
 * ¿El tenant puede operar (vender, registrar, modificar)?
 *
 * Solo `activo`. Un tenant `suspendido` conserva sus datos y su sesión, pero la
 * API rechaza las escrituras con 403 `tenant_suspendido`; la UI debe reflejarlo
 * antes de dejar que el usuario llene un formulario que va a rebotar.
 */
export function esTenantOperativo(tenant: Pick<Tenant, 'estado'> | null | undefined): boolean {
  return tenant?.estado === 'activo';
}

/**
 * ¿Un tenant en este estado debe seguir siendo visible en la consola?
 *
 * `eliminado` es una baja lógica: sigue en la base de datos por auditoría, pero
 * no se lista salvo que se pidan explícitamente los eliminados.
 */
export function esEstadoVisible(estado: EstadoTenant): boolean {
  return estado !== 'eliminado';
}
