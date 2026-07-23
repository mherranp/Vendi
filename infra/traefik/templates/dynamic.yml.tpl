# Configuración dinámica de Traefik para Vendi.
#
# NO editar el archivo renderizado (dynamic/dynamic.yml): se reescribe en cada
# arranque del contenedor a partir de este template, sustituyendo
# ${BASE_DOMAIN}, ${BASE_DOMAIN_REGEX} y ${TLS_OPCIONES} (ver
# traefik/entrypoint.sh).
#
# ${TLS_OPCIONES} vale:
#   {}                            con ACME_ENABLED=false → certificados de
#                                 /certs (mkcert), declarados por el
#                                 entrypoint en dynamic/certificados-locales.yml
#   { certResolver: letsencrypt } con ACME_ENABLED=true  → los emite la CA ACME
#
# Es el único punto donde se elige el origen de los certificados: si un router
# nuevo no lleva `tls: ${TLS_OPCIONES}`, no tendrá certificado en producción.

http:
  middlewares:
    cors-api:
      headers:
        accessControlAllowOriginListRegex:
          - "^https?://(.+\\.)?${BASE_DOMAIN_REGEX}(:[0-9]+)?$"
          # `ng serve` de las cuatro apps durante el desarrollo.
          - "^http://localhost:[0-9]+$"
          # WebView de Capacitor en Android/iOS (vendi-app).
          - "^capacitor://localhost$"
          - "^https://localhost$"
        accessControlAllowMethods:
          - GET
          - POST
          - PUT
          - PATCH
          - DELETE
          - OPTIONS
        # Lista EXPLÍCITA, no `"*"`. La combinación `"*"` +
        # `accessControlAllowCredentials: true` es inválida: la especificación
        # de Fetch dice que en una petición con credenciales el `*` de
        # `Access-Control-Allow-Headers` se compara LITERALMENTE —no es un
        # comodín—, así que el preflight de cualquier petición con
        # `Authorization` (es decir, TODA petición autenticada de las SPAs en
        # cuanto alguien use `withCredentials`) se rechazaría en el navegador,
        # sin un solo log en el backend.
        #
        # Tiene que coincidir con `CABECERAS_CORS` de
        # backend/services/api/app/factory.py, que es la misma superficie vista
        # desde el otro lado del borde. Hay un test que compara los dos
        # archivos: backend/tests/api/test_cors.py.
        accessControlAllowHeaders:
          - Accept
          - Accept-Language
          - Authorization
          - Content-Type
          - X-Correlation-Id
          - X-Requested-With
          - X-Tenant-Id
        accessControlAllowCredentials: true
        accessControlMaxAge: 3600
        addVaryHeader: true
    secure-headers:
      headers:
        frameDeny: true
        contentTypeNosniff: true
        browserXssFilter: true
        referrerPolicy: "strict-origin-when-cross-origin"
    # Límite de tasa del borde, por IP de origen, sobre TODO /api/*. Es
    # generoso a propósito: atrapa clientes desbocados y raspadores antes de
    # que lleguen a la aplicación. Los límites finos por endpoint viven en la
    # API.
    api-ratelimit:
      rateLimit:
        average: 100
        burst: 200
        sourceCriterion:
          ipStrategy:
            depth: 1
    # Deniega SIEMPRE. `ipAllowList` con un rango que ninguna dirección puede
    # tener (240.0.0.0/4 es «reservado para uso futuro», RFC 1112 §4) responde
    # 403 a todo el mundo sin excepción posible. Traefik no tiene un middleware
    # «deny» explícito y este es el idiom equivalente; se documenta aquí porque
    # el rango parece arbitrario y no lo es.
    denegar-todo:
      ipAllowList:
        sourceRange:
          - "240.0.0.0/4"

  routers:
    # --- API ---
    # El router de `/metrics` va PRIMERO por claridad; el orden real lo decide
    # Traefik por longitud de regla, y `Host(...) && PathPrefix(...)` es más
    # larga que `Host(...)`, así que gana esta.
    #
    # POR QUÉ EXISTE: el router `api` enruta por Host, no por path, de modo que
    # todo lo que sirva la aplicación queda publicado bajo
    # `https://api.${BASE_DOMAIN}/...`, incluida la exposición de Prometheus.
    # Esa exposición lleva el mapa de rutas internas, los contadores de error
    # por endpoint y —en cuanto haya métricas por negocio— identificadores de
    # negocio. Prometheus la raspa por dentro de la red del compose
    # (`http://api:8000/metrics`), así que no necesita salir por el borde: aquí
    # se cierra.
    #
    # Es la primera de dos capas. La segunda es la credencial que exige la
    # propia ruta (`METRICS_TOKEN`, ver backend/services/api/app/metrics.py):
    # el borde protege el perímetro, la credencial protege dentro de él.
    api-metrics-bloqueado:
      rule: "Host(`api.${BASE_DOMAIN}`) && PathPrefix(`/metrics`)"
      entryPoints: [websecure]
      service: api
      middlewares: [denegar-todo]
      tls: ${TLS_OPCIONES}

    api:
      rule: "Host(`api.${BASE_DOMAIN}`)"
      entryPoints: [websecure]
      service: api
      middlewares: [api-ratelimit, cors-api, secure-headers]
      tls: ${TLS_OPCIONES}

    # --- Keycloak ---
    accounts:
      rule: "Host(`accounts.${BASE_DOMAIN}`)"
      entryPoints: [websecure]
      service: keycloak
      middlewares: [secure-headers]
      tls: ${TLS_OPCIONES}

    # --- Observabilidad ---
    # Prometheus no tiene router a propósito: solo se consulta desde dentro de
    # la red del compose.
    grafana:
      rule: "Host(`grafana.${BASE_DOMAIN}`)"
      entryPoints: [websecure]
      service: grafana
      middlewares: [secure-headers]
      tls: ${TLS_OPCIONES}

    # --- Herramienta de desarrollo: interfaz de MailHog ---
    # El servicio mailhog solo existe en docker-compose.override.dev.yml. En
    # producción este router queda huérfano y responde 502 si alguien lo
    # visita; no expone nada.
    mailhog:
      rule: "Host(`mail.${BASE_DOMAIN}`)"
      entryPoints: [websecure]
      service: mailhog
      tls: ${TLS_OPCIONES}

    # --- Apps de frontend ---
    # Las tres SPAs web se sirven desde imágenes nginx (frontend/Dockerfile,
    # servicios `portal`/`tenant`/`admin` del compose). `vendi-app` no tiene
    # router: es la app móvil y su artefacto es el AAB.
    #
    # Vendi NO enruta por subdominio de tenant (no hay HostRegexp comodín como
    # en BaseSaaS): el tenant se resuelve del claim `organization` del token.
    #
    # NO llevan `cors-api`: CORS lo negocia el navegador contra el ORIGEN de la
    # API (`api.${BASE_DOMAIN}`), no contra el que sirve la SPA. Poner el
    # middleware aquí solo añadiría cabeceras que nadie mira.
    portal:
      rule: "Host(`${BASE_DOMAIN}`) || Host(`www.${BASE_DOMAIN}`)"
      entryPoints: [websecure]
      service: portal
      middlewares: [secure-headers]
      tls: ${TLS_OPCIONES}

    tenant:
      rule: "Host(`app.${BASE_DOMAIN}`)"
      entryPoints: [websecure]
      service: tenant
      middlewares: [secure-headers]
      tls: ${TLS_OPCIONES}

    admin:
      rule: "Host(`admin.${BASE_DOMAIN}`)"
      entryPoints: [websecure]
      service: admin
      middlewares: [secure-headers]
      tls: ${TLS_OPCIONES}

  services:
    api:
      loadBalancer:
        servers:
          - url: "http://api:8000"
    keycloak:
      loadBalancer:
        servers:
          - url: "http://keycloak:8080"
    grafana:
      loadBalancer:
        servers:
          - url: "http://grafana:3000"
    mailhog:
      loadBalancer:
        servers:
          - url: "http://mailhog:8025"
    portal:
      loadBalancer:
        servers:
          - url: "http://portal:80"
    tenant:
      loadBalancer:
        servers:
          - url: "http://tenant:80"
    admin:
      loadBalancer:
        servers:
          - url: "http://admin:80"

