# Arquitectura de Vendi

> Documento vivo. Cada etapa del plan de Fase 0 añade su sección; el arquitecto
> lo consolida al cerrar cada etapa.

## Cosecha desde BaseSaaS

El principio: la cosecha se hace **archivo por archivo**, nunca por copia masiva
del árbol. Esta sección registra qué vino de dónde y con qué cambio, porque los
LOC del spec eran estimación y lo que vale es la medición final.

> **Ratificación del arquitecto (cierre de la Etapa 3), criterio de
> integración (4).** El grep literal
> `grep -rn 'base_saas\|search_path\|tenant_slug' backend/libs frontend/projects/libs`
> devuelve 27 coincidencias, todas en prosa de procedencia (docstrings y
> comentarios que este mismo documento exige por el criterio (5)); ninguna es
> código. En `frontend/projects/libs` da vacío. Se ratifica que el criterio se
> considera cumplido en su intención —ningún resto *funcional* de BaseSaaS— y
> que el mecanismo de defensa vigente es
> `backend/tests/test_candado_cosecha.py`, que tokeniza y distingue código de
> prosa. Punto ciego aceptado y anotado: ese candado solo cubre `backend/`;
> las libs del frontend quedan defendidas por el lint de fronteras y por este
> grep en cada cierre de etapa.

### Frontend — Etapa 3 (libs `domain`, `data-access`, `auth`, `ui-kit`)

Origen: `/Users/maoherran/BaseSaaS/frontend/projects/{ui-core,ui-components,ui-dataforms,ui-theme}`.

| Destino en Vendi | Origen en BaseSaaS | Cambio |
| --- | --- | --- |
| `domain/src/lib/models/api-response.model.ts` | `ui-core/src/lib/models/api-response.model.ts` | Se elimina `PaginatedResponse` (ya estaba `@deprecated`); `Tenant` se muda a su propio archivo; se añade `ApiError` |
| `domain/src/lib/models/user.model.ts` | `ui-core/src/lib/models/user.model.ts` + el `UserProfile` embebido en `ui-core/src/lib/auth/auth.service.ts` | Se fusionan los dos perfiles duplicados y se conserva el derivado del token; el slug de tenant pasa a `tenantId: string \| null` |
| `domain/src/lib/models/tenant.model.ts` | (nuevo) | Alineado con el contrato congelado en `docs/api/openapi-fase0.json`: `{id, nombre, estado, kc_org_id?, created_at?}`; `plan` opcional porque la API de Fase 0 no lo emite |
| `domain/src/lib/reglas/tenant.reglas.ts` | (nuevo) | `esIdDeTenant` (alias = UUID), `esTenantOperativo`, `esEstadoVisible` |
| `data-access/src/lib/api.service.ts` | `ui-core/src/lib/services/api.service.ts` | Sin cambios de fondo; opciones renombradas al español |
| `data-access/src/lib/interceptors/correlation-id.interceptor.ts` | ídem en `ui-core` | Sin cambios de fondo |
| `data-access/src/lib/interceptors/error.interceptor.ts` | ídem en `ui-core` | Mensajes traducidos por clave (`errores.*`); `status 0` deja de caer en el genérico; nunca devuelve `[object Object]` ni HTML del proxy |
| `data-access/src/lib/notificaciones/notificador.service.ts` | `ui-core/src/lib/services/notification.service.ts` | **Reescrito**: fuera `WebSocketService` (excluido de la cosecha) y fuera `MatSnackBar` (metía Material en la capa HTTP). Queda una cola de avisos como señal; quien pinta es la app |
| `data-access/src/lib/services/feature-flags.service.ts` | ídem en `ui-core` | La petición va con `SILENCIAR_AVISO_ERROR`: en Fase 0 el endpoint no existe |
| `data-access/src/lib/i18n/*` | `ui-core/src/lib/i18n/translate-initializer.ts` | **Reescrito**: cargador resiliente + catálogo empotrado + `traducir()`. El original resolvía la promesa en el `error` del `subscribe`, pero las apps de Vendi (Etapa 2) usaban `firstValueFrom` sin `catch` y quedaban fail-hard |
| `auth/src/lib/auth.service.ts` | `ui-core/src/lib/auth/auth.service.ts` | Claim `organization` en lugar del slug; `scope=organization:*` fijo; señales `organizaciones`/`tenantId`/`roles`; `selectTenant`; `refrescar()` público. Se conservan intactos los guards de refresco re-entrante y de logout doble |
| `auth/src/lib/token.ts` | (nuevo) | Parser del claim en sus **dos** formas (lista y mapa) con validación de UUID |
| `auth/src/lib/auth.guard.ts` | `ui-core/src/lib/auth/auth.guard.ts` | Se quita el `Router` inyectado y no usado; se añade `tenantGuard` |
| `auth/src/lib/auth.interceptor.ts` | ídem en `ui-core` | `X-Organization: <slug>` → `X-Tenant-Id: <uuid>` |
| `auth/src/lib/has-permission.directive.ts` | ídem en `ui-core` | Prefijo `bsHasPermission` → `vdHasPermission` |
| `auth/src/lib/keycloak.fake.ts` | ídem en `ui-core` | Token por defecto con claim `organization`; mandos nuevos (`updateManual`, `setOrganizaciones`, `ultimasOpcionesDeInit`) |
| `ui-kit/src/lib/theme/*` | `ui-theme/src/styles/*` | Prefijo `--bs-` → `--vd-`; superficies y textos derivados de `--mat-sys-*` en vez de una paleta paralela; fuera el acento por tenant (no hay white-label) |
| `ui-kit/src/lib/components/*` (8) | `ui-components/src/lib/*` | Prefijo de selector `bs-` → `vd-`; textos a claves de ngx-translate; API de botones de Material 3 (`matButton`) |
| `ui-kit/src/lib/forms/*` | `ui-dataforms/src/lib/*` | Fuera los tipos de campo `lookup` (exigía HTTP) y `color` (era para branding); mensajes de validación a claves |
| `ui-kit/src/lib/layout/full-layout/*` | `ui-core/src/lib/layouts/full-layout/*` | **Presentacional**: sin `AuthService`, sin selector de idioma, sin campana empotrada; ranuras `[slot=acciones]` y `[slot=aviso-superior]` |
| `ui-kit/src/lib/notifications/*` | `ui-core/src/lib/components/notifications-badge/*` | **Presentacional**: se elimina el `ApiService` que hacía `GET /notifications` en `ngOnInit` |
| `ui-kit/src/lib/impersonation/impersonation-banner.*` | ídem en `ui-core` | **Presentacional** (`actor` por input). No se cablea: en Fase 0 no hay suplantación. **Decisión del arquitecto (cierre de Etapa 3): se queda.** Es presentación pura sin ningún camino que lo alimente (no reintroduce el agujero del cambio de alcance 9) y retirarlo hoy solo obligaría a re-cosecharlo en Fase 1, cuando la suplantación se rediseñe con aislamiento por tenant. Prohibido cablearlo hasta entonces |

**No portado**, con motivo:

| Archivo de BaseSaaS | Por qué no |
| --- | --- |
| `ui-core/realtime/websocket.service.ts` | Excluido por el plan; no hay canal realtime en Fase 0 |
| `ui-core/tenant/freeze.service.ts`, `frozen-banner`, `when-not-frozen.directive` | El congelado de workspace no existe en Vendi; la suspensión es app-level y responde 403 |
| `ui-core/components/idp-logos/*` | No hay IdPs externos |
| `ui-core/branding/*` | Vendi no es white-label |
| `ui-core/impersonation/impersonation.service.ts` | El rol `impersonation` se retiró de la cuenta de servicio en la Etapa 2 |
| `ui-core/tenant/tenant.service.ts` | Resolvía el tenant por HTTP; ahora sale del claim del token |
| `ui-core/directives/feature-flag.directive.ts` | El módulo `feature_flags` es backlog; el servicio sí se cosecha porque falla cerrado |
| `ui-core/i18n/locale-storage-key.token.ts` | Un solo idioma en Fase 0 |
| `ui-components` — sin excepciones | Los 8 componentes se cosecharon completos |

### Backend — Etapa 3 (`vendi-core`)

Origen: `/Users/maoherran/BaseSaaS/backend/base_saas/src/base_saas/`.
Destino: `backend/libs/vendi-core/src/vendi_core/`.

Todo lo cosechado lleva el renombre `base_saas` → `vendi_core` en imports y
`basesaas_*` → `vendi_*` en nombres de métricas de Prometheus.

#### Cosecha sin cambios de fondo

| Paquete | Cambio |
| --- | --- |
| `middleware/` (7 archivos) | Solo renombres |
| `config/`, `errors/`, `cache/`, `logging/`, `models/` | Solo renombres. `errors/domain.py` gana `ExternalServiceError` (502) para que un Keycloak caído no suba como traza cruda; `models/pagination.py` pasa a genéricos de PEP 695 |
| `storage/` | Solo renombres. **Sin `policy.py`** |
| `files/` | Solo renombres. `File` hereda `TenantModel`, que ahora aporta `tenant_id` |
| `tracing/` | `tenant_slug_var`/`bind_tenant_slug` → `tenant_id_var`/`bind_tenant_id` |
| `events/service.py` | `tenant_slug: str` → `tenant_id: uuid.UUID \| None`; clave de enrutado `plataforma.<evento>` cuando no hay negocio |
| `mail/` | Se portan **solo** `system_mailer.py`, `mime.py` y `providers/`. Fuera el respaldo de HTML a texto plano con `html2text` (dependencia no portada): la falta de plantilla `.txt.j2` pasa a ser error |

#### Cosecha con adaptación real

| Paquete | Cambio |
| --- | --- |
| `audit/events.py` | `tenant_slug: str` → `tenant_id: uuid.UUID \| None`. `None` = evento de plataforma. Muere `actor` (claim `act` de RFC 8693): sin suplantación no hay camino que lo produzca |
| `audit/models.py` | Columna `tenant_slug String(64)` → `tenant_id UUID NULL`; índice `ix_audit_events_tenant_timestamp` recolocado; fuera `{"schema": "public"}` |
| `audit/decorator.py` | Lee `request.state.tenant.tenant_id`; fuera el bloque que publicaba `actor` en los metadatos. Lo vigilan `test_auditoria_decorator.py::test_el_decorador_no_publica_ningun_actor_de_suplantacion` y su complemento sobre `UserContext`, para que no vuelva por copia-pega |
| `audit/service.py` | Persiste `tenant_id` |
| `messaging/outbox.py` | Fuera `{"schema": "public"}`; `outbox_messages` gana `tenant_id UUID NULL`; `OutboxService.enqueue(..., tenant_id=None)`; `__mapper_args__ = {"eager_defaults": False}` para que el `INSERT` no lleve `RETURNING` (ver la matriz de privilegios) |
| `jobs/types.py` | `JobContext`: `tenant_slug`/`tenant_schema` → `tenant_id: uuid.UUID \| None` |
| `jobs/scheduler.py` | El scope `tenant` itera `tenant_id` vía callable inyectado `list_active_tenant_ids` (no un `SELECT` cableado a `public.tenants`) y **siembra `current_tenant_id` alrededor de todo el bucle de reintentos**. Se elimina `last_exc`, que ya era código muerto |
| `retention/policies.py` | `PUBLIC_POLICIES` → `PLATFORM_POLICIES`. De 13 políticas quedan 3: las otras 10 apuntaban a tablas de módulos fuera de Fase 0 y habrían producido un warning diario permanente |
| `retention/runner.py` | Fuera `set_search_path_sql`. Usa la sesión de plataforma, siembra `current_tenant_id` por negocio (para los pre-purge hooks) y acota el `DELETE` con `AND tenant_id = :tenant_id`, porque `BYPASSRLS` hace que la policy no filtre en esa sesión. **Además**: cada política corre dentro de un `SAVEPOINT` y los fallos se acumulan en la fila de auditoría (antes, un fallo dejaba la transacción abortada y todas las políticas siguientes devolvían 0 en silencio con la pasada registrada como éxito) |
| `auth/context.py` | `tenant_slug` → `organizations: dict[str, str]` (alias → id). Muere `actor` |
| `auth/jwt.py` | Nace `allowed_realms` (obligatorio, sin lista vacía) y `parsear_claim_organization`, que acepta **lista y mapa** |
| `auth/dependencies.py` | Fuera el camino de API keys (`sk_live_*`) y su resolver. `get_current_user` reutiliza la validación del middleware solo si el token es byte a byte el mismo |
| `auth/policies.py` | Catálogo reescrito para Fase 0 (6 permisos). Roles de negocio `dueno`/`cajero`/`almacenista`; los dos últimos con permisos **vacíos** hasta el spec del MVP |
| `auth/ssl.py` | Solo renombres |
| `auth/keycloak_admin.py` | **Reescrito.** De 797 LOC a dos clases sobre `client_credentials`. Ver abajo |
| `db/base.py` | `TenantModel` gana `tenant_id` **y** el índice `ix_<tabla>_tenant_id` por defecto. Nacen `TABLAS_DE_PLATAFORMA` y `verificar_indices_de_tenant()` |
| `db/engine.py` | El hook de checkout pasa de `RESET search_path` a `SET vendi.tenant_id = ''` |
| `db/session.py` | **Reescrito.** `create_session_factory` emite el GUC en `after_begin` sobre una subclase de `Session` por fábrica; nace `create_platform_session_factory` (sin listener) y `es_sesion_de_plataforma()` |
| `db/rls.py` | **Nuevo.** `enable_rls`/`disable_rls` con el SQL exacto que fijó el spike 1.2 |
| `tenant/context.py` | **Reescrito.** `current_tenant_id: ContextVar[UUID \| None]` + `TenantContext` |
| `tenant/middleware.py` | **Reescrito.** Ver abajo |

#### No portado, con motivo

| Archivo de BaseSaaS | Por qué no |
| --- | --- |
| `storage/policy.py` | Política de bucket-por-tenant. Fase 0 usa un bucket por región con prefijo `{tenant_id}/` (ADR-016): decenas de miles de buckets del plan gratuito no escalan en S3, y con bucket compartido el aislamiento lo da el prefijo y la firma de URLs |
| `tenant/schema.py` | `tenant_schema_name`, `set_search_path_sql`. No hay schema por inquilino |
| `tenant/freeze_middleware.py` | El congelado de workspace no existe; la suspensión es app-level: la comprueba la dependencia `exigir_negocio_activo` contra la columna `estado` de `tenants`, con cache Redis de 60 s |
| `auth/passwords.py` | Las contraseñas las guarda Keycloak; la API nunca las ve |
| `mail/mailer.py` | Mailer por tenant: escribía en `email_messages` dentro del schema del inquilino |
| `mail/renderer.py` | Plantillas en base de datos, editables por inquilino. Aquí el catálogo es Jinja en el paquete, versionado con el código |
| `mail/tracking.py` | Píxeles de apertura y reescritura de enlaces. Vendi no rastrea aperturas |
| `mail/secrets.py` | Credenciales SMTP cifradas por inquilino. Hay unas, las de la plataforma |
| `keycloak_admin`: `create_realm`, `delete_realm`, `set_realm_enabled` | No hay realm por negocio. **Consecuencia: no existe "deshabilitar el realm" por tenant; la suspensión es un estado en la tabla `tenants`** |
| `keycloak_admin`: `ensure_identity_provider`, `delete_identity_provider` | Sin IdPs externos en Fase 0 |
| `keycloak_admin`: `create_service_account_client`, `ensure_platform_admin_client` | Los clientes vienen del realm como código. Además la cuenta de servicio no tiene `manage-clients` (medido: 403) |
| `keycloak_admin`: `exchange_token_for_user` | Suplantación (RFC 8693). El rol `impersonation` se retiró en la Etapa 2 por ser un agujero de aislamiento multi-tenant en realm regional. El permiso `impersonate:user` tampoco está en `policies.py` |

#### `keycloak_admin.py` y `keycloak_aprovisionamiento.py`: dos clases en dos módulos (cierre de D-02)

| Clase | Cliente de Keycloak | Roles de `realm-management` | Quién la usa |
| --- | --- | --- | --- |
| `VendiKeycloakAdmin` | `vendi-backend` | `manage-users` | La API general |
| `VendiKeycloakAprovisionamiento` | `vendi-provisioning` | `manage-realm` + `manage-users` | **Solo el servicio `provisioner`** (ADR-027): la API le pide el alta y la baja de negocios por HTTP interno; la siembra y el reconciliador también |

Motivo medido y alcance real: `docs/deuda-tecnica.md`, D-02 (cerrada en la Task 0.5.3).

#### `tenant/middleware.py`: qué **no** se portó del original

Resolución por subdominio (Vendi no da subdominio por negocio), header
`X-Organization` por slug (no hay slugs), prefijos `sk_live_`/`sk_test_` (API
keys fuera de Fase 0) y `tenant_status_resolver` para el freeze.

Cambio de comportamiento que merece leerse: el middleware de BaseSaaS envolvía
la validación del token en un `try/except` que **registraba el error y
continuaba**. Con schema-per-tenant era tolerable (sin `search_path` la consulta
fallaba sola). Con RLS no: sin tenant la sesión no siembra el GUC y las consultas
devuelven **cero filas sin error**, así que un token expirado se convertiría en
"tu negocio no tiene ventas". Este middleware corta con 401/403/400 explícitos.

#### Tablas de plataforma (sin RLS) y por qué

`audit_events`, `outbox_messages`, `tenants` y `alembic_version`.
La lista vive en `vendi_core.db.base.TABLAS_DE_PLATAFORMA` y la leen los dos
candados. «Sin RLS» significa aquí, con precisión, «sin la policy de aislamiento
`tenant_isolation`»: la consulta y el drenado de estas tablas son cross-tenant
por definición.

##### La matriz de privilegios, tabla por tabla

La excepción no se sostiene sobre la buena fe sino sobre los privilegios de
Postgres, y no es la misma para las dos tablas.

| Tabla             | `vendi_app` (rol de la API) | `vendi_platform` |
|-------------------|-----------------------------|------------------|
| `audit_events`    | nada                        | todo             |
| `outbox_messages` | **solo `INSERT`**, y acotado por policy | todo, salta la policy por `BYPASSRLS` |
| `tenants`         | nada                        | todo             |

**`tenants`: nada, por el mismo motivo que `audit_events` y con más urgencia.**
Es la única tabla del sistema que enumera **todos** los negocios de la región
—nombres, estados, ids de organización— y no lleva policy de aislamiento porque
no tiene columna `tenant_id` que comparar: no pertenece a un negocio, *es* el
negocio. Con `SELECT` para el rol de la API, cualquier handler podría listarla
entera, que es exactamente el dato que el producto promete no cruzar. Los
privilegios por defecto de `01-roles.sh` la habrían dejado accesible (dan CRUD
sobre toda tabla nueva creada por `vendi_platform`), así que la migración `0002`
hace `REVOKE ALL ON tenants FROM vendi_app` explícitamente.

El único camino de lectura es la sesión de plataforma: `/api/v1/platform/*`
—que exige `platform:admin`— y `GET /api/v1/tenants/me`, que filtra en Python
por el `tenant_id` que salió del claim firmado por Keycloak. Lo defiende
`test_rls_coverage.py::test_vendi_app_no_alcanza_las_tablas_de_plataforma` y
`test_aislamiento_end_to_end.py::test_el_rol_de_la_api_no_alcanza_la_tabla_de_negocios`.

**`audit_events`: nada, y no es un olvido simétrico.** `AuditService` no recibe
una sesión, recibe una `async_sessionmaker` y abre la suya
(`vendi_core/audit/service.py::_write`). La auditoría es deliberadamente
fire-and-forget y **fuera** de la transacción del llamante: si fuese dentro, el
rollback de una operación fallida borraría la prueba de que se intentó. Se
cablea siempre con la fábrica de plataforma, así que el rol de la API no
necesita —ni debe— alcanzar la tabla. Lo defiende
`test_outbox_transaccional.py::test_la_api_no_alcanza_audit_events_en_ninguna_forma`,
que además comprueba que la firma de `AuditService.log_sync` no acepta una
sesión: el día que alguien la cambie, el candado avisa de que esta matriz deja
de ser correcta.

**`outbox_messages`: `INSERT` y nada más.** Aquí sí hace falta, y la revocación
total anterior hacía el patrón inutilizable. Toda la garantía del outbox
transaccional es que la escritura de negocio y el encolado del evento ocurren en
la MISMA transacción; la escritura de negocio la hace la sesión de tenant (rol
`vendi_app`), luego el `INSERT` del outbox también. Encolar con la sesión de
plataforma sería una segunda transacción y no garantizaría nada.

Lo que `vendi_app` sigue sin poder hacer, y es lo que mantiene viva la
excepción: **no `SELECT`** (no lee la cola de nadie), **no `UPDATE`** (no marca
procesado ni reescribe un mensaje ajeno), **no `DELETE`** (no vacía la cola).
Drenar es exclusivo de `vendi_platform`.

Y para que «sin policy de aislamiento» no signifique «puedo encolar en nombre de
otro negocio», la tabla lleva una policy **solo de INSERT**,
`outbox_encolado_del_tenant`:

```sql
CREATE POLICY outbox_encolado_del_tenant ON outbox_messages
  FOR INSERT TO vendi_app
  WITH CHECK (tenant_id = NULLIF(current_setting('vendi.tenant_id', true), '')::uuid);
```

`vendi_platform` la salta por `BYPASSRLS` —de ahí que el dispatcher drene la cola
entera y que los eventos de plataforma con `tenant_id NULL` puedan encolarse—;
`vendi_app` no. Sin ella, un `INSERT` con `tenant_id` ajeno pasaría y el
dispatcher publicaría el evento con la clave de enrutado del otro negocio.

**Lo que la policy NO acota, y quién lo acota (cierre de D-05).** La policy mira
la *columna* `tenant_id` y nada más: el texto de `routing_key` y el contenido de
`payload` pasan sin revisar. Una sesión de `vendi_app` con el GUC del negocio A
podía encolar legalmente una fila con `tenant_id = A` y
`routing_key = '<B>.venta.creada'`, y el dispatcher la publicaba literal.

Lo cierra el dispatcher, no la base: `OutboxDispatcher` **deriva** la clave de
enrutado de `msg.tenant_id` (`derivar_clave_de_enrutado`) y reescribe el campo
`tenant_id` del payload con el mismo valor. Lo que aporta el llamante es solo el
sufijo —el nombre del evento—, que no decide destinatario. Para el código
correcto es un no-op; para el equivocado es un candado, y la corrección se
registra como `outbox_clave_de_enrutado_corregida` con las dos claves. El
candado con dos colas reales de RabbitMQ está en
`tests/worker/test_outbox_dispatch.py`.

Detalle de implementación con nombre y apellidos: `OutboxMessage` declara
`__mapper_args__ = {"eager_defaults": False}`. SQLAlchemy 2 emite por defecto
`INSERT ... RETURNING created_at` para rellenar el `server_default` en caliente,
y PostgreSQL exige privilegio `SELECT` sobre las columnas de un `RETURNING`: con
él, encolar fallaría con `permission denied for table outbox_messages` aunque el
`INSERT` sea perfectamente legal.

Los candados: `tests/test_outbox_transaccional.py` (siete casos contra el
Postgres real: encolar, rollback sin evento fantasma, commit a mitad de request,
encolado cross-tenant rechazado, lectura/actualización/borrado denegados) y
`test_rls_coverage.py::test_vendi_app_no_alcanza_las_tablas_de_plataforma`.

### Backend — Etapa 3: la suite de tests

Los tests son artefacto cosechado como cualquier otro y llevan su procedencia en
la cabecera del archivo. Estado tras la ronda de corrección:
**321 tests, cobertura de `vendi_core` al 87 %**, ningún módulo por debajo del
54 %. Antes de esta ronda: 85 tests, 37 %, con doce paquetes al 0 % —incluidos
los dos que la Etapa 3 modificó para la tenancy—.

`bash scripts/dev.sh` levantado, y desde `backend/`:

```
uv run pytest -q --cov=vendi_core --cov-report=term
```

#### Tests portados desde `/Users/maoherran/BaseSaaS/backend/tests/`

| Archivo en Vendi | Origen | Adaptación |
| --- | --- | --- |
| `test_jobs_scheduler.py` | `test_job_timeout_retry.py` | `_run_one` recibe `tenant_id` en vez del par (slug, schema); métrica `vendi_job_failed_total`. **Ampliado** con seis casos de siembra/restauración de `current_tenant_id`, que es lo que la tarea 3.6 modificó |
| `test_retention_runner.py` | `test_retention_hook.py` + `test_retention_concurrency.py` | `_purge(..., ambito=)`, `_purge_tenant(tenant_id)`; se sustituye la SQLite en memoria por el Postgres del compose, porque el estado «transacción abortada» y los SAVEPOINT son comportamiento de PostgreSQL. **Ampliado** con el acotado por negocio, el ContextVar y el aislamiento de fallos entre políticas |
| `test_audit_service.py` | `test_audit_service_failure.py` + `test_audit_pool_exhaust.py` | Métrica `vendi_audit_write_failed_total` |
| `test_auditoria_decorator.py` | `test_audit_xff.py` + `test_oidc_client_secret_redaction.py` | **Ampliado** con el candado que impide que vuelva el bloque `actor` de suplantación |
| `test_middleware_client_ip.py` | `test_client_ip.py` | Solo renombres |
| `test_middleware_api_version.py` | `test_api_version_middleware.py` | Solo renombres |
| `test_middleware_http.py` | `test_otel_optin.py` (mitad `traceparent`) + `test_security_headers.py` + `test_service_account_secret_redaction.py` | Solo renombres |
| `test_tracing_otel.py` | `test_otel_optin.py` (mitad `configure_tracing`) | Solo renombres |
| `test_auth_policies.py` | `test_auth_policies.py` | Reescrito: el catálogo y los roles son otros (`dueno`/`cajero`/`almacenista`). **Ampliado** con «ningún rol de negocio alcanza `platform:admin`» y «el catálogo no declara permisos de suplantación» |
| `test_auth_ssl.py` | `test_keycloak_ssl_verify.py` | Solo renombres |
| `test_storage_factory.py` | `test_storage_factory.py` | Solo renombres |
| `test_errores_de_dominio.py` | `test_errors.py` | **Ampliado** con `ExternalServiceError`, que no existía en BaseSaaS |
| `test_mail_mime.py` | `test_mail_mime.py` | Datos de ejemplo al dominio de Vendi |
| `test_cache_redis.py` | `test_cache_publish_json.py` | **Ampliado** con `get`/`set`/`delete` |

#### Tests nuevos (el módulo existe en `vendi-core` y BaseSaaS no lo cubría)

`test_outbox_transaccional.py`, `test_outbox_dispatcher.py`,
`test_auth_dependencies.py`, `test_db_rls_helpers.py`,
`test_storage_backends.py`, `test_mail_envio.py`, `test_config_secrets.py`,
`test_modelos_compartidos.py`, `test_logging_setup.py`,
`test_files_retention_hook.py`.

#### Tests de BaseSaaS que NO se portan, con motivo

| Origen | Por qué |
| --- | --- |
| `test_job_trigger.py` | Prueba el router `POST /api/v1/platform/jobs/{job}/trigger` de `app.modules.jobs`, con `slowapi` y `require_platform_admin`. Es un test de servicio, no de `vendi-core`: el router llega en la Etapa 4 y el test con él |
| `test_impersonation.py` | La suplantación no existe en Fase 0 (rol `impersonation` retirado en la Etapa 2) |
| `test_mail_renderer.py`, `test_mail_tracking.py`, `test_mail_bounce_webhook.py`, `test_mail_worker_supervisor.py`, `test_mail_secrets.py` | Cubren el mailer por inquilino, las plantillas en base de datos, el rastreo de aperturas y las credenciales SMTP cifradas por negocio. Nada de eso se portó |
| `test_tenant_schema*.py`, `test_search_path_reset_hook.py`, `test_alembic_multi_schema.py` | Aislamiento por schema. Vendi aísla por RLS; los equivalentes son `test_rls_*.py` y `test_cross_tenant_isolation.py`, que ya existen |
| `test_freeze_*.py`, `test_webhook_*.py`, `test_realtime_*.py`, `test_notifications_router.py`, `test_queues_router.py`, `test_oidc_providers.py`, `test_service_accounts.py`, `test_invitation_tokens.py`, `test_bulk_invite.py`, `test_api_keys`… | Módulos fuera del alcance de Fase 0 |
| `test_account_router.py`, `test_tenant_*_router.py`, `test_docs_gate.py`, `test_rate_limit.py`, `test_production_checks.py`, `test_state_configuration.py`, `test_traefik_domains.py` | Tests de servicio (`app.*`). El servicio de API llega en la Etapa 4 |

---

## Panorama del sistema (consolidado en la Etapa 5)

Hasta aquí este documento era el **registro de la cosecha**: qué archivo vino de
dónde y con qué cambio. Sigue siéndolo. Lo que faltaba —y se añade aquí— es el
mapa: qué piezas hay, cómo se hablan y dónde vive cada decisión.

```
                    Internet / LAN
                          │
                    ┌─────▼─────┐   TLS (mkcert en local, ACME en producción)
                    │  Traefik  │   enruta por Host, termina CORS
                    └─────┬─────┘
     ┌───────────┬────────┼─────────┬──────────────┬─────────────┐
     │           │        │         │              │             │
 vendi.co    app.       admin.    api.         accounts.     grafana.
 (portal)   (tenant)   (admin)   (API)        (Keycloak)    (Grafana)
                                    │              │
                              ┌─────▼──────┐       │
                              │  api       │───────┘  valida JWT (JWKS)
                              │ (FastAPI)  │          y aprovisiona
                              └──┬───┬───┬─┘          Organizations
                                 │   │   │
              ┌──────────────────┘   │   └─────────────┐
        ┌─────▼─────┐          ┌─────▼─────┐     ┌─────▼─────┐
        │ PostgreSQL│          │   Redis   │     │  MinIO    │
        │  (RLS)    │          │  (cache)  │     │ (objetos) │
        └─────▲─────┘          └───────────┘     └───────────┘
              │  outbox_messages
        ┌─────┴─────┐          ┌───────────┐
        │  worker   │─────────►│ RabbitMQ  │
        │(dispatcher│          │  (topic)  │
        │ + jobs)   │          └───────────┘
        └───────────┘
```

`vendi-app` (Android/iOS, Capacitor) no aparece en el diagrama porque en Fase 0
**solo compila y produce un AAB**: no tiene login ni habla con la API todavía.

### Dónde está escrita cada decisión

| Pregunta | Respuesta corta | Dónde |
|---|---|---|
| ¿Cómo se aísla un negocio de otro? | RLS en schema único, dos roles, GUC `vendi.tenant_id` | [ADR-013](adr/adr-013-rls-schema-unico.md) |
| ¿Cómo sabe la API de qué negocio es una petición? | Del claim `organization`; el alias **es** el `tenant_id` | [ADR-014](adr/adr-014-realm-por-region-organizations.md) |
| ¿Cómo se autoriza? | `realm_access.roles`: permisos y roles de negocio en el mismo claim | [ADR-015](adr/adr-015-roles-de-negocio-como-roles-de-realm.md) |
| ¿Por qué dos procesos y no cinco? | La frontera se pone donde cambia la operación | [ADR-016](adr/adr-016-backend-api-worker.md) |
| ¿Por qué cuatro apps? | Cuatro públicos, cuatro clientes de Keycloak | [ADR-012](adr/adr-012-cuatro-apps-angular.md) |
| ¿Qué puede importar cada lib? | Lo dice ESLint, y explica el porqué | [ADR-011](adr/adr-011-fronteras-workspace-angular.md) |

### Catálogo de módulos: qué existe y qué es backlog

Fase 0 implementa **`tenants`, `auth`, `audit`** y el esqueleto de `platform`.

Backlog declarado del §5.3 del spec, con su motivo (detalle en
[ADR-016](adr/adr-016-backend-api-worker.md)): `api_keys` y `webhooks` (no hay
integradores externos), `feature_flags` (con un despliegue no hay nada que
conmutar), `notifications` (llega con el fiado), `account` y `tenant_settings`
(necesitan el modelo de datos del MVP para saber qué se configura).

### Tablas de plataforma y privilegios del rol de la API

Cuatro tablas viven en el schema regional **sin RLS**, porque se consultan
cross-negocio por definición. La excepción solo se sostiene mientras el rol de la
API no las alcance:

| Tabla | Privilegios de `vendi_app` | Por qué |
|---|---|---|
| `audit_events` | **ninguno** | la auditoría se escribe con la sesión de plataforma, fuera de la transacción del llamante |
| `outbox_messages` | **solo INSERT** | `enqueue()` escribe en la sesión del llamante para compartir transacción; una policy de INSERT ata `tenant_id` al GUC |
| `tenants` | **ninguno** | sin policy y con SELECT, cualquier handler listaría todos los negocios de la región |
| `alembic_version` | **ninguno** | decide qué DDL se considera aplicado; con UPDATE, un handler puede desordenar las migraciones (deuda D-06, cerrada en la Etapa 5) |

Lo vigila `backend/tests/test_privilegios_de_vendi_app.py`, un candado
**invertido**: enumera lo permitido y falla ante cualquier tabla del esquema
`public` que conceda algo distinto — incluida una tabla nueva que nadie
clasificó.

### Por qué NO existe un runbook `orm-alembic-sync.md`

BaseSaaS tenía uno: con schema-per-tenant, el ORM y las N copias del esquema se
desincronizaban y hacía falta un procedimiento para detectarlo y repararlo. En
Vendi hay **un** schema y **una** cadena de migraciones, así que el problema no
tiene dónde ocurrir. Se anota aquí para que nadie lo eche de menos y lo escriba
de nuevo por analogía.

### Superficie de seguridad del borde (estado al cierre de Fase 0)

| Ruta | Quién puede | Cómo se garantiza |
|---|---|---|
| `/metrics` | nadie desde fuera | router `denegar-todo` en Traefik + `METRICS_TOKEN` en la app (dos capas) |
| `/docs`, `/redoc`, `/openapi.json` | nadie, salvo `DOCS_PUBLICOS=true` | las rutas **no se registran**: el 404 es real |
| `/api/v1/platform/*` | `platform:admin` | dependencia de permiso |
| `/api/v1/*` | token del realm `vendi-co` con `aud=vendi-backend` | `JWTValidator` (realm permitido + audiencia) |
| preflight CORS | orígenes de `*.vendi.co`, `localhost:*` y el WebView de Capacitor | middleware `cors-api` de Traefik, con lista **explícita** de cabeceras |

El grant de contraseña (ROPC) está **apagado en todos los clientes** del realm
`vendi-co`, incluido `admin-cli` —que Keycloak trae encendido de fábrica y es el
mismo agujero con otro nombre—. Lo comprueba el check 22 de `verify-setup.sh`
contra el realm vivo, no contra el JSON.
