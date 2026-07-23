# Runbook · Deriva del realm y organizaciones de Keycloak

## El hecho que explica todo este runbook

`--import-realm` importa `infra/keycloak/realm-vendi-co.json` **solo si el realm
no existe**. Medido contra 26.6.4:

```
INFO [ImportUtils] Realm 'vendi-co' already exists. Import skipped
```

Es decir: **cambiar el JSON y reiniciar no aplica nada.** El JSON es la semilla
del día 1, no el estado deseado continuo. Este runbook es lo que mantiene el
estado deseado continuo.

## Síntomas típicos

| Síntoma | Casi siempre es |
|---|---|
| Cambiaste el JSON y no pasa nada | lo de arriba |
| El login redirige a un dominio viejo | `redirectUris` con el `BASE_DOMAIN` anterior |
| La API devuelve 401 con un token recién emitido | al token le falta `aud=vendi-backend`: el client scope `vendi-audiencia` no está asignado |
| `sin_organizacion_en_token` (403) | el cliente no pidió `scope=organization:*`, o el negocio no tiene Organization |
| Un negocio existe en `tenants` y no en Keycloak | el alta se quedó a medias |

## 1. Ver qué está desalineado

```bash
bash scripts/reconcile-keycloak.sh
```

Compara **dos** cosas distintas y las informa por separado:

- **Configuración**: clientes, flujos de autenticación, ajustes de seguridad del
  realm y roles de las cuentas de servicio, contra el JSON.
- **Datos**: organizaciones de Keycloak contra la tabla `tenants`.

Sale 0 si no hay deriva. Solo informa.

## 2. Aplicar la deriva de configuración

```bash
RECONCILE_APLICAR_CONFIG=1 bash scripts/reconcile-keycloak.sh
```

Aplica **solo** el subconjunto en el que corregir no puede tirar sesiones ni
rotar credenciales: interruptores de cliente, `redirectUris`, `webOrigins`,
client scopes declarados con sus mappers, y las listas de scopes por defecto y
opcionales. Después vuelve a comparar e imprime el resultado.

El `PUT` se hace sobre una copia del objeto **vivo** con los campos declarados
encima: así conserva el `secret` del cliente y todo lo que el JSON no declara.

**Lo que NO aplica, y es a propósito:** flujos de autenticación y sus enlaces
(reenlazar `browserFlow` con sesiones abiertas deja a todo el mundo fuera),
ajustes del realm, roles, usuarios y creación de clientes. Eso lo decide el
operador con el informe delante. Ver D-03 en `docs/deuda-tecnica.md`.

## 3. Aplicar la deriva de datos (organizaciones)

```bash
RECONCILE_APLICAR=1 bash scripts/reconcile-keycloak.sh
```

Crea las organizaciones que falten y reenlaza las que existan con otro id,
llamando al **mismo** servicio de aprovisionamiento que usa la consola. Las
organizaciones huérfanas —sin negocio vivo— solo se informan; borrarlas exige
además `RECONCILE_BORRAR_HUERFANAS=1`, porque es irreversible y se lleva la
membresía de sus usuarios.

## 4. Comprobar que quedó bien

```bash
bash scripts/verify-setup.sh
```

Los checks que importan aquí: **8** (Organizations habilitado), **16** (el
negocio demo tiene fila y Organization con el mismo alias), **21** (las cuentas
de servicio no tienen ni un rol de más), **22** (ningún cliente acepta el grant
de contraseña) y **23** (los tokens llevan la audiencia y el rol de negocio).

## Cosas que se han medido y conviene no volver a descubrir

- **El alias de una Organization es `str(tenant_id)`.** Keycloak acepta el UUID
  con guiones y lo devuelve literal. No hay tabla de traducción ni cache.
- **Toda la API de Organizations exige `manage-realm`, incluso para leer.** Por
  eso hay dos credenciales: `vendi-backend` (solo `manage-users`) para la API
  general y `vendi-provisioning` para el alta y baja. Ver D-02.
- **`GET /users/{id}/organizations` no existe** en 26.6.4 (404 con cualquier
  privilegio). La ruta buena es
  `/organizations/members/{user_id}/organizations`.
- **Deshabilitar una Organization NO bloquea el login** de sus miembros: solo
  saca la organización del claim, y no invalida los tokens ya emitidos. La
  suspensión de un negocio es estado en la tabla `tenants`, no en el IdP.
- **`description` de un cliente es `varchar(255)`.** Un texto más largo revienta
  el import con un 500 y un `BatchUpdateException` de JDBC, no con un error de
  validación.
- **Crear un usuario sin `firstName` y `lastName`** hace que el login falle con
  «Account is not fully set up», que no menciona el perfil por ninguna parte.
