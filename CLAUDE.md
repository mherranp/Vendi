# CLAUDE.md

Instrucciones para agentes que trabajen en este repositorio. Lo que sigue no son
sugerencias: son las reglas que hacen que el trabajo se integre en vez de tener
que rehacerse.

---

## Lo primero

Lee [`README.md`](README.md) y [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Antes de tocar algo relacionado con tenancy, identidad o fronteras del
frontend, lee el ADR correspondiente en [`docs/adr/`](docs/adr/): esas
decisiones ya se tomaron con evidencia medida, y contradecirlas sin argumento
nuevo cuesta una etapa entera.

---

## Idioma

**Todo en español.** Código comentado, nombres de tests, documentación, mensajes
de commit y mensajes de error de cara al usuario.

Excepción única: los **identificadores técnicos** van sin tildes ni eñes
(`dueno`, no `dueño`). Viajan por roles de Keycloak, claves de JSON en tokens,
segmentos de URL de la Admin API y literales de TypeScript; cada salto es una
oportunidad de romper el round-trip de UTF-8. La etiqueta legible sí lleva la
eñe y vive en el catálogo de i18n.

---

## Cómo se verifica: por el dominio, siempre

Todo lo que se pruebe contra el stack levantado se prueba **por su dominio y a
través de Traefik**, sobre HTTPS y validando el certificado:

- `https://api.vendi.co`, `https://accounts.vendi.co`, `https://app.vendi.co`,
  `https://admin.vendi.co`.
- **Nunca** `localhost:<puerto>`, `127.0.0.1:<puerto>` ni el puerto interno del
  contenedor.
- **Nunca** `curl -k`, `--insecure` ni `ignoreHTTPSErrors`. `mkcert` instaló la
  CA en el sistema precisamente para que no haga falta.

Motivo: saltarse el dominio es probar una topología que no es la que se
despliega. Te ahorras el enrutado de Traefik, las cabeceras que inyecta, el TLS
y la resolución de nombres — que es exactamente donde viven los fallos reales.
Si algo funciona por `localhost:<puerto>` y falla por el dominio, **eso es un
defecto**, no una particularidad del entorno.

> ⚠️ **`vendi.co` es un dominio real registrado por un tercero.** Si
> `/etc/resolver/vendi.co` no existe en la máquina, cada petición sale a
> Internet, a un host con certificado válido que no es nuestro — y por tanto sin
> ningún aviso. Mientras falte, usa `curl --resolve <host>:443:127.0.0.1` y, en
> Chromium, `--host-resolver-rules='MAP *.vendi.co 127.0.0.1'`. Eso fija la
> resolución sin aflojar nada más: hostname, SNI, cabecera `Host`, enrutado y
> validación del certificado siguen siendo los reales.

Excepciones legítimas, porque no son HTTP y Traefik no los enruta: PostgreSQL
(`127.0.0.1:5432`), RabbitMQ (`127.0.0.1:5672`) y la Admin API de Keycloak
usada por los scripts de operación.

---

## Reglas del backend

- Rol de conexión de la API: **`vendi_app`**, sin `BYPASSRLS`. Rol de plataforma
  y migraciones: **`vendi_platform`**, con `BYPASSRLS`.
- GUC de negocio: **`vendi.tenant_id`**. En código de petición **siempre
  `SET LOCAL`, nunca `SET`**. Un `SET` de sesión sobrevive al final de la
  petición y el siguiente uso de esa conexión del pool hereda el negocio
  anterior.
- Toda tabla de negocio nueva llama a `enable_rls(op, '<tabla>')` en su
  migración. Si se olvida, `test_rls_coverage.py` se pone rojo — y hace bien.
- Toda tabla nueva **sin** `tenant_id` tiene que declararse en
  `PRIVILEGIOS_DE_VENDI_APP` con su `REVOKE` en la migración, o
  `test_privilegios_de_vendi_app.py` falla. Es un candado invertido a propósito:
  enumera lo permitido, no lo prohibido.
- Ningún secreto ni DSN de producción lleva valor por defecto en `Settings`.
- Los tests `integration` **no se omiten** si falta el servicio: fallan. Un test
  que desaparece del recuento no prueba nada.

## Reglas del frontend

- Prefijo de selectores: **`vd`**.
- Las fronteras entre librerías las impone ESLint (`no-restricted-imports`), no
  la buena voluntad. Ver [ADR-011](docs/adr/adr-011-fronteras-workspace-angular.md).
- **`native` es el único punto del workspace que puede importar `@capacitor/*`.**
  Todo lo demás usa su fachada.
- Nada de texto de interfaz incrustado: va al catálogo de i18n.

## Reglas de infraestructura

- Realm de Keycloak: **`vendi-co`**. Imagen fijada a **`26.6.4`**, nunca
  `latest`: el comportamiento de Organizations cambió entre 26.0 y 26.6.
- El realm es **semilla, no estado deseado continuo**: `--import-realm` no
  reimporta sobre un realm existente. Un cambio en
  `infra/keycloak/realm-vendi-co.json` **no se aplica reiniciando**. Usa
  `bash scripts/reconcile-keycloak.sh` para ver la deriva y
  `RECONCILE_APLICAR_CONFIG=1` para aplicar el subconjunto seguro.
- El CORS lo termina Traefik. La aplicación **no** lo duplica: dos dueños
  producen la cabecera `Access-Control-Allow-Origin` duplicada y el navegador
  rechaza la respuesta entera, sin un solo log en el backend.

---

## Comandos

```bash
# Stack
./scripts/dev.sh                     # levantar (se niega si el DNS no está bien)
bash scripts/migrate.sh              # migraciones con el rol de plataforma
bash scripts/seed.sh                 # negocio demo + usuarios
bash scripts/verify-setup.sh         # 27 comprobaciones; 0 solo si no hay fallos
bash scripts/reconcile-keycloak.sh   # deriva del realm

# Backend (desde backend/)
uv run pytest -q -m 'not integration'
uv run pytest -q                     # todo; exige el stack levantado
uv run ruff check . && uv run ruff format --check .

# Frontend (desde frontend/)
npm run build:libs && npx ng test --watch=false
npx ng lint && npm run format:check
npm run e2e
```

Tras cambiar código del backend hay que **reconstruir la imagen**: los
contenedores no montan el código fuente.

```bash
docker compose -f infra/docker-compose.yml -f infra/docker-compose.override.dev.yml build api worker
docker compose -f infra/docker-compose.yml -f infra/docker-compose.override.dev.yml up -d api worker
```

---

## Estilo de comentarios y documentación

Un comentario explica **por qué**, no **qué**. El código ya dice qué hace; lo
que no dice es qué alternativa se descartó, qué se midió y qué se rompe si
alguien lo «simplifica».

Cuando algo se decide con evidencia, se escribe la evidencia: el comando y su
salida real, no lo que se esperaba que saliera.

---

## Deuda técnica

`docs/deuda-tecnica.md` registra lo que está mal **a sabiendas**, con quién lo
decidió, por qué, y **cuándo deja de ser aceptable**. Una deuda sin fecha de
vencimiento no es deuda: es una decisión permanente que nadie firmó.

Una entrada se cierra **borrándola de ahí y dejando la evidencia de que el
arreglo funciona** (comando + salida), no marcándola como «hecha».

---

## Lo que no se hace

- **No se hace commit** salvo que se pida explícitamente.
- **No se usa `sudo`.** Si un paso lo necesita, se documenta y se deja al
  operador.
- **No se relajan los guardas.** `verify-setup.sh`, los candados de RLS y de
  privilegios, y el rechazo de `dev.sh` cuando el DNS apunta a Internet existen
  para incomodar en el momento correcto. Ponerlos en verde a base de aflojarlos
  es peor que dejarlos en rojo, porque el rojo al menos se ve.
- **No se modifica `/Users/maoherran/BaseSaaS`.** Es la fuente de la cosecha y
  es de solo lectura.
