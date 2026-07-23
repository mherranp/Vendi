# =============================================================================
# frontend/Dockerfile — imagen de cualquiera de las SPAs de Vendi
#
# Una sola receta para las tres apps web (`vendi-portal`, `vendi-tenant`,
# `vendi-admin`): el argumento de construcción `APP` elige cuál se compila.
# `vendi-app` NO se sirve así — es la app móvil y su artefacto es el AAB que
# produce `.github/workflows/android.yml`.
#
# Cosechado de /Users/maoherran/BaseSaaS/frontend/Dockerfile, con las
# diferencias propias de este workspace:
#
#   - Las cinco librerías del monorepo se compilan ANTES que la app. No es
#     opcional: `tsconfig.json` resuelve los alias (`auth`, `ui-kit`, …) contra
#     `dist/`, no contra el código fuente (ver el comentario largo de
#     `frontend/tsconfig.json`), así que sin este paso `ng build` falla con
#     "Cannot find module 'ui-kit'".
#   - `npm ci` corre con el `package-lock.json` del repositorio: la imagen tiene
#     que ser reproducible byte a byte, no "lo que hubiera en npm ese día".
#   - La sustitución de dominio es un no-op cuando BASE_DOMAIN=vendi.co (el
#     caso normal, tanto en desarrollo como en producción CO). Existe para que
#     una segunda región —ADR-014, un realm y un dominio por región— no
#     obligue a tocar código fuente.
#
# POR QUÉ EXISTE ESTA IMAGEN: hasta la Etapa 4 las apps se servían con
# `ng serve` en puertos pelados, y los E2E de la Etapa 5 no pueden verificarse
# así. Lo que se prueba es la integración con Keycloak y con la API: por
# `localhost:4202` no se ejercita ni el enrutado de Traefik, ni las cabeceras
# que inyecta, ni el TLS, ni la resolución de nombres — que es exactamente
# donde viven los fallos reales. Con esta imagen las tres apps se sirven por su
# hostname (`vendi.co`, `app.vendi.co`, `admin.vendi.co`) igual que en
# producción.
# =============================================================================

ARG NODE_VERSION=22
ARG NGINX_VERSION=1.27-alpine

# --- Construcción ------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS builder

ARG APP
ARG BASE_DOMAIN=vendi.co

WORKDIR /src

# Capa de dependencias, separada del código para que el caché de Docker no se
# invalide en cada cambio de un componente.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY angular.json tsconfig.json ./
COPY eslint.config.js eslint.fronteras.js ./
COPY projects/ projects/

# Renombrado de dominio para despliegues regionales. Se busca el literal
# `vendi.co` con el punto escapado, de modo que no toca `co.vendi.app` (el
# applicationId de Android), ni `vendi-web`/`vendi-admin` (los clientes de
# Keycloak), ni `vendi-net` (la red del compose).
RUN if [ "${BASE_DOMAIN}" != "vendi.co" ]; then \
      find projects -type f \( -name '*.ts' -o -name '*.html' \) \
        -exec sed -i "s/vendi\.co/${BASE_DOMAIN}/g" {} \; ; \
    fi

# Las librerías primero (ver la cabecera). El orden respeta las dependencias
# entre ellas: domain → data-access → auth, con native y ui-kit al margen.
RUN npx ng build domain --configuration=production \
 && npx ng build native --configuration=production \
 && npx ng build ui-kit --configuration=production \
 && npx ng build data-access --configuration=production \
 && npx ng build auth --configuration=production

# La app. `--configuration=production` es redundante (es la configuración por
# defecto de las cuatro apps) pero se escribe explícito: si alguien cambia
# `defaultConfiguration` en angular.json, la imagen no debe empezar a
# empaquetar en silencio `environment.development.ts`.
RUN npx ng build ${APP} --configuration=production

# --- Ejecución ---------------------------------------------------------------
FROM nginx:${NGINX_VERSION} AS runtime

ARG APP
LABEL org.opencontainers.image.title="vendi-${APP}"
LABEL org.opencontainers.image.source="https://github.com/vendi/software"

COPY --from=builder /src/dist/${APP}/browser /usr/share/nginx/html
COPY nginx-spa.conf /etc/nginx/conf.d/default.conf

# Sonda: pide `/salud`, que nginx responde sin tocar el disco. Un `wget` a `/`
# también pasaría con un directorio vacío (nginx serviría su índice por
# defecto), así que la sonda comprueba además que el index de la SPA existe.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --spider -q http://127.0.0.1/salud && test -s /usr/share/nginx/html/index.html
