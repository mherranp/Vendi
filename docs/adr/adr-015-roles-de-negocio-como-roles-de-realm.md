# ADR-015 — Los roles de negocio son roles de realm; no se usa el claim `groups`

**Fecha:** 2026-07-23 · **Estado:** Firmada (Etapa 5 de Fase 0)
**Cierra:** deuda D-08.

## Contexto

Vendi tiene tres roles de negocio: `dueno`, `cajero`, `almacenista`. El código
cosechado de BaseSaaS traía un mapeo en dos canales: los **permisos**
(`tenant:read`, `platform:admin`…) llegaban en `realm_access.roles` y los
**roles** llegaban en un claim `groups`, con `UserContext.groups`, `has_role()` y
`require_role()` leyendo ese segundo canal.

**El realm de Vendi no emite `groups`.** Medido sobre un token real de
`dueno@demo.vendi.co`: `groups: None`. Ningún mapper de grupo está en los
default client scopes. Consecuencia: `has_role()` devolvía `False` para todo el
mundo, el dueño incluido, y cualquier `require_role` denegaba **por la razón
equivocada** — parecía funcionar mientras nadie tuviera el rol, y habría seguido
denegando el día que alguien lo tuviera.

## Decisión

**Los roles de negocio son roles de realm.** Viajan en `realm_access.roles`,
junto a los permisos, y `has_role()` lee de ahí. El claim `groups` no se usa y
el campo `UserContext.groups` **se retira**.

Los grupos de Keycloak siguen existiendo como comodidad de administración: el
grupo `dueno` mapea `{dueno} ∪ {sus permisos}` (`roles_de_realm_del_grupo`), de
modo que meter a un usuario en el grupo le da las dos cosas de una vez. Lo que
cambia es qué canal lee la autorización.

## Alternativas descartadas

- **Añadir el mapper de grupos al realm.** Era la opción obvia y es peor por dos
  motivos. Primero, la credencial de aprovisionamiento **no puede gestionar
  client scopes** (403 medido en `/client-scopes`), así que habría que tocar el
  JSON del realm sin poder aplicarlo al realm vivo — creando exactamente la
  deriva que documenta D-03. Segundo, y más de fondo: emitiría por un segundo
  canal lo que ya viaja por el primero. Dos fuentes de verdad para la misma
  pregunta es cómo se construye un bug de autorización.
- **Dejar `groups` inerte y documentarlo.** Un campo que siempre está vacío es
  una trampa esperando: el siguiente que escriba `require_role()` obtendrá un
  403 permanente y perderá una tarde averiguando por qué.

## Consecuencias

- Permisos y roles de negocio **comparten el espacio de nombres** de los roles de
  realm. Se distinguen por forma (el permiso lleva `recurso:accion`, con dos
  puntos; el rol no) y por catálogo (`PERMISSION_CATALOG` frente a
  `ROLES_DE_NEGOCIO`). Es la contrapartida de tener un solo canal, y se acepta:
  una colisión exigiría llamar a un rol de negocio `algo:algo`.
- `has_role()` **no** honra `is_superuser` ni el comodín `*`, a diferencia de
  `has_permission()`. Un permiso es «puede hacer esto»; un rol de negocio es «es
  esto». Que un administrador de plataforma pudiera pasar por `dueno` de
  cualquier negocio sería justo el cruce que el producto promete que no ocurre.
- La siembra crea los tres roles de realm y les mapea el grupo homónimo. El
  check 23 de `verify-setup.sh` falla si el token del dueño deja de traer
  `dueno`, y `test_un_rol_ausente_deniega_de_verdad` distingue «deniega porque no
  lo tiene» de «deniega siempre».

## Evidencia

Token de ejemplo generado por Keycloak para `vendi-web` y `dueno@demo.vendi.co`,
tras la corrección:

```
aud          = vendi-backend
realm_access = ['audit:read', 'default-roles-vendi-co-1', 'dueno', 'tenant:read', 'tenant:update']
organization = ['3038b70d-e480-4c21-801e-4688d538a9bd']
```
