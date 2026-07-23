import { esIdDeTenant } from 'domain';
import type { KeycloakTokenParsed } from 'keycloak-js';

/**
 * Forma del claim `organization` de Keycloak 26.
 *
 * **Es polimórfica**, y esto no es una hipótesis: está medido en
 * `docs/superpowers/specs/2026-07-22-verificacion-kc-organizations.md`
 * (Pregunta 1).
 *
 *  - Por defecto, el mapper "Organization Membership" emite una **lista de
 *    alias**: `"organization": ["1b8e...", "2c9f..."]`.
 *  - Con `addOrganizationId=true` pasa a **mapa por alias**:
 *    `"organization": {"1b8e...": {"id": "..."}}`.
 *
 * El plan (Tarea 3.11) solo declaraba la segunda forma. Se aceptan las dos: si
 * alguien activa o desactiva esa opción del mapper en el realm, el frontend no
 * puede quedarse sin tenant en silencio.
 */
export type ClaimOrganizacion = string[] | Record<string, { id?: string } | null | undefined>;

/**
 * Token de acceso de Vendi: el de Keycloak más el claim de organizaciones y
 * los claims de perfil del scope `profile`.
 *
 * `KeycloakTokenParsed` de keycloak-js solo declara los claims del núcleo de
 * OIDC (`sub`, `exp`, `realm_access`…). Los del scope `profile` —`name`,
 * `preferred_username`, `given_name`, `family_name`, `email`— viajan en el
 * mismo token pero no están en el tipo, así que se declaran aquí.
 *
 * POR QUÉ IMPORTA: el perfil del usuario se leía exclusivamente de
 * `loadUserProfile()`, que llama a la API de cuenta de Keycloak
 * (`/realms/{realm}/account`) y exige que el token lleve la audiencia
 * `account`. El de Vendi no la lleva, así que esa llamada devolvía **401** y el
 * shell nunca pintaba el nombre de nadie. Estos claims ya venían en el token
 * desde el primer día: no hacía falta ninguna petición.
 */
export type VendiTokenParsed = KeycloakTokenParsed & {
  organization?: ClaimOrganizacion;
  /** Nombre completo tal y como lo compone Keycloak. */
  name?: string;
  preferred_username?: string;
  given_name?: string;
  family_name?: string;
  email?: string;
};

/**
 * Alias de organización presentes en el token, ya validados.
 *
 * El alias **es** el `tenant_id` (`alias = str(tenant_id)`, confirmado en el
 * informe de verificación, Pregunta 4), así que se descarta todo lo que no
 * tenga forma de UUID: un alias no-UUID no puede acabar en la cabecera
 * `X-Tenant-Id`, igual que el middleware del backend responde 401 en vez de
 * dejar que reviente el casteo en PostgreSQL.
 *
 * Devuelve lista vacía —nunca `undefined`— cuando el claim falta. El claim
 * ausente es un caso **normal**: un usuario multi-organización que no pidió
 * `scope=organization:*` llega sin él (Pregunta 3 del informe), y también un
 * usuario de plataforma que no pertenece a ninguna organización. El fallo es
 * cerrado: sin alias no hay tenant, y el backend responde 403 en las rutas de
 * tenant.
 */
export function aliasDeOrganizaciones(claim: unknown): string[] {
  if (Array.isArray(claim)) {
    return unicos(claim.filter((a): a is string => esIdDeTenant(a)));
  }
  if (claim !== null && typeof claim === 'object') {
    return unicos(Object.keys(claim).filter((a) => esIdDeTenant(a)));
  }
  return [];
}

function unicos(valores: string[]): string[] {
  return [...new Set(valores)];
}

/** Roles de realm del token, o lista vacía. */
export function rolesDeRealm(token: VendiTokenParsed | undefined): string[] {
  return token?.realm_access?.roles ?? [];
}
