# Runbooks

Procedimientos de operación. Cada uno responde a «tengo este problema delante,
¿qué hago?», no a «cómo funciona esto» (eso es `docs/ARCHITECTURE.md` y los
ADRs).

| Runbook | Cuándo se abre |
|---|---|
| [dns-y-tls-local.md](dns-y-tls-local.md) | `*.vendi.co` no resuelve, o resuelve a Internet; certificados locales |
| [anadir-una-tabla-de-negocio.md](anadir-una-tabla-de-negocio.md) | vas a crear una tabla nueva y no quieres abrir un agujero de aislamiento |
| [keycloak-deriva-y-organizaciones.md](keycloak-deriva-y-organizaciones.md) | tocaste el realm a mano, cambiaste el JSON, o un negocio se quedó sin Organization |
| [rabbitmq-outbox-y-dlq.md](rabbitmq-outbox-y-dlq.md) | los eventos no llegan, el outbox se acumula, hay mensajes en `failed` |
| [despliegue-en-la-vm.md](despliegue-en-la-vm.md) | desplegar, revertir, o el despliegue automático falló |
| [rotacion-de-certificados.md](rotacion-de-certificados.md) | caducó un certificado, o pasas de mkcert a Let's Encrypt |
| [`../respaldo-y-restauracion.md`](../respaldo-y-restauracion.md) | restaurar una copia, o comprobar que las copias sirven |

## Runbooks de BaseSaaS que NO se portan, y por qué

De los 33 originales, la mayoría cubre módulos que Vendi no tiene (`webhooks`,
`feature-flags`, `service-accounts`, `signup`, `impersonation`, `mail-bounces`,
`oidc-providers`, `custom-domains`, `gdpr`, `rate-limiting`…). Se reescribirán
cuando exista el módulo, no antes: un runbook de algo que no existe es una
promesa.

Merece mención aparte **`orm-alembic-sync.md`**. En BaseSaaS hacía falta porque
con schema-per-tenant el ORM y las N copias del esquema se desincronizaban y
había que detectarlo y repararlo. En Vendi hay **un** schema y **una** cadena de
migraciones: el problema no tiene dónde ocurrir. Se anota aquí para que nadie lo
eche de menos y lo escriba de nuevo por analogía.
