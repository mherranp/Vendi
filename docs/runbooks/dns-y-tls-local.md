# Runbook · DNS y TLS locales

Cómo se resuelven y se cifran los `*.vendi.co` de la máquina de desarrollo, qué
pasos quedan pendientes de `sudo`, y cómo recuperar el acceso al **`vendi.co`
real de producción** cuando haga falta.

## El trato

El stack local usa el **TLD real del producto**, `vendi.co`, no un dominio
inventado. La ventaja es que todo lo que se escribe una vez —redirect URIs de
Keycloak, orígenes CORS, `environment.development.ts`, cookies— vale igual en
local y en producción, sin un dominio de mentira que traducir mentalmente.

El precio tiene **dos direcciones**, y durante un tiempo este runbook solo
documentó la inofensiva. Las dos importan, y la segunda es la peligrosa.

### Dirección 1 · Con el DNS local activo, no se llega al `vendi.co` público

Todo `*.vendi.co` cae en 127.0.0.1. Molesto cuando quieres mirar producción; el
procedimiento B de abajo es el interruptor para recuperarlo. Se nota enseguida y
no rompe nada.

### Dirección 2 · Sin el DNS local, todo sale a Internet ⚠️

Esta es la que muerde. **`vendi.co` es un dominio real y registrado.** Mientras
falte `/etc/resolver/vendi.co`, cada nombre `*.vendi.co` se resuelve por el
camino normal y acaba en un host que no es nuestro:

```
$ curl -s -o /dev/null -w '%{http_code} ip=%{remote_ip} verify=%{ssl_verify_result}\n' \
    https://accounts.vendi.co/realms/vendi-co/.well-known/openid-configuration
436 ip=64.190.63.222 verify=0        # verify=0 = cadena TLS VÁLIDA
```

Lo que hace esto grave y no meramente molesto es `verify=0`. Ese host presenta
un certificado **DigiCert legítimo para `accounts.vendi.co`**, así que la
validación TLS pasa limpia y ningún cliente avisa de nada. Y `accounts` es el
**IdP**: un POST al endpoint de token entrega el `client_secret` de
`vendi-provisioning` a un tercero, sin un solo error por el camino.

No todos los nombres se comportan igual — solo fallan abiertos los que tienen
certificado público:

| Nombre | Código | verify | Comportamiento |
|---|---|---|---|
| `api.vendi.co` | 000 | 1 | cierra (el certificado no valida) |
| `app.vendi.co` | 000 | 1 | cierra |
| `admin.vendi.co` | 000 | 1 | cierra |
| **`accounts.vendi.co`** | 436 | **0** | **ABRE — y es el IdP** |
| **`vendi.co`** | 436 | **0** | **ABRE** |

Por eso comprobar solo `api.vendi.co` no sirve: es justo uno de los que falla
cerrado. Lo mide el check **11c** de `verify-setup.sh`, que los recorre todos.

Con el dominio anterior, `vendi.local`, este riesgo no existía: `.local` no se
resuelve en Internet, así que el mismo error de configuración fallaba cerrado
(`000 verify=20 ip=127.0.0.1`, sin llegar a ninguna parte). Al pasar a un TLD
real el fallo cambió de signo. **Mientras el procedimiento A esté pendiente, el
estado de la máquina no es "incompleto": es inseguro.** `dev.sh` aborta y
`verify-setup.sh` suspende en ese estado, a propósito.

Las tres piezas, y qué hace cada una:

| Pieza | Dónde | Qué hace | ¿Necesita `sudo`? |
|---|---|---|---|
| Entrada de dnsmasq | `/opt/homebrew/etc/dnsmasq.conf` | Le dice a dnsmasq que conteste 127.0.0.1 a `*.vendi.co` | No (el archivo es del usuario) |
| Reinicio de dnsmasq | `brew services restart dnsmasq` | Hace que dnsmasq **lea** esa entrada | **Sí** (corre como root) |
| Resolver del sistema | `/etc/resolver/vendi.co` | Hace que macOS **pregunte** a dnsmasq por `*.vendi.co` | **Sí** (`/etc/` es de root) |
| Certificado | `infra/certs/vendi.co*.pem` | TLS de confianza para `vendi.co` y `*.vendi.co` | No (mkcert, CA ya instalada) |

Las dos primeras son independientes y hacen falta **las dos**: sin el reinicio,
dnsmasq sigue reenviando `vendi.co` a Internet aunque la línea esté escrita; sin
el resolver, macOS ni siquiera le pregunta a dnsmasq.

---

## Procedimiento A · Completar el DNS local (pendiente de `sudo`)

Estado actual: la línea ya está escrita en `dnsmasq.conf` y los certificados ya
están generados. Faltan **solo** estos dos comandos, que piden contraseña.

```sh
# 1. Que macOS enrute las consultas de *.vendi.co a dnsmasq.
sudo tee /etc/resolver/vendi.co >/dev/null <<'EOF'
nameserver 127.0.0.1
EOF

# 2. Que dnsmasq relea su configuración y empiece a contestar por vendi.co.
sudo brew services restart dnsmasq

# 3. macOS cachea el resultado anterior; sin esto los dos pasos parecen no haber
#    servido de nada.
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```

### Comprobación

```sh
# dnsmasq contesta loopback (antes del reinicio devolvía la IP pública real).
dig +short @127.0.0.1 api.vendi.co          # esperado: 127.0.0.1

# El resolver del sistema enruta hacia dnsmasq.
dscacheutil -q host -a name api.vendi.co    # esperado: ip_address: 127.0.0.1

# La cadena entera, ya sin --resolve, con TLS validado de verdad (sin -k).
curl https://api.vendi.co/health             # esperado: {"status":"ok"}

# Y el verificador completo: 11b pasa de FALLO a verde y 11c deja de listar
# nombres que salen a Internet. Debe terminar con 0 fallos y exit 0.
./scripts/verify-setup.sh

# Los tests de integración de Keycloak van EXPRESAMENTE por el dominio (no por
# el puerto). NO dependen de este procedimiento: fijan la resolución en el
# propio proceso (el equivalente de --resolve) y validan contra la CA de mkcert,
# así que ya pasan antes de tener el resolver. Aquí solo se confirma que siguen
# pasando cuando el DNS del sistema entra en juego.
cd backend && .venv/bin/python -m pytest -q tests/test_keycloak_admin_orgs.py
```

> ⚠️ **Sí hace falta esperar a esto.** Este párrafo decía lo contrario («no hace
> falta esperar; el stack funciona igual sin DNS»), y era cierto con
> `vendi.local` pero es falso con `vendi.co`. Traefik sigue haciendo bind en
> `127.0.0.1:443`, sí, pero lo que se pierde no es "poder teclear el nombre en
> el navegador": es que **todo cliente que no fije la resolución a mano sale a
> Internet**, y `accounts.vendi.co` responde allí con certificado válido. Ver
> «Dirección 2» arriba.
>
> Hasta completar los dos comandos con `sudo`:
>
> - `./scripts/dev.sh` **aborta** en vez de levantar el stack.
> - `./scripts/verify-setup.sh` **suspende** (checks 11b y 11c) y sale con 1.
> - La suite del backend fija la resolución y **comprueba de quién es el
>   certificado** antes de mandar ninguna credencial, así que falla cerrada.
>
> Si necesitas trabajar antes de que el dueño de la máquina pueda teclear la
> contraseña, usa el apéndice: fija la resolución en cada cliente. Lo que no
> vale es ignorar el aviso y dejar que los nombres salgan a Internet.

---

## Procedimiento B · Llegar al `vendi.co` real de producción

Necesario para mirar el sitio público, probar un despliegue, revisar un
certificado de producción o depurar DNS de verdad. En orden de menor a mayor
alcance: **usa el primero que resuelva tu problema.**

### B.0 · Sin tocar nada (sin `sudo`, sin afectar a nadie más)

Sirve para la mayoría de los casos: consultar y llegar al sitio real puntualmente.

```sh
# ¿Cuál es la IP pública real? Se pregunta a un resolver público, saltándose
# dnsmasq por completo.
dig +short @1.1.1.1 vendi.co            # p. ej. 64.190.63.222

# Llegar al sitio real fijando esa IP en el propio cliente. El SNI, la cabecera
# Host y la validación del certificado de producción siguen siendo los reales.
curl --resolve vendi.co:443:"$(dig +short @1.1.1.1 vendi.co | head -1)" https://vendi.co/
```

El navegador no tiene equivalente cómodo de esto; para navegar de verdad, pasa
a B.1.

### B.1 · Apagar solo `vendi.co` (recomendado)

Quita el resolver de **ese** dominio. dnsmasq sigue en pie y los demás dominios
locales del desarrollador (`alexandria.co`, `dynamics.co`, `forgeflow.co`,
`mailsystem.co`, `basesaas.dev`, `vendi.local`…) no se enteran.

```sh
# Apagar: se guarda, no se borra.
sudo mv /etc/resolver/vendi.co /etc/resolver/vendi.co.off
sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder

# Comprobar que ya sale a Internet:
dscacheutil -q host -a name vendi.co     # esperado: la IP pública, NO 127.0.0.1

# ... trabajar contra producción ...

# Volver a encender:
sudo mv /etc/resolver/vendi.co.off /etc/resolver/vendi.co
sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder
dscacheutil -q host -a name api.vendi.co # esperado: 127.0.0.1
```

### B.2 · Apagar dnsmasq entero (última opción)

**Cuesta caro y casi nunca es lo que quieres.** Esta máquina resuelve con
dnsmasq una docena de dominios locales de otros productos; pararlo los tumba
todos a la vez, y el síntoma en los demás stacks es un DNS que falla sin
explicación. Úsalo solo si sospechas del propio dnsmasq.

```sh
sudo brew services stop dnsmasq
sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder

# ... y en cuanto termines, sin dejarlo para luego:
sudo brew services start dnsmasq
sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder
```

Comprobación de que todo volvió, no solo Vendi:

```sh
for d in vendi.co vendi.local alexandria.co dynamics.co forgeflow.co mailsystem.co basesaas.dev; do
    printf '%-18s %s\n' "$d" "$(dig +short @127.0.0.1 "api.$d" | head -1)"
done
```

Todos deben decir `127.0.0.1`. Dos salvedades:

- `vendi.co` solo lo dirá **después** del procedimiento A; hasta entonces
  devuelve la IP pública real, porque dnsmasq todavía no ha releído la línea
  nueva. Eso no es un fallo del resto — pero tampoco es benigno: es exactamente
  la «Dirección 2» de arriba. Si lo ves, completa el procedimiento A.
- `vendi.local` está en la lista por inercia y es residuo de esta migración, no
  de otro producto. Ver «Residuo de la migración» más abajo.

### Lo que NO funciona

- **Editar `/etc/hosts` para apuntar `vendi.co` a la IP real.** `/etc/hosts` no
  admite comodines: tendrías que enumerar a mano `vendi.co`, `www.vendi.co` y
  cada subdominio que exista hoy en producción, y descubrir los que falten a
  base de errores. Además se olvida puesto, y semanas después el stack local
  «misteriosamente» deja de funcionar. Usa B.1, que es una línea y reversible.
- **Borrar la línea de `dnsmasq.conf` sin reiniciar.** No hace nada: dnsmasq
  solo lee ese archivo al arrancar.

### Residuo de la migración: `vendi.local`

Aquí decía que `address=/vendi.local/127.0.0.1` «no es de Vendi y hay otro
trabajo que depende de ella». **Es falso, y conviene corregirlo por escrito:**
`vendi.local` era exactamente el dominio anterior de este producto, y tanto esa
línea como `/etc/resolver/vendi.local` son residuo de esta misma migración. La
frase, además de equivocada, era auto-perpetuante: mientras diga que pertenece a
otro proyecto, nadie la va a limpiar nunca.

No hay ningún otro stack apuntando ahí. Se puede quitar, y así es como se hace
(el primer paso no necesita `sudo`; los otros dos sí):

```sh
# 1. Quitar la línea de dnsmasq (el archivo es escribible por el usuario).
sed -i '' '/^address=\/vendi\.local\/127\.0\.0\.1$/d' "$(brew --prefix)/etc/dnsmasq.conf"

# 2. Quitar el resolver del sistema.
sudo rm -f /etc/resolver/vendi.local

# 3. Que surta efecto.
sudo brew services restart dnsmasq
sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder
```

Comprobación de que se fue y de que no se llevó nada por delante:

```sh
dscacheutil -q host -a name api.vendi.local     # esperado: sin resultados
dscacheutil -q host -a name api.vendi.co        # esperado: 127.0.0.1
```

No es urgente —`.local` no se resuelve en Internet, así que el residuo es
inerte, no peligroso— pero mientras siga ahí conviene que diga la verdad sobre
de quién es.

---

## Certificados TLS

Los emite mkcert con la CA local, ya instalada en el llavero del sistema. No
necesitan `sudo`.

```sh
./scripts/setup-certs.sh     # lee BASE_DOMAIN del .env
cd infra && docker compose restart traefik
```

Escribe `infra/certs/${BASE_DOMAIN}.pem` y `-key.pem`, que es exactamente lo que
`infra/traefik/entrypoint.sh` referencia al renderizar la configuración
dinámica en cada arranque del contenedor. Si falta alguno, Traefik **no
arranca** y lo dice: es deliberado, para no dejar el borde a medias.

Comprobar qué cubre el certificado:

```sh
openssl x509 -in infra/certs/vendi.co.pem -noout -ext subjectAltName -dates
```

`*.vendi.co` cubre un solo nivel: `api.vendi.co` sí, `a.b.vendi.co` no. Los
dominios sintéticos de organización (`<tenant_id>.tenants.vendi.co`) **no** están
cubiertos, y no importa: nunca se sirven por HTTPS, son identificadores dentro
de Keycloak.

---

## Apéndice · Verificar sin depender del DNS

Mientras el procedimiento A esté pendiente —o para aislar un fallo de DNS de uno
de TLS o de enrutado— se fija la resolución **en el cliente**, no en el sistema.
Esto no afloja nada: el hostname, el SNI, la cabecera `Host` y el enrutado por
`Host()` de Traefik son los reales, y el certificado se valida entero contra la
CA de mkcert.

```sh
curl --resolve api.vendi.co:443:127.0.0.1      https://api.vendi.co/health
curl --resolve accounts.vendi.co:443:127.0.0.1 https://accounts.vendi.co/realms/vendi-co/.well-known/openid-configuration
curl --resolve grafana.vendi.co:443:127.0.0.1  https://grafana.vendi.co/
curl --resolve mail.vendi.co:443:127.0.0.1     https://mail.vendi.co/
```

Para navegadores headless (Playwright, Chrome):

```sh
--host-resolver-rules="MAP *.vendi.co 127.0.0.1"
```

Es lo que hace el check 11 de `verify-setup.sh`, y por eso ese check sigue en
verde con el DNS pendiente: mide el **borde**, no el DNS.

Ojo con la consecuencia, que costó un bloqueante: **el check 11 no puede
detectar la fuga de la «Dirección 2»**, porque al fijar la resolución con
`--resolve` nunca sale a Internet, por construcción. Lo que sí la detecta:

- **11b** — el resolver del sistema, para `api.vendi.co`. Distingue tres
  estados, no dos: resuelve a loopback (verde), **resuelve fuera de esta máquina
  (FALLO)**, o no resuelve (OMITIDO — falla cerrado y es inofensivo). Antes
  trataba los dos últimos como el mismo caso y se auto-omitía justo cuando había
  algo que detectar.
- **11c** — recorre `accounts`, `api`, `app`, `admin`, `grafana`, `mail` y el
  ápice, y suspende si **cualquiera** resuelve fuera. Existe porque 11b mira
  solo `api`, que es de los que fallan cerrado: mirar ahí es mirar donde el
  problema no se ve.

**Lo que sigue prohibido**, con DNS o sin él: `curl -k` / `--insecure`,
`NODE_TLS_REJECT_UNAUTHORIZED=0` y pegarle a un puerto pelado
(`http://localhost:8000`). Las tres cosas dejan de probar justo lo que hay que
probar —que la cadena de confianza y el enrutado del borde funcionan— y
convierten el verificador en decoración.
