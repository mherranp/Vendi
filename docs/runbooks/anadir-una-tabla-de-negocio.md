# Runbook · Añadir una tabla de negocio

Aplica a cualquier tabla que contenga datos **de un negocio concreto**: ventas,
productos, movimientos de caja, clientes. Si la tabla no pertenece a ningún
negocio, no es una tabla de negocio y hay una sección aparte al final.

Esto es el procedimiento de la promesa central del producto. Sáltate un paso y
la tabla queda legible por todos los negocios de la región, sin ningún error
visible.

## 1. El modelo hereda `TenantModel`

```python
from vendi_core.db.base import TenantModel

class Venta(TenantModel):
    __tablename__ = "ventas"
    # `tenant_id` y el índice `ix_ventas_tenant_id` los pone el mixin.
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
```

## 2. La migración llama a `enable_rls`

```python
from vendi_core.db.rls import enable_rls

def upgrade() -> None:
    op.create_table("ventas", ...)
    enable_rls(op, "ventas")     # ← ESTA línea es el runbook entero
```

`enable_rls` hace tres cosas y las tres importan: `ENABLE` + **`FORCE`** row
level security, la policy `tenant_isolation` con `USING` **y** `WITH CHECK`, y
el índice sobre `tenant_id`. El porqué de cada pieza está en
[ADR-013](../adr/adr-013-rls-schema-unico.md); el resumen es que sin `FORCE` el
owner se salta la policy, sin `WITH CHECK` un `UPDATE` puede **regalarle la fila
a otro negocio**, y sin índice cada consulta recorre las filas de toda la
región.

Si tu migración ya declara un índice compuesto que **empieza** por `tenant_id`
—por ejemplo `(tenant_id, creado_en)`—, pasa `crear_indice=False`. Solo en ese
caso: el orden de las columnas es el contrato, no su mera presencia.

## 3. Comprueba que el candado te ve

```bash
bash scripts/migrate.sh
cd backend && uv run pytest -q tests/test_rls_coverage.py tests/test_privilegios_de_vendi_app.py
```

Dos candados distintos, y cada uno pilla un fallo que el otro no:

- `test_rls_coverage.py` recorre `pg_class` y `pg_policy` y falla si alguna tabla
  con `tenant_id` no tiene RLS forzado, policy e índice que empiece por
  `tenant_id`.
- `test_privilegios_de_vendi_app.py` es el candado **invertido**: enumera lo
  permitido y falla ante cualquier tabla que conceda algo distinto.

**Si el segundo te falla con «no tiene `tenant_id` y no está declarada»**, es que
creaste una tabla sin columna de aislamiento. Sigue a la sección de abajo.

## 4. En el código: `SET LOCAL`, nunca `SET`

No lo escribes tú: lo emite la sesión de tenant de `vendi-core`. Lo que sí tienes
que saber es la consecuencia — **`SET LOCAL` muere en cada `commit()`**. Un
handler que hace `commit()` a mitad y sigue consultando en la misma sesión verá
**cero filas en silencio**, que es peor que un error. Si necesitas varias
transacciones, pide una sesión nueva.

Y nunca uses la sesión de **plataforma** para datos de negocio: salta RLS por
`BYPASSRLS` y no verá ni respetará ninguna policy.

---

## Si la tabla NO pertenece a ningún negocio

Entonces es una tabla de **plataforma** y no puede llevar RLS (no hay
`tenant_id` que comparar). La excepción solo se sostiene si el rol de la API no
la alcanza, así que hacen falta **tres** cosas y ninguna es opcional:

1. `REVOKE ALL ON <tabla> FROM vendi_app` en la migración. Sin esto la tabla nace
   accesible: `01-roles.sh` deja privilegios por defecto para toda tabla nueva
   creada por `vendi_platform`, que para una tabla de negocio es correcto (RLS la
   acota) y para ésta es un agujero directo.
2. Añadirla a `TABLAS_DE_PLATAFORMA` en `vendi_core.db.base`.
3. Añadirla a `PRIVILEGIOS_DE_VENDI_APP` **con el conjunto exacto** de
   privilegios que necesita —normalmente `frozenset()`— y un comentario que diga
   por qué.

Un test comprueba que las dos listas no diverjan. Si te saltas cualquiera de las
tres, el candado invertido se pone rojo, y hace bien.
