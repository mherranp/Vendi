/*
 * Perfil del usuario autenticado.
 *
 * Cosechado de BaseSaaS fusionando dos fuentes que describían lo mismo dos
 * veces: `ui-core/src/lib/models/user.model.ts` (forma del endpoint `/users`,
 * en snake_case, con `Role`/`Permission`/`Group` embebidos) y el `UserProfile`
 * declarado dentro de `ui-core/src/lib/auth/auth.service.ts` (forma derivada
 * del token, en camelCase).
 *
 * Vendi Fase 0 se queda con la **segunda**: el perfil se arma del token y del
 * `loadUserProfile()` de Keycloak, no de un endpoint de usuarios — el módulo
 * `account` no está en el alcance de Fase 0 (ver "Restricciones globales" del
 * plan). Cuando exista, sus DTOs se añaden aquí como tipos aparte.
 *
 * Cambio respecto al origen: `tenantSlug: string` → `tenantId: string | null`.
 * Con Keycloak Organizations el tenant se resuelve del claim `organization`,
 * cuyo alias **es** el `tenant_id` (`alias = str(tenant_id)`, confirmado en
 * `docs/superpowers/specs/2026-07-22-verificacion-kc-organizations.md`,
 * Pregunta 4). Ya no existe ningún slug.
 *
 * Es nulable a propósito: un usuario de plataforma (consola `vendi-admin`) no
 * pertenece a ninguna organización, y un usuario con varias organizaciones no
 * tiene tenant hasta que elige uno. Forzarlo a `string` obligaría a inventar un
 * `''` que se cuela como tenant válido en cualquier comparación descuidada.
 */
export interface UserProfile {
  /** `sub` del token: identificador del usuario en Keycloak. */
  id: string;
  username: string;
  email: string;
  firstName: string;
  lastName: string;
  /** Roles de realm (`dueno`, `cajero`, `almacenista`, `platform:admin`, …). */
  roles: string[];
  /** Tenant activo. `null` si no hay ninguno o si hay varios sin elegir. */
  tenantId: string | null;
}
