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
        accessControlAllowHeaders:
          - "*"
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

  routers:
    # --- API ---
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
    # Vendi todavía no empaqueta las apps Angular en imágenes: en desarrollo
    # se sirven con `ng serve`. Cuando exista frontend/Dockerfile (Etapa 5),
    # descomentar estos routers y sus servicios de abajo:
    #
    #   portal:  Host(`${BASE_DOMAIN}`) || Host(`www.${BASE_DOMAIN}`) -> vendi-portal
    #   tenant:  Host(`app.${BASE_DOMAIN}`)                           -> vendi-tenant
    #   admin:   Host(`admin.${BASE_DOMAIN}`)                         -> vendi-admin
    #
    # Vendi NO enruta por subdominio de tenant (no hay HostRegexp comodín como
    # en BaseSaaS): el tenant se resuelve del claim `organization` del token.

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

