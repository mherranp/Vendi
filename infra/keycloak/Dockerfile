# Imagen de Keycloak de Vendi: la que permite arrancar con `--optimized`.
#
# ## Qué cierra (deuda D-04)
#
# `docker-compose.override.prod.yml` arrancaba con `start --import-realm` y sin
# `--optimized`, de modo que **cada arranque de producción hacía un build
# implícito** de decenas de segundos: aumenta la ventana de indisponibilidad de
# cada despliegue y de cada reinicio no planificado.
#
# `--optimized` no es un flag que se pueda añadir sin más: exige una imagen
# sobre la que ya se haya ejecutado `kc.sh build` **con las mismas opciones de
# build** con las que se va a arrancar. Con la imagen oficial tal cual, el
# servidor se niega a arrancar. Esta imagen es esa imagen.
#
# ## La regla que hay que respetar al tocar esto
#
# Las opciones de Keycloak son de DOS clases y solo unas se pueden cambiar en
# el arranque:
#
# - **De build** (`db`, `features`, `health-enabled`, `metrics-enabled`,
#   proveedores…): se fijan aquí, en `kc.sh build`. Cambiar una en el entorno
#   con `--optimized` puesto **no tiene efecto** —o el servidor se niega a
#   arrancar—, así que si mañana hace falta otra funcionalidad, se añade a esta
#   línea y se reconstruye la imagen.
# - **De runtime** (`db-url-host`, `hostname`, credenciales, `proxy-headers`…):
#   siguen viniendo por variables de entorno del compose, como hasta ahora.
#
# Aquí NO se pasa `--features`, y merece explicación porque es contraintuitivo:
# Organizations —el mecanismo con el que Vendi separa negocios dentro del realm
# regional— **no es una funcionalidad opcional en 26.6.4**, está activa de
# fábrica. Se comprobó al escribir este archivo: `--features=organizations`
# aborta el build con «'organizations' is an unrecognized feature» (el nombre en
# la lista es `organization`, en singular, y tampoco hace falta declararlo). El
# compose ya funciona sin declararla y `organizationsEnabled` del realm basta.
# Si algún día hace falta una funcionalidad de verdad opcional, se añade aquí y
# se reconstruye: en el entorno, con `--optimized`, no tendría efecto.
#
# El realm y el tema NO se copian a la imagen: siguen montados como volúmenes
# desde `infra/`, para que corregir un texto del tema no obligue a reconstruir
# y publicar una imagen.

# Versión fijada por restricción global del plan. NUNCA `latest`: el
# comportamiento de Organizations cambió entre 26.0 y 26.6.
FROM quay.io/keycloak/keycloak:26.6.4 AS builder

# `db=postgres` y `health-enabled` son de build y tienen que coincidir con lo
# que el compose configura por entorno. `metrics-enabled` deja preparada la
# exposición de Prometheus del propio Keycloak (hoy no se raspa).
RUN /opt/keycloak/bin/kc.sh build \
    --db=postgres \
    --health-enabled=true \
    --metrics-enabled=true

FROM quay.io/keycloak/keycloak:26.6.4

COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Sin ENTRYPOINT propio: se hereda el de la imagen oficial. El comando concreto
# (`start --optimized --import-realm`) lo pone el compose, que es donde se ve
# junto al resto de la configuración del servicio.
