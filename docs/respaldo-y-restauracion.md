# Respaldo y restauración

Qué se respalda, qué NO, y cómo se recupera el servicio. Un respaldo que nunca
se restauró no es un respaldo: el procedimiento de abajo está pensado para
ejecutarse en un simulacro con la misma facilidad que en un incidente, y hay un
comando que lo prueba entero.

## Qué se respalda

El sidecar `postgres-backup` (`infra/docker-compose.yml`) escribe cada 24 h —y
una vez al arrancar, para que el operador vea un archivo en el primer minuto—
**tres** archivos con la MISMA marca de tiempo, que es lo único que los
empareja:

| Archivo | Qué lleva | Por qué es imprescindible |
|---|---|---|
| `vendi-<ts>.sql.gz` | Base `vendi`: los datos de la aplicación | Es el negocio |
| `keycloak-<ts>.sql.gz` | Base `keycloak`: realm, usuarios, credenciales, clientes con sus secretos, organizaciones | Es la identidad: sin ella nadie se autentica |
| `vendi-roles-<ts>.sql.gz` | Roles del clúster (`pg_dumpall --roles-only`), con sus hashes | Sin los roles, el restore falla en el primer `ALTER OWNER` |

**Las dos bases se respaldan siempre juntas, y esto no es opcional.** Como
`alias = str(tenant_id)` y el tenant se resuelve del claim `organization` del
token, una copia de `vendi` sin la de `keycloak` es una base cuyas filas apuntan
a organizaciones y usuarios que no existen en ninguna parte: nadie puede
iniciar sesión, así que nadie puede leer los datos. Restaurar media copia no
recupera un servicio.

`realm-vendi-co.json` **no sustituye** al volcado de `keycloak`: es semilla (ver
D-03 en `deuda-tecnica.md`), no lleva usuarios, ni credenciales, ni las
organizaciones que crea en caliente el aprovisionamiento de tenants.

Los volcados conservan **dueños y privilegios** a propósito (nada de
`--no-owner --no-privileges`): bajo `FORCE ROW LEVEL SECURITY`, un volcado sin
privilegios se restaura en una base que la aplicación no puede usar. El razonamiento
largo, con la medición, está en el comentario del sidecar en
`infra/docker-compose.yml`.

Retención: 7 volcados de cada tipo.

## Qué NO se respalda

Con criterio, y hay que saberlo antes del incidente, no durante:

- **MinIO / objetos subidos.** Fuera del alcance de Fase 0.
- **RabbitMQ y Redis.** Son estado transitorio y reconstruible por diseño.
- **Los secretos del `.env`.** Viven fuera del repositorio y fuera del volcado.
  Sin ellos no se levanta el stack aunque las bases estén perfectas: guárdalos
  en el gestor de secretos, no aquí.
- **Los ACL de nivel de base** (`REVOKE CONNECT ... FROM PUBLIC`). `pg_dump`
  solo los emite con `--create`, y la base destino la crea el script de
  restauración. `restore-backup.sh` los repone a mano y **verifica** que
  quedaron puestos; si restauras por tu cuenta, repónlos tú.

## Simulacro (hazlo antes de necesitarlo)

```bash
scripts/restore-backup.sh --simulacro
```

Restaura el último par a `vendi_restaurada` + `keycloak_restaurada`, verifica y
borra las bases. Códigos de salida, pensados para que una automatización no
pueda confundir «no probé nada» con «funciona»:

| Código | Significa |
|---|---|
| `0` | El respaldo restaura un sistema utilizable. Se ejecutaron todas las comprobaciones pedidas y pasaron. Con `--sin-keycloak` también sale `0`: lo pedido —solo los datos— se restauró y verificó, y el `[AVISO]` de que la identidad no se probó queda en la salida. |
| `1` | El respaldo está roto o incompleto. |
| `2` | **Inconcluso**: no se pudo verificar nada (típicamente, volcado vacío porque el esquema aún no existe). No es un aprobado. |

> Hasta la tarea 4.2 —la que crea el esquema— la base `vendi` no tiene tablas,
> así que el simulacro sale **2**. Es lo esperado, y es deliberado que no salga
> 0: sin tablas no se comprueba ni un dueño, ni un GRANT, ni una política.

**Falla —no avisa: falla— cuando:**

- falta el volcado de `keycloak` emparejado (medio respaldo);
- la copia de `vendi` no tiene ni una tabla (respaldo vacío);
- alguna tabla no es de `vendi_platform`, o `vendi_app` no tiene `SELECT`;
- `PUBLIC` conserva `CONNECT` sobre la base restaurada;
- `vendi_app` sin el GUC del tenant devuelve algo distinto de 0 filas (RLS
  dejó de ser fail-closed);
- la copia de identidad no trae el realm `vendi-co` o ningún cliente `vendi-*`.

Salida de un simulacro en verde:

```
[OK]    las 1 tablas son de vendi_platform
[OK]    vendi_app tiene SELECT sobre las 1 tablas restauradas
[OK]    PUBLIC no tiene CONNECT sobre vendi_restaurada (el ACL de base se repuso)
[OK]    vendi_app consulta ventas_prueba sin el GUC y ve 0 filas (RLS fail-closed sobrevivió al restore)
[OK]    vendi_platform lee 2 fila(s) de ventas_prueba en la copia (hay datos, no solo esquema)
[OK]    el realm vendi-co está en la copia
[OK]    los clientes vendi-* viajan en la copia (con su secreto: la API puede volver a hablar con el IdP)
[OK]    simulacro completo: el par vendi-<ts>.sql.gz + keycloak-<ts>.sql.gz restaura un sistema utilizable (datos + identidad).
```

## Recuperación real

1. **Levanta solo Postgres.** La API y Keycloak no deben escribir mientras
   restauras.

   ```bash
   docker compose -f infra/docker-compose.yml up -d postgres postgres-backup
   ```

2. **Restaura a bases nuevas y verifica**, sin tocar todavía las vivas:

   ```bash
   scripts/restore-backup.sh --archivo vendi-<ts>.sql.gz
   ```

   El script se niega a escribir sobre `vendi` o `keycloak`: eso es un paso
   manual y consciente.

3. **Promueve las copias** solo si el paso 2 salió en verde. Con todo lo demás
   parado:

   ```bash
   docker compose -f infra/docker-compose.yml stop api worker keycloak
   docker compose -f infra/docker-compose.yml exec postgres psql -U postgres \
     -c 'ALTER DATABASE vendi RENAME TO vendi_rota' \
     -c 'ALTER DATABASE keycloak RENAME TO keycloak_rota' \
     -c 'ALTER DATABASE vendi_restaurada RENAME TO vendi' \
     -c 'ALTER DATABASE keycloak_restaurada RENAME TO keycloak'
   ```

   Conserva `*_rota` hasta que el sistema lleve un rato sano. Es la única red
   que te queda si la copia resulta estar peor que el original.

4. **Arranca el resto y comprueba.** Keycloak cachea en memoria: tiene que
   arrancar *después* de que su base esté en su sitio, no antes.

   ```bash
   docker compose -f infra/docker-compose.yml up -d
   scripts/verify-setup.sh
   scripts/reconcile-keycloak.sh   # ¿cuadran organizaciones y tenants tras el corte?
   ```

## Limitación conocida: el par no es atómico

Son dos `pg_dump` distintos: cada uno es consistente consigo mismo, pero el par
no es un snapshot común. Si un alta de tenant cae justo entre los dos volcados,
la copia puede tener la organización en Keycloak sin la fila en `tenants`, o al
revés. Para Fase 0 es aceptable —el aprovisionamiento es la única escritura que
cruza las dos bases— y `scripts/reconcile-keycloak.sh` detecta el desfase
después de restaurar. Cerrarlo del todo pide un snapshot del clúster
(`pg_basebackup`) o PITR, que es trabajo de Fase 1.
