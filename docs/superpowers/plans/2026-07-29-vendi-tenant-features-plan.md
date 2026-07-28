# Features web de `vendi-tenant` — consola del negocio: caja, catálogo, inventario, cuaderno y números por rol (Fase 1, Etapa 1.3, pista web) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir `vendi-tenant` de la demo de Fase 0 (una pantalla `/mi-negocio` y un selector que muestra UUIDs) en la consola real del negocio: **Mi caja** (estado de la sesión con esperado solo para quien cierra, abrir con base, movimientos con motivo y categoría, cerrar con contado y diferencia, historial de arqueos), **Mi catálogo** (CRUD de productos con granel, EAN e IVA), **Mi inventario** (stock con niveles agotado/crítico/bajo, ajuste por conteo o merma con motivo obligatorio, registro de compra con ítems), **Mi cuaderno** (clientes con saldo y cupo, alta/edición, detalle del crédito con abonos, abono con idempotencia, botón de WhatsApp con el `wa.me` prearmado, reprogramar vencimiento, filtro de vencidos) y **Mis números** (P&L día/semana/mes con fuentes declaradas y forecast 30 días —solo `reporte:leer`—). Todo multi-rol según ADR-023: las rutas llevan un `permisoGuard` nuevo en la lib `auth`, la navegación del shell se filtra por permiso y las acciones se ocultan con `*vdHasPermission`; el backend sigue siendo quien manda. Incluye los tres pendientes que el plan maestro asigna a esta pista: `GET /api/v1/tenants/mios` como **tarea backend acotada** (con su excepción en el middleware de tenant, el contrato congelado regenerado en el mismo commit y el selector mostrando NOMBRES), la deduplicación de `nucleo/sesion.ts` (a la lib `auth`) y de `layout/avisos.component.ts` (a `ui-kit`, invertido por input), y la ruta `/sin-permiso`. Specs por feature con el patrón de `vendi-admin`; sin E2E nuevo. Gate: los 9 proyectos del workspace verdes en test y lint, backend verde (unitarios e integración), build de producción de `vendi-tenant` verde sin relajar budgets, codegen sin deriva.

**Architecture:** Se mantiene la arquitectura firmada del workspace (ADR-011): las features viven en `vendi-tenant/src/app/features/<nombre>/` con el patrón de `vendi-admin` (componente + servicio + `contrato.ts` de amarre compile-time contra el cliente generado + specs), consumiendo `ApiService` y los tipos de `api-client` de `data-access`, los componentes del `ui-kit` (DataTable, ConfirmDialog, PageHeader, StatusBadge, EmptyState, FormRenderer, FullLayout), `domain` para el dinero (centavos enteros, `formatearPesos`, `miliDeCantidad`/`textoDeCantidad` para el granel) y `auth` para sesión, guards y `HasPermissionDirective`. La única novedad de arquitectura es deliberada y pequeña: la lib `auth` gana `permisoGuard` y `proveerSesion`, y `ui-kit` gana el anfitrión de avisos por input. El backend solo cambia en el módulo `tenants` (una ruta de lectura, un método de servicio, una excepción de middleware) — ningún módulo de negocio se toca.

**Tech Stack:** Angular 21 (standalone, signals, control flow `@if`/`@for`) · TypeScript 5.9 · Vitest sobre jsdom (`@angular/build:unit-test`) · RxJS 7 · Angular Material 21 · ngx-translate 17 · keycloak-js 26 · openapi-typescript (cliente generado, solo tipos) · Backend: FastAPI + SQLAlchemy async + pytest (integración contra el compose).

**Spec fuente:**
- `docs/superpowers/plans/2026-07-27-fase1-mvp-colombia-plan.md` §Etapa 1.3, pista web (verbatim): «features en `vendi-tenant` (caja, inventario, fiado) sobre el cliente generado; `GET /tenants/mios` para reemplazar UUIDs por nombres en el selector (pendiente conocido de Fase 0); deduplicar `nucleo/sesion.ts` y `layout/avisos.component.ts` hacia libs; corregir `roleGuard` → ruta `/sin-permiso` (crearla o apuntar a `/sin-acceso`)». Gate de etapa: «`ng test` verde en los 9 proyectos + nuevos specs por feature; E2E Playwright nuevo por flujo de dinero» — el E2E es gate posterior con el stack, NO de este plan (igual que en la pista móvil).
- `docs/adr/adr-023-multi-empleado-permisos.md` (catálogo cerrado de 14 permisos `recurso:accion` como roles de realm en `realm_access.roles`; matriz dueno/cajero/almacenista; «La app oculta lo que el usuario no puede hacer leyendo los mismos claims del token (el backend sigue siendo el que manda; la UI solo ahorra el 403)»).
- ADRs de negocio: `adr-019-catalogo-y-productos.md` (EAN opcional y único por negocio, granel con `unidad_medida`, IVA 0/5/19 como dato, borrado lógico), `adr-020-inventario-y-compras.md` (el stock negativo es dato legítimo que se muestra como información; ajuste online-obligatorio con motivo; proveedor texto libre; total de compra lo calcula el servidor), `adr-021-caja-y-arqueo.md` (una sesión abierta por tienda; arqueo congelado; categorías cerradas `arriendo`/`servicios`/`retiro_dueno`/`otro`; `motivo` obligatorio), `adr-006-finanzas-simples.md` («el forecast es una proyección explicada, no una promesa: la pantalla tiene que decir de qué datos sale»), `adr-022-fiado-y-clientes-tecnico.md` (abono contra el crédito que el usuario toca; cupo como advertencia nunca como bloqueo; `wa.me` manual; crédito sin fecha = sin recordatorio declarado en pantalla).
- Contrato `docs/api/openapi-fase0.json` + `docs/api/README.md` (sobre de error único `{success, message, code, details}`, `code` estable; campos condicionados por permiso: `efectivo_esperado` null sin `caja:cerrar`, `ultimo_costo` null sin `compra:crear`; lista completa de códigos: `caja_ya_abierta`, `caja_ya_cerrada`, `caja_sin_sesion_abierta`, `codigo_barras_duplicado`, `abono_excede_saldo`, `credito_no_abonable`, `credito_no_editable`, `limite_de_productos_alcanzado`, `permiso_ausente`, …).
- `docs/estado.md` (secciones de módulos backend: comportamiento exacto de cada endpoint, incluido «el historial de arqueos exige `caja:cerrar` porque faltantes y sobrantes históricos son un reporte»).
- Plantillas a imitar: `frontend/projects/vendi-admin/src/app/features/tenants/` (feature CRUD completa: paginación servidor, `DialogoFalso`, `CargadorDePrueba` con el `es.json` real fusionado, retroceso de última página vaciada, candado de doble clic), `frontend/projects/vendi-admin/src/app/nucleo/plataforma.guard.ts` (guard de permiso con `hasPermission`), `frontend/projects/vendi-tenant/src/app/app.spec.ts` (patrón `KeycloakFake` + `arrancarSesionFalsa` + `RouterTestingHarness`).
- Cliente generado `frontend/projects/libs/data-access/src/lib/api-client/index.ts` — nombres reales verificados contra disco: `SesionAbrir`/`SesionCerrar`/`SesionSalida`/`SesionActualSalida`/`ArqueoSalida`/`ArqueoConDesglose`/`DesgloseSalida`/`MovimientoCrear`/`MovimientoSalida`, `ProductoCrear`/`ProductoActualizar`/`ProductoSalida`, `CompraCrear`/`CompraItemEntrada`/`CompraDetalleSalida`, `AjusteCrear`/`AjusteCreado`/`StockSalida` (`nivel` es `string` libre, NO un enum TS), `PyLSalida`/`ForecastSalida`, `ClienteCrear`/`ClienteEditar`/`ClienteConSaldo`/`ClienteDetalleSalida`, `CreditoResumenSalida`/`CreditoDetalleSalida` (con `whatsapp_url`)/`CreditoReprogramar`/`AbonoCrear`/`AbonoSalida`, `TenantSalida`.

## Global Constraints

- Todo artefacto en español riguroso (código, docstrings, commits, claves i18n, mensajes). Sin tildes ni eñes en identificadores técnicos que viajen en tokens, URLs, JSON o claves de traducción.
- TDD en cada tarea: primero el test que falla (con la salida del fallo esperada), luego la implementación completa, luego el test en verde, luego el commit. Prohibido «similar a», «agregar validación», TODO o código elidido.
- Dinero SIEMPRE en centavos enteros; cantidades SIEMPRE como string de 3 decimales en el cable (granel). El único `number` fraccionario es el input del tendero, convertido a entero en el borde del diálogo (`Math.round(pesos * 100)`; `miliDeCantidad` + `textoDeCantidad` de `domain` para cantidades).
- El contrato OpenAPI NO cambia salvo por la Tarea 1 (la ruta `/tenants/mios` que el plan maestro asigna a esta pista): contrato congelado y cliente generado se regeneran juntos en el mismo commit, y ningún otro endpoint cambia. Fuera de eso, si el codegen deriva, es un bug del frontend y se corrige el frontend.
- La autorización la impone el backend; la UI solo ahorra el 403 (ADR-023). Ningún guard ni directiva del frontend es una frontera de seguridad, y ningún comentario puede sugerir lo contrario.
- Los ids de idempotencia (`AjusteCrear.id`, `MovimientoCrear.id`, `AbonoCrear.id` —requeridos— y los opcionales de compra, sesión, cliente y producto) se generan con `crypto.randomUUID()` **al abrir el diálogo**, no al enviar: el reenvío del mismo formulario reutiliza el mismo id y el servidor responde el no-op idempotente en vez de duplicar.
- Toda cadena visible va por `translate` con claves en `frontend/projects/vendi-tenant/public/i18n/es.json` (los specs fusionan el `es.json` real: una clave olvidada pinta la clave cruda y rompe el spec).
- Los 9 proyectos del workspace quedan verdes en test y lint en cada corte de tarea que toca libs; el build de producción de `vendi-tenant` no relaja budgets (700 kB aviso / 1 MB error iniciales — las features se cargan con `loadComponent`).
- `vendi-admin` y `vendi-app` solo se tocan en lo que la deduplicación exige (Tareas 2 y 3) y sus suites deben seguir verdes sin reescribir su lógica.
- Los commits son por tarea, mensajes en español estilo oración. Nunca `git push` sin confirmación humana.
- Un ADR no se edita para cambiar de opinión: lo que este plan decide más allá de los ADRs queda listado en la sección siguiente, con su justificación.

## Decisiones de diseño tomadas en este plan (más allá de los ADRs)

1. **`GET /api/v1/tenants/mios` entra como tarea backend acotada (Tarea 1); no hay rodeo honesto con lo que existe.** El claim `organization` del token lleva alias que SON el `tenant_id` (UUID), no nombres — Keycloak 26 no emite el nombre comercial en el claim. Resolverlo «con lo que hay» exigiría llamar `GET /tenants/me` una vez por organización, y esa ruta exige `X-Tenant-Id`, o sea, mutar la selección global de tenant por cada negocio solo para pintar el selector: un efecto colateral inaceptable para decorar una lista. El plan maestro además ASIGNA el endpoint a esta pista (verbatim en Spec fuente). La tarea es pequeña pero tiene una trampa real, medida contra el código: `TenantMiddleware` corre sobre toda ruta no pública y a un usuario multi-organización sin `X-Tenant-Id` le responde 400 `tenant_no_especificado` ANTES del handler — el endpoint pensado exactamente para quien no ha elegido negocio sería inalcanzable para él. Por eso la tarea incluye la excepción de ruta en el middleware (`/api/v1/tenants/mios` se sirve con token validado y sin resolver tenant), un método `listar_por_ids` en `TenantService` (sesión de plataforma: la tabla `tenants` tiene `REVOKE` para el rol de aplicación) y un esquema nuevo `TenantMioSalida` (id, nombre, estado — sin `kc_org_id`, que es un identificador del IdP que el selector no necesita). El contrato congelado `openapi-fase0.json` y el cliente TS se regeneran en el mismo commit (decisión 2). Alternativa descartada: añadir el nombre al claim de Keycloak — cambia la configuración del realm para todas las apps y el token ya crece con los permisos.
2. **El contrato congelado se descongela solo para esta ruta, en un solo commit.** La regla «el backend está congelado» de la pista móvil no aplicaba a esta pista: el plan maestro encarga el endpoint aquí. El candado del CI (`frontend-contratos`: codegen + `git diff --exit-code`) sigue verde porque contrato y cliente se regeneran juntos. Ninguna otra operación del OpenAPI se toca; el diff del congelado debe contener únicamente `/api/v1/tenants/mios` y el schema `TenantMioSalida`, y la tarea lo verifica.
3. **Ocultar por rol: `permisoGuard` nuevo en `libs/auth` + navegación filtrada en el shell + `*vdHasPermission` en las acciones. `roleGuard` NO se toca.** `roleGuard` usa `hasAnyRole` y no honra el comodín `*`; `vendi-admin` ya resolvió esto a su manera (`plataforma.guard.ts` con `hasPermission`). Este plan generaliza ESE patrón en la lib como `permisoGuard(...permisos)` (OR semántico, honra `*`, redirige a `/sin-permiso`), en vez de cambiar la semántica de `roleGuard` bajo los pies de futuros consumidores. El ítem del plan maestro «corregir `roleGuard` → ruta `/sin-permiso`» se cumple por la otra vía que él mismo ofrece: «crearla» — se crea `/sin-permiso` en `vendi-tenant` y el guard nuevo apunta ahí. Tensión declarada con la redacción del plan maestro (él nombraba `roleGuard`), no con su intención.
4. **Las secciones sin permiso se OCULTAN, nunca se deshabilitan.** ADR-023: «la app oculta lo que el usuario no puede hacer». Un botón gris invita a preguntar «¿por qué no puedo?»; una sección ausente no. Consecuencia para «Mis números»: P&L y forecast cuelgan del mismo permiso `reporte:leer`, que en la semilla solo tiene `dueno` — para cajero y almacenista la sección entera no existe (ni menú, ni ruta, ni tarjeta), no aparece deshabilitada. Matriz ruta↔permiso firmada en este plan (el permiso de lectura de cada módulo, según los guards del backend):

   | Ruta | Guard | Acciones visibles solo con |
   |---|---|---|
   | `/mi-negocio` | `tenantGuard` | — (todo miembro) |
   | `/caja` | `tenantGuard` + `permisoGuard('caja:leer')` | abrir: `caja:abrir` · movimiento: `caja:movimiento` · cerrar, esperado e historial: `caja:cerrar` |
   | `/catalogo` | `tenantGuard` + `permisoGuard('producto:leer')` | crear/editar/eliminar: `producto:editar` |
   | `/inventario` | `tenantGuard` + `permisoGuard('producto:leer')` | ajustar: `inventario:ajustar` · compra: `compra:crear` |
   | `/cuaderno` | `tenantGuard` + `permisoGuard('cliente:gestionar')` | abonar: `fiado:abonar` · reprogramar: `fiado:crear` |
   | `/numeros` | `tenantGuard` + `permisoGuard('reporte:leer')` | — (solo lectura) |

   Resultado por rol (semilla de Keycloak): el **cajero** ve Mi negocio, Mi caja (sin esperado, sin cierre, sin historial), Catálogo (sin editar), Inventario (sin ajustar ni comprar) y Cuaderno; el **almacenista** ve Mi negocio, Catálogo e Inventario; el **dueño** lo ve todo. El `efectivo_esperado` además viaja `null` del backend para el cajero (no es solo cosmética): la UI lo muestra solo cuando es no-nulo.
5. **`proveerSesion` se mueve a `libs/auth` y las tres copias se borran.** La función es byte a byte idéntica en `vendi-admin`, `vendi-tenant` y `vendi-app` (solo difieren los docstrings) y depende únicamente de `AuthService` y `provideAppInitializer`: su casa natural es la propia lib `auth`. Los tres `app.config.ts` pasan a importarla de `'auth'`; `nucleo/sesion.ts` desaparece de las tres apps. El comportamiento (`check-sso`, `catch` que no aborta el bootstrap) no cambia ni una línea.
6. **`AvisosComponent` se mueve a `ui-kit` invertido por input; el `Notificador` se queda en las apps.** La frontera de ADR-011 prohíbe a `ui-kit` importar `data-access` — por eso el componente nació duplicado. La salida legal: el componente deja de INYECTAR `Notificador` y recibe el aviso por `input()`; la lógica que valía deduplicar (dedup por `id`, duraciones por tipo, `MatSnackBar`, traducción de «Cerrar») vive una sola vez en `ui-kit`, y cada shell pasa `notificador.ultimo()` (tres líneas por app). `ui-kit` ya depende de Angular Material (ConfirmDialog) y de ngx-translate (traduce las claves de sus inputs), así que no entra dependencia nueva. Tipo puente `AvisoEnPantalla` definido en `ui-kit`, estructuralmente compatible con el `Aviso` de `data-access`.
7. **Ids de idempotencia al abrir el diálogo (repetida de Constraints porque cambia el código de cada formulario).** `crypto.randomUUID()` se ejecuta en el método `abrirDialogoX()` del componente y viaja en el payload. Si el usuario envía dos veces, o la red corta tras un POST que el servidor sí procesó y la pantalla reintenta, el servidor responde el no-op idempotente (`duplicada`/200 con lo grabado) en vez de duplicar el ajuste, el movimiento, el abono o la compra. Es la misma disciplina del POS offline, aplicada a la consola online.
8. **Los códigos de error de negocio se leen en la feature, no en el interceptor.** `errorInterceptor` ya muestra el `message` del backend (en español) para todo 4xx, y no se toca. Cuando el flujo necesita REACCIONAR al `code` — `caja_ya_abierta` (409 con la sesión vigente en `details`: refrescar el estado y seguir), `caja_ya_cerrada` (ídem al cerrar), `abono_excede_saldo` / `codigo_barras_duplicado` (marcar el campo en el formulario) — el `subscribe` de la feature inspecciona `err.error?.code`. No se extiende el interceptor: su contrato (avisar) está completo; decidir es de la pantalla.
9. **Alcance recortado declarado: sin historial de compras ni de ajustes, sin `ultimo_costo` en catálogo, sin ancla `fecha` en el P&L.** El contrato soporta `GET /compras`, `GET /inventario/ajustes` y `periodo+fecha`, pero el encargo es «registro de compra» y «ajuste de stock»; sus historiales y la navegación a períodos pasados son pantallas propias que llegarán con el uso del piloto. `ultimo_costo` (null sin `compra:crear`) no se pinta: el costo se captura en la compra y se consulta en el P&L, que es donde decide algo. Lo que NO se recorta: los niveles de stock, el esperado condicionado, el cupo como advertencia, las fuentes del P&L/forecast (ADR-006 las exige en pantalla) y el `wa.me`.
10. **El aviso `cupo_excedido` vive aquí, como decretó la pista móvil.** El POS no lo muestra (decisión 4 del plan móvil: «vive en el cuaderno web»). La lista de clientes lo pinta como badge de advertencia junto al saldo, y la ficha del crédito repite el cupo y el exceso. Nunca bloquea (ADR-022: «el cuaderno nunca le dijo que no a nadie»).
11. **La cantidad del granel se captura como texto y se convierte en el borde con `domain`.** Coma o punto (`1,5` / `1.5`) → `Number` → `miliDeCantidad` (lanza sobre ≤0/NaN: el diálogo no cierra y marca el campo) → `textoDeCantidad` (`"1.500"`) para el payload. Es exactamente la regla del POS; compartir la función es compartir los bugs ya corregidos.
12. **Specs con el patrón de `vendi-admin`, ahora con sesión falsa cuando hace falta.** Los componentes nuevos usan `*vdHasPermission`, así que sus specs arrancan un `AuthService` real sobre `KeycloakFake` (patrón de `app.spec.ts` de `vendi-tenant`: `vi.mock('keycloak-js', ...)` + `arrancarSesionFalsa(auth, { roles: [...] })`) y prueban los tres perfiles de permiso que importan (dueño completo, cajero, almacenista). Los servicios se prueban sin sesión (no pintan nada): patrón de `tenants.service.spec.ts`.

---

## Tarea 1: Backend acotado — `GET /api/v1/tenants/mios` (los nombres del selector)

**Files:**
- Create: `backend/tests/api/test_tenants_mios.py` (primero: el test que falla)
- Modify: `backend/libs/vendi-core/src/vendi_core/tenant/middleware.py` (excepción de ruta)
- Modify: `backend/services/api/app/modules/tenants/service.py` (método `listar_por_ids`)
- Modify: `backend/services/api/app/modules/tenants/schemas.py` (`TenantMioSalida`)
- Modify: `backend/services/api/app/modules/tenants/router.py` (la ruta)
- Modify: `docs/api/openapi-fase0.json` (regenerado, NO editado a mano)
- Modify: `frontend/projects/libs/data-access/src/lib/api-client/openapi.json` + `index.ts` (regenerados)
- Modify: `docs/api/README.md` (fila nueva en la tabla de rutas)

**Interfaces:**
- Consume: `UserContext.alias_de_organizacion` (`vendi_core/auth/context.py`: «Alias de las organizaciones del token. Cada alias es un `tenant_id`»); `TenantService` con sesión de plataforma (`servicio_de_tenants` ya la inyecta); el patrón de test de `backend/tests/api/test_tenants_crud.py` (`app_con_base` + `ValidadorFalso` + `usuario_de_negocio(*ids)`).
- Produce: `GET /api/v1/tenants/mios` → `200 list[TenantMioSalida]` (id, nombre, estado; solo negocios del token, sin eliminados, ordenados por nombre); el schema `TenantMioSalida` en el cliente TS; la base de la Tarea 10.

**Por qué la excepción del middleware va en esta tarea y no «si hiciera falta»:** verificado contra `vendi_core/tenant/middleware.py:191-214` — con varias organizaciones y sin cabecera `X-Tenant-Id`, el middleware responde 400 `tenant_no_especificado` antes del handler. El usuario que NECESITA este endpoint es precisamente ese. El test del Paso 1 lo demuestra en rojo antes de tocar nada.

- [ ] **Paso 1: el test que falla.** Crear `backend/tests/api/test_tenants_mios.py`:

```python
"""`GET /api/v1/tenants/mios`: los negocios del token, con nombre.

Existe para el selector de negocio de la consola web: el claim `organization`
del token lleva alias que SON el tenant_id (UUID), y elegir entre UUIDs no es
elegir. La ruta se sirve con el token validado y SIN resolver tenant (es la
excepción `RUTAS_SIN_TENANT` del middleware): quien tiene varios negocios y
todavía no ha elegido ninguno es exactamente su usuario.
"""

from __future__ import annotations

import uuid

import pytest

from tests.api.ayudas import PREFIJO_PRUEBA, usuario_de_negocio

pytestmark = pytest.mark.integration


def _crear(cliente, cabeceras_admin, nombre: str) -> str:
    respuesta = cliente.post(
        "/api/v1/platform/tenants",
        json={"nombre": PREFIJO_PRUEBA + nombre},
        headers=cabeceras_admin,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def test_mios_devuelve_los_negocios_del_token_con_nombre(app_con_base, cabeceras_admin):
    cliente, validador, _ = app_con_base
    id_a = _crear(cliente, cabeceras_admin, "Tienda A")
    id_b = _crear(cliente, cabeceras_admin, "Tienda B")

    validador.registrar("tok-mios", usuario_de_negocio(uuid.UUID(id_a), uuid.UUID(id_b)))
    # SIN cabecera X-Tenant-Id a propósito: el usuario aún no ha elegido.
    respuesta = cliente.get("/api/v1/tenants/mios", headers={"Authorization": "Bearer tok-mios"})

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    nombres = {fila["nombre"] for fila in cuerpo}
    assert nombres == {PREFIJO_PRUEBA + "Tienda A", PREFIJO_PRUEBA + "Tienda B"}
    for fila in cuerpo:
        assert set(fila) == {"id", "nombre", "estado"}
        assert fila["estado"] == "activo"


def test_mios_no_incluye_negocios_que_no_estan_en_el_token(app_con_base, cabeceras_admin):
    cliente, validador, _ = app_con_base
    mio = _crear(cliente, cabeceras_admin, "La mia")
    _crear(cliente, cabeceras_admin, "La ajena")

    validador.registrar("tok-uno", usuario_de_negocio(uuid.UUID(mio)))
    respuesta = cliente.get("/api/v1/tenants/mios", headers={"Authorization": "Bearer tok-uno"})

    assert respuesta.status_code == 200, respuesta.text
    assert [fila["nombre"] for fila in respuesta.json()] == [PREFIJO_PRUEBA + "La mia"]


def test_mios_sin_organizaciones_devuelve_lista_vacia(app_con_base):
    cliente, validador, _ = app_con_base
    validador.registrar("tok-cero", usuario_de_negocio())
    respuesta = cliente.get("/api/v1/tenants/mios", headers={"Authorization": "Bearer tok-cero"})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == []


def test_mios_sin_token_es_401(app_con_base):
    cliente, _, _ = app_con_base
    respuesta = cliente.get("/api/v1/tenants/mios")
    assert respuesta.status_code == 401
```

```bash
cd backend && uv run pytest -q -rs -m integration tests/api/test_tenants_mios.py
# Esperado: fallo — el primer test recibe 400 tenant_no_especificado (el
# middleware exige X-Tenant-Id con varias organizaciones) o 404 si la ruta
# aún no existe. ESE 400 es la trampa que esta tarea cierra.
```

(Nota de patrón: `PREFIJO_PRUEBA` y la limpieza por prefijo siguen el estilo de `test_tenants_crud.py` — si `PREFIJO_PRUEBA` está definido en ese archivo y no en `tests/api/ayudas.py`, se importa de ahí o se define igual (`"PRUEBA "`); y las cabeceras de admin se construyen con el helper del archivo vecino (`_admin(cliente, validador)` en la sección `/tenants/me`), copiando su forma exacta. El aserto que importa es el del middleware.)

- [ ] **Paso 2: la excepción en el middleware.** En `backend/libs/vendi-core/src/vendi_core/tenant/middleware.py`, junto a las constantes de cabecera (donde vive `HEADER_TENANT = "X-Tenant-Id"`):

```python
#: Rutas autenticadas que NO resuelven tenant: el usuario todavía no ha
#: elegido negocio — es justo lo que `/tenants/mios` le permite hacer. Sin
#: esta excepción, un usuario con varias organizaciones recibiría 400
#: `tenant_no_especificado` en el endpoint pensado para él.
RUTAS_SIN_TENANT: frozenset[str] = frozenset({"/api/v1/tenants/mios"})
```

Y en `TenantMiddleware.dispatch`, DESPUÉS de validar el token y fijar `request.state.user` (el bloque que hoy termina en `request.state.token_validado = token`) y ANTES del bloque de selección de alias (`alias = list(user.organizations)` … `tenant_no_especificado`), insertar:

```python
        if request.url.path in RUTAS_SIN_TENANT:
            return await call_next(request)
```

(Si el nombre del callable difiere — es el `call_next` estándar de `BaseHTTPMiddleware`/`dispatch` — usar el del archivo. El ancla es el bloque `alias = list(user.organizations)`; la excepción va inmediatamente antes.)

- [ ] **Paso 3: el método de servicio.** En `backend/services/api/app/modules/tenants/service.py`, junto a `listar`:

```python
    async def listar_por_ids(self, ids: list[uuid.UUID]) -> list[Tenant]:
        """Los negocios vivos de una lista de ids (los alias del token).

        Sesión de plataforma (el constructor ya la exige): la tabla `tenants`
        no es visible para el rol de aplicación. Los eliminados no vuelven:
        un negocio dado de baja no se ofrece en el selector.
        """
        if not ids:
            return []
        consulta = (
            select(Tenant)
            .where(Tenant.id.in_(ids), Tenant.deleted_at.is_(None))
            .order_by(Tenant.nombre, Tenant.id)
        )
        return list((await self._session.execute(consulta)).scalars().all())
```

- [ ] **Paso 4: el esquema y la ruta.** En `backend/services/api/app/modules/tenants/schemas.py`, junto a `TenantSalida`:

```python
class TenantMioSalida(BaseModel):
    """Lo mínimo para el selector de negocio: id, nombre y estado.

    Sin `kc_org_id`: es un identificador del IdP que el tendero no necesita.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    estado: EstadoTenant
```

En `backend/services/api/app/modules/tenants/router.py` (imports nuevos: `uuid`, `UserContext`, `get_current_user`, `TenantMioSalida`):

```python
@router.get(
    "/mios",
    response_model=list[TenantMioSalida],
    summary="Los negocios del usuario autenticado",
    responses={
        401: {"model": ErrorResponse, "description": "Sin token o token inválido"},
    },
)
async def mis_negocios(
    user: UserContext = Depends(get_current_user),
    servicio: TenantService = Depends(servicio_de_tenants),
) -> list[Tenant]:
    ids = [uuid.UUID(alias) for alias in user.alias_de_organizacion]
    return await servicio.listar_por_ids(ids)
```

Ojo al orden: `/mios` es literal como `/me`, no colisiona con ningún path-param de este router (no los hay). La ruta NO depende de `negocio_del_token` ni de `exigir_negocio_activo`: el usuario aún no tiene tenant.

- [ ] **Paso 5: verde en backend.**

```bash
cd backend && uv run pytest -q -rs -m integration tests/api/test_tenants_mios.py
# Esperado: 4 passed
uv run pytest -q -m 'not integration'
# Esperado: verde (nada unitario roto)
uv run pytest -q -rs -m integration
# Esperado: verde en toda la suite de integración (la excepción del
# middleware no altera ninguna ruta existente)
```

- [ ] **Paso 6: regenerar el contrato congelado y el cliente, juntos.** Con el stack levantado (`./scripts/dev.sh` o el compose habitual):

```bash
# Desde la raíz del repo (software/):
curl -sS --resolve api.vendi.co:443:127.0.0.1 https://api.vendi.co/openapi.json \
  | python3 -c 'import json,sys; json.dump(json.load(sys.stdin), open("docs/api/openapi-fase0.json","w"), indent=2, ensure_ascii=False, sort_keys=True)'
git diff --stat docs/api/openapi-fase0.json
# Esperado: solo la operación /api/v1/tenants/mios y el schema TenantMioSalida
git diff docs/api/openapi-fase0.json | grep -E '^[-+]' | grep -v 'tenants/mios\|TenantMioSalida' | head -20
# Esperado: vacío — si aparece cualquier otra cosa, el backend local tiene
# cambios ajenos a esta tarea y hay que parar y entender por qué.
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git diff --exit-code --stat
# (el diff --exit-code falla a propósito: hay cambios nuevos a commitear)
```

- [ ] **Paso 7: la fila del README de API.** En `docs/api/README.md`, tabla de rutas, junto a `GET /api/v1/tenants/me`:

```markdown
| `GET /api/v1/tenants/mios` | (token, sin tenant) | Lista los negocios vivos del claim `organization` (id, nombre, estado), ordenados por nombre. Se sirve SIN `X-Tenant-Id` (excepción del middleware): es la lista del selector de negocio. |
```

- [ ] **Paso 8: commit**

```bash
git add backend docs/api/openapi-fase0.json docs/api/README.md frontend/projects/libs/data-access/src/lib/api-client
git commit -m "GET /tenants/mios: los negocios del token con nombre, con excepción de tenant en el middleware y contrato regenerado"
```

**Criterios de aceptación:** los 4 tests nuevos pasan (el primero demuestra que la excepción del middleware era necesaria); la suite de integración completa sigue verde; el diff del congelado contiene ÚNICAMENTE `/api/v1/tenants/mios` + `TenantMioSalida`; el cliente TS expone `components['schemas']['TenantMioSalida']` y `paths['/api/v1/tenants/mios']`; la respuesta no incluye `kc_org_id`.

---

## Tarea 2: `permisoGuard` y `proveerSesion` en la lib `auth` (deduplicación 1 de 2)

**Files:**
- Create: `frontend/projects/libs/auth/src/lib/permiso.guard.ts`
- Create: `frontend/projects/libs/auth/src/lib/permiso.guard.spec.ts` (primero: el test que falla)
- Create: `frontend/projects/libs/auth/src/lib/sesion.provider.ts`
- Modify: `frontend/projects/libs/auth/src/public-api.ts`
- Modify: `frontend/projects/vendi-tenant/src/app/app.config.ts` (importa `proveerSesion` de `'auth'`)
- Modify: `frontend/projects/vendi-admin/src/app/app.config.ts` (ídem)
- Modify: `frontend/projects/vendi-app/src/app/app.config.ts` (ídem)
- Delete: `frontend/projects/vendi-tenant/src/app/nucleo/sesion.ts`, `frontend/projects/vendi-admin/src/app/nucleo/sesion.ts`, `frontend/projects/vendi-app/src/app/nucleo/sesion.ts`

**Interfaces:**
- Consume: `AuthService.hasPermission` (honra `*`); el patrón de `vendi-admin/src/app/nucleo/plataforma.guard.ts`; las tres copias idénticas de `proveerSesion`.
- Produce: `permisoGuard(...permisos)` y `proveerSesion(config)` exportados de `'auth'`; la base de las rutas de la Tarea 4.

- [ ] **Paso 1: el spec del guard, primero.** Crear `frontend/projects/libs/auth/src/lib/permiso.guard.spec.ts`:

```ts
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Ver `auth/testing`: la fábrica tira del punto de entrada secundario para no
// cerrar un ciclo con el `keycloak-js` que está resolviendo.
vi.mock('keycloak-js', async () => {
  const mod = await import('../../testing/src/public-api');
  return { default: mod.KeycloakFake };
});

import { AuthService } from './auth.service';
import { permisoGuard } from './permiso.guard';
import { KeycloakFake, arrancarSesionFalsa } from '../../testing/src/public-api';

async function preparar(roles: string[]): Promise<{ auth: AuthService; router: Router }> {
  TestBed.resetTestingModule();
  KeycloakFake.reiniciar();
  TestBed.configureTestingModule({ providers: [provideRouter([]), AuthService] });
  const auth = TestBed.inject(AuthService);
  await arrancarSesionFalsa(auth, { roles });
  return { auth, router: TestBed.inject(Router) };
}

describe('permisoGuard', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('deja pasar cuando el token trae el permiso', async () => {
    await preparar(['dueno', 'caja:leer']);
    const guard = permisoGuard('caja:leer');
    const veredicto = TestBed.runInInjectionContext(() => guard({} as never, {} as never));
    expect(veredicto).toBe(true);
  });

  it('deja pasar con CUALQUIERA de los permisos (semántica OR)', async () => {
    await preparar(['almacenista', 'inventario:ajustar']);
    const guard = permisoGuard('caja:leer', 'inventario:ajustar');
    const veredicto = TestBed.runInInjectionContext(() => guard({} as never, {} as never));
    expect(veredicto).toBe(true);
  });

  it('sin el permiso redirige a /sin-permiso, no al login', async () => {
    const { router } = await preparar(['cajero', 'caja:leer']);
    const guard = permisoGuard('reporte:leer');
    const veredicto = TestBed.runInInjectionContext(() => guard({} as never, {} as never));
    expect(String(veredicto)).toBe(String(router.createUrlTree(['/sin-permiso'])));
    expect(KeycloakFake.ultimaInstancia?.loginCalls ?? 0).toBe(0);
  });

  it('honra el comodín * (un superusuario entra a todas partes)', async () => {
    await preparar(['*']);
    const guard = permisoGuard('reporte:leer');
    const veredicto = TestBed.runInInjectionContext(() => guard({} as never, {} as never));
    expect(veredicto).toBe(true);
  });

  it('sin sesión dispara el login y no deja pasar', async () => {
    TestBed.resetTestingModule();
    KeycloakFake.reiniciar();
    // `init()` que devuelve false = no hay sesión. Se restaura en el finally:
    // un prototype parchado sin restaurar contamina los demás specs del archivo.
    const original = KeycloakFake.prototype.init;
    KeycloakFake.prototype.init = async function (this: KeycloakFake) {
      this.initReturns = false;
      return false;
    };
    try {
      TestBed.configureTestingModule({ providers: [provideRouter([]), AuthService] });
      const auth = TestBed.inject(AuthService);
      await auth.init({ url: 'https://accounts.vendi.co', realm: 'vendi-co', clientId: 'vendi-web' });

      const guard = permisoGuard('caja:leer');
      const veredicto = TestBed.runInInjectionContext(() => guard({} as never, {} as never));
      expect(veredicto).toBe(false);
      expect(KeycloakFake.ultimaInstancia?.loginCalls).toBeGreaterThan(0);
    } finally {
      KeycloakFake.prototype.init = original;
    }
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test auth --watch=false
# Esperado: fallo — Cannot find module './permiso.guard' (TS2307)
```

- [ ] **Paso 2: el guard.** Crear `frontend/projects/libs/auth/src/lib/permiso.guard.ts`:

```ts
import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';

/**
 * Guard de rutas por permiso de dominio (ADR-023).
 *
 * Es el hermano de `roleGuard` para los permisos `recurso:accion`: usa
 * `hasPermission`, que honra el comodín `*` (cosa que `hasAnyRole`, y por
 * tanto `roleGuard`, no hace a propósito). Semántica OR: basta UN permiso.
 *
 * Sin permiso redirige a `/sin-permiso`: la app que lo use debe proveer esa
 * ruta (igual que `tenantGuard` exige `/elegir-negocio`). No es una frontera
 * de seguridad —eso es el backend—: solo ahorra el 403.
 */
export const permisoGuard = (...permisos: string[]): CanActivateFn => {
  return () => {
    const auth = inject(AuthService);
    const router = inject(Router);

    if (!auth.authenticated()) {
      auth.login();
      return false;
    }
    if (permisos.length === 0 || permisos.some((permiso) => auth.hasPermission(permiso))) {
      return true;
    }
    return router.createUrlTree(['/sin-permiso']);
  };
};
```

- [ ] **Paso 3: `proveerSesion` en la lib.** Crear `frontend/projects/libs/auth/src/lib/sesion.provider.ts`, con el cuerpo IDÉNTICO al de las tres copias (hoy en `*/src/app/nucleo/sesion.ts`) y este docstring único:

```ts
import { EnvironmentProviders, inject, provideAppInitializer } from '@angular/core';
import { AuthService, ConfiguracionAuth } from './auth.service';

/**
 * Arranca la sesión de Keycloak antes de que se pinte la primera ruta.
 *
 * ## Por qué `check-sso` y no `login-required`
 *
 * Con `login-required`, keycloak-js redirige al IdP **durante el bootstrap**:
 * si Keycloak está caído o tarda, el usuario ve una pantalla en blanco sin
 * ninguna explicación. Con `check-sso` la app arranca siempre; quien manda al
 * login es `authGuard`, que corre cuando ya hay una aplicación viva capaz de
 * enseñar un error. Además, `login-required` no deja sitio para las pantallas
 * de antes del tenant: el selector de negocio (`vendi-tenant`), la de «sin
 * acceso» (`vendi-admin`) y el arranque offline (`vendi-app`) necesitan una
 * aplicación viva aunque no haya sesión.
 *
 * El `catch` es deliberado: `init()` rechaza cuando el IdP no responde, y un
 * inicializador que rechaza aborta el bootstrap de Angular. La consecuencia
 * correcta de «no pude comprobar la sesión» es «arranca sin sesión», no
 * «pantalla en blanco».
 *
 * Vivía copiada en `nucleo/sesion.ts` de las tres apps; la deduplicación es
 * de la Etapa 1.3 (pista web). Depende solo de esta lib, así que aquí está.
 */
export function proveerSesion(config: ConfiguracionAuth): EnvironmentProviders {
  return provideAppInitializer(async () => {
    const auth = inject(AuthService);
    try {
      await auth.init({ ...config, onLoad: 'check-sso' });
    } catch (error) {
      console.error('No se pudo comprobar la sesión con Keycloak; se arranca sin sesión.', error);
    }
  });
}
```

- [ ] **Paso 4: exportar ambos.** En `frontend/projects/libs/auth/src/public-api.ts`, tras la línea de los guards:

```ts
export { permisoGuard } from './lib/permiso.guard';
export { proveerSesion } from './lib/sesion.provider';
```

- [ ] **Paso 5: recablear las tres apps y borrar las copias.** En los tres `app.config.ts` (`vendi-tenant`, `vendi-admin`, `vendi-app`): quitar `import { proveerSesion } from './nucleo/sesion';` y añadir `proveerSesion` al import de `'auth'` (en `vendi-tenant` y `vendi-admin` queda `import { authInterceptor, proveerSesion } from 'auth';`; en `vendi-app` igual según su import actual de `authInterceptor`). Borrar los tres `src/app/nucleo/sesion.ts`. Verificar que no queda ninguna referencia:

```bash
grep -rn "nucleo/sesion" frontend/projects --include="*.ts" || echo "limpio"
# Esperado: limpio
```

- [ ] **Paso 6: verde en el workspace.**

```bash
cd frontend && npm run build:libs && npx ng test --watch=false
# Esperado: verde en los 9 proyectos (los specs de app.config no existen;
# los de rutas siguen pasando: el comportamiento del bootstrap no cambió)
npx ng lint
# Esperado: sin errores
```

- [ ] **Paso 7: commit**

```bash
git add frontend
git commit -m "permisoGuard y proveerSesion en la lib auth: guard por permiso con comodín y sesion.ts deduplicado de las tres apps"
```

**Criterios de aceptación:** los 5 specs del guard pasan (incluido el del comodín `*` y el de redirección a `/sin-permiso` sin login); `proveerSesion` vive una sola vez y las tres apps la importan de `'auth'`; los 9 proyectos verdes en test y lint.

---

## Tarea 3: `AvisosComponent` en `ui-kit`, invertido por input (deduplicación 2 de 2)

**Files:**
- Create: `frontend/projects/libs/ui-kit/src/lib/avisos/avisos.component.ts`
- Create: `frontend/projects/libs/ui-kit/src/lib/avisos/avisos.component.spec.ts` (primero)
- Modify: `frontend/projects/libs/ui-kit/src/public-api.ts`
- Modify: `frontend/projects/vendi-tenant/src/app/layout/shell.component.ts` + `.html`
- Modify: `frontend/projects/vendi-admin/src/app/layout/shell.component.ts` + `.html`
- Delete: `frontend/projects/vendi-tenant/src/app/layout/avisos.component.ts`, `frontend/projects/vendi-admin/src/app/layout/avisos.component.ts`

**Interfaces:**
- Consume: `Notificador.ultimo()` de `data-access` (lo leen las apps, no el kit); `MatSnackBar` y `TranslateService` (ya son dependencias de `ui-kit`: ConfirmDialog usa `MatDialog`, y el kit traduce las claves de sus inputs).
- Produce: `vd-avisos` con `input aviso: AvisoEnPantalla | null`; shells de tres líneas.

**Por qué por input y no «un día una lib de feedback»:** la frontera de ADR-011 veta `data-access` en `ui-kit` (el viejo docstring lo explicaba bien); lo que NO veta es que el kit reciba el dato. Toda la lógica que se duplicaba —dedup por `id`, duraciones, snackbar— cabe detrás de un `input()` sin romper la frontera.

- [ ] **Paso 1: el spec, primero.** Crear `frontend/projects/libs/ui-kit/src/lib/avisos/avisos.component.spec.ts`:

```ts
import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { TranslateService, provideTranslateService } from '@ngx-translate/core';
import { beforeEach, describe, expect, it } from 'vitest';
import { AvisoEnPantalla, AvisosComponent } from './avisos.component';

class SnackBarFalso {
  readonly aperturas: { mensaje: string; accion: string; config: unknown }[] = [];
  open(mensaje: string, accion: string, config: unknown): void {
    this.aperturas.push({ mensaje, accion, config });
  }
}

function montar(): { snack: SnackBarFalso } {
  TestBed.resetTestingModule();
  const snack = new SnackBarFalso();
  TestBed.configureTestingModule({
    providers: [
      { provide: MatSnackBar, useValue: snack },
      ...provideTranslateService({ fallbackLang: 'es', lang: 'es' }),
    ],
  });
  TestBed.inject(TranslateService).setTranslation('es', { comun: { cerrar: 'Cerrar' } });
  return { snack };
}

function aviso(id: string, tipo: string): AvisoEnPantalla {
  return { id, tipo, mensaje: `mensaje ${id}` };
}

describe('AvisosComponent (anfitrión de avisos por input)', () => {
  let snack: SnackBarFalso;

  beforeEach(() => {
    ({ snack } = montar());
  });

  it('sin aviso no abre nada', () => {
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.detectChanges();
    expect(snack.aperturas.length).toBe(0);
  });

  it('abre la barra con el mensaje y la acción traducida', () => {
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.componentRef.setInput('aviso', aviso('a1', 'info'));
    fixture.detectChanges();
    expect(snack.aperturas.length).toBe(1);
    expect(snack.aperturas[0].mensaje).toBe('mensaje a1');
    expect(snack.aperturas[0].accion).toBe('Cerrar');
  });

  it('un error no se cierra solo; un éxito dura 3 s', () => {
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.componentRef.setInput('aviso', aviso('a1', 'error'));
    fixture.detectChanges();
    expect((snack.aperturas[0].config as { duration: number }).duration).toBe(0);

    fixture.componentRef.setInput('aviso', aviso('a2', 'exito'));
    fixture.detectChanges();
    expect((snack.aperturas[1].config as { duration: number }).duration).toBe(3_000);
  });

  it('el mismo aviso no se repinta aunque el input se reemplace por otro igual', () => {
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.componentRef.setInput('aviso', aviso('a1', 'info'));
    fixture.detectChanges();
    fixture.componentRef.setInput('aviso', aviso('a1', 'info'));
    fixture.detectChanges();
    expect(snack.aperturas.length).toBe(1);
  });

  it('dos avisos con distinto id se pintan los dos', () => {
    const fixture = TestBed.createComponent(AvisosComponent);
    fixture.componentRef.setInput('aviso', aviso('a1', 'info'));
    fixture.detectChanges();
    fixture.componentRef.setInput('aviso', aviso('a2', 'advertencia'));
    fixture.detectChanges();
    expect(snack.aperturas.length).toBe(2);
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test ui-kit --watch=false
# Esperado: fallo — Cannot find module './avisos.component' (TS2307)
```

- [ ] **Paso 2: el componente.** Crear `frontend/projects/libs/ui-kit/src/lib/avisos/avisos.component.ts`:

```ts
import { Component, effect, inject, input } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { TranslateService } from '@ngx-translate/core';

/**
 * El aviso tal como lo necesita el anfitrión. Es estructuralmente compatible
 * con el `Aviso` de `data-access` (que trae además `instante`): la app pasa
 * `notificador.ultimo()` tal cual, sin mapear nada.
 *
 * Se declara aquí y no se importa de `data-access` porque la frontera de
 * ADR-011 lo prohíbe: `ui-kit` es presentación pura.
 */
export interface AvisoEnPantalla {
  id: string;
  tipo: string;
  mensaje: string;
}

/** Cuánto se queda en pantalla cada aviso, por tipo. */
const DURACION_MS: Record<string, number> = {
  exito: 3_000,
  info: 4_000,
  advertencia: 6_000,
  // Un error se lee, no se pilla al vuelo: se queda hasta que lo cierren.
  error: 0,
};

/**
 * Pinta el aviso vigente en una `MatSnackBar`.
 *
 * Antes vivía duplicado en `layout/avisos.component.ts` de `vendi-admin` y
 * `vendi-tenant` inyectando `Notificador` — imposible aquí por la frontera.
 * La inversión es el arreglo de la Etapa 1.3: el kit recibe el aviso por
 * input y la app hace el puente con una línea.
 *
 * La deduplicación va por `id`: dos avisos idénticos consecutivos tienen ids
 * distintos (los genera el `Notificador` con marca de tiempo y aleatorio), así
 * que el segundo sí se ve.
 */
@Component({
  selector: 'vd-avisos',
  template: '',
})
export class AvisosComponent {
  /** El aviso a mostrar; `null` cuando no hay ninguno. */
  readonly aviso = input<AvisoEnPantalla | null>(null);

  private readonly barra = inject(MatSnackBar);
  private readonly traductor = inject(TranslateService);
  private ultimoMostrado: string | null = null;

  constructor() {
    effect(() => {
      const actual = this.aviso();
      if (!actual || actual.id === this.ultimoMostrado) {
        return;
      }
      this.ultimoMostrado = actual.id;
      const cerrar = this.traductor.instant('comun.cerrar');
      this.barra.open(actual.mensaje, cerrar === 'comun.cerrar' ? 'Cerrar' : cerrar, {
        duration: DURACION_MS[actual.tipo] ?? 4_000,
        panelClass: `vd-aviso--${actual.tipo}`,
      });
    });
  }
}
```

- [ ] **Paso 3: exportar.** En `frontend/projects/libs/ui-kit/src/public-api.ts`, tras la línea de `ConfirmDialogComponent`:

```ts
export { AvisosComponent } from './lib/avisos/avisos.component';
export type { AvisoEnPantalla } from './lib/avisos/avisos.component';
```

- [ ] **Paso 4: los shells adelgazados.** En `vendi-tenant/src/app/layout/shell.component.ts` y `vendi-admin/src/app/layout/shell.component.ts`: quitar el import de `./avisos.component`, añadir `AvisosComponent` al import de `ui-kit`, importar `Notificador` de `data-access` y añadir la propiedad:

```ts
  /** Puente Notificador → ui-kit (el kit no puede conocer data-access). */
  readonly ultimoAviso = inject(Notificador).ultimo;
```

y en los dos `shell.component.html`:

```html
<vd-avisos [aviso]="ultimoAviso()" />
```

Borrar los dos `layout/avisos.component.ts`. Verificar:

```bash
grep -rn "avisos.component" frontend/projects --include="*.ts" | grep -v libs/ui-kit || echo "limpio"
# Esperado: limpio
```

- [ ] **Paso 5: verde en el workspace.**

```bash
cd frontend && npm run build:libs && npx ng test --watch=false
# Esperado: verde en los 9 proyectos (los specs de shell de admin/tenant
# montan el componente real: si pedían un Notificador ya lo provee el DI)
npx ng lint
# Esperado: sin errores (la sonda de frontera: ui-kit NO importa data-access)
grep -n "data-access" frontend/projects/libs/ui-kit/src/lib/avisos/avisos.component.ts || echo "frontera intacta"
# Esperado: frontera intacta
```

- [ ] **Paso 6: commit**

```bash
git add frontend
git commit -m "AvisosComponent deduplicado en ui-kit por input: las apps pasan Notificador.ultimo y la frontera queda intacta"
```

**Criterios de aceptación:** los 5 specs del anfitrión pasan; la dedup por `id` y las duraciones viven una sola vez; `ui-kit` no importa `data-access` (grep limpio); los 9 proyectos verdes.

---

## Tarea 4: Esqueleto de la consola — rutas por permiso, navegación del shell y `/sin-permiso`

**Files:**
- Create: `frontend/projects/vendi-tenant/src/app/features/sin-permiso/sin-permiso.component.ts`
- Modify: `frontend/projects/vendi-tenant/src/app/app.routes.ts`
- Modify: `frontend/projects/vendi-tenant/src/app/layout/shell.component.ts`
- Modify: `frontend/projects/vendi-tenant/src/app/app.spec.ts` (candados de rutas nuevos)
- Modify: `frontend/projects/vendi-tenant/public/i18n/es.json` (claves de menú y `sin_permiso`)

**Interfaces:**
- Consume: `permisoGuard` (Tarea 2), `tenantGuard`/`authGuard` existentes, `EmptyStateComponent` del ui-kit, la matriz de la decisión 4.
- Produce: `/sin-permiso` y la navegación filtrada. Las rutas de las features (`/caja`, `/catalogo`, `/inventario`, `/cuaderno`, `/numeros`) NO se añaden aquí: cada una entra con su componente en las Tareas 5-9, para que el workspace quede verde al final de cada tarea. El candado de `app.spec.ts` está escrito para crecer con ellas.

- [ ] **Paso 1: el candado, primero.** En `frontend/projects/vendi-tenant/src/app/app.spec.ts`, añadir al final un `describe` nuevo (el `preparar` existente gana un parámetro `roles` opcional que se pasa a `arrancarSesionFalsa`; por defecto `['dueno']`):

```ts
describe('mapa de la consola (Etapa 1.3, pista web)', () => {
  beforeEach(() => {
    KeycloakFake.reiniciar();
  });

  it('/elegir-negocio NO lleva tenantGuard (sería un bucle de redirección)', () => {
    const shell = routes[0];
    const elegir = shell.children?.find((r) => r.path === 'elegir-negocio');
    expect(elegir?.canActivate ?? []).toEqual([]);
  });

  it('/sin-permiso no lleva guard de permiso (sería el mismo bucle)', () => {
    const shell = routes[0];
    const sinPermiso = shell.children?.find((r) => r.path === 'sin-permiso');
    expect(sinPermiso).toBeTruthy();
    expect(sinPermiso?.canActivate ?? []).toEqual([]);
  });

  it('cada ruta de feature exige tenant; la matriz completa está en la decisión 4 del plan', () => {
    const shell = routes[0];
    const conPermiso = ['caja', 'catalogo', 'inventario', 'cuaderno', 'numeros'];
    for (const camino of conPermiso) {
      const ruta = shell.children?.find((r) => r.path === camino);
      // Las rutas llegan con sus features (Tareas 5-9): este aserto crece con
      // ellas. Si la ruta existe, su guard debe ser [tenantGuard, <uno más>].
      if (ruta) {
        expect(ruta.canActivate?.length).toBe(2);
      }
    }
  });

  it('quien no tiene el permiso cae en /sin-permiso y ve por qué', async () => {
    // Cajero: caja sí, reportes no (ADR-023).
    await preparar({
      autenticado: true,
      organizaciones: [ORG_A],
      roles: ['cajero', 'caja:leer', 'caja:abrir', 'caja:movimiento'],
    });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/sin-permiso');
    expect(TestBed.inject(Router).url).toBe('/sin-permiso');
    expect(harness.routeNativeElement?.textContent).toContain('No tienes acceso a esta sección');
  });
});
```

(Ajustar `preparar` para aceptar `roles?: string[]` y pasarlo en `arrancarSesionFalsa(auth, { organizaciones: opciones.organizaciones, roles: opciones.roles, perfil: ... })`, y añadir al `setTranslation('es', {...})` del propio `preparar` las claves nuevas que el candado aserta: `sin_permiso: { titulo: 'No tienes acceso a esta sección' }`. El catálogo de ese spec es mínimo a propósito; una clave que falte pinta la clave cruda y el aserto de texto falla aquí, no en pantalla.)

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: fallo — la ruta /sin-permiso no existe (el último it recibe el
# redirect a /mi-negocio o el NotFound, no el texto)
```

- [ ] **Paso 2: la pantalla `/sin-permiso`.** Crear `frontend/projects/vendi-tenant/src/app/features/sin-permiso/sin-permiso.component.ts`:

```ts
import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';
import { EmptyStateComponent } from 'ui-kit';

/**
 * Aterrizaje del `permisoGuard`: autenticado, con negocio elegido, pero sin
 * el permiso que la sección pide (un cajero que escribe `/numeros` a mano).
 *
 * No es un error y no se trata como tal: el mensaje dice qué pasó y devuelve
 * al trabajo, sin acusar a nadie. El backend seguiría respondiendo 403 aunque
 * esta pantalla no existiera — esto solo ahorra el viaje.
 */
@Component({
  selector: 'vd-sin-permiso',
  imports: [EmptyStateComponent],
  template: `
    <vd-empty-state
      icono="lock"
      titulo="sin_permiso.titulo"
      descripcion="sin_permiso.descripcion"
      textoAccion="sin_permiso.volver"
      (accion)="volver()"
    />
  `,
})
export class SinPermisoComponent {
  private readonly router = inject(Router);

  volver(): void {
    this.router.navigate(['/mi-negocio']).catch((error: unknown) => {
      console.error('No se pudo volver a «Mi negocio».', error);
    });
  }
}
```

- [ ] **Paso 3: la ruta.** En `frontend/projects/vendi-tenant/src/app/app.routes.ts`, dentro de `children` del shell, antes del comodín:

```ts
      {
        path: 'sin-permiso',
        loadComponent: () =>
          import('./features/sin-permiso/sin-permiso.component').then(
            (m) => m.SinPermisoComponent,
          ),
      },
```

- [ ] **Paso 4: la navegación filtrada.** Reemplazar el `navegacion` de `frontend/projects/vendi-tenant/src/app/layout/shell.component.ts` (las entradas de features apuntan a rutas que las Tareas 5-9 crean; el filtro ya es el definitivo de la decisión 4):

```ts
  /**
   * Navegación de la consola, filtrada por los permisos del token (ADR-023).
   *
   * `FullLayoutComponent` no conoce la sesión (ADR-011): el filtro es aquí.
   * Las secciones sin permiso se OCULTAN, no se deshabilitan — un botón gris
   * invita a preguntar «¿por qué no puedo?»; la sección ausente, no. La
   * defensa real es el guard de la ruta y, detrás, el backend.
   */
  readonly navegacion = computed<ElementoDeNavegacion[]>(() => {
    const elementos: ElementoDeNavegacion[] = [
      { etiqueta: 'negocio.titulo', icono: 'storefront', ruta: '/mi-negocio' },
    ];
    if (this.auth.hasPermission('caja:leer')) {
      elementos.push({ etiqueta: 'menu.caja', icono: 'point_of_sale', ruta: '/caja' });
    }
    if (this.auth.hasPermission('producto:leer')) {
      elementos.push(
        { etiqueta: 'menu.catalogo', icono: 'inventory_2', ruta: '/catalogo' },
        { etiqueta: 'menu.inventario', icono: 'warehouse', ruta: '/inventario' },
      );
    }
    if (this.auth.hasPermission('cliente:gestionar')) {
      elementos.push({ etiqueta: 'menu.cuaderno', icono: 'menu_book', ruta: '/cuaderno' });
    }
    if (this.auth.hasPermission('reporte:leer')) {
      elementos.push({ etiqueta: 'menu.numeros', icono: 'monitoring', ruta: '/numeros' });
    }
    return elementos;
  });
```

(`shell.component.ts` ya inyecta `AuthService` como `auth`; hacerlo `private readonly auth` → quitar el `private` si la plantilla lo necesita — hoy solo lo usa el `computed`, así que puede quedar privado.)

- [ ] **Paso 5: las claves de i18n.** En `frontend/projects/vendi-tenant/public/i18n/es.json`, añadir al nivel raíz:

```json
  "menu": {
    "caja": "Mi caja",
    "catalogo": "Catálogo",
    "inventario": "Inventario",
    "cuaderno": "Mi cuaderno",
    "numeros": "Mis números"
  },
  "sin_permiso": {
    "titulo": "No tienes acceso a esta sección",
    "descripcion": "Esta parte de la consola es para otro rol del negocio. Si crees que deberías verla, habla con el dueño.",
    "volver": "Volver a mi negocio"
  },
```

- [ ] **Paso 6: verde.**

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: verde (los 4 casos nuevos + los 6 que ya había)
npx ng lint vendi-tenant
# Esperado: sin errores
npx ng build vendi-tenant
# Esperado: build de desarrollo verde
```

- [ ] **Paso 7: commit**

```bash
git add frontend/projects/vendi-tenant
git commit -m "Esqueleto de la consola: /sin-permiso con su candado antibucle y navegación del shell filtrada por permisos"
```

**Criterios de aceptación:** `/sin-permiso` existe sin guard (el candado lo fija); la navegación muestra solo lo que el token permite (verificable en el spec del shell: con roles de cajero no aparece `menu.numeros` — añadir ese caso al `shell.component.spec.ts` si el archivo lo permite sin reescribirlo entero; si no, queda cubierto por el candado de `app.spec.ts` de las tareas 5-9); la app compila.

---

## Tarea 5: Mi caja (`/caja`) — sesión, movimientos, arqueo e historial

**Files:**
- Create: `frontend/projects/vendi-tenant/src/app/features/caja/contrato.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/caja/caja.service.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/caja/caja.service.spec.ts` (primero)
- Create: `frontend/projects/vendi-tenant/src/app/features/caja/movimiento-dialogo.component.ts` (+ `.html`)
- Create: `frontend/projects/vendi-tenant/src/app/features/caja/cerrar-caja-dialogo.component.ts` (+ `.html`)
- Create: `frontend/projects/vendi-tenant/src/app/features/caja/mi-caja.component.ts` (+ `.html` + `.scss`)
- Create: `frontend/projects/vendi-tenant/src/app/features/caja/mi-caja.component.spec.ts` (primero, junto al del servicio)
- Modify: `frontend/projects/vendi-tenant/src/app/app.routes.ts`
- Modify: `frontend/projects/vendi-tenant/public/i18n/es.json`

**Interfaces:**
- Consume: `GET /caja/sesiones/actual` (`SesionActualSalida`; 404 = sin sesión; `efectivo_esperado` null sin `caja:cerrar`), `POST /caja/sesiones` (`SesionAbrir`: `id`, `base_inicial`; 409 `caja_ya_abierta` con la sesión vigente en `details`), `GET/POST /caja/movimientos` (`MovimientoCrear`: `id` REQUERIDO, `tipo`, `categoria` cerrada, `monto` centavos, `motivo`), `POST /caja/sesiones/{id}/cerrar` (`SesionCerrar`: `contado`; → `ArqueoConDesglose`; 409 `caja_ya_cerrada`), `GET /caja/sesiones` (`PagedList_ArqueoSalida_`, exige `caja:cerrar` — el historial de arqueos es un reporte, `estado.md`). `formatearPesos` de `domain`.
- Produce: la primera feature completa de la consola; el patrón que repiten las Tareas 6-9.

- [ ] **Paso 1: el spec del servicio, primero.** Crear `frontend/projects/vendi-tenant/src/app/features/caja/caja.service.spec.ts` siguiendo el patrón de `tenants.service.spec.ts` de `vendi-admin` (setup mínimo: `provideHttpClient()` + `provideHttpClientTesting()` + `API_BASE_URL`; sin router ni translate; `afterEach(() => http.verify())`). Casos obligatorios, todos con aserto de método HTTP, URL, params y body:

```ts
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { API_BASE_URL } from 'data-access';
import { afterEach, describe, expect, it } from 'vitest';
import { CajaService } from './caja.service';

const BASE = 'https://api.vendi.co/api/v1';
const SESION = '5f1d0e2a-0000-4000-8000-aaaaaaaaaaaa';
const ID_OP = '5f1d0e2a-0000-4000-8000-bbbbbbbbbbbb';

function configurar(): { servicio: CajaService; http: HttpTestingController } {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
    ],
  });
  return { servicio: TestBed.inject(CajaService), http: TestBed.inject(HttpTestingController) };
}

describe('CajaService — contrato con la API', () => {
  let c: { servicio: CajaService; http: HttpTestingController };

  beforeEach(() => {
    c = configurar();
  });

  afterEach(() => {
    c.http.verify();
  });

  it('la sesión actual se pide en silencio (el 404 es "sin sesión", no un error)', () => {
    let resultado: unknown = 'sin-respuesta';
    c.servicio.sesionActual().subscribe((s) => (resultado = s));
    const req = c.http.expectOne(`${BASE}/caja/sesiones/actual`);
    expect(req.request.method).toBe('GET');
    req.flush({ id: SESION, estado: 'abierta', base_inicial: 50000, efectivo_esperado: null });
    expect((resultado as { id: string }).id).toBe(SESION);
  });

  it('el 404 de la sesión actual se traduce a null, no a error', () => {
    let resultado: unknown = 'sin-respuesta';
    c.servicio.sesionActual().subscribe({ next: (s) => (resultado = s), error: () => (resultado = 'error') });
    c.http
      .expectOne(`${BASE}/caja/sesiones/actual`)
      .flush({ message: 'no hay' }, { status: 404, statusText: 'Not Found' });
    expect(resultado).toBeNull();
  });

  it('otro error de la sesión actual SÍ se propaga', () => {
    let fallo = false;
    c.servicio.sesionActual().subscribe({ error: () => (fallo = true) });
    c.http.expectOne(`${BASE}/caja/sesiones/actual`).error(new ProgressEvent('error'));
    expect(fallo).toBe(true);
  });

  it('abrir manda id y base en centavos', () => {
    c.servicio.abrir(ID_OP, 50000).subscribe();
    const req = c.http.expectOne(`${BASE}/caja/sesiones`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ id: ID_OP, base_inicial: 50000 });
    req.flush({ id: SESION });
  });

  it('los movimientos se filtran por sesión y paginan en el servidor', () => {
    c.servicio.movimientos(SESION, 20, 10).subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/caja/movimientos`);
    expect(req.request.params.get('sesion_id')).toBe(SESION);
    expect(req.request.params.get('skip')).toBe('20');
    expect(req.request.params.get('limit')).toBe('10');
    req.flush({ items: [], total: 0, skip: 20, limit: 10 });
  });

  it('el movimiento viaja con su id de idempotencia, motivo y monto en centavos', () => {
    c.servicio
      .registrarMovimiento({
        id: ID_OP,
        tipo: 'egreso',
        categoria: 'arriendo',
        monto: 150000,
        motivo: 'Arriendo de junio',
      })
      .subscribe();
    const req = c.http.expectOne(`${BASE}/caja/movimientos`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      id: ID_OP,
      tipo: 'egreso',
      categoria: 'arriendo',
      monto: 150000,
      motivo: 'Arriendo de junio',
    });
    req.flush({ id: ID_OP });
  });

  it('cerrar manda solo el contado y devuelve el arqueo con desglose', () => {
    let arqueo: { diferencia?: number | null } | null = null;
    c.servicio.cerrar(SESION, 230000).subscribe((a) => (arqueo = a));
    const req = c.http.expectOne(`${BASE}/caja/sesiones/${SESION}/cerrar`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ contado: 230000 });
    req.flush({ id: SESION, estado: 'cerrada', diferencia: -5000, desglose: null });
    expect(arqueo?.diferencia).toBe(-5000);
  });

  it('el historial de arqueos pagina en el servidor', () => {
    c.servicio.historial(10, 10).subscribe();
    const req = c.http.expectOne((r) => r.url === `${BASE}/caja/sesiones`);
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('skip')).toBe('10');
    req.flush({ items: [], total: 0, skip: 10, limit: 10 });
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: fallo — Cannot find module './caja.service' (TS2307)
```

- [ ] **Paso 2: el contrato de tipos y el servicio.** Crear `frontend/projects/vendi-tenant/src/app/features/caja/contrato.ts`:

```ts
/**
 * Amarre compile-time con el cliente generado (patrón `contrato.ts` de
 * vendi-admin): los nombres son los del OpenAPI, no se redeclaran. Si el
 * backend cambia el contrato, esto deja de compilar — que es su trabajo.
 */
import type { components } from 'data-access';

export type SesionActualSalida = components['schemas']['SesionActualSalida'];
export type SesionSalida = components['schemas']['SesionSalida'];
export type MovimientoSalida = components['schemas']['MovimientoSalida'];
export type ArqueoSalida = components['schemas']['ArqueoSalida'];
export type ArqueoConDesglose = components['schemas']['ArqueoConDesglose'];

/** Lista cerrada del backend (migración 0008, ADR-021). */
export type TipoMovimiento = 'ingreso' | 'egreso';
export type CategoriaMovimiento = 'arriendo' | 'servicios' | 'retiro_dueno' | 'otro';

/** Cuerpo de `POST /caja/movimientos`; `id` es la ancla de idempotencia. */
export interface MovimientoNuevo {
  id: string;
  tipo: TipoMovimiento;
  categoria: CategoriaMovimiento;
  /** Centavos enteros. */
  monto: number;
  motivo: string;
}
```

Crear `frontend/projects/vendi-tenant/src/app/features/caja/caja.service.ts`:

```ts
import { HttpContext, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { ApiService, SILENCIAR_AVISO_ERROR } from 'data-access';
import { PagedList } from 'domain';
import { Observable, catchError, of, throwError } from 'rxjs';
import {
  ArqueoConDesglose,
  ArqueoSalida,
  MovimientoNuevo,
  MovimientoSalida,
  SesionActualSalida,
  SesionSalida,
} from './contrato';

const RUTA = '/caja';

/**
 * Cliente del módulo de caja (ADR-021).
 *
 * Solo `sesionActual` va silenciada: su 404 es «no hay caja abierta», un
 * estado normal de la pantalla, no un fallo que avisar. Todo lo demás deja
 * que `errorInterceptor` avise con el mensaje del backend, y la pantalla
 * reacciona al `code` cuando el flujo lo necesita (decisión 8 del plan).
 */
@Injectable({ providedIn: 'root' })
export class CajaService {
  private readonly api = inject(ApiService);

  /** La sesión abierta con su esperado vivo (null en el campo sin `caja:cerrar`), o null si no hay. */
  sesionActual(): Observable<SesionActualSalida | null> {
    return this.api
      .get<SesionActualSalida>(`${RUTA}/sesiones/actual`, undefined, {
        context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true),
      })
      .pipe(
        catchError((error: unknown) => {
          if (error instanceof HttpErrorResponse && error.status === 404) {
            return of(null);
          }
          return throwError(() => error);
        }),
      );
  }

  /** Apertura con `id` del cliente: el reenvío es un no-op (ADR-017). */
  abrir(id: string, baseInicial: number): Observable<SesionSalida> {
    return this.api.post<SesionSalida>(`${RUTA}/sesiones`, { id, base_inicial: baseInicial });
  }

  movimientos(
    sesionId: string,
    skip: number,
    limit: number,
  ): Observable<PagedList<MovimientoSalida>> {
    return this.api.get<PagedList<MovimientoSalida>>(`${RUTA}/movimientos`, {
      sesion_id: sesionId,
      skip,
      limit,
    });
  }

  registrarMovimiento(movimiento: MovimientoNuevo): Observable<MovimientoSalida> {
    return this.api.post<MovimientoSalida>(`${RUTA}/movimientos`, movimiento);
  }

  /** El arqueo: el servidor calcula y CONGELA esperado y diferencia. */
  cerrar(sesionId: string, contado: number): Observable<ArqueoConDesglose> {
    return this.api.post<ArqueoConDesglose>(`${RUTA}/sesiones/${sesionId}/cerrar`, { contado });
  }

  /** Historial de arqueos: exige `caja:cerrar` en el backend. */
  historial(skip: number, limit: number): Observable<PagedList<ArqueoSalida>> {
    return this.api.get<PagedList<ArqueoSalida>>(`${RUTA}/sesiones`, { skip, limit });
  }
}
```

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: los 8 specs del servicio en verde
```

- [ ] **Paso 3: el spec del componente, antes del componente.** Crear `frontend/projects/vendi-tenant/src/app/features/caja/mi-caja.component.spec.ts`. El montaje combina el `DialogoFalso` de `vendi-admin` con la sesión falsa de `app.spec.ts` (los botones llevan `*vdHasPermission`, que inyecta `AuthService` real):

```ts
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import {
  API_BASE_URL,
  CATALOGO_MINIMO_ES,
  errorInterceptor,
  fusionarCatalogos,
} from 'data-access';
import { Observable, of } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('keycloak-js', async () => {
  const mod = await import('auth/testing');
  return { default: mod.KeycloakFake };
});

import { AuthService } from 'auth';
import { KeycloakFake, arrancarSesionFalsa } from 'auth/testing';
import { formatearPesos } from 'domain';

import catalogoApp from '../../../../public/i18n/es.json';
import { MiCajaComponent } from './mi-caja.component';

const BASE = 'https://api.vendi.co/api/v1';
const SESION = '5f1d0e2a-0000-4000-8000-aaaaaaaaaaaa';

const ROLES_DUENO = [
  'dueno', 'caja:leer', 'caja:abrir', 'caja:cerrar', 'caja:movimiento', 'reporte:leer',
];
const ROLES_CAJERO = ['cajero', 'caja:leer', 'caja:abrir', 'caja:movimiento'];

class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

class DialogoFalso {
  resultados: unknown[] = [];
  readonly aperturas: { componente: unknown; datos: unknown }[] = [];
  open(componente: unknown, config?: { data?: unknown }) {
    this.aperturas.push({ componente, datos: config?.data });
    return { afterClosed: () => of(this.resultados.shift()) };
  }
}

interface Montaje {
  fixture: ComponentFixture<MiCajaComponent>;
  http: HttpTestingController;
  dialogos: DialogoFalso;
}

async function montar(roles: string[]): Promise<Montaje> {
  TestBed.resetTestingModule();
  KeycloakFake.reiniciar();
  const dialogos = new DialogoFalso();
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      provideHttpClient(withInterceptors([errorInterceptor])),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
      { provide: MatDialog, useValue: dialogos },
      AuthService,
      ...provideTranslateService({
        lang: 'es',
        fallbackLang: 'es',
        loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
      }),
    ],
  });
  TestBed.inject(TranslateService).use('es');
  await arrancarSesionFalsa(TestBed.inject(AuthService), { roles });
  return {
    fixture: TestBed.createComponent(MiCajaComponent),
    http: TestBed.inject(HttpTestingController),
    dialogos,
  };
}

function sesion(esperado: number | null) {
  return {
    id: SESION,
    estado: 'abierta',
    abierta_en: '2026-07-29T08:00:00-05:00',
    abierta_por: 'ana',
    base_inicial: 50000,
    efectivo_esperado: esperado,
  };
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

/** Responde el arranque "sin sesión" (404 silenciado → null). */
function arrancarSinSesion(m: Montaje): void {
  m.fixture.detectChanges();
  m.http
    .expectOne(`${BASE}/caja/sesiones/actual`)
    .flush({ message: 'no hay' }, { status: 404, statusText: 'Not Found' });
  // El historial se pide igual (es de quien cierra, haya o no sesión hoy).
  m.http
    .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'GET')
    .flush({ items: [], total: 0, skip: 0, limit: 10 });
  m.fixture.detectChanges();
}

/** Responde el arranque con sesión abierta (y sus movimientos e historial). */
function arrancarConSesion(m: Montaje, esperado: number | null, conHistorial: boolean): void {
  m.fixture.detectChanges();
  m.http.expectOne(`${BASE}/caja/sesiones/actual`).flush(sesion(esperado));
  m.http
    .expectOne((r) => r.url === `${BASE}/caja/movimientos`)
    .flush({ items: [], total: 0, skip: 0, limit: 10 });
  if (conHistorial) {
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'GET')
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
  }
  m.fixture.detectChanges();
}

describe('MiCajaComponent — sin sesión', () => {
  let m: Montaje;

  beforeEach(async () => {
    m = await montar(ROLES_DUENO);
    arrancarSinSesion(m);
  });

  afterEach(() => {
    m.http.verify();
  });

  it('ofrece abrir la caja con base inicial', () => {
    expect(texto(m.fixture)).toContain('Abrir caja');
  });

  it('abrir manda la base en centavos y recarga el estado', () => {
    m.fixture.componentInstance.basePesos.set(500);
    m.fixture.componentInstance.abrirCaja();
    const apertura = m.http.expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'POST');
    expect(apertura.request.body).toEqual({
      id: m.fixture.componentInstance.idApertura(),
      base_inicial: 50000,
    });
    apertura.flush(sesion(null));
    m.http.expectOne(`${BASE}/caja/sesiones/actual`).flush(sesion(50000));
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/movimientos`)
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'GET')
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    expect(m.fixture.componentInstance.sesion()?.id).toBe(SESION);
  });

  it('un 409 caja_ya_abierta (otra caja abrió primero) refresca el estado en vez de morir', () => {
    m.fixture.componentInstance.basePesos.set(500);
    m.fixture.componentInstance.abrirCaja();
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'POST')
      .flush(
        { message: 'Ya hay una caja abierta', code: 'caja_ya_abierta' },
        { status: 409, statusText: 'Conflict' },
      );
    m.http.expectOne(`${BASE}/caja/sesiones/actual`).flush(sesion(50000));
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/movimientos`)
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'GET')
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    m.fixture.detectChanges();
    expect(m.fixture.componentInstance.sesion()?.estado).toBe('abierta');
  });
});

describe('MiCajaComponent — con sesión abierta', () => {
  afterEach(() => {
    TestBed.inject(HttpTestingController).verify();
  });

  it('el dueño ve el esperado; el backend se lo manda', async () => {
    const m = await montar(ROLES_DUENO);
    arrancarConSesion(m, 230000, true);
    // Sin asertar el símbolo exacto: Intl puede meter un espacio duro tras
    // el "$" según la versión de ICU. Lo que importa es la cifra.
    expect(texto(m.fixture)).toContain('2.300');
  });

  it('el cajero NO ve la cifra: llega null y no se pinta (ni como cero)', async () => {
    const m = await montar(ROLES_CAJERO);
    arrancarConSesion(m, null, false);
    const visible = texto(m.fixture);
    expect(visible).not.toContain('Esperado en gaveta');
    expect(visible).not.toContain('Historial de arqueos');
    // Y nunca pidió el historial: http.verify() del afterEach lo garantiza.
  });

  it('registrar un movimiento manda motivo, categoría y monto en centavos con id estable', async () => {
    const m = await montar(ROLES_DUENO);
    arrancarConSesion(m, 230000, true);
    m.dialogos.resultados = [
      { tipo: 'egreso', categoria: 'arriendo', montoCentavos: 150000, motivo: 'Arriendo de junio' },
    ];
    m.fixture.componentInstance.registrarMovimiento();
    const req = m.http.expectOne((r) => r.url === `${BASE}/caja/movimientos` && r.method === 'POST');
    expect(req.request.body).toEqual({
      id: expect.any(String),
      tipo: 'egreso',
      categoria: 'arriendo',
      monto: 150000,
      motivo: 'Arriendo de junio',
    });
    req.flush({ id: 'x' });
    // La escritura recarga movimientos y refresca la sesión (esperado vivo).
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/movimientos` && r.method === 'GET')
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    m.http.expectOne(`${BASE}/caja/sesiones/actual`).flush(sesion(230000));
  });

  it('cerrar pide el contado y muestra la diferencia del arqueo', async () => {
    const m = await montar(ROLES_DUENO);
    arrancarConSesion(m, 230000, true);
    expect(m.dialogos.aperturas.length).toBe(0);
    m.dialogos.resultados = [225000];
    m.fixture.componentInstance.cerrarCaja();
    expect((m.dialogos.aperturas[0].datos as { esperado: number | null }).esperado).toBe(230000);

    const cierre = m.http.expectOne(`${BASE}/caja/sesiones/${SESION}/cerrar`);
    expect(cierre.request.body).toEqual({ contado: 225000 });
    cierre.flush({
      ...sesion(null),
      estado: 'cerrada',
      cerrada_en: '2026-07-29T20:00:00-05:00',
      cerrada_por: 'ana',
      efectivo_esperado: 230000,
      efectivo_contado: 225000,
      diferencia: -5000,
      desglose: {
        base_inicial: 50000, ventas_efectivo: 180000, abonos_efectivo: 0,
        ingresos: 0, egresos: 0, devoluciones: 0, esperado: 230000,
      },
    });
    // Tras cerrar, el historial se recarga solo.
    m.http
      .expectOne((r) => r.url === `${BASE}/caja/sesiones` && r.method === 'GET')
      .flush({ items: [], total: 0, skip: 0, limit: 10 });
    m.fixture.detectChanges();

    const visible = texto(m.fixture);
    expect(visible).toContain('Diferencia');
    expect(m.fixture.componentInstance.textoDiferencia(-5000)).toBe(`-${formatearPesos(5000)}`);
    expect(m.fixture.componentInstance.sesion()).toBeNull();
  });

  it('un fallo de red deja la pantalla en estado de reintento, no en spinner eterno', async () => {
    const m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne(`${BASE}/caja/sesiones/actual`).error(new ProgressEvent('error'));
    m.fixture.detectChanges();
    expect(m.fixture.componentInstance.fallo()).toBe(true);
    expect(texto(m.fixture)).toContain('Reintentar');
  });
});
```

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: fallo — Cannot find module './mi-caja.component' (TS2307)
```

- [ ] **Paso 4: los dos diálogos.** Crear `frontend/projects/vendi-tenant/src/app/features/caja/movimiento-dialogo.component.ts` (patrón de `tenant-formulario.component.ts`: diálogo tonto con `FormRenderer`, quien llama a la API es la página):

```ts
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit';
import { CategoriaMovimiento, TipoMovimiento } from './contrato';

/** Lo que devuelve el diálogo; `undefined` si se canceló. */
export interface ResultadoMovimiento {
  tipo: TipoMovimiento;
  categoria: CategoriaMovimiento;
  /** Centavos enteros, convertidos en el borde. */
  montoCentavos: number;
  motivo: string;
}

/**
 * Ingreso/egreso manual de la gaveta (ADR-021). El `motivo` es obligatorio
 * porque un movimiento sin justificación es un desfalco con buenos modales.
 */
@Component({
  selector: 'vd-movimiento-dialogo',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  template: `
    <h2 mat-dialog-title>{{ 'caja.movimiento.titulo' | translate }}</h2>
    <mat-dialog-content>
      <vd-form-renderer
        [configuracion]="configuracion"
        [formulario]="formulario"
        textoEnviar="comun.guardar"
        textoCancelar="comun.cancelar"
        (enviado)="alEnviar($event)"
        (cancelado)="cancelar()"
      />
    </mat-dialog-content>
  `,
})
export class MovimientoDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref = inject<MatDialogRef<MovimientoDialogoComponent, ResultadoMovimiento | undefined>>(
    MatDialogRef,
  );

  readonly configuracion: ConfiguracionFormulario = {
    campos: [
      {
        clave: 'tipo',
        etiqueta: 'caja.movimiento.tipo',
        tipo: 'select',
        valorPorDefecto: 'egreso',
        validadores: [{ tipo: 'required' }],
        opciones: [
          { etiqueta: 'caja.movimiento.ingreso', valor: 'ingreso' },
          { etiqueta: 'caja.movimiento.egreso', valor: 'egreso' },
        ],
      },
      {
        clave: 'categoria',
        etiqueta: 'caja.movimiento.categoria',
        tipo: 'select',
        valorPorDefecto: 'otro',
        validadores: [{ tipo: 'required' }],
        opciones: [
          { etiqueta: 'caja.categoria.arriendo', valor: 'arriendo' },
          { etiqueta: 'caja.categoria.servicios', valor: 'servicios' },
          { etiqueta: 'caja.categoria.retiro_dueno', valor: 'retiro_dueno' },
          { etiqueta: 'caja.categoria.otro', valor: 'otro' },
        ],
      },
      {
        clave: 'monto_pesos',
        etiqueta: 'caja.movimiento.monto',
        tipo: 'number',
        validadores: [{ tipo: 'required' }, { tipo: 'min', valor: 1 }],
      },
      {
        clave: 'motivo',
        etiqueta: 'caja.movimiento.motivo',
        tipo: 'text',
        marcador: 'caja.movimiento.motivo_marcador',
        validadores: [
          { tipo: 'required' },
          { tipo: 'minLength', valor: 3 },
          { tipo: 'maxLength', valor: 300 },
        ],
      },
    ],
  };

  readonly formulario: FormGroup = FormRendererComponent.construirFormulario(
    this.fb,
    this.configuracion,
  );

  /** Candado de doble envío: MatDialogRef.close() no es síncrono. */
  private readonly enviando = signal(false);

  alEnviar(valores: Record<string, unknown>): void {
    if (this.enviando()) {
      return;
    }
    const pesos = Number(valores['monto_pesos']);
    const motivo = String(valores['motivo'] ?? '').trim();
    if (!Number.isFinite(pesos) || pesos <= 0 || motivo.length < 3) {
      return;
    }
    this.enviando.set(true);
    this.ref.close({
      tipo: valores['tipo'] as TipoMovimiento,
      categoria: valores['categoria'] as CategoriaMovimiento,
      montoCentavos: Math.round(pesos * 100),
      motivo,
    });
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
```

Crear `frontend/projects/vendi-tenant/src/app/features/caja/cerrar-caja-dialogo.component.ts`:

```ts
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { formatearPesos } from 'domain';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit';

/** Datos con los que se abre el diálogo de cierre. */
export interface DatosCerrarCaja {
  /** El esperado vivo, o null si el backend no lo dio (no debería: cerrar exige `caja:cerrar`). */
  esperado: number | null;
}

/**
 * El arqueo (ADR-021): el tendero cuenta la gaveta y el servidor calcula y
 * congela esperado y diferencia. El diálogo muestra el esperado ANTES de
 * cerrar — quien llega hasta aquí tiene `caja:cerrar`, así que el backend ya
 * se lo reveló en `sesiones/actual`.
 */
@Component({
  selector: 'vd-cerrar-caja-dialogo',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  template: `
    <h2 mat-dialog-title>{{ 'caja.cerrar.titulo' | translate }}</h2>
    <mat-dialog-content>
      @if (datos.esperado !== null) {
        <p>{{ 'caja.cerrar.esperado' | translate: { monto: formatear(datos.esperado) } }}</p>
      }
      <vd-form-renderer
        [configuracion]="configuracion"
        [formulario]="formulario"
        textoEnviar="caja.cerrar.confirmar"
        textoCancelar="comun.cancelar"
        (enviado)="alEnviar($event)"
        (cancelado)="cancelar()"
      />
    </mat-dialog-content>
  `,
})
export class CerrarCajaDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref = inject<MatDialogRef<CerrarCajaDialogoComponent, number | undefined>>(MatDialogRef);
  readonly datos = inject<DatosCerrarCaja>(MAT_DIALOG_DATA);

  readonly formatear = formatearPesos;

  readonly configuracion: ConfiguracionFormulario = {
    campos: [
      {
        clave: 'contado_pesos',
        etiqueta: 'caja.cerrar.contado',
        tipo: 'number',
        ayuda: 'caja.cerrar.contado_ayuda',
        validadores: [{ tipo: 'required' }, { tipo: 'min', valor: 0 }],
      },
    ],
  };

  readonly formulario: FormGroup = FormRendererComponent.construirFormulario(
    this.fb,
    this.configuracion,
  );

  private readonly enviando = signal(false);

  alEnviar(valores: Record<string, unknown>): void {
    if (this.enviando()) {
      return;
    }
    const pesos = Number(valores['contado_pesos']);
    if (!Number.isFinite(pesos) || pesos < 0) {
      return;
    }
    this.enviando.set(true);
    this.ref.close(Math.round(pesos * 100));
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
```

- [ ] **Paso 5: el componente de página.** Crear `frontend/projects/vendi-tenant/src/app/features/caja/mi-caja.component.ts`:

```ts
import { Component, TemplateRef, computed, inject, signal, viewChild } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { PageEvent } from '@angular/material/paginator';
import { TranslateModule } from '@ngx-translate/core';
import { AuthService, HasPermissionDirective } from 'auth';
import { formatearPesos } from 'domain';
import {
  ColumnaTabla,
  DataTableComponent,
  LoadingSpinnerComponent,
  PageHeaderComponent,
  StatusBadgeComponent,
  VarianteEstado,
} from 'ui-kit';
import { CajaService } from './caja.service';
import {
  CerrarCajaDialogoComponent,
  DatosCerrarCaja,
} from './cerrar-caja-dialogo.component';
import { ArqueoConDesglose, ArqueoSalida, MovimientoSalida, SesionActualSalida } from './contrato';
import { MovimientoDialogoComponent, ResultadoMovimiento } from './movimiento-dialogo.component';

const TAMANO_PAGINA = 10;

/** Fila del historial: el arqueo más una clave fantasma para la diferencia. */
interface FilaArqueo extends ArqueoSalida {
  acciones?: never;
}

/**
 * Mi caja: la sesión del día, sus movimientos manuales y el arqueo.
 *
 * Lo que cada rol ve lo decide primero el backend: al cajero le llega
 * `efectivo_esperado: null` y un 403 si pide el historial; la pantalla solo
 * se lo ahorra (ADR-023). Quien cierra ve la cuenta completa: el esperado
 * vivo, el cierre con su diferencia y el historial congelado de arqueos.
 */
@Component({
  selector: 'vd-mi-caja',
  imports: [
    TranslateModule,
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatInputModule,
    HasPermissionDirective,
    PageHeaderComponent,
    LoadingSpinnerComponent,
    DataTableComponent,
    StatusBadgeComponent,
  ],
  templateUrl: './mi-caja.component.html',
  styleUrl: './mi-caja.component.scss',
})
export class MiCajaComponent {
  private readonly servicio = inject(CajaService);
  private readonly dialogos = inject(MatDialog);
  private readonly auth = inject(AuthService);

  /** null = no hay sesión abierta (el 404 silenciado del servicio). */
  readonly sesion = signal<SesionActualSalida | null>(null);
  readonly cargando = signal(true);
  readonly fallo = signal(false);

  /** Formulario de apertura (inline): la base en pesos y el id idempotente. */
  readonly basePesos = signal<number | null>(null);
  readonly idApertura = signal(crypto.randomUUID());
  readonly abriendo = signal(false);

  readonly movimientos = signal<MovimientoSalida[]>([]);
  readonly totalMovimientos = signal(0);
  readonly indiceMovimientos = signal(0);
  readonly cargandoMovimientos = signal(false);

  /** El arqueo recién hecho: la pantalla lo muestra hasta la próxima carga. */
  readonly arqueo = signal<ArqueoConDesglose | null>(null);

  readonly historial = signal<FilaArqueo[]>([]);
  readonly totalHistorial = signal(0);
  readonly indiceHistorial = signal(0);
  readonly cargandoHistorial = signal(false);

  readonly formatear = formatearPesos;
  readonly dialogoAbierto = signal(false);

  private readonly plantillaDiferencia =
    viewChild<TemplateRef<{ $implicit: FilaArqueo }>>('celdaDiferencia');

  readonly columnasHistorial = computed<ColumnaTabla<FilaArqueo>[]>(() => [
    { clave: 'abierta_en', etiqueta: 'caja.historial.abierta' },
    { clave: 'cerrada_por', etiqueta: 'caja.historial.cerrada_por' },
    { clave: 'efectivo_esperado', etiqueta: 'caja.historial.esperado' },
    { clave: 'efectivo_contado', etiqueta: 'caja.historial.contado' },
    {
      clave: 'acciones',
      etiqueta: 'caja.historial.diferencia',
      plantilla: this.plantillaDiferencia(),
      ancho: '8rem',
    },
  ]);

  constructor() {
    this.cargar();
  }

  cargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    this.servicio.sesionActual().subscribe({
      next: (sesion) => {
        this.sesion.set(sesion);
        this.cargando.set(false);
        if (sesion) {
          this.cargarMovimientos();
        }
        // El historial es de quien cierra, haya o no sesión abierta hoy.
        this.cargarHistorial();
      },
      error: () => {
        // El 404 ya es null en el servicio; llegar aquí es fallo de verdad.
        this.cargando.set(false);
        this.fallo.set(true);
      },
    });
  }

  abrirCaja(): void {
    const pesos = this.basePesos();
    if (this.abriendo() || pesos === null || pesos < 0) {
      return;
    }
    this.abriendo.set(true);
    this.servicio.abrir(this.idApertura(), Math.round(pesos * 100)).subscribe({
      next: () => this.recargarEstado(),
      error: (error: unknown) => {
        this.abriendo.set(false);
        // Otra caja abrió primero: la verdad está en el servidor, no aquí.
        if (codigoDe(error) === 'caja_ya_abierta') {
          this.recargarEstado();
        }
      },
    });
  }

  registrarMovimiento(): void {
    const sesion = this.sesion();
    if (!sesion || this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    // El id se genera AL ABRIR: el reenvío del mismo formulario es el no-op
    // idempotente del servidor, no un movimiento duplicado (decisión 7).
    const id = crypto.randomUUID();
    this.dialogos
      .open<MovimientoDialogoComponent, never, ResultadoMovimiento | undefined>(
        MovimientoDialogoComponent,
        { width: '32rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargandoMovimientos.set(true);
        this.servicio
          .registrarMovimiento({
            id,
            tipo: resultado.tipo,
            categoria: resultado.categoria,
            monto: resultado.montoCentavos,
            motivo: resultado.motivo,
          })
          .subscribe({
            next: () => {
              this.cargarMovimientos();
              this.refrescarSesion();
            },
            error: () => this.cargandoMovimientos.set(false),
          });
      });
  }

  cerrarCaja(): void {
    const sesion = this.sesion();
    if (!sesion || this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const datos: DatosCerrarCaja = { esperado: sesion.efectivo_esperado ?? null };
    this.dialogos
      .open<CerrarCajaDialogoComponent, DatosCerrarCaja, number | undefined>(
        CerrarCajaDialogoComponent,
        { data: datos, width: '32rem' },
      )
      .afterClosed()
      .subscribe((contado) => {
        this.dialogoAbierto.set(false);
        if (contado === undefined) {
          return;
        }
        this.servicio.cerrar(sesion.id, contado).subscribe({
          next: (arqueo) => {
            this.arqueo.set(arqueo);
            this.sesion.set(null);
            this.movimientos.set([]);
            this.totalMovimientos.set(0);
            this.idApertura.set(crypto.randomUUID());
            this.cargarHistorial();
          },
          error: (error: unknown) => {
            // Ya estaba cerrada (doble clic entre pestañas): refrescar.
            if (codigoDe(error) === 'caja_ya_cerrada') {
              this.recargarEstado();
            }
          },
        });
      });
  }

  alPaginarMovimientos(evento: PageEvent): void {
    this.indiceMovimientos.set(evento.pageIndex);
    this.cargarMovimientos();
  }

  alPaginarHistorial(evento: PageEvent): void {
    this.indiceHistorial.set(evento.pageIndex);
    this.cargarHistorial();
  }

  varianteDiferencia(diferencia: number | null | undefined): VarianteEstado {
    return diferencia ? 'peligro' : 'exito';
  }

  textoDiferencia(diferencia: number | null | undefined): string {
    if (diferencia === null || diferencia === undefined) {
      return '—';
    }
    const signo = diferencia < 0 ? '-' : '';
    return `${signo}${this.formatear(Math.abs(diferencia))}`;
  }

  textoMonto(movimiento: MovimientoSalida): string {
    const signo = movimiento.tipo === 'egreso' ? '-' : '';
    return `${signo}${this.formatear(movimiento.monto)}`;
  }

  private cargarMovimientos(): void {
    const sesion = this.sesion();
    if (!sesion) {
      return;
    }
    this.cargandoMovimientos.set(true);
    this.servicio
      .movimientos(sesion.id, this.indiceMovimientos() * TAMANO_PAGINA, TAMANO_PAGINA)
      .subscribe({
        next: (pagina) => {
          this.movimientos.set(pagina.items);
          this.totalMovimientos.set(pagina.total);
          this.cargandoMovimientos.set(false);
        },
        error: () => this.cargandoMovimientos.set(false),
      });
  }

  private cargarHistorial(): void {
    // Sin `caja:cerrar` el backend responde 403: ni se pide (decisión 4). La
    // directiva oculta la sección; esta guarda evita la petición huérfana.
    if (!this.auth.hasPermission('caja:cerrar')) {
      return;
    }
    this.cargandoHistorial.set(true);
    this.servicio
      .historial(this.indiceHistorial() * TAMANO_PAGINA, TAMANO_PAGINA)
      .subscribe({
        next: (pagina) => {
          this.historial.set(pagina.items);
          this.totalHistorial.set(pagina.total);
          this.cargandoHistorial.set(false);
        },
        error: () => this.cargandoHistorial.set(false),
      });
  }

  /** Recarga sesión + tablas tras una escritura (el esperado vivo cambia). */
  private recargarEstado(): void {
    this.abriendo.set(false);
    this.cargar();
  }

  private refrescarSesion(): void {
    this.servicio.sesionActual().subscribe({
      next: (sesion) => this.sesion.set(sesion),
      error: () => undefined,
    });
  }
}

/** El `code` estable del sobre de error del backend (decisión 8 del plan). */
function codigoDe(error: unknown): string | null {
  if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
    const codigo = (error.error as { code?: unknown }).code;
    return typeof codigo === 'string' ? codigo : null;
  }
  return null;
}
```

- [ ] **Paso 6: la plantilla.** Crear `frontend/projects/vendi-tenant/src/app/features/caja/mi-caja.component.html`:

```html
<vd-page-header titulo="caja.titulo" subtitulo="caja.subtitulo" />

@if (cargando()) {
  <vd-loading-spinner />
} @else if (fallo()) {
  <div role="alert">
    <span>{{ 'caja.fallo' | translate }}</span>
    <button matButton type="button" (click)="cargar()">{{ 'comun.reintentar' | translate }}</button>
  </div>
} @else {
  @if (arqueo(); as cierre) {
    <mat-card>
      <mat-card-header>
        <mat-card-title>{{ 'caja.arqueo.titulo' | translate }}</mat-card-title>
      </mat-card-header>
      <mat-card-content>
        <dl>
          @if (cierre.desglose; as desglose) {
            <dt>{{ 'caja.arqueo.base' | translate }}</dt>
            <dd>{{ formatear(desglose.base_inicial) }}</dd>
            <dt>{{ 'caja.arqueo.ventas' | translate }}</dt>
            <dd>{{ formatear(desglose.ventas_efectivo) }}</dd>
            <dt>{{ 'caja.arqueo.abonos' | translate }}</dt>
            <dd>{{ formatear(desglose.abonos_efectivo) }}</dd>
            <dt>{{ 'caja.arqueo.ingresos' | translate }}</dt>
            <dd>{{ formatear(desglose.ingresos) }}</dd>
            <dt>{{ 'caja.arqueo.egresos' | translate }}</dt>
            <dd>{{ formatear(desglose.egresos) }}</dd>
          }
          <dt>{{ 'caja.historial.esperado' | translate }}</dt>
          <dd>{{ formatear(cierre.efectivo_esperado ?? 0) }}</dd>
          <dt>{{ 'caja.historial.contado' | translate }}</dt>
          <dd>{{ formatear(cierre.efectivo_contado ?? 0) }}</dd>
          <dt>{{ 'caja.historial.diferencia' | translate }}</dt>
          <dd>
            <vd-status-badge
              [etiqueta]="textoDiferencia(cierre.diferencia)"
              [variante]="varianteDiferencia(cierre.diferencia)"
            />
          </dd>
        </dl>
      </mat-card-content>
    </mat-card>
  }

  @if (sesion(); as sesion) {
    <mat-card>
      <mat-card-header>
        <mat-card-title>{{ 'caja.sesion.abierta' | translate }}</mat-card-title>
      </mat-card-header>
      <mat-card-content>
        <p>{{ 'caja.sesion.base' | translate: { monto: formatear(sesion.base_inicial) } }}</p>
        @if (sesion.efectivo_esperado !== null && sesion.efectivo_esperado !== undefined) {
          <p>
            {{ 'caja.sesion.esperado' | translate: { monto: formatear(sesion.efectivo_esperado) } }}
          </p>
        }
      </mat-card-content>
      <mat-card-actions>
        <button
          matButton="outlined"
          type="button"
          *vdHasPermission="'caja:movimiento'"
          (click)="registrarMovimiento()"
        >
          {{ 'caja.movimiento.nuevo' | translate }}
        </button>
        <button
          matButton="filled"
          type="button"
          *vdHasPermission="'caja:cerrar'"
          (click)="cerrarCaja()"
        >
          {{ 'caja.cerrar.accion' | translate }}
        </button>
      </mat-card-actions>
    </mat-card>

    <h2>{{ 'caja.movimientos.titulo' | translate }}</h2>
    <vd-data-table
      [columnas]="[
        { clave: 'created_at', etiqueta: 'caja.movimientos.columna.fecha' },
        { clave: 'tipo', etiqueta: 'caja.movimientos.columna.tipo' },
        { clave: 'categoria', etiqueta: 'caja.movimientos.columna.categoria' },
        { clave: 'motivo', etiqueta: 'caja.movimientos.columna.motivo' },
        { clave: 'monto', etiqueta: 'caja.movimientos.columna.monto' }
      ]"
      [filas]="movimientos()"
      [total]="totalMovimientos()"
      [cargando]="cargandoMovimientos()"
      [indicePagina]="indiceMovimientos()"
      [tamanoPagina]="10"
      iconoVacio="payments"
      tituloVacio="caja.movimientos.vacio"
      (paginaCambia)="alPaginarMovimientos($event)"
    />
  } @else {
    <!--
      Tras cerrar queda el arqueo en pantalla Y se puede abrir la caja del
      turno siguiente sin recargar: el resultado no tapa la operación.
    -->
    <mat-card *vdHasPermission="'caja:abrir'">
      <mat-card-header>
        <mat-card-title>{{ 'caja.abrir.titulo' | translate }}</mat-card-title>
      </mat-card-header>
      <mat-card-content>
        <p>{{ 'caja.abrir.descripcion' | translate }}</p>
        <mat-form-field>
          <mat-label>{{ 'caja.abrir.base' | translate }}</mat-label>
          <input
            matInput
            type="number"
            min="0"
            [ngModel]="basePesos()"
            (ngModelChange)="basePesos.set($event)"
          />
        </mat-form-field>
      </mat-card-content>
      <mat-card-actions>
        <button
          matButton="filled"
          type="button"
          [disabled]="abriendo() || basePesos() === null"
          (click)="abrirCaja()"
        >
          {{ 'caja.abrir.accion' | translate }}
        </button>
      </mat-card-actions>
    </mat-card>
  }

  <section *vdHasPermission="'caja:cerrar'">
    <h2>{{ 'caja.historial.titulo' | translate }}</h2>
    <vd-data-table
      [columnas]="columnasHistorial()"
      [filas]="historial()"
      [total]="totalHistorial()"
      [cargando]="cargandoHistorial()"
      [indicePagina]="indiceHistorial()"
      [tamanoPagina]="10"
      iconoVacio="receipt_long"
      tituloVacio="caja.historial.vacio"
      (paginaCambia)="alPaginarHistorial($event)"
    />
    <ng-template #celdaDiferencia let-fila>
      <vd-status-badge
        [etiqueta]="textoDiferencia(fila.diferencia)"
        [variante]="varianteDiferencia(fila.diferencia)"
      />
    </ng-template>
  </section>
}
```

(Aviso de formato: la tabla de movimientos pinta `monto` crudo de la API — centavos — en la columna por defecto. Si al ejecutar la tarea se prefiere el formato de pesos, añadir una `ng-template #celdaMonto` con `textoMonto(fila)` y cablearla como `celdaDiferencia`; el spec no aserta formato en esa tabla, así que la mejora no rompe nada. Lo correcto es hacerla con plantilla desde el inicio si el ejecutor lo ve claro; queda a su criterio con esta nota.)

- [ ] **Paso 7: los estilos.** Crear `frontend/projects/vendi-tenant/src/app/features/caja/mi-caja.component.scss` con lo mínimo: tarjetas con margen inferior, `dl` en dos columnas, tablas a ancho completo. Sin diseño elaborado: es la entrega funcional; la capa visual llega con la pista de UX.

- [ ] **Paso 8: la ruta.** En `app.routes.ts`, dentro de `children`, tras `mi-negocio`:

```ts
      {
        path: 'caja',
        canActivate: [tenantGuard, permisoGuard('caja:leer')],
        loadComponent: () =>
          import('./features/caja/mi-caja.component').then((m) => m.MiCajaComponent),
      },
```

(y añadir `permisoGuard` al import de `'auth'`).

- [ ] **Paso 9: las claves de i18n.** En `public/i18n/es.json`:

```json
  "caja": {
    "titulo": "Mi caja",
    "subtitulo": "La caja del día: base, movimientos y arqueo",
    "fallo": "No pudimos cargar el estado de la caja.",
    "abrir": {
      "titulo": "No hay caja abierta",
      "descripcion": "Abre la caja para registrar los movimientos del día. La base es el efectivo con el que empiezas.",
      "base": "Base inicial (pesos)",
      "accion": "Abrir caja"
    },
    "sesion": {
      "abierta": "Caja abierta",
      "base": "Base inicial: {{monto}}",
      "esperado": "Esperado en gaveta: {{monto}}"
    },
    "movimiento": {
      "nuevo": "Registrar movimiento",
      "titulo": "Movimiento de caja",
      "tipo": "Tipo",
      "ingreso": "Ingreso",
      "egreso": "Egreso",
      "categoria": "Categoría",
      "monto": "Monto (pesos)",
      "motivo": "Motivo",
      "motivo_marcador": "Ej.: pago del arriendo de junio"
    },
    "categoria": {
      "arriendo": "Arriendo",
      "servicios": "Servicios",
      "retiro_dueno": "Retiro del dueño",
      "otro": "Otro"
    },
    "movimientos": {
      "titulo": "Movimientos de la sesión",
      "vacio": "Todavía no hay movimientos manuales",
      "columna": {
        "fecha": "Fecha",
        "tipo": "Tipo",
        "categoria": "Categoría",
        "motivo": "Motivo",
        "monto": "Monto"
      }
    },
    "cerrar": {
      "accion": "Cerrar caja",
      "titulo": "Cerrar la caja del día",
      "esperado": "Según el sistema debería haber {{monto}}.",
      "contado": "Efectivo contado (pesos)",
      "contado_ayuda": "Cuenta la gaveta y escribe el total, sin comas ni puntos de miles.",
      "confirmar": "Cerrar con este conteo"
    },
    "arqueo": {
      "titulo": "Arqueo del día",
      "base": "Base inicial",
      "ventas": "Ventas en efectivo",
      "abonos": "Abonos de fiado en efectivo",
      "ingresos": "Ingresos manuales",
      "egresos": "Egresos manuales"
    },
    "historial": {
      "titulo": "Historial de arqueos",
      "vacio": "Todavía no hay arqueos",
      "abierta": "Abierta",
      "cerrada_por": "Cerrada por",
      "esperado": "Esperado",
      "contado": "Contado",
      "diferencia": "Diferencia"
    }
  },
```

- [ ] **Paso 10: verde y commit.**

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: verde — 8 del servicio + 8 del componente + los anteriores
npx ng lint vendi-tenant && npx ng build vendi-tenant
# Esperado: sin errores; build de desarrollo verde
git add frontend/projects/vendi-tenant
git commit -m "Mi caja en vendi-tenant: sesión con esperado por permiso, movimientos con motivo, arqueo con diferencia e historial"
```

**Criterios de aceptación:** los 16 specs nuevos pasan; el cajero no ve esperado ni historial (y nunca se pide el historial sin `caja:cerrar` — lo garantiza `http.verify()`); `caja_ya_abierta` y `caja_ya_cerrada` refrescan el estado en vez de romper la pantalla; el id de idempotencia se genera al abrir el diálogo; la ruta lleva `tenantGuard` + `permisoGuard('caja:leer')`.

---

## Tarea 6: Mi catálogo (`/catalogo`) — productos con granel, EAN e IVA

**Files:**
- Create: `frontend/projects/vendi-tenant/src/app/features/catalogo/contrato.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/catalogo/catalogo.service.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/catalogo/catalogo.service.spec.ts` (primero)
- Create: `frontend/projects/vendi-tenant/src/app/features/catalogo/producto-dialogo.component.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/catalogo/catalogo.component.ts` (+ `.html` + `.scss`)
- Create: `frontend/projects/vendi-tenant/src/app/features/catalogo/catalogo.component.spec.ts` (primero)
- Modify: `frontend/projects/vendi-tenant/src/app/app.routes.ts`
- Modify: `frontend/projects/vendi-tenant/public/i18n/es.json`

**Interfaces:**
- Consume: `GET /productos` (`q`, `skip`, `limit` → `PagedList_ProductoSalida_`), `POST /productos` (`ProductoCrear`; 409 `codigo_barras_duplicado`, 403 `limite_de_productos_alcanzado`), `PATCH /productos/{id}` (`ProductoActualizar` — sin `stock_actual`: el stock lo mueven los movimientos, ADR-020), `DELETE /productos/{id}` (204, borrado lógico que libera el EAN). `formatearPesos`, `miliDeCantidad`, `textoDeCantidad` de `domain`. El patrón entero de `vendi-admin/features/tenants/` (retroceso de última página vaciada, candado de diálogo, menú de acciones por fila).
- Produce: el CRUD del catálogo; el almacenista y el dueño editan, el cajero solo lee.

- [ ] **Paso 1: el spec del servicio, primero.** Crear `catalogo.service.spec.ts` con el mismo setup mínimo que `caja.service.spec.ts`. Casos (método, URL, params y body con aserto exacto en cada uno):

```ts
it('lista con búsqueda y paginación del servidor', () => {
  c.servicio.listar(20, 10, 'arroz').subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/productos`);
  expect(req.request.params.get('q')).toBe('arroz');
  expect(req.request.params.get('skip')).toBe('20');
  expect(req.request.params.get('limit')).toBe('10');
  req.flush({ items: [], total: 0, skip: 20, limit: 10 });
});

it('la búsqueda vacía NO manda el parámetro q', () => {
  c.servicio.listar(0, 10, '').subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/productos`);
  expect(req.request.params.has('q')).toBe(false);
  req.flush({ items: [], total: 0, skip: 0, limit: 10 });
});

it('crear manda el id idempotente, el precio en centavos y el mínimo como string de 3 decimales', () => {
  c.servicio
    .crear({
      id: ID_OP,
      nombre: 'Arroz blanco x kg',
      categoria: 'Granos',
      codigo_barras: null,
      precio_venta: 420000,
      unidad_medida: 'kg',
      iva_pct: 0,
      stock_minimo: '5.000',
    })
    .subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/productos` && r.method === 'POST');
  expect(req.request.body).toEqual({
    id: ID_OP,
    nombre: 'Arroz blanco x kg',
    categoria: 'Granos',
    codigo_barras: null,
    precio_venta: 420000,
    unidad_medida: 'kg',
    iva_pct: 0,
    stock_minimo: '5.000',
  });
  req.flush({ id: ID_OP });
});

it('actualizar manda solo los campos del formulario (nunca stock ni costo)', () => {
  c.servicio.actualizar(ID_PROD, { nombre: 'Nuevo nombre', precio_venta: 500000 }).subscribe();
  const req = c.http.expectOne(`${BASE}/productos/${ID_PROD}`);
  expect(req.request.method).toBe('PATCH');
  expect(req.request.body).toEqual({ nombre: 'Nuevo nombre', precio_venta: 500000 });
  req.flush({ id: ID_PROD });
});

it('eliminar es un DELETE sin cuerpo', () => {
  c.servicio.eliminar(ID_PROD).subscribe();
  const req = c.http.expectOne(`${BASE}/productos/${ID_PROD}`);
  expect(req.request.method).toBe('DELETE');
  req.flush(null, { status: 204, statusText: 'No Content' });
});
```

(Setup idéntico al de la Tarea 5 Paso 1: `provideHttpClient()`, `provideHttpClientTesting()`, `API_BASE_URL`, `afterEach(() => c.http.verify())`.)

- [ ] **Paso 2: contrato y servicio.** Crear `frontend/projects/vendi-tenant/src/app/features/catalogo/contrato.ts`:

```ts
import type { components } from 'data-access';

export type ProductoSalida = components['schemas']['ProductoSalida'];

/** Unidades del catálogo (ADR-019): el granel se vende por peso o volumen. */
export const UNIDADES_DE_MEDIDA = ['unidad', 'kg', 'g', 'lt', 'ml'] as const;
export type UnidadDeMedida = (typeof UNIDADES_DE_MEDIDA)[number];

/** IVA como dato, no módulo fiscal (ADR-019): los tres valores de Colombia. */
export const TASAS_IVA = [0, 5, 19] as const;

/** Lo que el formulario de producto produce; números ya en unidades del cable. */
export interface ProductoNuevo {
  id: string;
  nombre: string;
  categoria: string | null;
  codigo_barras: string | null;
  /** Centavos enteros. */
  precio_venta: number;
  unidad_medida: UnidadDeMedida;
  iva_pct: number;
  /** String de 3 decimales (`"5.000"`): el granel no cabe en un entero. */
  stock_minimo: string;
}

/** PATCH: todo opcional; lo que no se toca no viaja. */
export type CambiosDeProducto = Partial<Omit<ProductoNuevo, 'id'>>;
```

Crear `frontend/projects/vendi-tenant/src/app/features/catalogo/catalogo.service.ts`:

```ts
import { Injectable, inject } from '@angular/core';
import { ApiService } from 'data-access';
import { PagedList } from 'domain';
import { Observable } from 'rxjs';
import { CambiosDeProducto, ProductoNuevo, ProductoSalida } from './contrato';

const RUTA = '/productos';

/** Cliente del catálogo (ADR-019). El stock no se edita aquí: ADR-020. */
@Injectable({ providedIn: 'root' })
export class CatalogoService {
  private readonly api = inject(ApiService);

  listar(skip: number, limit: number, consulta = ''): Observable<PagedList<ProductoSalida>> {
    const params: Record<string, string | number> = { skip, limit };
    const q = consulta.trim();
    if (q.length > 0) {
      params['q'] = q;
    }
    return this.api.get<PagedList<ProductoSalida>>(RUTA, params);
  }

  crear(producto: ProductoNuevo): Observable<ProductoSalida> {
    return this.api.post<ProductoSalida>(RUTA, producto);
  }

  actualizar(id: string, cambios: CambiosDeProducto): Observable<ProductoSalida> {
    return this.api.patch<ProductoSalida>(`${RUTA}/${id}`, cambios);
  }

  /** Borrado lógico: el producto desaparece de las listas y su EAN queda libre. */
  eliminar(id: string): Observable<void> {
    return this.api.delete<void>(`${RUTA}/${id}`);
  }
}
```

- [ ] **Paso 3: el spec del componente, antes del componente.** Crear `catalogo.component.spec.ts` con el montaje de la Tarea 5 Paso 3 (mismo `CargadorDePrueba`, `DialogoFalso`, sesión falsa con roles). Casos:

```ts
describe('CatalogoComponent — lectura', () => {
  it('pide la primera página y pinta precio formateado y unidad', async () => {
    const m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http
      .expectOne((r) => r.url === `${BASE}/productos`)
      .flush(pagina([{ ...productoBase, nombre: 'Arroz blanco x kg' }]));
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Arroz blanco x kg');
    expect(visible).toContain('4.200'); // $42,00/kg → 420000 centavos
  });

  it('la búsqueda vuelve a la primera página y manda q', async () => {
    const m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([]));
    m.fixture.componentInstance.consulta.set('arroz');
    m.fixture.componentInstance.buscar();
    const req = m.http.expectOne((r) => r.url === `${BASE}/productos`);
    expect(req.request.params.get('q')).toBe('arroz');
    expect(req.request.params.get('skip')).toBe('0');
    req.flush(pagina([]));
  });

  it('el cajero no ve los botones de editar ni el de nuevo producto', async () => {
    const m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([productoBase]));
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).not.toContain('Nuevo producto');
    expect(visible).not.toContain('Editar');
  });
});

describe('CatalogoComponent — escritura', () => {
  it('crear convierte pesos y granel en el borde y recarga', async () => {
    const m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([]));

    m.dialogos.resultados = [
      {
        nombre: 'Arroz blanco x kg',
        categoria: 'Granos',
        codigo_barras: null,
        precio_venta: 420000,
        unidad_medida: 'kg',
        iva_pct: 0,
        stock_minimo: '5.000',
      },
    ];
    m.fixture.componentInstance.crear();
    const alta = m.http.expectOne((r) => r.url === `${BASE}/productos` && r.method === 'POST');
    expect((alta.request.body as { id: string }).id).toBeTruthy();
    expect((alta.request.body as { stock_minimo: string }).stock_minimo).toBe('5.000');
    alta.flush(productoBase);
    m.http
      .expectOne((r) => r.url === `${BASE}/productos` && r.method === 'GET')
      .flush(pagina([productoBase]));
  });

  it('eliminar pide confirmación marcada como peligrosa y manda DELETE', async () => {
    const m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([productoBase]));

    m.dialogos.resultados = [true];
    m.fixture.componentInstance.eliminar(productoBase);
    expect((m.dialogos.aperturas[0].datos as { peligroso?: boolean }).peligroso).toBe(true);
    const baja = m.http.expectOne(`${BASE}/productos/${productoBase.id}`);
    expect(baja.request.method).toBe('DELETE');
    baja.flush(null, { status: 204, statusText: 'No Content' });
    m.http
      .expectOne((r) => r.url === `${BASE}/productos` && r.method === 'GET')
      .flush(pagina([]));
  });

  it('un EAN duplicado (409) no cierra la pantalla ni pierde el listado', async () => {
    const m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([productoBase]));

    m.dialogos.resultados = [
      {
        nombre: 'Otro', categoria: null, codigo_barras: '7701234567890',
        precio_venta: 1000, unidad_medida: 'unidad', iva_pct: 19, stock_minimo: '0.000',
      },
    ];
    m.fixture.componentInstance.crear();
    m.http
      .expectOne((r) => r.url === `${BASE}/productos` && r.method === 'POST')
      .flush(
        { message: 'Ya existe un producto con ese código de barras.', code: 'codigo_barras_duplicado' },
        { status: 409, statusText: 'Conflict' },
      );
    // El interceptor ya avisó con el mensaje del backend; la tabla sigue viva.
    expect(m.fixture.componentInstance.cargando()).toBe(false);
    m.fixture.componentInstance.recargar();
    m.http.expectOne((r) => r.url === `${BASE}/productos`).flush(pagina([productoBase]));
  });
});
```

con `productoBase`:

```ts
const productoBase = {
  id: '5f1d0e2a-0000-4000-8000-cccccccccccc',
  nombre: 'Arroz blanco x kg',
  categoria: 'Granos',
  codigo_barras: null,
  precio_venta: 420000,
  unidad_medida: 'kg',
  iva_pct: '0',
  stock_actual: '12.500',
  stock_minimo: '5.000',
  ultimo_costo: null,
  padre_id: null,
  created_at: '2026-07-01T00:00:00Z',
};

const ROLES_ALMACENISTA = ['almacenista', 'producto:leer', 'producto:editar', 'inventario:ajustar', 'compra:crear'];
const ROLES_CAJERO = ['cajero', 'producto:leer'];
```

y el helper `pagina(items, total = items.length, skip = 0, limit = 10)` del patrón de `vendi-admin`.

- [ ] **Paso 4: el diálogo de producto.** Crear `frontend/projects/vendi-tenant/src/app/features/catalogo/producto-dialogo.component.ts`:

```ts
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { miliDeCantidad, textoDeCantidad } from 'domain';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit';
import { ProductoNuevo, ProductoSalida, TASAS_IVA, UNIDADES_DE_MEDIDA } from './contrato';

/** Datos con los que se abre el diálogo. Sin `producto` es un alta. */
export interface DatosProductoDialogo {
  producto?: ProductoSalida;
}

/**
 * Alta y edición de producto (ADR-019).
 *
 * Conversiones en el borde: el precio entra en pesos y sale en centavos; el
 * stock mínimo entra como texto (coma o punto) y sale como string de 3
 * decimales vía `miliDeCantidad`/`textoDeCantidad` — la misma regla del POS,
 * compartida en `domain`. El EAN es opcional porque gran parte del surtido
 * de barrio no lo tiene.
 */
@Component({
  selector: 'vd-producto-dialogo',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  template: `
    <h2 mat-dialog-title>
      {{ (esEdicion ? 'catalogo.editar.titulo' : 'catalogo.nuevo.titulo') | translate }}
    </h2>
    <mat-dialog-content>
      <vd-form-renderer
        [configuracion]="configuracion"
        [formulario]="formulario"
        textoEnviar="comun.guardar"
        textoCancelar="comun.cancelar"
        (enviado)="alEnviar($event)"
        (cancelado)="cancelar()"
      />
      @if (errorFormulario()) {
        <p role="alert">{{ 'catalogo.formulario.invalido' | translate }}</p>
      }
    </mat-dialog-content>
  `,
})
export class ProductoDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref = inject<
    MatDialogRef<ProductoDialogoComponent, Omit<ProductoNuevo, 'id'> | undefined>
  >(MatDialogRef);
  readonly datos = inject<DatosProductoDialogo>(MAT_DIALOG_DATA, { optional: true }) ?? {};

  readonly esEdicion = !!this.datos.producto;
  readonly errorFormulario = signal(false);

  readonly configuracion: ConfiguracionFormulario = {
    disposicion: 'dos-columnas',
    campos: [
      {
        clave: 'nombre',
        etiqueta: 'catalogo.campo.nombre',
        tipo: 'text',
        valorPorDefecto: this.datos.producto?.nombre ?? '',
        validadores: [{ tipo: 'required' }, { tipo: 'minLength', valor: 2 }, { tipo: 'maxLength', valor: 160 }],
      },
      {
        clave: 'categoria',
        etiqueta: 'catalogo.campo.categoria',
        tipo: 'text',
        ayuda: 'catalogo.campo.categoria_ayuda',
        valorPorDefecto: this.datos.producto?.categoria ?? '',
      },
      {
        clave: 'codigo_barras',
        etiqueta: 'catalogo.campo.ean',
        tipo: 'text',
        ayuda: 'catalogo.campo.ean_ayuda',
        valorPorDefecto: this.datos.producto?.codigo_barras ?? '',
        validadores: [{ tipo: 'maxLength', valor: 32 }],
      },
      {
        clave: 'precio_pesos',
        etiqueta: 'catalogo.campo.precio',
        tipo: 'number',
        valorPorDefecto: this.datos.producto ? this.datos.producto.precio_venta / 100 : null,
        validadores: [{ tipo: 'required' }, { tipo: 'min', valor: 0 }],
      },
      {
        clave: 'unidad_medida',
        etiqueta: 'catalogo.campo.unidad',
        tipo: 'select',
        valorPorDefecto: this.datos.producto?.unidad_medida ?? 'unidad',
        validadores: [{ tipo: 'required' }],
        opciones: UNIDADES_DE_MEDIDA.map((unidad) => ({
          etiqueta: `catalogo.unidad.${unidad}`,
          valor: unidad,
        })),
      },
      {
        clave: 'iva_pct',
        etiqueta: 'catalogo.campo.iva',
        tipo: 'select',
        valorPorDefecto: this.datos.producto ? Number(this.datos.producto.iva_pct) : 0,
        opciones: TASAS_IVA.map((tasa) => ({
          etiqueta: `catalogo.iva.${tasa}`,
          valor: tasa,
        })),
      },
      {
        clave: 'stock_minimo',
        etiqueta: 'catalogo.campo.stock_minimo',
        tipo: 'text',
        ayuda: 'catalogo.campo.stock_minimo_ayuda',
        valorPorDefecto: this.datos.producto?.stock_minimo ?? '0',
        validadores: [{ tipo: 'required' }],
      },
    ],
  };

  readonly formulario: FormGroup = FormRendererComponent.construirFormulario(
    this.fb,
    this.configuracion,
  );

  private readonly enviando = signal(false);

  alEnviar(valores: Record<string, unknown>): void {
    if (this.enviando()) {
      return;
    }
    const nombre = String(valores['nombre'] ?? '').trim();
    const pesos = Number(valores['precio_pesos']);
    let stockMinimo: string;
    try {
      stockMinimo = textoDeCantidad(
        miliDeCantidad(Number(String(valores['stock_minimo'] ?? '').replace(',', '.'))),
      );
    } catch {
      // Cantidad ilegible o <= 0: el diálogo no cierra con un payload inválido.
      // Ojo: un mínimo de 0 ES legítimo (sin alertas); se trata aparte.
      const crudo = String(valores['stock_minimo'] ?? '').replace(',', '.').trim();
      if (Number(crudo) === 0) {
        stockMinimo = '0.000';
      } else {
        this.errorFormulario.set(true);
        return;
      }
    }
    if (nombre.length < 2 || !Number.isFinite(pesos) || pesos < 0) {
      this.errorFormulario.set(true);
      return;
    }
    this.enviando.set(true);
    const ean = String(valores['codigo_barras'] ?? '').trim();
    const categoria = String(valores['categoria'] ?? '').trim();
    this.ref.close({
      nombre,
      categoria: categoria.length > 0 ? categoria : null,
      codigo_barras: ean.length > 0 ? ean : null,
      precio_venta: Math.round(pesos * 100),
      unidad_medida: valores['unidad_medida'] as ProductoNuevo['unidad_medida'],
      iva_pct: Number(valores['iva_pct'] ?? 0),
      stock_minimo: stockMinimo,
    });
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
```

- [ ] **Paso 5: el componente de página.** Crear `frontend/projects/vendi-tenant/src/app/features/catalogo/catalogo.component.ts` siguiendo `tenants.component.ts` de `vendi-admin` CASI línea a línea — es la referencia del repo y copiar su estructura es el patrón, no una casualidad. Diferencias exactas:

- `FilaProducto extends ProductoSalida { acciones?: never }`.
- Estado: `filas`, `total`, `cargando`, `fallo`, `indicePagina`, `tamanoPagina` (10), `consulta = signal('')`, `dialogoAbierto` privado.
- Columnas: `nombre`, `categoria`, `precio_venta` (plantilla `#celdaPrecio` → `formatear(fila.precio_venta)`), `stock_actual` (plantilla `#celdaStock` → `{{ fila.stock_actual }} {{ 'catalogo.unidad.' + fila.unidad_medida | translate }}`), `acciones` (menú con Editar y Eliminar, cada `mat-menu-item` con `*vdHasPermission="'producto:editar'"`).
- `recargar()` idéntico al de admin incluido el retroceso de última página vaciada; llama `servicio.listar(skip, tamano, this.consulta())`.
- `buscar()`: `indicePagina.set(0); recargar();`.
- `crear()`: candado `dialogoAbierto`; genera `const id = crypto.randomUUID()` ANTES de abrir; abre `ProductoDialogoComponent` sin datos; con resultado llama `servicio.crear({ id, ...resultado })` y recarga; error → `cargando.set(false)` (el interceptor ya avisó: EAN duplicado, límite de tier, etc.).
- `editar(producto)`: abre el diálogo con `{ producto }`; con resultado llama `servicio.actualizar(producto.id, resultado)` y recarga.
- `eliminar(producto)`: `ConfirmDialogComponent` con `peligroso: true`, claves `catalogo.confirmar.eliminar_*`; confirma → `servicio.eliminar(producto.id)` → recargar.
- `formatear = formatearPesos` para la plantilla de precio.
- El botón «Nuevo producto» del `PageHeader` lleva `*vdHasPermission="'producto:editar'"` y el bloque de búsqueda un `<input type="search">` con `[(ngModel)]="consulta"` + botón Buscar (o `(keyup.enter)`).

El `.html` sigue la estructura de `tenants.component.html`: `vd-page-header` con acciones (buscador + botón nuevo), bloque `fallo` con reintentar, y `vd-data-table` con `iconoVacio="inventory_2"`, `tituloVacio="catalogo.vacio.titulo"`, `descripcionVacio="catalogo.vacio.descripcion"`, más las dos `ng-template` de precio y stock y la de acciones con `mat-menu`. Escribirlo completo copiando la forma del de admin.

- [ ] **Paso 6: la ruta y las claves.** En `app.routes.ts`, tras `caja`:

```ts
      {
        path: 'catalogo',
        canActivate: [tenantGuard, permisoGuard('producto:leer')],
        loadComponent: () =>
          import('./features/catalogo/catalogo.component').then((m) => m.CatalogoComponent),
      },
```

En `public/i18n/es.json`:

```json
  "catalogo": {
    "titulo": "Catálogo",
    "subtitulo": "Los productos de tu tienda",
    "fallo": "No pudimos cargar el catálogo.",
    "buscar_placeholder": "Buscar por nombre…",
    "nuevo": { "titulo": "Nuevo producto", "accion": "Nuevo producto" },
    "editar": { "titulo": "Editar producto", "accion": "Editar" },
    "eliminar": "Eliminar",
    "confirmar": {
      "eliminar_titulo": "Eliminar el producto",
      "eliminar_mensaje": "El producto dejará de aparecer en el catálogo. Las ventas y compras que ya lo usaron no se tocan.",
      "eliminar_accion": "Eliminar"
    },
    "campo": {
      "nombre": "Nombre",
      "categoria": "Categoría",
      "categoria_ayuda": "Texto libre: granos, aseo, fruver…",
      "ean": "Código de barras (EAN)",
      "ean_ayuda": "Opcional: muchos productos de barrio no tienen.",
      "precio": "Precio de venta (pesos)",
      "unidad": "Se vende por",
      "iva": "IVA",
      "stock_minimo": "Stock mínimo",
      "stock_minimo_ayuda": "Con decimales si es a granel: 5 o 2,5. Con 0 no hay alertas."
    },
    "unidad": {
      "unidad": "unidad",
      "kg": "kg",
      "g": "g",
      "lt": "litro",
      "ml": "ml"
    },
    "iva": { "0": "0 %", "5": "5 %", "19": "19 %" },
    "columna": {
      "nombre": "Nombre",
      "categoria": "Categoría",
      "precio": "Precio",
      "stock": "Stock",
      "acciones": "Acciones"
    },
    "vacio": {
      "titulo": "Todavía no hay productos",
      "descripcion": "Crea el primero para empezar a vender y a llevar el inventario."
    },
    "formulario": {
      "invalido": "Revisa el formulario: falta un dato o una cantidad no es válida."
    }
  },
```

(Las columnas usan las claves `catalogo.columna.*`, no las literales del Paso 5: al escribir el componente, las `etiqueta` de `ColumnaTabla` son estas claves.)

- [ ] **Paso 7: verde y commit.**

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: verde — 5 del servicio + 6 del componente + todo lo anterior
npx ng lint vendi-tenant && npx ng build vendi-tenant
git add frontend/projects/vendi-tenant
git commit -m "Catálogo en vendi-tenant: CRUD de productos con granel, EAN opcional e IVA, con edición solo para quien tiene producto:editar"
```

**Criterios de aceptación:** los 11 specs nuevos pasan; el EAN vacío viaja `null` (no cadena vacía); el stock mínimo sale como string de 3 decimales con coma o punto; el PATCH nunca lleva `stock_actual` ni `ultimo_costo`; el cajero no ve acciones de edición; el borrado pide confirmación peligrosa.

---

## Tarea 7: Mi inventario (`/inventario`) — stock con niveles, ajuste con motivo y compra

**Files:**
- Create: `frontend/projects/vendi-tenant/src/app/features/inventario/contrato.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/inventario/inventario.service.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/inventario/inventario.service.spec.ts` (primero)
- Create: `frontend/projects/vendi-tenant/src/app/features/inventario/ajuste-dialogo.component.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/inventario/compra-dialogo.component.ts` (+ `.html`)
- Create: `frontend/projects/vendi-tenant/src/app/features/inventario/inventario.component.ts` (+ `.html` + `.scss`)
- Create: `frontend/projects/vendi-tenant/src/app/features/inventario/inventario.component.spec.ts` (primero)
- Modify: `frontend/projects/vendi-tenant/src/app/app.routes.ts`
- Modify: `frontend/projects/vendi-tenant/public/i18n/es.json`

**Interfaces:**
- Consume: `GET /inventario/stock` (`skip`, `limit`, `solo_alertas` → `PagedList_StockSalida_`; `nivel` es string libre: `agotado`/`critico`/`bajo`/`ok`; el stock negativo es dato legítimo, ADR-020), `POST /inventario/ajustes` (`AjusteCrear`: `id` REQUERIDO, `tipo` `ajuste`/`merma`, `motivo` obligatorio, `stock_contado` XOR `cantidad`; online-obligatorio), `POST /compras` (`CompraCrear`: `id`, `proveedor_nombre` texto libre, `items[{producto_id, cantidad, costo_unitario_centavos}]`; el total lo calcula el servidor — la UI no se fía del suyo).
- Produce: la pantalla del almacenista; las alertas de stock de la tienda.

- [ ] **Paso 1: el spec del servicio, primero.** Crear `inventario.service.spec.ts` (setup mínimo como los anteriores). Casos:

```ts
it('el estado de stock pagina y filtra por alertas en el servidor', () => {
  c.servicio.stock(10, 10, true).subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/inventario/stock`);
  expect(req.request.params.get('solo_alertas')).toBe('true');
  expect(req.request.params.get('skip')).toBe('10');
  req.flush({ items: [], total: 0, skip: 10, limit: 10 });
});

it('el ajuste por conteo manda stock_contado y NO cantidad', () => {
  c.servicio
    .ajustar({ id: ID_OP, tipo: 'ajuste', producto_id: ID_PROD, motivo: 'Conteo del lunes', stock_contado: '14.000' })
    .subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/inventario/ajustes` && r.method === 'POST');
  expect(req.request.body).toEqual({
    id: ID_OP, tipo: 'ajuste', producto_id: ID_PROD, motivo: 'Conteo del lunes', stock_contado: '14.000',
  });
  expect(req.request.body['cantidad']).toBeUndefined();
  req.flush({ id: ID_OP });
});

it('la merma manda cantidad y NO stock_contado', () => {
  c.servicio
    .ajustar({ id: ID_OP, tipo: 'merma', producto_id: ID_PROD, motivo: 'Se dañó', cantidad: '0.500' })
    .subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/inventario/ajustes` && r.method === 'POST');
  expect(req.request.body['cantidad']).toBe('0.500');
  expect(req.request.body['stock_contado']).toBeUndefined();
  req.flush({ id: ID_OP });
});

it('la compra viaja con id, proveedor e ítems en centavos y 3 decimales', () => {
  c.servicio
    .registrarCompra({
      id: ID_OP,
      proveedor_nombre: 'Distribuidora La 33',
      items: [{ producto_id: ID_PROD, cantidad: '10.000', costo_unitario_centavos: 350000 }],
    })
    .subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/compras` && r.method === 'POST');
  expect(req.request.body).toEqual({
    id: ID_OP,
    proveedor_nombre: 'Distribuidora La 33',
    items: [{ producto_id: ID_PROD, cantidad: '10.000', costo_unitario_centavos: 350000 }],
  });
  req.flush({ id: ID_OP, total_centavos: 3500000 });
});
```

- [ ] **Paso 2: contrato y servicio.** Crear `frontend/projects/vendi-tenant/src/app/features/inventario/contrato.ts`:

```ts
import type { components } from 'data-access';

export type StockSalida = components['schemas']['StockSalida'];
export type AjusteCreado = components['schemas']['AjusteCreado'];
export type CompraDetalleSalida = components['schemas']['CompraDetalleSalida'];

/** Niveles que documenta el backend (`nivel` llega como string libre). */
export type NivelStock = 'agotado' | 'critico' | 'bajo' | 'ok';

/**
 * El ajuste (ADR-020): `stock_contado` para el conteo, `cantidad` para la
 * merma; nunca los dos. `motivo` obligatorio — un ajuste sin justificación
 * es un desfalco con buenos modales. Online-obligatorio: el delta lo calcula
 * el servidor contra SU stock del momento.
 */
export interface AjusteNuevo {
  id: string;
  tipo: 'ajuste' | 'merma';
  producto_id: string;
  motivo: string;
  stock_contado?: string;
  cantidad?: string;
}

export interface ItemCompra {
  producto_id: string;
  /** String de 3 decimales. */
  cantidad: string;
  costo_unitario_centavos: number;
}

/** El total NO viaja: lo calcula el servidor (ADR-020, decisión 7 del módulo). */
export interface CompraNueva {
  id: string;
  proveedor_nombre: string;
  items: ItemCompra[];
}
```

Crear `inventario.service.ts`:

```ts
import { Injectable, inject } from '@angular/core';
import { ApiService } from 'data-access';
import { PagedList } from 'domain';
import { Observable } from 'rxjs';
import { AjusteCreado, AjusteNuevo, CompraDetalleSalida, CompraNueva, StockSalida } from './contrato';

/** Cliente de inventario y compras (ADR-020). */
@Injectable({ providedIn: 'root' })
export class InventarioService {
  private readonly api = inject(ApiService);

  stock(skip: number, limit: number, soloAlertas: boolean): Observable<PagedList<StockSalida>> {
    return this.api.get<PagedList<StockSalida>>('/inventario/stock', {
      skip,
      limit,
      solo_alertas: String(soloAlertas),
    });
  }

  ajustar(ajuste: AjusteNuevo): Observable<AjusteCreado> {
    return this.api.post<AjusteCreado>('/inventario/ajustes', ajuste);
  }

  registrarCompra(compra: CompraNueva): Observable<CompraDetalleSalida> {
    return this.api.post<CompraDetalleSalida>('/compras', compra);
  }
}
```

- [ ] **Paso 3: el diálogo de ajuste.** Crear `ajuste-dialogo.component.ts`:

```ts
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { miliDeCantidad, textoDeCantidad } from 'domain';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit';
import { AjusteNuevo, StockSalida } from './contrato';

/** Datos con los que se abre el ajuste: el producto y su stock del sistema. */
export interface DatosAjusteDialogo {
  producto: StockSalida;
}

/** Resultado del diálogo, listo para el servicio salvo el `id` (lo pone la página). */
export type ResultadoAjuste = Omit<AjusteNuevo, 'id'>;

/**
 * Ajuste por conteo o merma (ADR-020). El formulario dice el stock que el
 * sistema cree que hay, porque el conteo se hace contra ESE número: «conté
 * 14, el sistema dice 16». Es online-obligatorio — el delta lo calcula el
 * servidor— y el motivo no es opcional.
 */
@Component({
  selector: 'vd-ajuste-dialogo',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  template: `
    <h2 mat-dialog-title>{{ 'inventario.ajuste.titulo' | translate: { nombre: datos.producto.nombre } }}</h2>
    <mat-dialog-content>
      <p>
        {{
          'inventario.ajuste.stock_sistema'
            | translate: { stock: datos.producto.stock_actual, nivel: datos.producto.nivel }
        }}
      </p>
      <vd-form-renderer
        [configuracion]="configuracion"
        [formulario]="formulario"
        textoEnviar="comun.guardar"
        textoCancelar="comun.cancelar"
        (enviado)="alEnviar($event)"
        (cancelado)="cancelar()"
      />
      @if (errorFormulario()) {
        <p role="alert">{{ 'inventario.ajuste.invalido' | translate }}</p>
      }
    </mat-dialog-content>
  `,
})
export class AjusteDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref = inject<MatDialogRef<AjusteDialogoComponent, ResultadoAjuste | undefined>>(
    MatDialogRef,
  );
  readonly datos = inject<DatosAjusteDialogo>(MAT_DIALOG_DATA);

  readonly errorFormulario = signal(false);

  readonly configuracion: ConfiguracionFormulario = {
    campos: [
      {
        clave: 'tipo',
        etiqueta: 'inventario.ajuste.tipo',
        tipo: 'select',
        valorPorDefecto: 'ajuste',
        validadores: [{ tipo: 'required' }],
        opciones: [
          { etiqueta: 'inventario.ajuste.conteo', valor: 'ajuste' },
          { etiqueta: 'inventario.ajuste.merma', valor: 'merma' },
        ],
      },
      {
        clave: 'cantidad',
        etiqueta: 'inventario.ajuste.cantidad',
        tipo: 'text',
        ayuda: 'inventario.ajuste.cantidad_ayuda',
        validadores: [{ tipo: 'required' }],
      },
      {
        clave: 'motivo',
        etiqueta: 'inventario.ajuste.motivo',
        tipo: 'text',
        marcador: 'inventario.ajuste.motivo_marcador',
        validadores: [{ tipo: 'required' }, { tipo: 'minLength', valor: 3 }, { tipo: 'maxLength', valor: 300 }],
      },
    ],
  };

  readonly formulario: FormGroup = FormRendererComponent.construirFormulario(
    this.fb,
    this.configuracion,
  );

  private readonly enviando = signal(false);

  alEnviar(valores: Record<string, unknown>): void {
    if (this.enviando()) {
      return;
    }
    const motivo = String(valores['motivo'] ?? '').trim();
    let cantidad: string;
    try {
      cantidad = textoDeCantidad(
        miliDeCantidad(Number(String(valores['cantidad'] ?? '').replace(',', '.'))),
      );
    } catch {
      this.errorFormulario.set(true);
      return;
    }
    if (motivo.length < 3) {
      this.errorFormulario.set(true);
      return;
    }
    this.enviando.set(true);
    const tipo = valores['tipo'] as 'ajuste' | 'merma';
    // Conteo → el servidor calcula el delta contra su stock; merma → el
    // delta es la cantidad que se reporta. Nunca viajan los dos campos.
    this.ref.close(
      tipo === 'ajuste'
        ? { tipo, producto_id: this.datos.producto.producto_id, motivo, stock_contado: cantidad }
        : { tipo, producto_id: this.datos.producto.producto_id, motivo, cantidad },
    );
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
```

- [ ] **Paso 4: el diálogo de compra (con ítems dinámicos).** `FormRenderer` no modela listas de ítems; este diálogo lleva formulario propio con `FormArray`. Crear `compra-dialogo.component.ts`:

```ts
import { Component, inject, signal } from '@angular/core';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TranslateModule } from '@ngx-translate/core';
import { miliDeCantidad, textoDeCantidad } from 'domain';
import { CompraNueva, StockSalida } from './contrato';

/** Datos del diálogo: el catálogo con stock (de donde se eligen los ítems). */
export interface DatosCompraDialogo {
  productos: StockSalida[];
}

/** Resultado listo para el servicio salvo el `id`. */
export type ResultadoCompra = Omit<CompraNueva, 'id'>;

/**
 * Registro de una compra a proveedor (ADR-020): el proveedor es texto libre
 * (la factura es un papel; no hay módulo de proveedores) y cada ítem lleva su
 * costo de ESTA compra. El total no se calcula aquí: lo calcula el servidor.
 */
@Component({
  selector: 'vd-compra-dialogo',
  imports: [
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    ReactiveFormsModule,
    TranslateModule,
  ],
  templateUrl: './compra-dialogo.component.html',
})
export class CompraDialogoComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref = inject<MatDialogRef<CompraDialogoComponent, ResultadoCompra | undefined>>(
    MatDialogRef,
  );
  readonly datos = inject<DatosCompraDialogo>(MAT_DIALOG_DATA);

  readonly errorFormulario = signal(false);
  private readonly enviando = signal(false);

  readonly formulario = this.fb.group({
    proveedor_nombre: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(160)]],
    items: this.fb.array([this.nuevoItem()]),
  });

  get items(): FormArray<FormGroup> {
    return this.formulario.get('items') as FormArray<FormGroup>;
  }

  agregarItem(): void {
    this.items.push(this.nuevoItem());
  }

  quitarItem(indice: number): void {
    if (this.items.length > 1) {
      this.items.removeAt(indice);
    }
  }

  alEnviar(): void {
    if (this.enviando() || this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      this.errorFormulario.set(this.formulario.invalid);
      return;
    }
    try {
      const bruto = this.formulario.getRawValue() as {
        proveedor_nombre: string;
        items: { producto_id: string; cantidad: string; costo_pesos: number }[];
      };
      const items = bruto.items.map((item) => ({
        producto_id: item.producto_id,
        cantidad: textoDeCantidad(miliDeCantidad(Number(String(item.cantidad).replace(',', '.')))),
        costo_unitario_centavos: Math.round(Number(item.costo_pesos) * 100),
      }));
      this.enviando.set(true);
      this.ref.close({ proveedor_nombre: bruto.proveedor_nombre.trim(), items });
    } catch {
      // Una cantidad ilegible o <= 0: el diálogo no cierra con basura.
      this.errorFormulario.set(true);
    }
  }

  cancelar(): void {
    this.ref.close(undefined);
  }

  private nuevoItem(): FormGroup {
    return this.fb.group({
      producto_id: ['', Validators.required],
      cantidad: ['', Validators.required],
      costo_pesos: [null as number | null, [Validators.required, Validators.min(0)]],
    });
  }
}
```

y `compra-dialogo.component.html`:

```html
<h2 mat-dialog-title>{{ 'inventario.compra.titulo' | translate }}</h2>
<mat-dialog-content>
  <form [formGroup]="formulario" (ngSubmit)="alEnviar()">
    <label>
      {{ 'inventario.compra.proveedor' | translate }}
      <input type="text" formControlName="proveedor_nombre" />
    </label>

    <div formArrayName="items">
      @for (item of items.controls; track $index) {
        <fieldset [formGroupName]="$index">
          <label>
            {{ 'inventario.compra.producto' | translate }}
            <select formControlName="producto_id">
              <option value="" disabled>{{ 'inventario.compra.elegir_producto' | translate }}</option>
              @for (producto of datos.productos; track producto.producto_id) {
                <option [value]="producto.producto_id">{{ producto.nombre }}</option>
              }
            </select>
          </label>
          <label>
            {{ 'inventario.compra.cantidad' | translate }}
            <input type="text" formControlName="cantidad" inputmode="decimal" />
          </label>
          <label>
            {{ 'inventario.compra.costo' | translate }}
            <input type="number" min="0" formControlName="costo_pesos" />
          </label>
          <button matIconButton type="button" (click)="quitarItem($index)">
            <mat-icon aria-hidden="true">delete</mat-icon>
          </button>
        </fieldset>
      }
    </div>

    <button matButton="outlined" type="button" (click)="agregarItem()">
      {{ 'inventario.compra.agregar_item' | translate }}
    </button>

    @if (errorFormulario()) {
      <p role="alert">{{ 'inventario.compra.invalido' | translate }}</p>
    }
  </form>
</mat-dialog-content>
<mat-dialog-actions>
  <button matButton type="button" (click)="cancelar()">{{ 'comun.cancelar' | translate }}</button>
  <button matButton="filled" type="button" (click)="alEnviar()">{{ 'comun.guardar' | translate }}</button>
</mat-dialog-actions>
```

(Nota de alcance honesta: el selector de producto ofrece la página de stock YA cargada — los 10/25 visibles. Buscar en todo el catálogo desde el diálogo es mejora posterior; la compra del piloto se registra sobre productos existentes y el almacenista los tiene a la vista. Declarado en riesgos.)

- [ ] **Paso 5: el spec del componente, antes del componente.** Crear `inventario.component.spec.ts` (montaje de la Tarea 5 Paso 3). Casos:

```ts
describe('InventarioComponent — stock y alertas', () => {
  it('pinta el nivel como badge y el stock negativo como dato, no como error', async () => {
    const m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(
      pagina([
        { producto_id: ID_PROD, nombre: 'Arroz', stock_actual: '-2.000', stock_minimo: '5.000', nivel: 'agotado' },
        { producto_id: ID_PROD_2, nombre: 'Aceite', stock_actual: '8.000', stock_minimo: '10.000', nivel: 'bajo' },
      ]),
    );
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('-2.000'); // vendiste de más según el sistema: información
    expect(visible).toContain('Agotado');
    expect(visible).toContain('Bajo');
  });

  it('el interruptor de alertas recarga con solo_alertas=true desde la primera página', async () => {
    const m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([], 30));
    m.fixture.componentInstance.alternarAlertas(true);
    const req = m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`);
    expect(req.request.params.get('solo_alertas')).toBe('true');
    expect(req.request.params.get('skip')).toBe('0');
    req.flush(pagina([]));
  });

  it('el cajero no ve los botones de ajustar ni de registrar compra', async () => {
    const m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([stockBase]));
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).not.toContain('Registrar compra');
    expect(visible).not.toContain('Ajustar');
  });
});

describe('InventarioComponent — ajuste y compra', () => {
  it('el ajuste por conteo manda stock_contado, motivo y el id generado al abrir', async () => {
    const m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([stockBase]));

    m.dialogos.resultados = [
      { tipo: 'ajuste', producto_id: ID_PROD, motivo: 'Conteo del lunes', stock_contado: '14.000' },
    ];
    m.fixture.componentInstance.ajustar(stockBase);
    const req = m.http.expectOne((r) => r.url === `${BASE}/inventario/ajustes` && r.method === 'POST');
    expect(req.request.body).toEqual({
      id: expect.any(String),
      tipo: 'ajuste',
      producto_id: ID_PROD,
      motivo: 'Conteo del lunes',
      stock_contado: '14.000',
    });
    req.flush({ id: 'x', nivel: 'ok' });
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([stockBase]));
  });

  it('la compra manda los ítems convertidos y recarga el stock', async () => {
    const m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([stockBase]));

    m.dialogos.resultados = [
      {
        proveedor_nombre: 'Distribuidora La 33',
        items: [{ producto_id: ID_PROD, cantidad: '10.000', costo_unitario_centavos: 350000 }],
      },
    ];
    m.fixture.componentInstance.registrarCompra();
    const req = m.http.expectOne((r) => r.url === `${BASE}/compras` && r.method === 'POST');
    expect((req.request.body as { id: string }).id).toBeTruthy();
    req.flush({ id: 'x', total_centavos: 3500000 });
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).flush(pagina([stockBase]));
  });

  it('un fallo de red deja reintento, no spinner eterno', async () => {
    const m = await montar(ROLES_ALMACENISTA);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/inventario/stock`).error(new ProgressEvent('error'));
    m.fixture.detectChanges();
    expect(m.fixture.componentInstance.fallo()).toBe(true);
    expect(texto(m.fixture)).toContain('Reintentar');
  });
});
```

con `stockBase = { producto_id: ID_PROD, nombre: 'Arroz', stock_actual: '12.500', stock_minimo: '5.000', nivel: 'ok' }` y los helpers de siempre.

- [ ] **Paso 6: el componente de página.** Crear `inventario.component.ts`:

```ts
import { Component, TemplateRef, computed, inject, signal, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { PageEvent } from '@angular/material/paginator';
import { TranslateModule } from '@ngx-translate/core';
import { HasPermissionDirective } from 'auth';
import {
  ColumnaTabla,
  DataTableComponent,
  PageHeaderComponent,
  StatusBadgeComponent,
  VarianteEstado,
} from 'ui-kit';
import { AjusteDialogoComponent, DatosAjusteDialogo, ResultadoAjuste } from './ajuste-dialogo.component';
import { CompraDialogoComponent, DatosCompraDialogo, ResultadoCompra } from './compra-dialogo.component';
import { NivelStock, StockSalida } from './contrato';
import { InventarioService } from './inventario.service';

const TAMANO_PAGINA = 10;

interface FilaStock extends StockSalida {
  acciones?: never;
}

const NIVELES: readonly NivelStock[] = ['agotado', 'critico', 'bajo', 'ok'];

/**
 * Mi inventario: el stock con su nivel derivado (ADR-020).
 *
 * El stock negativo se muestra tal cual — «vendiste de más según el sistema»
 * es información, no un error— y las alertas se filtran en el servidor
 * (`solo_alertas`: agotado o por debajo del mínimo). Ajustar y comprar son
 * gestos del almacenista y del dueño; el cajero solo lee.
 */
@Component({
  selector: 'vd-inventario',
  imports: [
    TranslateModule,
    MatButtonModule,
    MatIconModule,
    MatSlideToggleModule,
    HasPermissionDirective,
    PageHeaderComponent,
    DataTableComponent,
    StatusBadgeComponent,
  ],
  templateUrl: './inventario.component.html',
  styleUrl: './inventario.component.scss',
})
export class InventarioComponent {
  private readonly servicio = inject(InventarioService);
  private readonly dialogos = inject(MatDialog);

  readonly filas = signal<FilaStock[]>([]);
  readonly total = signal(0);
  readonly cargando = signal(false);
  readonly fallo = signal(false);
  readonly indicePagina = signal(0);
  readonly soloAlertas = signal(false);
  private readonly dialogoAbierto = signal(false);

  private readonly plantillaNivel = viewChild<TemplateRef<{ $implicit: FilaStock }>>('celdaNivel');
  private readonly plantillaAcciones =
    viewChild<TemplateRef<{ $implicit: FilaStock }>>('celdaAcciones');

  readonly columnas = computed<ColumnaTabla<FilaStock>[]>(() => [
    { clave: 'nombre', etiqueta: 'inventario.columna.nombre' },
    { clave: 'stock_actual', etiqueta: 'inventario.columna.stock' },
    { clave: 'stock_minimo', etiqueta: 'inventario.columna.minimo' },
    { clave: 'nivel', etiqueta: 'inventario.columna.nivel', plantilla: this.plantillaNivel() },
    {
      clave: 'acciones',
      etiqueta: 'inventario.columna.acciones',
      plantilla: this.plantillaAcciones(),
      ancho: '8rem',
    },
  ]);

  constructor() {
    this.recargar();
  }

  recargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    this.servicio
      .stock(this.indicePagina() * TAMANO_PAGINA, TAMANO_PAGINA, this.soloAlertas())
      .subscribe({
        next: (pagina) => {
          if (pagina.items.length === 0 && pagina.total > 0 && this.indicePagina() > 0) {
            this.indicePagina.update((indice) => indice - 1);
            this.recargar();
            return;
          }
          this.filas.set(pagina.items);
          this.total.set(pagina.total);
          this.cargando.set(false);
        },
        error: () => {
          this.cargando.set(false);
          this.fallo.set(true);
        },
      });
  }

  alternarAlertas(solo: boolean): void {
    this.soloAlertas.set(solo);
    this.indicePagina.set(0);
    this.recargar();
  }

  alPaginar(evento: PageEvent): void {
    this.indicePagina.set(evento.pageIndex);
    this.recargar();
  }

  ajustar(producto: FilaStock): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const id = crypto.randomUUID();
    const datos: DatosAjusteDialogo = { producto };
    this.dialogos
      .open<AjusteDialogoComponent, DatosAjusteDialogo, ResultadoAjuste | undefined>(
        AjusteDialogoComponent,
        { data: datos, width: '32rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargando.set(true);
        this.servicio.ajustar({ id, ...resultado }).subscribe({
          next: () => this.recargar(),
          error: () => this.cargando.set(false),
        });
      });
  }

  registrarCompra(): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const id = crypto.randomUUID();
    const datos: DatosCompraDialogo = { productos: this.filas() };
    this.dialogos
      .open<CompraDialogoComponent, DatosCompraDialogo, ResultadoCompra | undefined>(
        CompraDialogoComponent,
        { data: datos, width: '40rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargando.set(true);
        this.servicio.registrarCompra({ id, ...resultado }).subscribe({
          next: () => this.recargar(),
          error: () => this.cargando.set(false),
        });
      });
  }

  varianteDeNivel(nivel: string): VarianteEstado {
    switch (nivel) {
      case 'agotado':
        return 'peligro';
      case 'critico':
        return 'aviso';
      case 'bajo':
        return 'info';
      default:
        return 'exito';
    }
  }

  etiquetaDeNivel(nivel: string): string {
    return NIVELES.includes(nivel as NivelStock) ? `inventario.nivel.${nivel}` : nivel;
  }
}
```

El `.html`: `vd-page-header` con acciones (slide-toggle «Solo alertas» + botón «Registrar compra» con `*vdHasPermission="'compra:crear'"`), bloque `fallo` con reintentar, y `vd-data-table` (`iconoVacio="warehouse"`, `tituloVacio="inventario.vacio.titulo"`, `descripcionVacio="inventario.vacio.descripcion"`) con las dos plantillas: `#celdaNivel` → `vd-status-badge` con `etiquetaDeNivel`/`varianteDeNivel`; `#celdaAcciones` → botón «Ajustar» (`matButton="outlined"`) con `*vdHasPermission="'inventario:ajustar'"`.

- [ ] **Paso 7: la ruta y las claves.** En `app.routes.ts`, tras `catalogo`:

```ts
      {
        path: 'inventario',
        canActivate: [tenantGuard, permisoGuard('producto:leer')],
        loadComponent: () =>
          import('./features/inventario/inventario.component').then((m) => m.InventarioComponent),
      },
```

En `public/i18n/es.json`:

```json
  "inventario": {
    "titulo": "Inventario",
    "subtitulo": "El stock de tu tienda y sus alertas",
    "fallo": "No pudimos cargar el inventario.",
    "solo_alertas": "Solo alertas",
    "columna": {
      "nombre": "Producto",
      "stock": "Stock",
      "minimo": "Mínimo",
      "nivel": "Nivel",
      "acciones": "Acciones"
    },
    "nivel": {
      "agotado": "Agotado",
      "critico": "Crítico",
      "bajo": "Bajo",
      "ok": "Bien"
    },
    "vacio": {
      "titulo": "Sin productos en esta vista",
      "descripcion": "Con «Solo alertas» activo es una buena noticia: nada está por debajo del mínimo."
    },
    "ajuste": {
      "accion": "Ajustar",
      "titulo": "Ajustar «{{nombre}}»",
      "stock_sistema": "El sistema cree que hay {{stock}} (nivel: {{nivel}}).",
      "tipo": "Tipo de ajuste",
      "conteo": "Conteo físico",
      "merma": "Merma (daño, pérdida)",
      "cantidad": "Cantidad",
      "cantidad_ayuda": "En conteo: lo que contaste. En merma: lo que se perdió. Con coma o punto.",
      "motivo": "Motivo",
      "motivo_marcador": "Ej.: conteo del lunes, se dañaron 2 paquetes",
      "invalido": "Revisa la cantidad y el motivo: la cantidad debe ser mayor que cero."
    },
    "compra": {
      "accion": "Registrar compra",
      "titulo": "Compra a proveedor",
      "proveedor": "Proveedor",
      "producto": "Producto",
      "elegir_producto": "Elige un producto…",
      "cantidad": "Cantidad",
      "costo": "Costo unitario (pesos)",
      "agregar_item": "Agregar ítem",
      "invalido": "Revisa la compra: proveedor, cantidades mayores que cero y costos válidos."
    }
  },
```

- [ ] **Paso 8: verde y commit.**

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: verde — 4 del servicio + 6 del componente + todo lo anterior
npx ng lint vendi-tenant && npx ng build vendi-tenant
git add frontend/projects/vendi-tenant
git commit -m "Inventario en vendi-tenant: stock con niveles y alertas, ajuste con motivo obligatorio y compra con ítems"
```

**Criterios de aceptación:** los 10 specs nuevos pasan; el stock negativo se pinta tal cual; el ajuste manda `stock_contado` XOR `cantidad` según el tipo, con `motivo` y `id` generado al abrir; la compra no manda total; el cajero solo lee.

---

## Tarea 8: Mi cuaderno (`/cuaderno`) — clientes, fiados, abonos y WhatsApp

**Files:**
- Create: `frontend/projects/vendi-tenant/src/app/features/cuaderno/contrato.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/cuaderno/cuaderno.service.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/cuaderno/cuaderno.service.spec.ts` (primero)
- Create: `frontend/projects/vendi-tenant/src/app/features/cuaderno/cliente-dialogo.component.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/cuaderno/abono-dialogo.component.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/cuaderno/cuaderno.component.ts` (+ `.html` + `.scss`)
- Create: `frontend/projects/vendi-tenant/src/app/features/cuaderno/credito-detalle.component.ts` (+ `.html` + `.scss`)
- Create: `frontend/projects/vendi-tenant/src/app/features/cuaderno/cuaderno.component.spec.ts` (primero)
- Create: `frontend/projects/vendi-tenant/src/app/features/cuaderno/credito-detalle.component.spec.ts` (primero)
- Modify: `frontend/projects/vendi-tenant/src/app/app.routes.ts`
- Modify: `frontend/projects/vendi-tenant/public/i18n/es.json`

**Interfaces:**
- Consume: `GET /clientes` (`q`, paginación → `PagedList_ClienteConSaldo_` con `saldo_pendiente_total` y `cupo_excedido`), `POST /clientes` (`ClienteCrear`), `PATCH /clientes/{id}` (`ClienteEditar`: `null` explícito BORRA cupo/teléfono/nota), `GET /fiado/creditos` (`estado`: por defecto `vigente`+`vencido`, `estado=vencido`, `estado=todos`), `GET /fiado/creditos/{id}` (`CreditoDetalleSalida` con `abonos` y `whatsapp_url` — null sin teléfono), `POST /fiado/creditos/{id}/abonos` (`AbonoCrear`: `id` REQUERIDO; 422 `abono_excede_saldo`, 409 `credito_no_abonable`, 409 `caja_sin_sesion_abierta` si es en efectivo sin caja abierta), `PATCH /fiado/creditos/{id}` (`CreditoReprogramar`: `fecha_vencimiento` requerida en el body, `null` = sin recordatorio; 409 `credito_no_editable` en saldado/anulado).
- Produce: el cuaderno del tendero; el hogar del aviso `cupo_excedido` (decisión 10) y del `wa.me` (ADR-022).

- [ ] **Paso 1: el spec del servicio, primero.** Crear `cuaderno.service.spec.ts` (setup mínimo). Casos:

```ts
it('los clientes se buscan con q y paginan en el servidor', () => {
  c.servicio.clientes(10, 10, 'rosa').subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/clientes`);
  expect(req.request.params.get('q')).toBe('rosa');
  expect(req.request.params.get('skip')).toBe('10');
  req.flush({ items: [], total: 0, skip: 10, limit: 10 });
});

it('crear cliente manda el id idempotente y el límite en centavos', () => {
  c.servicio
    .crearCliente({ id: ID_OP, nombre: 'Rosa Mejía', telefono: '3001234567', limite_credito: 20000000, nota: null })
    .subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/clientes` && r.method === 'POST');
  expect(req.request.body).toEqual({
    id: ID_OP, nombre: 'Rosa Mejía', telefono: '3001234567', limite_credito: 20000000, nota: null,
  });
  req.flush({ id: ID_OP });
});

it('los créditos se filtran por estado (vencido, todos)', () => {
  c.servicio.creditos('vencido', 0, 10).subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/fiado/creditos`);
  expect(req.request.params.get('estado')).toBe('vencido');
  req.flush({ items: [], total: 0, skip: 0, limit: 10 });
});

it('sin filtro de estado NO se manda el parámetro (el backend aplica vigente+vencido)', () => {
  c.servicio.creditos(null, 0, 10).subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/fiado/creditos`);
  expect(req.request.params.has('estado')).toBe(false);
  req.flush({ items: [], total: 0, skip: 0, limit: 10 });
});

it('el detalle del crédito trae abonos y el wa.me', () => {
  let detalle: { whatsapp_url?: string | null } | null = null;
  c.servicio.credito(ID_CRED).subscribe((d) => (detalle = d));
  c.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush({
    id: ID_CRED, whatsapp_url: 'https://wa.me/573001234567?text=...', abonos: [],
  });
  expect(detalle?.whatsapp_url).toContain('wa.me');
});

it('el abono viaja con id, método y monto en centavos', () => {
  c.servicio.abonar(ID_CRED, { id: ID_OP, metodo_pago: 'efectivo', monto: 500000, nota: null }).subscribe();
  const req = c.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}/abonos`);
  expect(req.request.method).toBe('POST');
  expect(req.request.body).toEqual({ id: ID_OP, metodo_pago: 'efectivo', monto: 500000, nota: null });
  req.flush({ id: ID_OP });
});

it('reprogramar manda SIEMPRE la clave fecha_vencimiento (body {} es 422)', () => {
  c.servicio.reprogramar(ID_CRED, null).subscribe();
  const req = c.http.expectOne({ method: 'PATCH', url: `${BASE}/fiado/creditos/${ID_CRED}` });
  expect(req.request.body).toEqual({ fecha_vencimiento: null });
  req.flush({ id: ID_CRED });

  c.servicio.reprogramar(ID_CRED, '2026-08-15').subscribe();
  const con_fecha = c.http.expectOne({ method: 'PATCH', url: `${BASE}/fiado/creditos/${ID_CRED}` });
  expect(con_fecha.request.body).toEqual({ fecha_vencimiento: '2026-08-15' });
  con_fecha.flush({ id: ID_CRED });
});
```

- [ ] **Paso 2: contrato y servicio.** Crear `frontend/projects/vendi-tenant/src/app/features/cuaderno/contrato.ts`:

```ts
import type { components } from 'data-access';

export type ClienteConSaldo = components['schemas']['ClienteConSaldo'];
export type CreditoResumenSalida = components['schemas']['CreditoResumenSalida'];
export type CreditoDetalleSalida = components['schemas']['CreditoDetalleSalida'];
export type AbonoSalida = components['schemas']['AbonoSalida'];

/** Estados del crédito (ADR-022): un saldado nunca vuelve a vigente. */
export type EstadoCredito = 'vigente' | 'vencido' | 'saldado' | 'anulado';

export interface ClienteNuevo {
  id: string;
  nombre: string;
  telefono: string | null;
  /** Centavos; null = sin cupo. */
  limite_credito: number | null;
  nota: string | null;
}

/** Edición parcial; `null` explícito BORRA el valor en el backend. */
export type CambiosDeCliente = Partial<Omit<ClienteNuevo, 'id'>>;

export interface AbonoNuevo {
  id: string;
  metodo_pago: 'efectivo' | 'transferencia' | 'otro';
  /** Centavos. */
  monto: number;
  nota: string | null;
}
```

Crear `cuaderno.service.ts`:

```ts
import { Injectable, inject } from '@angular/core';
import { ApiService } from 'data-access';
import { PagedList } from 'domain';
import { Observable } from 'rxjs';
import {
  AbonoNuevo,
  AbonoSalida,
  CambiosDeCliente,
  ClienteConSaldo,
  ClienteNuevo,
  CreditoDetalleSalida,
  CreditoResumenSalida,
} from './contrato';

/**
 * Cliente del cuaderno (ADR-009/ADR-022). El cupo se muestra, nunca bloquea;
 * el abono se registra contra el crédito que el usuario tocó.
 */
@Injectable({ providedIn: 'root' })
export class CuadernoService {
  private readonly api = inject(ApiService);

  clientes(skip: number, limit: number, consulta = ''): Observable<PagedList<ClienteConSaldo>> {
    const params: Record<string, string | number> = { skip, limit };
    const q = consulta.trim();
    if (q.length > 0) {
      params['q'] = q;
    }
    return this.api.get<PagedList<ClienteConSaldo>>('/clientes', params);
  }

  crearCliente(cliente: ClienteNuevo): Observable<ClienteConSaldo> {
    return this.api.post<ClienteConSaldo>('/clientes', cliente);
  }

  editarCliente(id: string, cambios: CambiosDeCliente): Observable<ClienteConSaldo> {
    return this.api.patch<ClienteConSaldo>(`/clientes/${id}`, cambios);
  }

  /** `estado` null = el filtro por defecto del backend (vigente + vencido). */
  creditos(
    estado: string | null,
    skip: number,
    limit: number,
  ): Observable<PagedList<CreditoResumenSalida>> {
    const params: Record<string, string | number> = { skip, limit };
    if (estado) {
      params['estado'] = estado;
    }
    return this.api.get<PagedList<CreditoResumenSalida>>('/fiado/creditos', params);
  }

  credito(id: string): Observable<CreditoDetalleSalida> {
    return this.api.get<CreditoDetalleSalida>(`/fiado/creditos/${id}`);
  }

  abonar(creditoId: string, abono: AbonoNuevo): Observable<AbonoSalida> {
    return this.api.post<AbonoSalida>(`/fiado/creditos/${creditoId}/abonos`, abono);
  }

  /** `null` explícito = sin fecha (y sin recordatorio, declarado en pantalla). */
  reprogramar(creditoId: string, fecha: string | null): Observable<CreditoResumenSalida> {
    return this.api.patch<CreditoResumenSalida>(`/fiado/creditos/${creditoId}`, {
      fecha_vencimiento: fecha,
    });
  }
}
```

- [ ] **Paso 3: los dos diálogos.** `cliente-dialogo.component.ts` (patrón de los anteriores; `FormRenderer`; resultado `Omit<ClienteNuevo, 'id'>`):

```ts
campos: [
  { clave: 'nombre', etiqueta: 'cuaderno.campo.nombre', tipo: 'text',
    valorPorDefecto: datos.cliente?.nombre ?? '',
    validadores: [{ tipo: 'required' }, { tipo: 'minLength', valor: 2 }, { tipo: 'maxLength', valor: 120 }] },
  { clave: 'telefono', etiqueta: 'cuaderno.campo.telefono', tipo: 'tel',
    ayuda: 'cuaderno.campo.telefono_ayuda',
    valorPorDefecto: datos.cliente?.telefono ?? '' },
  { clave: 'limite_pesos', etiqueta: 'cuaderno.campo.cupo', tipo: 'number',
    ayuda: 'cuaderno.campo.cupo_ayuda',
    valorPorDefecto: datos.cliente?.limite_credito ? datos.cliente.limite_credito / 100 : null,
    validadores: [{ tipo: 'min', valor: 0 }] },
  { clave: 'nota', etiqueta: 'cuaderno.campo.nota', tipo: 'textarea',
    valorPorDefecto: datos.cliente?.nota ?? '',
    validadores: [{ tipo: 'maxLength', valor: 500 }] },
]
```

`alEnviar`: nombre trimmed ≥2 o no cierra; `limite_pesos` vacío → `limite_credito: null` (sin cupo — y en edición BORRA el cupo, semántica del backend, mencionada en la ayuda); teléfono vacío → `null`; devuelve `{ nombre, telefono, limite_credito, nota }`. Escribir el componente completo siguiendo la forma de `ProductoDialogoComponent` (Tarea 6, Paso 4) con estos campos y conversiones.

`abono-dialogo.component.ts` (`FormRenderer`; resultado `Omit<AbonoNuevo, 'id'>`):

```ts
campos: [
  { clave: 'monto_pesos', etiqueta: 'cuaderno.abono.monto', tipo: 'number',
    ayuda: 'cuaderno.abono.monto_ayuda',
    validadores: [{ tipo: 'required' }, { tipo: 'min', valor: 1 }] },
  { clave: 'metodo_pago', etiqueta: 'cuaderno.abono.metodo', tipo: 'select',
    valorPorDefecto: 'efectivo',
    opciones: [
      { etiqueta: 'cuaderno.metodo.efectivo', valor: 'efectivo' },
      { etiqueta: 'cuaderno.metodo.transferencia', valor: 'transferencia' },
      { etiqueta: 'cuaderno.metodo.otro', valor: 'otro' },
    ] },
  { clave: 'nota', etiqueta: 'cuaderno.campo.nota', tipo: 'text',
    validadores: [{ tipo: 'maxLength', valor: 300 }] },
]
```

La ayuda del monto dice que el abono en efectivo entra a la caja abierta del momento (y exige que haya una — el 409 `caja_sin_sesion_abierta` llega con el mensaje del backend si no). El diálogo recibe por `MAT_DIALOG_DATA` el saldo vivo (`{ saldoPendiente: number }`) y lo muestra formateado; NO valida contra él — el tope lo impone el servidor (`abono_excede_saldo`) y el exceso de cupo nunca bloquea (ADR-022). Escribir completo con la misma forma.

- [ ] **Paso 4: los specs de los componentes, antes de los componentes.** `cuaderno.component.spec.ts` (montaje de siempre; roles dueno y cajero — ambos gestionan el cuaderno, ADR-023):

```ts
describe('CuadernoComponent — clientes', () => {
  it('pinta saldo formateado y el badge de cupo excedido como advertencia', async () => {
    const m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/clientes`).flush(
      pagina([
        { ...clienteBase, nombre: 'Rosa Mejía', saldo_pendiente_total: 4500000, cupo_excedido: true },
      ]),
    );
    m.http.expectOne((r) => r.url === `${BASE}/fiado/creditos`).flush(pagina([], 0));
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Rosa Mejía');
    expect(visible).toContain('45.000');
    expect(visible).toContain('Cupo excedido');
  });

  it('avisa cuántos créditos vencidos hay (el cuaderno cobra, no esconde)', async () => {
    const m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/clientes`).flush(pagina([]));
    m.http.expectOne((r) => r.url === `${BASE}/fiado/creditos`).flush(pagina([creditoBase], 3));
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain('3 créditos vencidos');
  });

  it('el filtro de vencidos pide estado=vencido al servidor', async () => {
    const m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/clientes`).flush(pagina([]));
    m.http.expectOne((r) => r.url === `${BASE}/fiado/creditos`).flush(pagina([]));
    m.fixture.componentInstance.filtrarEstado('vencido');
    const req = m.http.expectOne((r) => r.url === `${BASE}/fiado/creditos`);
    expect(req.request.params.get('estado')).toBe('vencido');
    req.flush(pagina([]));
  });

  it('crear cliente manda el payload convertido y recarga', async () => {
    const m = await montar(ROLES_CAJERO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/clientes`).flush(pagina([]));
    m.http.expectOne((r) => r.url === `${BASE}/fiado/creditos`).flush(pagina([]));

    m.dialogos.resultados = [
      { nombre: 'Rosa Mejía', telefono: '3001234567', limite_credito: 20000000, nota: null },
    ];
    m.fixture.componentInstance.crearCliente();
    const alta = m.http.expectOne((r) => r.url === `${BASE}/clientes` && r.method === 'POST');
    expect((alta.request.body as { id: string }).id).toBeTruthy();
    expect((alta.request.body as { limite_credito: number }).limite_credito).toBe(20000000);
    alta.flush(clienteBase);
    m.http.expectOne((r) => r.url === `${BASE}/clientes` && r.method === 'GET').flush(pagina([clienteBase]));
  });
});
```

`credito-detalle.component.spec.ts` (mismo montaje de siempre, con una diferencia: el id de la ruta se simula con un `ActivatedRoute` de mentira — `{ provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => ID_CRED } } } }` — más simple que levantar el harness para un solo parámetro):

```ts
describe('CreditoDetalleComponent', () => {
  // El montaje es el de siempre más el ActivatedRoute de mentira con el id;
  // `montar(roles)` crea el componente directo, sin router.

  it('pinta saldo, vencimiento y el botón de WhatsApp con el wa.me del backend', async () => {
    const m = await montar(ROLES_CAJERO);
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush(detalleBase);
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Rosa Mejía');
    expect(visible).toContain('45.000');
    const enlace = (m.fixture.nativeElement as HTMLElement).querySelector('a[href*="wa.me"]');
    expect(enlace?.getAttribute('href')).toBe(detalleBase.whatsapp_url);
    expect(enlace?.getAttribute('target')).toBe('_blank');
  });

  it('sin teléfono NO hay botón de WhatsApp (whatsapp_url llega null)', async () => {
    const m = await montar(ROLES_CAJERO);
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush({ ...detalleBase, whatsapp_url: null });
    m.fixture.detectChanges();
    expect((m.fixture.nativeElement as HTMLElement).querySelector('a[href*="wa.me"]')).toBeNull();
  });

  it('crédito sin fecha lo declara en pantalla: sin fecha, sin recordatorio', async () => {
    const m = await montar(ROLES_CAJERO);
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush({ ...detalleBase, fecha_vencimiento: null });
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain('Sin fecha de vencimiento');
  });

  it('el abono manda id, método y centavos, y recarga el detalle', async () => {
    const m = await montar(ROLES_CAJERO);
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush(detalleBase);
    m.fixture.detectChanges();

    m.dialogos.resultados = [{ metodo_pago: 'efectivo', monto: 500000, nota: null }];
    m.fixture.componentInstance.registrarAbono();
    const req = m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}/abonos`);
    expect(req.request.body).toEqual({
      id: expect.any(String), metodo_pago: 'efectivo', monto: 500000, nota: null,
    });
    req.flush({ id: 'x' });
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush(detalleBase);
  });

  it('reprogramar a null manda la clave con null (nunca body vacío)', async () => {
    const m = await montar(ROLES_CAJERO);
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush(detalleBase);
    m.fixture.detectChanges();

    m.fixture.componentInstance.quitarVencimiento();
    const req = m.http.expectOne({ method: 'PATCH', url: `${BASE}/fiado/creditos/${ID_CRED}` });
    expect(req.request.body).toEqual({ fecha_vencimiento: null });
    req.flush({ id: ID_CRED });
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush(detalleBase);
  });

  it('el historial de abonos se pinta con método y monto', async () => {
    const m = await montar(ROLES_CAJERO);
    m.http.expectOne(`${BASE}/fiado/creditos/${ID_CRED}`).flush({
      ...detalleBase,
      abonos: [
        { id: 'a1', credito_id: ID_CRED, monto: 300000, metodo_pago: 'efectivo', nota: null, registrado_por: 'ana', sesion_caja_id: null, created_at: '2026-07-20T10:00:00Z' },
      ],
    });
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('3.000');
    expect(visible).toContain('Efectivo');
  });
});
```

con:

```ts
const clienteBase = {
  id: '5f1d0e2a-0000-4000-8000-dddddddddddd',
  nombre: 'Rosa Mejía',
  telefono: '3001234567',
  nota: null,
  limite_credito: 20000000,
  saldo_pendiente_total: 4500000,
  cupo_excedido: false,
  created_at: '2026-07-01T00:00:00Z',
};

const creditoBase = {
  id: ID_CRED,
  cliente_id: clienteBase.id,
  cliente_nombre: 'Rosa Mejía',
  venta_id: '5f1d0e2a-0000-4000-8000-eeeeeeeeeeee',
  estado: 'vencido',
  monto_total: 5000000,
  saldo_pendiente: 4500000,
  fecha_vencimiento: '2026-07-25',
  created_at: '2026-07-10T00:00:00Z',
};

const detalleBase = { ...creditoBase, abonos: [], whatsapp_url: 'https://wa.me/573001234567?text=Hola' };
```

- [ ] **Paso 5: `CuadernoComponent`.** Crear `cuaderno.component.ts`:

```ts
import { Component, TemplateRef, computed, inject, signal, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { PageEvent } from '@angular/material/paginator';
import { Router } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { HasPermissionDirective } from 'auth';
import { formatearPesos } from 'domain';
import {
  ColumnaTabla,
  DataTableComponent,
  PageHeaderComponent,
  StatusBadgeComponent,
  VarianteEstado,
} from 'ui-kit';
import { ClienteDialogoComponent, DatosClienteDialogo, ResultadoCliente } from './cliente-dialogo.component';
import { ClienteConSaldo, CreditoResumenSalida, EstadoCredito } from './contrato';
import { CuadernoService } from './cuaderno.service';

const TAMANO_PAGINA = 10;

interface FilaCliente extends ClienteConSaldo {
  acciones?: never;
}
interface FilaCredito extends CreditoResumenSalida {
  acciones?: never;
}

const ESTADOS: readonly EstadoCredito[] = ['vigente', 'vencido', 'saldado', 'anulado'];

/**
 * Mi cuaderno: los clientes con su deuda viva y los fiados (ADR-009/022).
 *
 * El cupo es advertencia, nunca bloqueo: `cupo_excedido` se pinta como badge
 * de aviso (aquí vive el aviso que el POS no muestra — decisión 10 del plan).
 * La tira de vencidos es el gesto de cobro del día: cuántos son y un filtro
 * para verlos. El detalle de cada crédito tiene su propia ruta.
 */
@Component({
  selector: 'vd-cuaderno',
  imports: [
    TranslateModule,
    MatButtonModule,
    MatIconModule,
    MatSelectModule,
    HasPermissionDirective,
    PageHeaderComponent,
    DataTableComponent,
    StatusBadgeComponent,
  ],
  templateUrl: './cuaderno.component.html',
  styleUrl: './cuaderno.component.scss',
})
export class CuadernoComponent {
  private readonly servicio = inject(CuadernoService);
  private readonly dialogos = inject(MatDialog);
  private readonly router = inject(Router);

  readonly clientes = signal<FilaCliente[]>([]);
  readonly totalClientes = signal(0);
  readonly indiceClientes = signal(0);
  readonly consulta = signal('');
  readonly creditos = signal<FilaCredito[]>([]);
  readonly totalCreditos = signal(0);
  readonly indiceCreditos = signal(0);
  /** null = filtro por defecto del backend (vigente + vencido). */
  readonly estadoFiltro = signal<string | null>(null);
  readonly cargando = signal(false);
  readonly fallo = signal(false);
  private readonly dialogoAbierto = signal(false);

  readonly formatear = formatearPesos;

  private readonly plantillaSaldo = viewChild<TemplateRef<{ $implicit: FilaCliente }>>('celdaSaldo');
  private readonly plantillaAccionesCliente =
    viewChild<TemplateRef<{ $implicit: FilaCliente }>>('celdaAccionesCliente');
  private readonly plantillaEstado =
    viewChild<TemplateRef<{ $implicit: FilaCredito }>>('celdaEstado');
  private readonly plantillaAccionesCredito =
    viewChild<TemplateRef<{ $implicit: FilaCredito }>>('celdaAccionesCredito');

  readonly columnasClientes = computed<ColumnaTabla<FilaCliente>[]>(() => [
    { clave: 'nombre', etiqueta: 'cuaderno.columna.nombre' },
    { clave: 'telefono', etiqueta: 'cuaderno.columna.telefono' },
    { clave: 'saldo_pendiente_total', etiqueta: 'cuaderno.columna.saldo', plantilla: this.plantillaSaldo() },
    { clave: 'acciones', etiqueta: 'cuaderno.columna.acciones', plantilla: this.plantillaAccionesCliente(), ancho: '7rem' },
  ]);

  readonly columnasCreditos = computed<ColumnaTabla<FilaCredito>[]>(() => [
    { clave: 'cliente_nombre', etiqueta: 'cuaderno.columna.cliente' },
    { clave: 'monto_total', etiqueta: 'cuaderno.columna.monto' },
    { clave: 'saldo_pendiente', etiqueta: 'cuaderno.columna.debe' },
    { clave: 'fecha_vencimiento', etiqueta: 'cuaderno.columna.vence' },
    { clave: 'estado', etiqueta: 'cuaderno.columna.estado', plantilla: this.plantillaEstado() },
    { clave: 'acciones', etiqueta: 'cuaderno.columna.acciones', plantilla: this.plantillaAccionesCredito(), ancho: '6rem' },
  ]);

  constructor() {
    this.recargar();
  }

  recargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    this.servicio
      .clientes(this.indiceClientes() * TAMANO_PAGINA, TAMANO_PAGINA, this.consulta())
      .subscribe({
        next: (pagina) => {
          this.clientes.set(pagina.items);
          this.totalClientes.set(pagina.total);
          this.cargarCreditos();
        },
        error: () => {
          this.cargando.set(false);
          this.fallo.set(true);
        },
      });
  }

  buscar(): void {
    this.indiceClientes.set(0);
    this.recargar();
  }

  filtrarEstado(estado: string | null): void {
    this.estadoFiltro.set(estado);
    this.indiceCreditos.set(0);
    this.cargarCreditos();
  }

  alPaginarClientes(evento: PageEvent): void {
    this.indiceClientes.set(evento.pageIndex);
    this.recargar();
  }

  alPaginarCreditos(evento: PageEvent): void {
    this.indiceCreditos.set(evento.pageIndex);
    this.cargarCreditos();
  }

  crearCliente(): void {
    this.abrirFormularioCliente({});
  }

  editarCliente(cliente: FilaCliente): void {
    this.abrirFormularioCliente({ cliente });
  }

  verCredito(credito: FilaCredito): void {
    this.router.navigate(['/cuaderno/creditos', credito.id]).catch((error: unknown) => {
      console.error('No se pudo abrir el detalle del crédito.', error);
    });
  }

  varianteDeEstado(estado: string): VarianteEstado {
    switch (estado) {
      case 'vencido':
        return 'peligro';
      case 'vigente':
        return 'info';
      case 'saldado':
        return 'exito';
      default:
        return 'neutro';
    }
  }

  etiquetaDeEstado(estado: string): string {
    return ESTADOS.includes(estado as EstadoCredito) ? `cuaderno.estado.${estado}` : estado;
  }

  private cargarCreditos(): void {
    this.servicio
      .creditos(this.estadoFiltro(), this.indiceCreditos() * TAMANO_PAGINA, TAMANO_PAGINA)
      .subscribe({
        next: (pagina) => {
          this.creditos.set(pagina.items);
          this.totalCreditos.set(pagina.total);
          this.cargando.set(false);
        },
        error: () => {
          this.cargando.set(false);
          this.fallo.set(true);
        },
      });
  }

  private abrirFormularioCliente(datos: DatosClienteDialogo): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const id = datos.cliente ? null : crypto.randomUUID();
    this.dialogos
      .open<ClienteDialogoComponent, DatosClienteDialogo, ResultadoCliente | undefined>(
        ClienteDialogoComponent,
        { data: datos, width: '32rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargando.set(true);
        const operacion = datos.cliente
          ? this.servicio.editarCliente(datos.cliente.id, resultado)
          : this.servicio.crearCliente({ id: id ?? crypto.randomUUID(), ...resultado });
        operacion.subscribe({
          next: () => this.recargar(),
          error: () => this.cargando.set(false),
        });
      });
  }
}
```

El `.html`: `vd-page-header` con botón «Nuevo cliente» (`*vdHasPermission="'cliente:gestionar'"`); tira de vencidos (`@if (totalVencidos > 0)` — ver nota abajo) con `role="status"`; tabla de clientes con buscador (plantilla `#celdaSaldo`: monto formateado + `@if (fila.cupo_excedido) { <vd-status-badge etiqueta="cuaderno.cupo_excedido" variante="aviso" /> }`); selector de estado (opciones: por defecto/vencido/todos) y tabla de créditos con `#celdaEstado` (badge) y `#celdaAccionesCredito` (botón «Ver»). Los montos de las tablas de créditos se pintan con plantillas propias (`#celdaMonto`, `#celdaDebe`) usando `formatear`.

**Nota de la tira de vencidos:** el `total` de la tabla de créditos con filtro por defecto (vigente+vencido) NO distingue vencidos. La tira se alimenta de una llamada aparte: `creditos('vencido', 0, 1)` al cargar, guardando `totalVencidos = signal(0)` con el `total` de esa página. Añadir esa llamada a `recargar()` (tras `cargarCreditos`, silenciada con `SILENCIAR_AVISO_ERROR`: si falla, la tira simplemente no sale) y el spec «avisa cuántos créditos vencidos hay» debe responderla: el flush de `pagina([creditoBase], 3)` del spec va a la petición con `estado=vencido`. Ajustar el orden de `expectOne` en los specs: la de clientes, la de créditos por defecto y la de vencidos (`r.url === creditos && r.params.get('estado') === 'vencido'`).

- [ ] **Paso 6: `CreditoDetalleComponent`.** Crear `credito-detalle.component.ts`:

```ts
import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { TranslateModule } from '@ngx-translate/core';
import { HasPermissionDirective } from 'auth';
import { formatearPesos } from 'domain';
import { LoadingSpinnerComponent, StatusBadgeComponent, VarianteEstado } from 'ui-kit';
import { AbonoDialogoComponent, DatosAbonoDialogo, ResultadoAbono } from './abono-dialogo.component';
import { CreditoDetalleSalida } from './contrato';
import { CuadernoService } from './cuaderno.service';

/**
 * La pantalla del fiado (ADR-022): su historial de pagos, el cobro por
 * WhatsApp con el `wa.me` prearmado del backend (null sin teléfono) y la
 * reprogramación del vencimiento — `null` explícito es «sin fecha», y la
 * pantalla lo declara: sin fecha no hay recordatorio.
 */
@Component({
  selector: 'vd-credito-detalle',
  imports: [
    TranslateModule,
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    HasPermissionDirective,
    LoadingSpinnerComponent,
    StatusBadgeComponent,
  ],
  templateUrl: './credito-detalle.component.html',
  styleUrl: './credito-detalle.component.scss',
})
export class CreditoDetalleComponent {
  private readonly servicio = inject(CuadernoService);
  private readonly dialogos = inject(MatDialog);
  private readonly ruta = inject(ActivatedRoute);

  readonly credito = signal<CreditoDetalleSalida | null>(null);
  readonly cargando = signal(true);
  readonly fallo = signal(false);
  /** Nueva fecha del input tipo date (`YYYY-MM-DD`); vacío = sin cambiar. */
  readonly nuevaFecha = signal('');
  private readonly dialogoAbierto = signal(false);

  readonly formatear = formatearPesos;
  private readonly id = this.ruta.snapshot.paramMap.get('id') ?? '';

  constructor() {
    this.cargar();
  }

  cargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    this.servicio.credito(this.id).subscribe({
      next: (credito) => {
        this.credito.set(credito);
        this.nuevaFecha.set(credito.fecha_vencimiento ?? '');
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.fallo.set(true);
      },
    });
  }

  registrarAbono(): void {
    const credito = this.credito();
    if (!credito || this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const id = crypto.randomUUID();
    const datos: DatosAbonoDialogo = { saldoPendiente: credito.saldo_pendiente };
    this.dialogos
      .open<AbonoDialogoComponent, DatosAbonoDialogo, ResultadoAbono | undefined>(
        AbonoDialogoComponent,
        { data: datos, width: '32rem' },
      )
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.servicio.abonar(credito.id, { id, ...resultado }).subscribe({
          next: () => this.cargar(),
          // 422 abono_excede_saldo, 409 credito_no_abonable o
          // caja_sin_sesion_abierta: el interceptor ya mostró el mensaje del
          // backend; no hay nada que la pantalla pueda corregir sola.
          error: () => undefined,
        });
      });
  }

  guardarVencimiento(): void {
    const fecha = this.nuevaFecha().trim();
    if (!fecha) {
      return;
    }
    this.servicio.reprogramar(this.id, fecha).subscribe({
      next: () => this.cargar(),
      error: () => undefined,
    });
  }

  quitarVencimiento(): void {
    this.servicio.reprogramar(this.id, null).subscribe({
      next: () => this.cargar(),
      error: () => undefined,
    });
  }

  varianteDeEstado(estado: string): VarianteEstado {
    switch (estado) {
      case 'vencido':
        return 'peligro';
      case 'vigente':
        return 'info';
      case 'saldado':
        return 'exito';
      default:
        return 'neutro';
    }
  }
}
```

El `.html`: enlace «← Volver al cuaderno» (`routerLink="/cuaderno"`); `vd-loading-spinner` mientras carga; bloque `fallo` con reintentar; con el crédito: tarjeta con cliente, badge de estado (`cuaderno.estado.${estado}`), monto total, saldo pendiente, vencimiento (`{{ fecha }}` o el texto «Sin fecha de vencimiento — sin recordatorio»), botón WhatsApp `<a matButton="outlined" [href]="credito.whatsapp_url" target="_blank" rel="noopener">` solo `@if (credito.whatsapp_url)`, botón «Registrar abono» (`*vdHasPermission="'fiado:abonar'"`, deshabilitado si el estado es `saldado`/`anulado`), bloque de reprogramación (`*vdHasPermission="'fiado:crear'"`: `<input type="date" [(ngModel)]="nuevaFecha">` + «Guardar fecha» + «Quitar fecha») y la lista de abonos (`@for` sobre `credito.abonos`: fecha, método traducido `cuaderno.metodo.${metodo_pago}`, monto formateado, nota).

- [ ] **Paso 7: las rutas y las claves.** En `app.routes.ts`, tras `inventario`:

```ts
      {
        path: 'cuaderno',
        canActivate: [tenantGuard, permisoGuard('cliente:gestionar')],
        loadComponent: () =>
          import('./features/cuaderno/cuaderno.component').then((m) => m.CuadernoComponent),
      },
      {
        path: 'cuaderno/creditos/:id',
        canActivate: [tenantGuard, permisoGuard('cliente:gestionar')],
        loadComponent: () =>
          import('./features/cuaderno/credito-detalle.component').then(
            (m) => m.CreditoDetalleComponent,
          ),
      },
```

En `public/i18n/es.json`:

```json
  "cuaderno": {
    "titulo": "Mi cuaderno",
    "subtitulo": "Clientes, fiados y abonos",
    "fallo": "No pudimos cargar el cuaderno.",
    "buscar_placeholder": "Buscar cliente…",
    "nuevo_cliente": "Nuevo cliente",
    "editar_cliente": "Editar cliente",
    "vencidos": "{{cantidad}} créditos vencidos esperando cobro",
    "filtro": {
      "por_cobrar": "Por cobrar",
      "vencido": "Solo vencidos",
      "todos": "Todos (incluye saldados)"
    },
    "columna": {
      "nombre": "Cliente",
      "telefono": "Teléfono",
      "saldo": "Debe",
      "cliente": "Cliente",
      "monto": "Fiado",
      "debe": "Debe",
      "vence": "Vence",
      "estado": "Estado",
      "acciones": "Acciones"
    },
    "estado": {
      "vigente": "Vigente",
      "vencido": "Vencido",
      "saldado": "Saldado",
      "anulado": "Anulado"
    },
    "cupo_excedido": "Cupo excedido",
    "campo": {
      "nombre": "Nombre",
      "telefono": "Teléfono (WhatsApp)",
      "telefono_ayuda": "Con indicativo o sin él: lo usa el botón de cobro por WhatsApp.",
      "cupo": "Cupo de crédito (pesos)",
      "cupo_ayuda": "Vacío = sin cupo. En edición, vaciarlo BORRA el cupo.",
      "nota": "Nota"
    },
    "abono": {
      "accion": "Registrar abono",
      "titulo": "Abono al fiado",
      "saldo": "Debe {{monto}}",
      "monto": "Monto (pesos)",
      "monto_ayuda": "En efectivo entra a la caja abierta; sin caja abierta el servidor lo rechaza.",
      "metodo": "Método de pago"
    },
    "metodo": {
      "efectivo": "Efectivo",
      "transferencia": "Transferencia",
      "otro": "Otro"
    },
    "detalle": {
      "volver": "Volver al cuaderno",
      "fiado_de": "Fiado",
      "debe": "Debe",
      "vence": "Vence",
      "sin_fecha": "Sin fecha de vencimiento — sin recordatorio",
      "whatsapp": "Cobrar por WhatsApp",
      "reprogramar": "Cambiar vencimiento",
      "guardar_fecha": "Guardar fecha",
      "quitar_fecha": "Quitar fecha",
      "abonos": "Abonos",
      "sin_abonos": "Todavía no hay abonos",
      "fallo": "No pudimos cargar el fiado."
    }
  },
```

- [ ] **Paso 8: verde y commit.**

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: verde — 7 del servicio + 4 del cuaderno + 6 del detalle + todo lo anterior
npx ng lint vendi-tenant && npx ng build vendi-tenant
git add frontend/projects/vendi-tenant
git commit -m "Cuaderno en vendi-tenant: clientes con saldo y cupo, detalle del fiado con abonos, wa.me y reprogramación"
```

**Criterios de aceptación:** los 17 specs nuevos pasan; `cupo_excedido` se pinta como advertencia y nunca bloquea; el botón de WhatsApp usa el `whatsapp_url` del backend y desaparece cuando es null; «sin fecha» se declara en pantalla; reprogramar manda siempre la clave `fecha_vencimiento`; el id del abono se genera al abrir el diálogo.

---

## Tarea 9: Mis números (`/numeros`) — P&L con fuentes y forecast 30 días

**Files:**
- Create: `frontend/projects/vendi-tenant/src/app/features/numeros/contrato.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/numeros/numeros.service.ts`
- Create: `frontend/projects/vendi-tenant/src/app/features/numeros/numeros.service.spec.ts` (primero)
- Create: `frontend/projects/vendi-tenant/src/app/features/numeros/numeros.component.ts` (+ `.html` + `.scss`)
- Create: `frontend/projects/vendi-tenant/src/app/features/numeros/numeros.component.spec.ts` (primero)
- Modify: `frontend/projects/vendi-tenant/src/app/app.routes.ts`
- Modify: `frontend/projects/vendi-tenant/public/i18n/es.json`

**Interfaces:**
- Consume: `GET /reportes/pyl` (`periodo: dia|semana|mes`, ancla Bogotá por defecto hoy → `PyLSalida` con `fuentes`), `GET /reportes/forecast` (→ `ForecastSalida` con `fuentes` y `dias_con_datos`). ADR-006: «el forecast es una proyección explicada, no una promesa: la pantalla tiene que decir de qué datos sale» — las `fuentes` se RENDERIZAN, no se ignoran. Las compras del período son línea informativa que NO se resta del resultado (el P&L ya lo declara).
- Produce: la sección solo-`reporte:leer`; en la semilla, solo el dueño la ve (decisión 4).

- [ ] **Paso 1: el spec del servicio, primero.** Crear `numeros.service.spec.ts` (setup mínimo). Casos:

```ts
it('el P&L se pide por período', () => {
  c.servicio.pyl('semana').subscribe();
  const req = c.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`);
  expect(req.request.params.get('periodo')).toBe('semana');
  req.flush(pylBase);
});

it('el forecast no lleva parámetros', () => {
  c.servicio.forecast().subscribe();
  const req = c.http.expectOne(`${BASE}/reportes/forecast`);
  expect([...req.request.params.keys()].length).toBe(0);
  req.flush(forecastBase);
});
```

- [ ] **Paso 2: contrato y servicio.** Crear `frontend/projects/vendi-tenant/src/app/features/numeros/contrato.ts`:

```ts
import type { components } from 'data-access';

export type PyLSalida = components['schemas']['PyLSalida'];
export type ForecastSalida = components['schemas']['ForecastSalida'];

export type PeriodoPyl = 'dia' | 'semana' | 'mes';

/** Una línea de dinero del reporte: clave i18n y valor en centavos. */
export interface LineaDeDinero {
  clave: string;
  centavos: number;
}
```

Crear `numeros.service.ts`:

```ts
import { Injectable, inject } from '@angular/core';
import { ApiService } from 'data-access';
import { Observable } from 'rxjs';
import { ForecastSalida, PeriodoPyl, PyLSalida } from './contrato';

/** Cliente de reportes (ADR-006): cada número declara su fuente. */
@Injectable({ providedIn: 'root' })
export class NumerosService {
  private readonly api = inject(ApiService);

  pyl(periodo: PeriodoPyl): Observable<PyLSalida> {
    return this.api.get<PyLSalida>('/reportes/pyl', { periodo });
  }

  forecast(): Observable<ForecastSalida> {
    return this.api.get<ForecastSalida>('/reportes/forecast');
  }
}
```

- [ ] **Paso 3: el spec del componente, antes del componente.** Crear `numeros.component.spec.ts` (montaje de siempre). Casos:

```ts
describe('NumerosComponent', () => {
  it('pide P&L del día y forecast al entrar, y pinta los números formateados', async () => {
    const m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).flush(pylBase);
    m.http.expectOne(`${BASE}/reportes/forecast`).flush(forecastBase);
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Ventas netas');
    expect(visible).toContain('180.000'); // ventas_netas_centavos = 18000000
    expect(visible).toContain('Saldo proyectado');
  });

  it('las fuentes se RENDERIZAN: la pantalla dice de qué datos sale (ADR-006)', async () => {
    const m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).flush(pylBase);
    m.http.expectOne(`${BASE}/reportes/forecast`).flush(forecastBase);
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain(pylBase.fuentes['costo_de_lo_vendido']);
    expect(visible).toContain(forecastBase.fuentes['cobros_fiado']);
    expect(visible).toContain('12'); // dias_con_datos
  });

  it('cambiar a la semana vuelve a pedir solo el P&L', async () => {
    const m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).flush(pylBase);
    m.http.expectOne(`${BASE}/reportes/forecast`).flush(forecastBase);

    m.fixture.componentInstance.cambiarPeriodo('semana');
    const req = m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`);
    expect(req.request.params.get('periodo')).toBe('semana');
    req.flush(pylBase);
    // No hay segunda petición de forecast: lo verifica http.verify().
  });

  it('las compras del período se muestran como línea informativa, no restada', async () => {
    const m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).flush(pylBase);
    m.http.expectOne(`${BASE}/reportes/forecast`).flush(forecastBase);
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Compras a proveedores (informativo');
  });

  it('un fallo deja reintento, no spinner eterno', async () => {
    const m = await montar(ROLES_DUENO);
    m.fixture.detectChanges();
    m.http.expectOne((r) => r.url === `${BASE}/reportes/pyl`).error(new ProgressEvent('error'));
    m.http.expectOne(`${BASE}/reportes/forecast`).error(new ProgressEvent('error'));
    m.fixture.detectChanges();
    expect(m.fixture.componentInstance.fallo()).toBe(true);
    expect(texto(m.fixture)).toContain('Reintentar');
  });
});
```

con:

```ts
const pylBase = {
  periodo: 'dia',
  desde: '2026-07-29T05:00:00Z',
  hasta: '2026-07-30T04:59:59Z',
  ventas_netas_centavos: 18000000,
  ventas_efectivo_centavos: 12000000,
  ventas_fiado_centavos: 6000000,
  ventas_anuladas_centavos: 0,
  costo_de_lo_vendido_centavos: 11000000,
  margen_bruto_centavos: 7000000,
  ingresos_caja_centavos: 0,
  egresos_caja_centavos: 1500000,
  compras_proveedores_centavos: 8000000,
  resultado_operativo_centavos: 5500000,
  fuentes: {
    costo_de_lo_vendido: 'Costeado con el último costo actual de cada producto',
    compras_proveedores: 'Compras del período, informativas: no se restan del resultado',
  },
};

const forecastBase = {
  dias: 30,
  dias_con_datos: 12,
  saldo_actual_centavos: 230000,
  ventas_proyectadas_centavos: 40000000,
  cobros_fiado_proyectados_centavos: 9000000,
  egresos_proyectados_centavos: 15000000,
  saldo_proyectado_centavos: 34230000,
  fuentes: {
    cobros_fiado: 'Créditos con vencimiento en los próximos 30 días; los sin fecha no entran',
    ventas: 'Promedio de ventas en efectivo de los últimos 30 días',
  },
};
```

- [ ] **Paso 4: el componente.** Crear `numeros.component.ts`:

```ts
import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { TranslateModule } from '@ngx-translate/core';
import { formatearPesos } from 'domain';
import { LoadingSpinnerComponent, PageHeaderComponent } from 'ui-kit';
import { ForecastSalida, LineaDeDinero, PeriodoPyl, PyLSalida } from './contrato';
import { NumerosService } from './numeros.service';

/**
 * Mis números (ADR-006): el P&L del período y el forecast a 30 días.
 *
 * Dos reglas del ADR hechas pantalla: nada aquí pide datos nuevos al tendero
 * (todo sale de lo ya registrado), y cada bloque muestra sus `fuentes` —
 * «proyección explicada, no promesa». Las compras del período son línea
 * informativa que NO se resta del resultado, y la etiqueta lo dice.
 */
@Component({
  selector: 'vd-numeros',
  imports: [TranslateModule, MatButtonToggleModule, MatCardModule, PageHeaderComponent, LoadingSpinnerComponent],
  templateUrl: './numeros.component.html',
  styleUrl: './numeros.component.scss',
})
export class NumerosComponent {
  private readonly servicio = inject(NumerosService);

  readonly periodo = signal<PeriodoPyl>('dia');
  readonly pyl = signal<PyLSalida | null>(null);
  readonly forecast = signal<ForecastSalida | null>(null);
  readonly cargando = signal(true);
  readonly fallo = signal(false);

  readonly formatear = formatearPesos;

  /** Las líneas del P&L en el orden en que la tienda las cuenta. */
  readonly lineasPyl = computed<LineaDeDinero[]>(() => {
    const p = this.pyl();
    if (!p) {
      return [];
    }
    return [
      { clave: 'numeros.pyl.ventas_netas', centavos: p.ventas_netas_centavos },
      { clave: 'numeros.pyl.ventas_efectivo', centavos: p.ventas_efectivo_centavos },
      { clave: 'numeros.pyl.ventas_fiado', centavos: p.ventas_fiado_centavos },
      { clave: 'numeros.pyl.ventas_anuladas', centavos: p.ventas_anuladas_centavos },
      { clave: 'numeros.pyl.costo_vendido', centavos: p.costo_de_lo_vendido_centavos },
      { clave: 'numeros.pyl.margen_bruto', centavos: p.margen_bruto_centavos },
      { clave: 'numeros.pyl.ingresos_caja', centavos: p.ingresos_caja_centavos },
      { clave: 'numeros.pyl.egresos_caja', centavos: p.egresos_caja_centavos },
      { clave: 'numeros.pyl.compras', centavos: p.compras_proveedores_centavos },
      { clave: 'numeros.pyl.resultado', centavos: p.resultado_operativo_centavos },
    ];
  });

  readonly lineasForecast = computed<LineaDeDinero[]>(() => {
    const f = this.forecast();
    if (!f) {
      return [];
    }
    return [
      { clave: 'numeros.forecast.saldo_actual', centavos: f.saldo_actual_centavos },
      { clave: 'numeros.forecast.ventas', centavos: f.ventas_proyectadas_centavos },
      { clave: 'numeros.forecast.cobros', centavos: f.cobros_fiado_proyectados_centavos },
      { clave: 'numeros.forecast.egresos', centavos: f.egresos_proyectados_centavos },
      { clave: 'numeros.forecast.saldo_proyectado', centavos: f.saldo_proyectado_centavos },
    ];
  });

  constructor() {
    this.cargar();
  }

  cargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    let pendientes = 2;
    const alTerminar = (error: boolean) => {
      pendientes -= 1;
      if (error) {
        this.fallo.set(true);
      }
      if (pendientes === 0) {
        this.cargando.set(false);
      }
    };
    this.servicio.pyl(this.periodo()).subscribe({
      next: (pyl) => {
        this.pyl.set(pyl);
        alTerminar(false);
      },
      error: () => alTerminar(true),
    });
    this.servicio.forecast().subscribe({
      next: (forecast) => {
        this.forecast.set(forecast);
        alTerminar(false);
      },
      error: () => alTerminar(true),
    });
  }

  cambiarPeriodo(periodo: PeriodoPyl): void {
    if (periodo === this.periodo()) {
      return;
    }
    this.periodo.set(periodo);
    this.servicio.pyl(periodo).subscribe({
      next: (pyl) => this.pyl.set(pyl),
      error: () => this.fallo.set(true),
    });
  }

  /** Las fuentes como lista clave-valor, en el orden en que llegan. */
  fuentesDe(mapa: Record<string, string> | undefined): { nombre: string; texto: string }[] {
    return Object.entries(mapa ?? {}).map(([nombre, texto]) => ({ nombre, texto }));
  }
}
```

El `.html`: `vd-page-header`; `mat-button-toggle-group` con los tres períodos (`numeros.periodo.dia/semana/mes`, `(change)="cambiarPeriodo($event.value)"`); `vd-loading-spinner` mientras; bloque `fallo` con reintentar; tarjeta P&L: lista `dl` con `@for (linea of lineasPyl())` — la línea `compras` lleva el sufijo de la clave `numeros.pyl.compras` que YA declara «(informativo: no se resta)»— y la línea `resultado` destacada; debajo `@for (fuente of fuentesDe(pyl.fuentes))` con `<strong>{{ fuente.nombre }}:</strong> {{ fuente.texto }}`; tarjeta forecast: ídem con `lineasForecast`, el texto `numeros.forecast.base` (`"Proyección a {{dias}} días con {{diasConDatos}} días de datos"`) y sus fuentes.

- [ ] **Paso 5: la ruta y las claves.** En `app.routes.ts`, tras `cuaderno/creditos/:id`:

```ts
      {
        path: 'numeros',
        canActivate: [tenantGuard, permisoGuard('reporte:leer')],
        loadComponent: () =>
          import('./features/numeros/numeros.component').then((m) => m.NumerosComponent),
      },
```

En `public/i18n/es.json`:

```json
  "numeros": {
    "titulo": "Mis números",
    "subtitulo": "Lo que la tienda vendió, gastó y puede esperar",
    "fallo": "No pudimos cargar tus números.",
    "periodo": {
      "dia": "Hoy",
      "semana": "Esta semana",
      "mes": "Este mes"
    },
    "pyl": {
      "titulo": "Ganancias y pérdidas",
      "ventas_netas": "Ventas netas",
      "ventas_efectivo": "Ventas en efectivo",
      "ventas_fiado": "Ventas a fiado",
      "ventas_anuladas": "Ventas anuladas",
      "costo_vendido": "Costo de lo vendido",
      "margen_bruto": "Margen bruto",
      "ingresos_caja": "Ingresos manuales de caja",
      "egresos_caja": "Egresos de caja",
      "compras": "Compras a proveedores (informativo: no se resta)",
      "resultado": "Resultado operativo",
      "fuentes": "De dónde salen estos números"
    },
    "forecast": {
      "titulo": "Lo que viene (30 días)",
      "saldo_actual": "Saldo actual en caja y por cobrar",
      "ventas": "Ventas proyectadas",
      "cobros": "Cobros de fiado proyectados",
      "egresos": "Egresos proyectados",
      "saldo_proyectado": "Saldo proyectado",
      "base": "Proyección a {{dias}} días con {{diasConDatos}} días de datos reales.",
      "fuentes": "De dónde sale esta proyección"
    }
  },
```

- [ ] **Paso 6: verde y commit.**

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: verde — 2 del servicio + 5 del componente + todo lo anterior
npx ng lint vendi-tenant && npx ng build vendi-tenant
git add frontend/projects/vendi-tenant
git commit -m "Mis números en vendi-tenant: P&L por período con fuentes y forecast de 30 días explicado, solo para reporte:leer"
```

**Criterios de aceptación:** los 7 specs nuevos pasan; las `fuentes` de ambos reportes se renderizan (ADR-006); las compras se etiquetan como informativas; cambiar de período repide solo el P&L; la ruta exige `reporte:leer` y la sección no existe para otros roles.

---

## Tarea 10: El selector con nombres (`/elegir-negocio` consume `/tenants/mios`)

**Files:**
- Create: `frontend/projects/vendi-tenant/src/app/features/elegir-negocio/elegir-negocio.service.ts`
- Modify: `frontend/projects/vendi-tenant/src/app/features/elegir-negocio/elegir-negocio.component.ts` (+ `.html`)
- Modify: `frontend/projects/vendi-tenant/src/app/features/elegir-negocio/elegir-negocio.component.spec.ts`
- Modify: `frontend/projects/vendi-tenant/public/i18n/es.json`

**Interfaces:**
- Consume: `GET /tenants/mios` (Tarea 1) → `TenantMioSalida[]` (`components['schemas']['TenantMioSalida']` del cliente regenerado); `AuthService.organizaciones` (los alias del token — la fuente de verdad de lo elegible: `selectTenant` rechaza lo que no venga en el token).
- Produce: el selector muestra NOMBRES; el UUID queda como dato secundario. Cierra el pendiente conocido de Fase 0.

- [ ] **Paso 1: el spec, primero.** Reescribir `elegir-negocio.component.spec.ts` (montaje con sesión falsa + `HttpTestingController`):

```ts
describe('ElegirNegocioComponent — con nombres (Etapa 1.3)', () => {
  it('pide los negocios del token y los muestra por NOMBRE, con el id como dato secundario', async () => {
    const m = await montar([ORG_A, ORG_B]);
    m.http.expectOne(`${BASE}/tenants/mios`).flush([
      { id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' },
      { id: ORG_B, nombre: 'Panadería La Espiga', estado: 'activo' },
    ]);
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).toContain('Tienda Don Carlos');
    expect(visible).toContain('Panadería La Espiga');
  });

  it('un negocio del token que el endpoint no devolvió (eliminado) NO se ofrece', async () => {
    const m = await montar([ORG_A, ORG_B]);
    m.http.expectOne(`${BASE}/tenants/mios`).flush([
      { id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' },
    ]);
    m.fixture.detectChanges();
    const visible = texto(m.fixture);
    expect(visible).not.toContain('Panadería');
    // El alias huérfano tampoco se muestra como UUID: no hay nada que elegir ahí.
    expect(visible).not.toContain(ORG_B);
  });

  it('si el endpoint falla, cae a la lista de alias como antes (degradación honesta)', async () => {
    const m = await montar([ORG_A, ORG_B]);
    m.http.expectOne(`${BASE}/tenants/mios`).error(new ProgressEvent('error'));
    m.fixture.detectChanges();
    expect(texto(m.fixture)).toContain(ORG_A);
  });

  it('elegir llama selectTenant con el id y navega a /mi-negocio', async () => {
    const m = await montar([ORG_A, ORG_B]);
    m.http.expectOne(`${BASE}/tenants/mios`).flush([
      { id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' },
    ]);
    m.fixture.detectChanges();
    m.fixture.componentInstance.elegir(ORG_A);
    expect(m.auth.tenantId()).toBe(ORG_A);
    // La navegación entra a /mi-negocio, que pide su propio dato.
    await m.fixture.whenStable();
    m.http.expectOne(`${BASE}/tenants/me`).flush({ id: ORG_A, nombre: 'Tienda Don Carlos', estado: 'activo' });
    expect(TestBed.inject(Router).url).toBe('/mi-negocio');
  });
});
```

(El montaje replica el del `app.spec.ts` de la app — sesión falsa con dos organizaciones, `provideRouter(routes)` y `RouterTestingHarness` para el último caso— devolviendo también el `AuthService` como `m.auth`.)

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: fallo — no hay petición a /tenants/mios; el componente actual pinta alias
```

- [ ] **Paso 2: el servicio.** Crear `frontend/projects/vendi-tenant/src/app/features/elegir-negocio/elegir-negocio.service.ts`:

```ts
import { Injectable, inject } from '@angular/core';
import { ApiService } from 'data-access';
import type { components } from 'data-access';
import { Observable } from 'rxjs';

export type TenantMioSalida = components['schemas']['TenantMioSalida'];

/**
 * Cliente de `GET /api/v1/tenants/mios` (Tarea 1 del plan): los negocios del
 * token con nombre. Es la única llamada de la consola que sale SIN
 * `X-Tenant-Id` — el usuario todavía no ha elegido; el backend la sirve con
 * el token validado gracias a la excepción del middleware.
 */
@Injectable({ providedIn: 'root' })
export class ElegirNegocioService {
  private readonly api = inject(ApiService);

  mios(): Observable<TenantMioSalida[]> {
    return this.api.get<TenantMioSalida[]>('/tenants/mios');
  }
}
```

- [ ] **Paso 3: el componente.** Reescribir `elegir-negocio.component.ts`:

```ts
import { Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { Router } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthService } from 'auth';
import { ElegirNegocioService, TenantMioSalida } from './elegir-negocio.service';

/**
 * Selector de negocio para el dueño que tiene más de uno.
 *
 * Desde la Etapa 1.3 la lista muestra NOMBRES: `/tenants/mios` traduce los
 * alias del token a negocios vivos. El token sigue mandando — un alias que el
 * endpoint no devuelve (negocio eliminado entre el login y ahora) no se
 * ofrece, y `selectTenant` rechaza cualquier id que no venga en el token.
 * Si el endpoint falla, se degrada a la lista de alias como en Fase 0: feo,
 * honesto y funcional.
 */
@Component({
  selector: 'vd-elegir-negocio',
  imports: [TranslateModule, MatListModule, MatButtonModule, MatIconModule],
  templateUrl: './elegir-negocio.component.html',
  styleUrl: './elegir-negocio.component.scss',
})
export class ElegirNegocioComponent {
  private readonly auth = inject(AuthService);
  private readonly servicio = inject(ElegirNegocioService);
  private readonly router = inject(Router);

  readonly organizaciones = this.auth.organizaciones;

  /** null mientras carga; lista vacía si el endpoint falló (→ degradación). */
  readonly negocios = signal<TenantMioSalida[] | null>(null);

  constructor() {
    this.servicio.mios().subscribe({
      next: (mios) => {
        // Defensa en profundidad: solo se ofrecen ids que están en el token.
        const elegibles = new Set(this.organizaciones());
        this.negocios.set(mios.filter((negocio) => elegibles.has(negocio.id)));
      },
      error: () => this.negocios.set([]),
    });
  }

  elegir(alias: string): void {
    if (!this.auth.selectTenant(alias)) {
      return;
    }
    this.router.navigate(['/mi-negocio']).catch((error: unknown) => {
      console.error('No se pudo abrir «Mi negocio» tras elegir el negocio.', error);
    });
  }

  cerrarSesion(): void {
    this.auth.logout();
  }
}
```

y el `.html`:

```html
<section class="vd-elegir">
  <h1>{{ 'elegir.titulo' | translate }}</h1>

  @if (organizaciones().length === 0) {
    <p>{{ 'elegir.sin_negocios' | translate }}</p>
    <button matButton="filled" type="button" (click)="cerrarSesion()">
      {{ 'layout.cerrar_sesion' | translate }}
    </button>
  } @else {
    <p>{{ 'elegir.descripcion' | translate }}</p>
    @if (negocios() === null) {
      <p>{{ 'elegir.cargando' | translate }}</p>
    }
    <mat-action-list>
      @if ((negocios() ?? []).length > 0) {
        @for (negocio of negocios(); track negocio.id) {
          <button mat-list-item type="button" (click)="elegir(negocio.id)">
            <mat-icon matListItemIcon aria-hidden="true">storefront</mat-icon>
            <span matListItemTitle>{{ negocio.nombre }}</span>
            <span matListItemLine><code>{{ negocio.id }}</code></span>
          </button>
        }
      } @else if (negocios() !== null) {
        <!--
          Degradación: /tenants/mios falló. La lista de alias de Fase 0 — fea,
          honesta y funcional; elegir sigue siendo posible.
        -->
        @for (alias of organizaciones(); track alias) {
          <button mat-list-item type="button" (click)="elegir(alias)">
            <mat-icon matListItemIcon aria-hidden="true">storefront</mat-icon>
            <span matListItemTitle><code>{{ alias }}</code></span>
          </button>
        }
      }
    </mat-action-list>
  }
</section>
```

- [ ] **Paso 4: las claves.** En `public/i18n/es.json`, dentro de `"elegir"`:

```json
    "cargando": "Buscando tus negocios…",
```

- [ ] **Paso 5: verde y commit.**

```bash
cd frontend && npm run build:libs && npx ng test vendi-tenant --watch=false
# Esperado: verde — los 4 casos nuevos + el resto de la suite
npx ng lint vendi-tenant && npx ng build vendi-tenant
git add frontend/projects/vendi-tenant
git commit -m "El selector de negocio muestra nombres: /tenants/mios con filtro del token y degradación honesta a los alias"
```

**Criterios de aceptación:** los 4 specs nuevos pasan; el alias que el endpoint no devuelve no se ofrece; la degradación por fallo muestra los alias; `selectTenant` sigue siendo la única puerta (el token manda).

---

## Tarea 11: Cierre — gate de la Etapa 1.3 (pista web), `docs/estado.md` y verificación final

**Files:**
- Modify: `docs/estado.md` (sección nueva de la pista web, con fecha de corte y evidencia comando+salida)

**NO se toca:** `docs/api/openapi-fase0.json` salvo lo ya regenerado en la Tarea 1 (el gate lo verifica), `docs/api/README.md` salvo la fila de la Tarea 1, el backend salvo la Tarea 1, los workflows de CI, los budgets de `vendi-tenant`.

- [ ] **Paso 1: ejecutar el gate completo de la pista web:**

```bash
cd backend && uv run pytest -q -m 'not integration'
# Esperado: verde
uv run pytest -q -rs -m integration
# Esperado: verde, con los 4 tests nuevos de /tenants/mios (requiere el stack)
cd ../frontend
npm ci --no-audit --no-fund
npm run build:libs
npx ng test --watch=false
# Esperado: verde en los 9 proyectos; los specs nuevos por feature corren
npx ng lint
# Esperado: sin errores en los 9 proyectos (fronteras incluidas)
npm run format:check
# Esperado: sin diferencias (si prettier marca archivos nuevos: npm run format)
npx ng build vendi-tenant --configuration production
# Esperado: build de producción verde, SIN relajar budgets (700 kB / 1 MB)
cd ..
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git diff --exit-code
# Esperado: salida 0 — contrato y cliente están sincronizados tras la Tarea 1
```

Gate de la pista (del plan maestro §Etapa 1.3), a verificar ítem a ítem:
- [ ] `ng test` verde en los 9 proyectos con specs nuevos por feature (caja, catálogo, inventario, cuaderno, números, elegir-negocio, permisoGuard, avisos).
- [ ] `GET /tenants/mios` entregado con su excepción de middleware y sus 4 tests de integración; el selector muestra nombres.
- [ ] `nucleo/sesion.ts` y `layout/avisos.component.ts` deduplicados hacia libs (`auth` y `ui-kit`); las tres apps compilando sobre la superficie pública.
- [ ] `/sin-permiso` creada (ítem del plan maestro resuelto por «crearla», decisión 3).
- [ ] El E2E Playwright del flujo de dinero queda para el gate posterior con el stack levantado (NO es de esta entrega, igual que en la pista móvil).
- [ ] Budgets de bundle no relajados; CI sin cambios.

- [ ] **Paso 2: actualizar `docs/estado.md`.** Añadir una sección «Consola del negocio en vendi-tenant (Fase 1, Etapa 1.3, pista web)» con: fecha de corte; qué se entregó (las cinco features con sus permisos por rol; `/tenants/mios` con la excepción del middleware; las dos deduplicaciones; `/sin-permiso`); el alcance honesto (sin historial de compras ni de ajustes, sin ancla `fecha` en el P&L, sin `ultimo_costo` en catálogo, sin E2E nuevo — gate posterior con el stack); y **al lado de cada afirmación el comando que la demuestra** con su salida pegada (regla del documento: no promete nada que un comando no demuestre).

- [ ] **Paso 3: verificar que no queda deuda nueva.** Los tres pendientes que este plan cerró (`/elegir-negocio` con UUIDs, `sesion.ts`/`avisos` duplicados) nunca tuvieron número D: vivían en el plan maestro. No hay D nueva que registrar — lo recortado en la decisión 9 son pantallas futuras, no deuda (el backend las soporta; nadie prometió que existieran). Si al ejecutar el plan aparece cualquier desviación del contrato o del alcance, se registra en `docs/deuda-tecnica.md` con el formato vigente ANTES de este commit.

- [ ] **Paso 4: commit de cierre**

```bash
git add docs/estado.md
git commit -m "Pista web de la Etapa 1.3 cerrada: consola del negocio con caja, catálogo, inventario, cuaderno y números por rol, con evidencia en estado"
```

---

## Superficie de ataque para QA — consola del negocio (permisos, dinero, idempotencia, multi-tenant)

Para el agente de QA adversarial de la Etapa 1.4 (agente distinto del implementador; su KPI son hallazgos). Los escenarios marcados (firmado) ya tienen test que los fija: verificarlos, no «redescubrirlos»; el hallazgo sería que el test miente. Todo lo que diga «con el stack» exige el backend levantado: son candidatos naturales del E2E del flujo de dinero.

- **Permisos (la superficie principal):** quitar un permiso en Keycloak con la sesión viva y recargar — el menú se recalcula con el token NUEVO, pero ¿y el token viejo cacheado? (hasta el refresco, la UI muestra lo que el token viejo dice y el backend 403: verificar que el aviso es decente); entrar a `/numeros` escribiendo la URL con un token de cajero (permisoGuard → `/sin-permiso` — firmado; verificar que NO hay bucle si el usuario tampoco puede volver a donde estaba); `/sin-permiso` con un rol que no tiene NADA (almacenista sin `cliente:gestionar` que va a `/cuaderno`: ¿el botón «Volver a mi negocio» siempre existe?); un token con `*` (superusuario) entra a todas las rutas (firmado en el guard — verificar con un usuario real); `efectivo_esperado` null para el cajero: abrir las herramientas de desarrollo y comprobar que la cifra NO está en el DOM ni en la respuesta (no es cosmética — el backend la omite; si aparece en el JSON, eso es hallazgo del BACKEND); el historial de arqueos nunca se pide sin `caja:cerrar` (firmado por `http.verify`; verificar en la pestaña de red con un cajero real).
- **Caja:** dos pestañas abriendo caja a la vez (409 `caja_ya_abierta` → la segunda refresca y opera sobre la abierta — firmado el manejo; provocarlo de verdad con el stack); cerrar en una pestaña y seguir registrando movimientos en otra (el movimiento cae en la NUEVA sesión implícita o es 409 — fijar el comportamiento real y documentarlo); doble clic en «Cerrar con este conteo» (candado `enviando` — firmado; verificar que no hay atajo por teclado con Enter); arqueo con esperado NEGATIVO (D-26 abierta: la pantalla lo muestra tal cual, sin juicio — verificar que el badge de diferencia no hace nada absurdo con negativos grandes); movimiento de 1 peso y de $999.999.999 (límites del input numérico — ¿el `Math.round(pesos*100)` desborda algo? no debería, verificar); categoría `retiro_dueno` registrada por el cajero: el backend la oculta a quien no cierra (fix `c49c4c0` en el listado) — con el stack, verificar que el cajero no la ve ni en movimientos ni en el arqueo.
- **Catálogo e inventario:** EAN duplicado (409 con mensaje del backend — firmado; verificar que el texto es el del backend y no `[object Object]`); borrar un producto y recrearlo con el mismo EAN (el borrado libera el EAN — con el stack); crear producto con `precio 0` y con nombre de 160 caracteres (no rompe el render); granel con coma y con punto en mínimo y en ajuste (firmado); ajuste de `0` (la UI no lo manda: `miliDeCantidad` lanza y el diálogo no cierra — firmado; intentar colarlo por REST con el stack: ¿el backend lo rechaza?); merma mayor que el stock (stock negativo legítimo: se pinta `-2.000` como dato — firmado el render; con el stack verificar el nivel `agotado`); ajuste sin red (online-obligatorio: el aviso de conexión sale del interceptor — verificar que el formulario no pierde lo escrito... LO PIERDE: el diálogo se cerró. Fijar y documentar; si duele, es mejora futura, no de esta entrega); compra con el selector que solo ofrece la página visible de stock (alcance declarado — con 200 productos, el que no está en la página no se puede comprar: HALLAZGO PROBABLE de UX, registrarlo con su prioridad); compra con costo 0 (D-25: el P&L mostrará margen del 100 % — verificar que el P&L lo hace visible y registrar si la tienda lo pisa).
- **Cuaderno:** abono que excede el saldo (422 `abono_excede_saldo`: el mensaje del backend llega por el interceptor — verificar el texto); abono en efectivo sin caja abierta (409 `caja_sin_sesion_abierta`: ¿el mensaje guía al tendero? — verificar y, si es críptico, registrar); abono a crédito `saldado` (botón deshabilitado en UI — forzarlo por REST con el stack: 409 `credito_no_abonable`); reprogramar un `vencido` a futuro (vuelve a `vigente` — con el stack, verificar que la tira de vencidos baja en uno); quitar la fecha (sin recordatorio, declarado en pantalla — firmado); `wa.me` con teléfono raro guardado a mano en la ficha del cliente (¿el backend sanea? si el link queda roto, documentar); el cupo excedido es badge y nunca bloquea (firmado — verificar que NO hay ningún `disabled` condicionado por cupo en el flujo de fiar desde el POS, que es donde se fía).
- **Números:** P&L del día sin ventas (ceros y fuentes, sin NaN — con el stack); forecast con `dias_con_datos: 0` (¿la pantalla dice algo sensato? fijar; la frase «con 0 días de datos reales» ya es honesta, verificar que se lee); las fuentes llegan en español del backend — si algún día llegan en inglés se pintan tal cual (contrato implícito: documentarlo); cambiar de período rápido tres veces (tres peticiones en vuelo — ¿gana la última o la más lenta? RACE REAL sin `switchMap`: el último `subscribe` que responde pisa `pyl()`. PROVOCARLO con red lenta; si responden fuera de orden, la pantalla muestra el período A con datos del B — registrar como hallazgo con su arreglo: cancelar la anterior o etiquetar la respuesta).
- **Multi-tenant y sesión:** dueño con dos negocios que cambia de negocio a mitad de una pantalla (los datos cargados son del tenant ANTERIOR hasta recargar — `cambiarDeNegocio` navega a `/elegir-negocio` y al elegir se vuelve a `/mi-negocio`, pero ¿los guards limpian las pantallas intermedias? cada feature carga en su constructor, así que al navegar se recarga: verificar con el stack que NO queda una tabla del tenant A visible tras elegir el B); `/tenants/mios` con un negocio SUSPENDIDO en la lista (llega con `estado: 'suspendido'` — elegirlo lleva al 403 `tenant_suspendido` de `/tenants/me`: verificar que el aviso es el de siempre y que el usuario puede volver al selector; ¿debería el selector marcar el suspendido? mejora futura, documentar); token con una sola organización (nunca ve el selector — firmado en Fase 0); token sin organizaciones (pantalla `sin_negocios` — firmado en Fase 0; el endpoint devuelve `[]` — firmado en backend).
- **Idempotencia web:** reintentar el POST de ajuste/abono/movimiento/compra con el mismo `id` por REST (el servidor responde lo grabado sin duplicar — con el stack); cerrar la pestaña a mitad del POST de cierre y reabrir (la sesión quedó cerrada con el primer conteo; la pantalla muestra el arqueo del historial — verificar).
- **Fronteras y contrato:** `import ... from 'dexie'` o `@capacitor/*` en `vendi-tenant` (lint rojo — la frontera ya existía); `ui-kit` importando `data-access` tras la Tarea 3 (grep firmado — sondar una vez más); codegen con deriva (CI rojo — firmado por `frontend-contratos`); el bundle de producción de `vendi-tenant` (¿las features quedaron en chunks lazy? revisar el análisis de chunks: si el bundle inicial se acerca al budget de 1 MB, registrarlo ANTES de pedir relajarlo — los budgets no se relajan sin ADR).

---

## Self-Review

- **Cobertura del spec:** plan maestro §Etapa 1.3 pista web — features caja/inventario/fiado sobre el cliente generado → Tareas 5, 6, 7, 8 (catálogo separado de inventario, como los módulos del backend); reportes → Tarea 9; `GET /tenants/mios` → Tareas 1 y 10; deduplicación de `sesion.ts` y `avisos.component.ts` → Tareas 2 y 3; `roleGuard` → `/sin-permiso` → Tareas 2 y 4 (resuelto por «crearla» + guard nuevo, decisión 3). ADR-023 (ocultar por permiso, matriz por rol) → Tareas 2, 4 y los `*vdHasPermission` de cada feature. ADR-019 (EAN opcional, granel, IVA 0/5/19, borrado lógico) → Tarea 6. ADR-020 (stock negativo como dato, ajuste online con motivo, proveedor texto libre, total en servidor) → Tarea 7. ADR-021 (una sesión, arqueo congelado, categorías cerradas, motivo obligatorio, esperado solo para quien cierra) → Tarea 5. ADR-006 (fuentes en pantalla, proyección explicada) → Tarea 9. ADR-022 (abono contra el crédito tocado, cupo advertencia, `wa.me`, sin fecha = sin recordatorio declarado) → Tarea 8. Encargo (los 7 puntos) → Tareas 5, 6-7, 8, 9, 1+10, 2-4, y los specs de cada tarea sin E2E nuevo. Gate → Tarea 11.
- **Placeholders:** ninguno. Las tareas llevan código completo o, en los tres «copiar la forma de» declarados (Tarea 6 Paso 5: `catalogo.component.ts` contra `tenants.component.ts` de vendi-admin; Tarea 8 Paso 3: los dos diálogos contra `ProductoDialogoComponent` de la Tarea 6; Tarea 4 Paso 1: el ajuste de `preparar`), el archivo fuente exacto y la lista exacta de diferencias — el mismo estándar que el plan de la pista móvil declaró en su self-review. Los conteos de specs son los escritos: 4 (backend mios) + 5 (permisoGuard) + 5 (avisos) + 4 (esqueleto) + 8+8 (caja) + 5+6 (catálogo) + 4+6 (inventario) + 7+4+6 (cuaderno) + 2+5 (números) + 4 (elegir) = 83 specs nuevos; si el ejecutor añade casos, ajusta el número (los comandos de gate son de suite, no de conteo).
- **Consistencia de tipos/contratos:** todos los nombres de schemas se verificaron contra `frontend/projects/libs/data-access/src/lib/api-client/index.ts` en disco (los reales son `SesionAbrir`/`SesionCerrar`/`SesionActualSalida`/`MovimientoCrear`/`ArqueoConDesglose`, `ProductoCrear`/`ProductoActualizar`, `AjusteCrear`/`AjusteCreado`/`StockSalida` — `nivel` string libre, no enum—, `CompraCrear`/`CompraItemEntrada`, `ClienteCrear`/`ClienteEditar`/`ClienteConSaldo`, `CreditoResumenSalida`/`CreditoDetalleSalida`/`CreditoReprogramar`/`AbonoCrear`, `PyLSalida`/`ForecastSalida`); los paths y query params salen del mismo archivo (`solo_alertas`, `estado`, `q`, `sesion_id`, `periodo`); los permisos son los strings exactos de `policies.py` (`caja:leer`, `caja:abrir`, `caja:cerrar`, `caja:movimiento`, `producto:leer`, `producto:editar`, `inventario:ajustar`, `compra:crear`, `cliente:gestionar`, `fiado:crear`, `fiado:abonar`, `reporte:leer`) verificados contra los routers del backend; los códigos de error usados (`caja_ya_abierta`, `caja_ya_cerrada`, `caja_sin_sesion_abierta`, `codigo_barras_duplicado`, `abono_excede_saldo`, `credito_no_abonable`, `credito_no_editable`, `limite_de_productos_alcanzado`, `tenant_no_especificado`) existen en `docs/api/README.md`; `TenantMioSalida` NO existe todavía — lo crea la Tarea 1 y la Tarea 10 lo consume del cliente regenerado, en ese orden; el backend de la Tarea 1 se verificó contra `middleware.py` (la trampa del 400), `tenants/router.py` (una sola ruta hoy), `service.py` (patrón `select` + sesión de plataforma exigida por el constructor), `ayudas.py` (`usuario_de_negocio`) y `test_tenants_crud.py` (patrón de integración).
- **Riesgos conocidos y declarados:** (1) la Tarea 1 toca el middleware de tenant — la mitigación es su test de integración y la suite completa en el gate, pero es el cambio de mayor blast radius del plan: revisarla con lupa en el code review; (2) la regeneración del congelado exige el stack levantado: si el entorno del ejecutor no lo tiene, la Tarea 1 se bloquea hasta tenerlo (no se edita `openapi-fase0.json` a mano, jamás); (3) el selector de productos de la compra solo ofrece la página visible de stock — declarado en la Tarea 7 Paso 4 y en la superficie de QA como hallazgo probable de UX; (4) `cambiarPeriodo` del P&L no cancela la petición anterior — race real, declarada en la superficie de QA con su arreglo sugerido; (5) el diálogo de ajuste pierde lo escrito si la red cae (online-obligatorio) — documentado en la superficie; (6) `/tenants/mios` devuelve también los suspendidos (con su estado): elegir uno lleva al 403 `tenant_suspendido` ya existente — flujo verificado en la superficie, marcado «suspendido» en el selector como mejora futura; (7) los specs de componente dependen de `Intl` (formato de pesos): los asertos evitan el símbolo exacto por el espacio duro de ICU — quien añada asertos de formato, que siga esa regla; (8) los ids de idempotencia se generan al abrir el diálogo: si el usuario abre, no envía, y vuelve a abrir, el id cambia — correcto (una intención = un id), pero un doble envío del MISMO diálogo reutiliza el id y el servidor responde el no-op: es la propiedad buscada, no un bug.
