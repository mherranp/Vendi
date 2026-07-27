# Módulo catálogo (Fase 1, Etapa 1.2, módulo 1) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar el primer módulo de negocio de Fase 1 —el catálogo de productos de ADR-019— con su tabla `productos` (RLS + índices + EAN único parcial), su CRUD en la API con permisos `producto:leer`/`producto:editar` (ADR-023), aceptación de UUID de cliente como PK (ADR-017), límite de productos por tier verificado en aplicación (ADR-010), eventos de outbox `producto.creado/actualizado/eliminado`, y el contrato OpenAPI regenerado con su cliente TS. Se cierra con el gate de módulo de la Etapa 1.2 del plan maestro de Fase 1.

**Architecture:** Se mantiene la arquitectura firmada: monolito modular FastAPI (`backend/services/api`) sobre `vendi-core`, RLS en schema único con los roles `vendi_app` (sin `BYPASSRLS`) y `vendi_platform` (con `BYPASSRLS`, owner, corre las migraciones). El módulo nuevo vive en `app/modules/catalogo/` y es el primer módulo de dominio que usa la **sesión de tenant** (`sesion_de_tenant`, GUC `vendi.tenant_id` sembrado por transacción): a diferencia de `tenants` (plataforma), todas sus consultas las acota la policy `tenant_isolation`. El stock se declara pero NO se mueve aquí: `stock_actual` es una proyección del libro de movimientos que implementará el módulo de inventario (ADR-020).

**Tech Stack:** Python 3.12 · FastAPI 0.139 · SQLAlchemy 2.0 async (asyncpg) · Alembic · PostgreSQL 17 RLS · Pydantic v2 · pytest + pytest-asyncio · ruff · uv · openapi-typescript (codegen).

**Spec fuente:**
- `docs/adr/adr-019-catalogo-y-productos.md` (el diseño firmado de la tabla y los eventos)
- `docs/adr/adr-017-sincronizacion-offline-first.md` (ids UUID de cliente aceptados como PK)
- `docs/adr/adr-020-inventario-y-compras.md` (`stock_actual` como proyección; el catálogo no mueve stock)
- `docs/adr/adr-023-multi-empleado-permisos.md` (`producto:leer`, `producto:editar`; reparto por rol)
- `docs/adr/adr-010-tiers-y-precios.md` + `docs/plan-maestro.md` §5 (límites 100 / 500 / ilimitado)
- Plantillas a imitar: `backend/services/api/alembic/versions/20260723_0002_tenants.py` y `.../20260722_0001_fundacion.py` (estilo de migración y uso de `enable_rls`), `backend/services/api/app/modules/tenants/` (estructura de módulo), `backend/tests/test_cross_tenant_isolation.py` y `backend/tests/api/test_tenants_crud.py` (estilo de tests).

## Global Constraints

- Todo artefacto en español riguroso (código, docstrings, commits, mensajes de error). Sin tildes ni eñes en identificadores técnicos que viajen en tokens, URLs o JSON (`dueno`, no `dueño`).
- Toda tabla nueva de dominio lleva `tenant_id` + policy RLS vía `enable_rls(op, ...)` + índice que empieza por `tenant_id`, verificada por test de aislamiento cross-tenant contra PostgreSQL real. Los tests de integración **fallan, no se omiten**, si falta el servicio.
- El candado invertido `backend/tests/test_privilegios_de_vendi_app.py` exige EXACTAMENTE `{SELECT, INSERT, UPDATE, DELETE}` para toda tabla de negocio: cualquier desviación de grants hay que justificarla y cablearla, no improvisarla.
- TDD en cada tarea: primero el test que falla (con la salida del fallo esperada), luego la implementación completa, luego el test en verde, luego el commit. Prohibido «similar a», «agregar validación», TODO o código elidido.
- Los errores de la API usan el sobre `{"success": false, "message": "...", "code": "..."}` (`vendi_core.errors.domain` + `ErrorHandlerMiddleware`). NO se usa `require_permission` de `vendi-core` en código nuevo: lanza `HTTPException` con cuerpo `{"detail": ...}` y rompería el formato (mismo motivo por el que existe `exigir_admin_de_plataforma`).
- Los commits son por tarea, mensajes en español estilo oración. Nunca `git push` sin confirmación humana.
- Un ADR no se edita para cambiar de opinión: lo que este plan decide más allá de los ADRs queda listado en la sección siguiente, con su justificación.

## Decisiones de diseño tomadas en este plan (más allá de los ADRs)

1. **`vendi_app` conserva los cuatro privilegios sobre `productos` (DELETE incluido).** Aunque el borrado es lógico y ningún endpoint emite `DELETE` físico, revocar `DELETE` obligaría a declarar `productos` en `PRIVILEGIOS_DE_VENDI_APP`, y ese dict está atado a `TABLAS_DE_PLATAFORMA` por el test de consistencia `test_las_dos_listas_de_tablas_de_plataforma_no_pueden_divergir`: meterla ahí la excluiría del candado de cobertura RLS, que es la protección que importa. Hay precedente firmado: `files` (migración 0001) también es borrado lógico y conserva los cuatro. La purga física es del runner de retención, que corre con `vendi_platform`.
2. **El tier del negocio se resuelve hoy como `"pro"` para todos**, en una dependencia `tier_del_negocio` que es el único punto de cambio futuro. Justificación: en Fase 1 no existe módulo de suscripciones ni columna de tier en `tenants`, y el plan maestro §5 registra a todo negocio nuevo en el trial de Pro (1 mes, sin tarjeta). El límite se implementa y se testea de verdad contra el mapa `LIMITES_PRODUCTOS_POR_TIER = {"gratis": 100, "light": 500, "pro": None}` usando `dependency_overrides` y el parámetro `tier` del servicio; lo que se difiere es solo la fuente del dato, no la verificación.
3. **El borrado lógico anula `codigo_barras`** (el EAN original viaja en el payload del evento `producto.eliminado`). El índice único parcial firmado en ADR-019 es `WHERE codigo_barras IS NOT NULL` y NO excluye filas borradas: sin liberar el EAN, volver a crear un producto dado de baja («lo eliminé por error», caso común en el piloto) chocaría contra el índice para siempre. Cambiar el predicado del índice sería cambiar el ADR, y los ADRs no se editan.
4. **POST con `id` que ya existe devuelve el producto existente** (mismo 201, mismo cuerpo): es la idempotencia de ADR-017 aplicada al CRUD —reenviar la misma creación es un no-op porque la fila ya existe con la PK que le puso el cliente—. Si el id existe pero pertenece a un producto dado de baja, se rechaza con 409 `producto_id_duplicado`: un UUID de cliente no se reutiliza jamás (mismo criterio que los ids de `tenants`).
5. **Se regenera `docs/api/openapi-fase0.json`; NO se crea `openapi-fase1.json`.** El archivo congelado es la fuente única del codegen y del job `frontend-contratos` del CI, y hay ~15 referencias a su ruta en repo (CI, scripts, READMEs, comentarios). Un segundo congelado crearía dos fuentes de verdad y obligaría a tocar el CI. Se actualiza `docs/api/README.md` para que describa el contrato vigente (no «la Fase 0») y liste las rutas nuevas.
6. **El guard de permisos es una fábrica `exigir_permiso` propia** en `app/modules/catalogo/dependencies.py`, que lanza `PermissionDeniedError` con `code="permiso_ausente"` y sobre estándar, siguiendo el patrón de `exigir_admin_de_plataforma` (ver Global Constraints).
7. **El límite de tier responde 403** (`PermissionDeniedError`, code `limite_de_productos_alcanzado`): no es un dato mal formado (422) ni un choque de estado (409); es el plan del negocio diciendo «hasta aquí». El frontend lo traduce a la pantalla de ampliación de plan.
8. **`stock_actual`, `stock_minimo` y `ultimo_costo` se declaran en la tabla** (ADR-019/ADR-020) pero solo `stock_minimo` es editable por el catálogo. `stock_actual` y `ultimo_costo` son de solo lectura en la salida: los mueven inventario (movimientos) y compras, respectivamente. Los schemas de entrada no los aceptan.
9. **PATCH no puede poner `codigo_barras` a `null`** (convención del repo: `None` = «no lo toques», igual que `TenantActualizar`). Liberar un EAN ocurre solo al dar de baja el producto.

---

## Tarea 1: Migración `0004_catalogo` — tabla `productos` con RLS, índices y grants

**Files:**
- Create: `backend/tests/test_aislamiento_productos.py` (primero: el test que falla)
- Create: `backend/services/api/alembic/versions/20260728_0004_catalogo.py`

**Interfaces:**
- Consume: `vendi_core.db.rls.enable_rls` / `disable_rls` (texto de policy fijado por el spike de RLS), fixtures `pg_app_url` / `pg_platform_url` y datos `T1`/`T2` de `backend/tests/datos_de_prueba.py`.
- Produce: la tabla `productos` migrada con policy `tenant_isolation`, índice `ix_productos_tenant_nombre` `(tenant_id, nombre)`, índice único parcial `ux_productos_ean`, checks de `unidad_medida` e `iva_pct`, y grants por defecto (los cuatro) para `vendi_app`.

- [ ] **Paso 1: escribir el test de aislamiento que falla.** Crear `backend/tests/test_aislamiento_productos.py`:

```python
"""Aislamiento cross-tenant y unicidad del EAN sobre la tabla real `productos`.

Hermano de `test_cross_tenant_isolation.py`, mismo criterio: SQL crudo con el
rol `vendi_app` y nada de ORM, para que ningún `WHERE` amable del ORM dé un
falso verde sobre una policy que no filtra. La tabla la crea la migración
`0004_catalogo`; hasta que existe, TODOS estos tests fallan — que es el punto
del paso TDD.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def productos_de_prueba(pg_platform_url: str):
    """Una fila por negocio, con el MISMO EAN en los dos (válido: el índice
    único es por tenant). Limpia antes y después: la suite es re-entrante."""
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM productos WHERE tenant_id = ANY(:ids)"), {"ids": [T1, T2]})
        for tenant in (T1, T2):
            await conn.execute(
                text("INSERT INTO productos (tenant_id, nombre, codigo_barras) VALUES (:t, 'Arroz 500g', '770000000001')"),
                {"t": tenant},
            )
    try:
        yield
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM productos WHERE tenant_id = ANY(:ids)"), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def sesion_t1(pg_app_url: str, productos_de_prueba):
    """Sesión de `vendi_app` con el negocio T1 en contexto."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield s
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


@pytest.mark.asyncio
async def test_select_solo_ve_los_productos_del_propio_tenant(sesion_t1):
    filas = (await sesion_t1.execute(text("SELECT tenant_id, nombre FROM productos"))).all()
    assert len(filas) == 1
    assert filas[0][0] == T1


@pytest.mark.asyncio
async def test_update_no_toca_productos_ajenos(sesion_t1):
    resultado = await sesion_t1.execute(text("UPDATE productos SET precio_venta = 2500"))
    assert resultado.rowcount == 1, "el UPDATE sin WHERE tocó productos de otro negocio"


@pytest.mark.asyncio
async def test_insert_con_tenant_ajeno_lo_bloquea_with_check(sesion_t1):
    with pytest.raises((DBAPIError, ProgrammingError), match="row-level security"):
        await sesion_t1.execute(
            text("INSERT INTO productos (tenant_id, nombre) VALUES (:t, 'Fuga')"),
            {"t": T2},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_mismo_ean_cabe_en_dos_tenants(pg_platform_url: str, productos_de_prueba):
    """El fixture ya insertó el EAN '770000000001' en T1 y en T2. Si el índice
    único parcial fuera global en vez de por tenant, el fixture no habría
    podido sembrar y este test no correría."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            cuantos = (
                await conn.execute(
                    text("SELECT count(*) FROM productos WHERE codigo_barras = '770000000001'"),
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert cuantos == 2


@pytest.mark.asyncio
async def test_el_ean_duplicado_en_el_mismo_tenant_se_rechaza(sesion_t1):
    with pytest.raises(IntegrityError, match="ux_productos_ean"):
        await sesion_t1.execute(
            text("INSERT INTO productos (tenant_id, nombre, codigo_barras) VALUES (:t, 'Otro arroz', '770000000001')"),
            {"t": T1},
        )
    await sesion_t1.rollback()


@pytest.mark.asyncio
async def test_el_ean_queda_libre_al_liberarlo_en_el_borrado_logico(sesion_t1):
    """Decisión 3 del plan: el índice firmado en ADR-019 NO excluye filas
    borradas, así que el borrado lógico anula `codigo_barras` para liberar el
    EAN. Este test fija que, liberado, el EAN se puede reusar en el mismo
    tenant."""
    await sesion_t1.execute(
        text("UPDATE productos SET deleted_at = now(), codigo_barras = NULL WHERE codigo_barras = '770000000001'")
    )
    await sesion_t1.execute(
        text("INSERT INTO productos (tenant_id, nombre, codigo_barras) VALUES (:t, 'Arroz nuevo', '770000000001')"),
        {"t": T1},
    )
    await sesion_t1.rollback()
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_aislamiento_productos.py -q
```

Esperado: 6 errores/fallos con `relation "productos" does not exist`.

- [ ] **Paso 2: escribir la migración.** Crear `backend/services/api/alembic/versions/20260728_0004_catalogo.py`:

```python
"""Catálogo: tabla `productos` (ADR-019). Primera tabla de negocio de Fase 1.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-28

## Las columnas y su porqué (todo viene de ADR-019, firmado)

- Una fila = un ítem vendible. `padre_id` autorreferencia al producto base:
  las variantes son filas más, cada una con su EAN, su precio y su stock.
- `codigo_barras TEXT NULL` con índice único parcial
  `(tenant_id, codigo_barras) WHERE codigo_barras IS NOT NULL`: opcional
  porque el granel no tiene EAN; único porque el escáner (ADR-024) necesita
  que un código resuelva a exactamente un producto.
- Cantidades en NUMERIC (el fruver se vende a 0,350 kg) y dinero en enteros
  de centavos (`precio_venta`, `ultimo_costo`), criterio unificado con
  ADR-018: el dinero nunca se representa en flotante.
- `iva_pct NUMERIC(5,2)` con CHECK contra las tres tarifas vigentes en
  Colombia (0, 5, 19). El IVA es dato del producto, no un módulo fiscal.
- `stock_actual` y `ultimo_costo` se DECLARAN aquí pero el catálogo no los
  mueve: `stock_actual` es una proyección del libro de movimientos de
  inventario y `ultimo_costo` lo actualizan las compras (ADR-020).
- Borrado lógico (`deleted_at`), como en `tenants`: el historial de ventas
  referencia productos que ya no se venden.

## Por qué `vendi_app` conserva los cuatro privilegios (DELETE incluido)

Revocar DELETE (borrado lógico: la API «nunca» borra) obligaría a declarar
`productos` en `PRIVILEGIOS_DE_VENDI_APP`, y ese dict está atado a
`TABLAS_DE_PLATAFORMA` por un test de consistencia: meterla ahí la sacaría
del candado de cobertura RLS, que es la protección que importa. Además hay
precedente firmado: `files` (migración 0001) también es borrado lógico y
conserva los cuatro. La defensa del borrado es la lógica de aplicación —los
servicios marcan `deleted_at` y ningún endpoint emite DELETE físico— más la
RLS, que acota cualquier daño al propio negocio. La purga física la hace el
runner de retención con `vendi_platform`, que no pasa por estos grants.

## Los índices

`ix_productos_tenant_nombre` empieza por `tenant_id` (regla de ADR-013: el
predicado de la policy se resuelve como `Index Cond`) y cubre además el
listado ordenado por nombre del POS, así que `enable_rls` va con
`crear_indice=False` para no crear un `ix_productos_tenant_id` redundante.
El candado `test_rls_coverage.py` lo acepta porque el índice compuesto ya
empieza por `tenant_id`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vendi_core.db.rls import disable_rls, enable_rls

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIDADES = ("unidad", "kg", "g", "lt", "ml")


def upgrade() -> None:
    op.create_table(
        "productos",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # FK a sí misma sin RLS en la comprobación: Postgres NO aplica las
        # policies al verificar llaves foráneas, así que la pertenencia del
        # padre al mismo tenant se valida en la aplicación
        # (`CatalogoService._exigir_padre`), no aquí.
        sa.Column(
            "padre_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("productos.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("codigo_barras", sa.Text(), nullable=True),
        sa.Column("categoria", sa.Text(), nullable=True),
        sa.Column("unidad_medida", sa.String(8), server_default="unidad", nullable=False),
        # Dinero en centavos enteros (ADR-018/ADR-019): jamás flotante.
        sa.Column("precio_venta", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ultimo_costo", sa.Integer(), server_default="0", nullable=False),
        sa.Column("iva_pct", sa.Numeric(5, 2), server_default="0", nullable=False),
        # Cantidades decimales (granel): el fruver se vende a 0,350 kg.
        sa.Column("stock_actual", sa.Numeric(14, 3), server_default="0", nullable=False),
        sa.Column("stock_minimo", sa.Numeric(14, 3), server_default="0", nullable=False),
        sa.CheckConstraint(
            "unidad_medida IN (" + ", ".join(f"'{u}'" for u in UNIDADES) + ")",
            name="ck_productos_unidad_medida",
        ),
        sa.CheckConstraint("iva_pct IN (0, 5, 19)", name="ck_productos_iva_pct"),
        sa.CheckConstraint("precio_venta >= 0", name="ck_productos_precio_no_negativo"),
        sa.CheckConstraint("ultimo_costo >= 0", name="ck_productos_costo_no_negativo"),
    )
    op.create_index("ix_productos_deleted_at", "productos", ["deleted_at"])
    # Empieza por tenant_id: sirve al predicado RLS como Index Cond y al
    # listado del POS ordenado por nombre (consecuencia firmada de ADR-019).
    op.create_index("ix_productos_tenant_nombre", "productos", ["tenant_id", "nombre"])
    # El EAN es único POR NEGOCIO y solo cuando existe: el granel no tiene.
    op.execute(
        "CREATE UNIQUE INDEX ux_productos_ean ON productos (tenant_id, codigo_barras) "
        "WHERE codigo_barras IS NOT NULL"
    )
    # crear_indice=False: `ix_productos_tenant_nombre` ya empieza por tenant_id
    # (ver la cabecera). El candado test_rls_coverage lo verifica igual.
    enable_rls(op, "productos", crear_indice=False)

    # Grants: los privilegios por defecto de 01-roles.sh ya conceden SELECT,
    # INSERT, UPDATE y DELETE a vendi_app sobre toda tabla creada por
    # vendi_platform, y es lo que el candado invertido
    # (test_privilegios_de_vendi_app.py) exige para una tabla de negocio. No se
    # toca nada aquí a propósito; la justificación está en la cabecera.


def downgrade() -> None:
    disable_rls(op, "productos", borrar_indice=False)
    op.execute("DROP INDEX IF EXISTS ux_productos_ean")
    op.drop_index("ix_productos_tenant_nombre", table_name="productos")
    op.drop_index("ix_productos_deleted_at", table_name="productos")
    op.drop_table("productos")
```

- [ ] **Paso 3: aplicar la migración y verificar el DDL real.** Con el stack levantado (`bash scripts/dev.sh`):

```bash
bash scripts/migrate.sh
docker compose -f infra/docker-compose.yml exec -T postgres psql -U vendi_platform -d vendi -c "\d productos"
```

Esperado: la tabla con las 14 columnas, los 4 checks, los 3 índices (`ix_productos_tenant_nombre`, `ix_productos_deleted_at`, `ux_productos_ean` parcial), `Policies: tenant_isolation` y `Row Level Security: enabled (forced)`.

- [ ] **Paso 4: el test del Paso 1 pasa, y los tres candados siguen verdes.**

```bash
cd backend && uv run pytest tests/test_aislamiento_productos.py -q
# Esperado: 6 passed
uv run pytest tests/test_rls_coverage.py tests/test_privilegios_de_vendi_app.py -q -m integration
# Esperado: todos passed (productos aparece en la cobertura con RLS y los cuatro grants, sin tocar esos archivos)
```

- [ ] **Paso 5: commit**

```bash
git add backend/services/api/alembic/versions/20260728_0004_catalogo.py backend/tests/test_aislamiento_productos.py
git commit -m "Migración 0004: tabla productos del catálogo con RLS, EAN único por negocio e índice por tenant"
```

**Criterios de aceptación:**
- `bash scripts/migrate.sh` aplica `0004` limpio sobre una base al día, y el `downgrade`+`upgrade` también corre (`alembic downgrade 0003 && alembic upgrade head` dentro del contenedor de migración).
- Los 6 tests de aislamiento pasan contra PostgreSQL real, 0 SKIPPED.
- `test_rls_coverage.py` y `test_privilegios_de_vendi_app.py` verdes **sin edición**: la tabla nueva entra sola en ambos candados.

---

## Tarea 2: Modelo SQLAlchemy `Producto`

**Files:**
- Create: `backend/tests/test_catalogo_modelo.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/catalogo/__init__.py` (vacío)
- Create: `backend/services/api/app/modules/catalogo/models.py`
- Modify: `backend/tests/test_rls_coverage.py` (un import: registra el modelo en el metadata del candado de nivel 1)

**Interfaces:**
- Consume: `vendi_core.db.base.Base`, `TenantModel` (PK UUID + `tenant_id` + timestamps), `SoftDeleteMixin` (`deleted_at`).
- Produce: la tabla `productos` registrada en `Base.metadata`, alineada columna a columna con la migración 0004.

- [ ] **Paso 1: escribir el test que falla.** Crear `backend/tests/test_catalogo_modelo.py`:

```python
"""El modelo `Producto` contra el metadata, sin base de datos.

Es el nivel barato de los candados: corre en cada `pytest` y en cada PR. Lo
caro —que la base migrada tenga la policy, los índices y los grants— lo
cubren `test_rls_coverage.py`, `test_privilegios_de_vendi_app.py` y
`test_aislamiento_productos.py`.
"""

from __future__ import annotations

from app.modules.catalogo.models import Producto
from sqlalchemy import CheckConstraint

from vendi_core.db.base import Base, verificar_indices_de_tenant


def test_productos_hereda_tenant_model_y_borrado_logico():
    columnas = Producto.__table__.columns
    for nombre in (
        "id", "tenant_id", "created_at", "updated_at", "deleted_at",
        "padre_id", "nombre", "codigo_barras", "categoria", "unidad_medida",
        "precio_venta", "ultimo_costo", "iva_pct", "stock_actual", "stock_minimo",
    ):
        assert nombre in columnas, f"falta la columna {nombre}"
    assert columnas["tenant_id"].nullable is False
    assert columnas["codigo_barras"].nullable is True, "el EAN es opcional: el granel no tiene (ADR-019)"
    assert columnas["deleted_at"].nullable is True


def test_la_regla_del_indice_de_tenant_se_cumple_con_el_modelo_registrado():
    # Importar el modelo ya lo registró en el metadata; el candado recorre
    # TODAS las tablas declaradas, no solo ésta.
    assert "productos" not in verificar_indices_de_tenant(Base.metadata)


def test_el_indice_unico_del_ean_es_parcial():
    indice = next(i for i in Producto.__table__.indexes if i.name == "ux_productos_ean")
    assert indice.unique is True
    assert [c.name for c in indice.columns] == ["tenant_id", "codigo_barras"]
    assert indice.dialect_options["postgresql"]["where"] is not None, (
        "sin el WHERE la unicidad aplicaría también a los NULL y solo cabría UN producto sin EAN por negocio"
    )


def test_el_indice_de_listado_empieza_por_tenant():
    indice = next(i for i in Producto.__table__.indexes if i.name == "ix_productos_tenant_nombre")
    assert [c.name for c in indice.columns] == ["tenant_id", "nombre"]


def test_los_checks_fijan_unidades_tarifas_y_dinero_no_negativo():
    checks = {c.name for c in Producto.__table__.constraints if isinstance(c, CheckConstraint)}
    assert {
        "ck_productos_unidad_medida",
        "ck_productos_iva_pct",
        "ck_productos_precio_no_negativo",
        "ck_productos_costo_no_negativo",
    } <= checks
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_catalogo_modelo.py -q
```

Esperado: error de colección `ModuleNotFoundError: No module named 'app.modules.catalogo'`.

- [ ] **Paso 2: implementar el modelo.** Crear `backend/services/api/app/modules/catalogo/__init__.py` vacío y `backend/services/api/app/modules/catalogo/models.py`:

```python
"""Modelo del catálogo: una fila = un ítem vendible (ADR-019).

`Producto` hereda `TenantModel` (PK UUID + `tenant_id` + timestamps) y
`SoftDeleteMixin` (`deleted_at`): es tabla DE NEGOCIO, con policy
`tenant_isolation` puesta por la migración 0004, y borrado lógico porque el
historial de ventas referencia productos que ya no se venden.

Dos cosas que este archivo NO hace, a propósito:

- No mueve stock. `stock_actual` es una proyección del libro de movimientos
  de inventario (ADR-020) y `ultimo_costo` lo actualizan las compras. Aquí
  solo se declaran; el único campo de stock editable por el catálogo es
  `stock_minimo` (el umbral de las alertas).
- No declara el `id` como autogenerado por el cliente ni por el servidor de
  forma exclusiva: `TenantModel` ya deja ambos caminos (`default` de Python y
  `server_default`), y el servicio acepta el UUID que traiga el cliente
  (ADR-017: es lo que hace al sync idempotente de raíz).

El índice único del EAN se declara aquí (para que el metadata sea fiel a la
base) y se crea en la migración (para que exista de verdad); las dos
definiciones deben coincidir y `test_catalogo_modelo.py` vigila ésta.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import UUID, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from vendi_core.db.base import Base, SoftDeleteMixin, TenantModel

#: Las cinco unidades del ADR-019. Se guardan como texto con CHECK, no como
#: ENUM de Postgres: el conjunto es corto y estable, y cambiar un enum es DDL
#: con sus propias reglas (mismo criterio que `estado` en `tenants`).
UNIDADES_DE_MEDIDA: tuple[str, ...] = ("unidad", "kg", "g", "lt", "ml")

#: Las tres tarifas de IVA vigentes en Colombia. Cuando llegue la DIAN (Fase
#: 2) esto se amplía, no se reescribe: `iva_pct` ya está en el sitio correcto.
TARIFAS_DE_IVA: tuple[Decimal, ...] = (Decimal("0"), Decimal("5"), Decimal("19"))


class Producto(Base, TenantModel, SoftDeleteMixin):
    """Un ítem vendible de un negocio. La variante es una fila más (`padre_id`)."""

    __tablename__ = "productos"
    __table_args__ = (
        # Sustituye al `ix_productos_tenant_id` que `TenantModel` declara por
        # defecto: éste también empieza por `tenant_id` (cumple la regla del
        # predicado RLS) y además ordena el listado del POS por nombre.
        Index("ix_productos_tenant_nombre", "tenant_id", "nombre"),
        # El EAN es único POR NEGOCIO y solo cuando existe. Sin el WHERE,
        # todos los NULL chocarían entre sí y un negocio solo podría tener UN
        # producto sin código de barras.
        Index(
            "ux_productos_ean",
            "tenant_id",
            "codigo_barras",
            unique=True,
            postgresql_where=text("codigo_barras IS NOT NULL"),
        ),
        CheckConstraint(
            "unidad_medida IN (" + ", ".join(f"'{u}'" for u in UNIDADES_DE_MEDIDA) + ")",
            name="ck_productos_unidad_medida",
        ),
        CheckConstraint("iva_pct IN (0, 5, 19)", name="ck_productos_iva_pct"),
        CheckConstraint("precio_venta >= 0", name="ck_productos_precio_no_negativo"),
        CheckConstraint("ultimo_costo >= 0", name="ck_productos_costo_no_negativo"),
    )

    #: La variante apunta al producto base. Postgres NO aplica RLS al
    #: verificar llaves foráneas, así que la pertenencia del padre al mismo
    #: negocio la valida el servicio, no la base.
    padre_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("productos.id", ondelete="RESTRICT"),
        nullable=True,
    )
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    #: Opcional: gran parte del surtido de barrio no tiene EAN (granel, huevo
    #: por unidad). Único por negocio cuando existe (ver `ux_productos_ean`).
    codigo_barras: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Texto libre, no tabla: la clasificación ABC es un cálculo sobre ventas,
    #: no una taxonomía que mantener (ADR-019).
    categoria: Mapped[str | None] = mapped_column(Text, nullable=True)
    unidad_medida: Mapped[str] = mapped_column(String(8), default="unidad", server_default="unidad", nullable=False)
    #: Dinero en centavos enteros, jamás flotante (criterio unificado ADR-018).
    precio_venta: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    #: Lo actualiza cada compra registrada (ADR-020). El catálogo solo lo lee.
    ultimo_costo: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    iva_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0"), server_default="0", nullable=False
    )
    #: Proyección del libro de movimientos. Puede quedar NEGATIVO y es un
    #: estado legítimo (ADR-020): la tienda ya vendió físicamente esa unidad.
    stock_actual: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal("0"), server_default="0", nullable=False
    )
    stock_minimo: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal("0"), server_default="0", nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Producto {self.id} {self.nombre!r}>"
```

- [ ] **Paso 3: registrar el modelo en el candado de nivel 1.** En `backend/tests/test_rls_coverage.py`, añadir junto a los imports de modelos (con su comentario):

```python
from app.modules.catalogo.models import Producto  # noqa: F401
```

- [ ] **Paso 4: verificar.**

```bash
cd backend && uv run pytest tests/test_catalogo_modelo.py tests/test_rls_coverage.py -q -m 'not integration'
# Esperado: 6 passed (5 del modelo + 1 del candado de nivel 1)
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 5: commit**

```bash
git add backend/services/api/app/modules/catalogo/__init__.py backend/services/api/app/modules/catalogo/models.py backend/tests/test_catalogo_modelo.py backend/tests/test_rls_coverage.py
git commit -m "Modelo Producto del catálogo alineado con la migración 0004"
```

**Criterios de aceptación:** los 5 tests del modelo pasan sin base de datos; el candado de nivel 1 de RLS sigue verde con el modelo registrado; `ruff` limpio.

---

## Tarea 3: Schemas Pydantic del catálogo

**Files:**
- Create: `backend/tests/test_catalogo_schemas.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/catalogo/schemas.py`

**Interfaces:**
- Consume: `UNIDADES_DE_MEDIDA` y `TARIFAS_DE_IVA` del modelo (una sola fuente).
- Produce: `ProductoCrear`, `ProductoActualizar`, `ProductoSalida`. Es el contrato que congela el OpenAPI: cada cambio aquí es un cambio de contrato.

- [ ] **Paso 1: escribir el test que falla.** Crear `backend/tests/test_catalogo_schemas.py`:

```python
"""Validación de entrada del catálogo, sin base de datos.

Lo que se prueba aquí es lo que el 422 le promete al tendero: que un precio
negativo, una tarifa de IVA que no existe o una unidad inventada no llegan
jamás a la base.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.modules.catalogo.schemas import ProductoActualizar, ProductoCrear, ProductoSalida
from pydantic import ValidationError


def test_crear_acepta_un_producto_minimo():
    datos = ProductoCrear(nombre="Arroz 500g", precio_venta=2500)
    assert datos.id is None
    assert datos.unidad_medida == "unidad"
    assert datos.iva_pct == Decimal("0")
    assert datos.codigo_barras is None


def test_crear_acepta_el_uuid_del_cliente():
    """ADR-017: el dispositivo genera el id y el servidor lo acepta como PK."""
    el_id = uuid.uuid4()
    assert ProductoCrear(id=el_id, nombre="Huevo", precio_venta=500).id == el_id


def test_el_precio_no_puede_ser_negativo():
    with pytest.raises(ValidationError):
        ProductoCrear(nombre="Arroz", precio_venta=-1)


def test_el_iva_solo_admite_las_tres_tarifas_de_colombia():
    with pytest.raises(ValidationError):
        ProductoCrear(nombre="Arroz", precio_venta=100, iva_pct=Decimal("8"))
    for tarifa in ("0", "5", "19"):
        assert ProductoCrear(nombre="Arroz", precio_venta=100, iva_pct=Decimal(tarifa)).iva_pct == Decimal(tarifa)


def test_la_unidad_solo_admite_las_cinco_del_adr():
    with pytest.raises(ValidationError):
        ProductoCrear(nombre="Arroz", precio_venta=100, unidad_medida="bulto")
    assert ProductoCrear(nombre="Fruver", precio_venta=100, unidad_medida="kg").unidad_medida == "kg"


def test_el_ean_en_blanco_se_normaliza_a_none():
    """Un EAN vacío no es un EAN: sin esta normalización, el segundo producto
    sin código chocaría con el primero en el índice único (cadena vacía)."""
    assert ProductoCrear(nombre="Arroz", precio_venta=100, codigo_barras="   ").codigo_barras is None
    assert ProductoCrear(nombre="Arroz", precio_venta=100, codigo_barras=" 7701 ").codigo_barras == "7701"


def test_el_nombre_se_limpia_de_espacios():
    assert ProductoCrear(nombre="  Arroz   500g ", precio_venta=100).nombre == "Arroz 500g"


def test_actualizar_es_todo_opcional_y_none_es_no_tocar():
    datos = ProductoActualizar()
    assert datos.model_dump(exclude_unset=True) == {}
    assert ProductoActualizar(precio_venta=3000).precio_venta == 3000


def test_actualizar_rechaza_los_mismos_valores_invalidos():
    with pytest.raises(ValidationError):
        ProductoActualizar(iva_pct=Decimal("7"))
    with pytest.raises(ValidationError):
        ProductoActualizar(unidad_medida="arroba")


def test_salida_expone_el_stock_y_el_costo_solo_como_lectura():
    """`stock_actual` y `ultimo_costo` están en la salida (los lee el POS) y
    NO en los schemas de entrada (los mueven inventario y compras, ADR-020)."""
    campos_entrada = set(ProductoCrear.model_fields) | set(ProductoActualizar.model_fields)
    assert "stock_actual" not in campos_entrada
    assert "ultimo_costo" not in campos_entrada
    assert {"stock_actual", "ultimo_costo", "stock_minimo"} <= set(ProductoSalida.model_fields)
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_catalogo_schemas.py -q
```

Esperado: error de colección `ModuleNotFoundError: No module named 'app.modules.catalogo.schemas'`.

- [ ] **Paso 2: implementar los schemas.** Crear `backend/services/api/app/modules/catalogo/schemas.py`:

```python
"""Esquemas de entrada y salida del catálogo.

El contrato que consume el frontend sale de aquí vía `openapi.json`, así que
cada cambio en estos modelos es un cambio de contrato: se regenera
`docs/api/openapi-fase0.json` y con él el cliente de Angular.

Dinero en centavos enteros (`precio_venta`, `ultimo_costo`); cantidades en
`Decimal` (`stock_minimo`, `stock_actual`), nunca flotante (ADR-019/ADR-018).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.catalogo.models import TARIFAS_DE_IVA, UNIDADES_DE_MEDIDA

LARGO_MAX_NOMBRE = 160


def _limpiar_texto(valor: str) -> str:
    return " ".join(valor.split())


def _validar_unidad(valor: str) -> str:
    if valor not in UNIDADES_DE_MEDIDA:
        raise ValueError(f"La unidad de medida debe ser una de: {', '.join(UNIDADES_DE_MEDIDA)}.")
    return valor


def _validar_iva(valor: Decimal) -> Decimal:
    if valor not in TARIFAS_DE_IVA:
        raise ValueError("El IVA debe ser 0, 5 o 19: son las tarifas vigentes en Colombia.")
    return valor


def _normalizar_ean(valor: str | None) -> str | None:
    """Un EAN en blanco es NULL, no cadena vacía: el índice único parcial
    trata los NULL como ausencia, y una cadena vacía chocaría con la
    siguiente."""
    if valor is None:
        return None
    limpio = valor.strip()
    return limpio or None


class ProductoCrear(BaseModel):
    #: UUID generado por el cliente (ADR-017). El servidor lo acepta como PK:
    #: reenviar la misma creación es un no-op porque la fila ya existe.
    id: uuid.UUID | None = None
    nombre: str = Field(min_length=1, max_length=LARGO_MAX_NOMBRE)
    codigo_barras: str | None = Field(default=None, max_length=64)
    categoria: str | None = Field(default=None, max_length=120)
    unidad_medida: str = "unidad"
    precio_venta: int = Field(ge=0)
    iva_pct: Decimal = Decimal("0")
    stock_minimo: Decimal = Field(default=Decimal("0"), ge=0)
    padre_id: uuid.UUID | None = None

    _nombre_limpio = field_validator("nombre")(lambda v: _limpiar_texto(v))
    _ean_normalizado = field_validator("codigo_barras")(_normalizar_ean)
    _unidad_valida = field_validator("unidad_medida")(_validar_unidad)
    _iva_valido = field_validator("iva_pct")(_validar_iva)


class ProductoActualizar(BaseModel):
    """Todo opcional: es un PATCH. `None` significa "no lo toques" (misma
    convención que `TenantActualizar`).

    No lleva `stock_actual` ni `ultimo_costo`: el stock lo mueven los
    movimientos de inventario y el costo las compras (ADR-020). Un endpoint
    que dejara editar el contador a mano rompería la invariante del libro.
    """

    nombre: str | None = Field(default=None, min_length=1, max_length=LARGO_MAX_NOMBRE)
    codigo_barras: str | None = Field(default=None, max_length=64)
    categoria: str | None = Field(default=None, max_length=120)
    unidad_medida: str | None = None
    precio_venta: int | None = Field(default=None, ge=0)
    iva_pct: Decimal | None = None
    stock_minimo: Decimal | None = Field(default=None, ge=0)
    padre_id: uuid.UUID | None = None

    _nombre_limpio = field_validator("nombre")(lambda v: None if v is None else _limpiar_texto(v))
    _ean_normalizado = field_validator("codigo_barras")(_normalizar_ean)
    _unidad_valida = field_validator("unidad_medida")(lambda v: None if v is None else _validar_unidad(v))
    _iva_valido = field_validator("iva_pct")(lambda v: None if v is None else _validar_iva(v))


class ProductoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    padre_id: uuid.UUID | None = None
    nombre: str
    codigo_barras: str | None = None
    categoria: str | None = None
    unidad_medida: str
    precio_venta: int
    ultimo_costo: int
    iva_pct: Decimal
    stock_actual: Decimal
    stock_minimo: Decimal
    created_at: datetime | None = None
```

- [ ] **Paso 3: verificar.**

```bash
cd backend && uv run pytest tests/test_catalogo_schemas.py -q
# Esperado: 10 passed
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/catalogo/schemas.py backend/tests/test_catalogo_schemas.py
git commit -m "Schemas del catálogo: dinero en centavos, IVA y unidades validadas, UUID de cliente"
```

**Criterios de aceptación:** los 10 tests pasan; ningún schema de entrada acepta `stock_actual` ni `ultimo_costo`; `ruff` limpio.

---

## Tarea 4: Permisos `producto:leer` / `producto:editar` en `vendi-core` (ADR-023)

**Files:**
- Modify: `backend/tests/test_auth_policies.py` (primero: los tests que fallan)
- Modify: `backend/libs/vendi-core/src/vendi_core/auth/policies.py`

**Interfaces:**
- Consume: `PERMISSION_CATALOG`, `PERMISOS_POR_ROL`, `roles_de_realm_del_grupo` (la siembra `app/scripts/seed.py` los lee: `ensure_realm_role` por cada permiso del catálogo y `set_group_realm_roles` con el diff por grupo, así que **no hay que tocar la siembra**: re-ejecutarla basta).
- Produce: los dos permisos de catálogo declarados y repartidos: `dueno` ambos, `cajero` solo `producto:leer`, `almacenista` ambos.

- [ ] **Paso 1: actualizar los tests que fallan.** En `backend/tests/test_auth_policies.py`:

  a) En `test_el_catalogo_declara_los_permisos_de_negocio_de_fase_0`, renombrar a `test_el_catalogo_declara_los_permisos` y ampliar el conjunto esperado:

```python
def test_el_catalogo_declara_los_permisos():
    nombres = {p[0] for p in PERMISSION_CATALOG}
    assert nombres == {
        PERM_TENANT_READ,
        PERM_TENANT_CREATE,
        PERM_TENANT_UPDATE,
        PERM_TENANT_DELETE,
        PERM_PLATFORM_ADMIN,
        PERM_AUDIT_READ,
        PERM_PRODUCTO_LEER,
        PERM_PRODUCTO_EDITAR,
    }
```

  b) Reemplazar `test_cajero_y_almacenista_estan_declarados_y_vacios_a_proposito` por:

```python
def test_el_reparto_de_permisos_de_catalogo_es_el_de_adr_023():
    """El cajero vende y consulta el catálogo, pero NO lo edita; el
    almacenista lo mantiene. Eso es lo que ADR-023 firma para estos dos
    permisos: el resto de sus permisos llega con sus módulos."""
    assert PERMISOS_POR_ROL[ROL_CAJERO] == frozenset({PERM_PRODUCTO_LEER})
    assert PERMISOS_POR_ROL[ROL_ALMACENISTA] == frozenset({PERM_PRODUCTO_LEER, PERM_PRODUCTO_EDITAR})
    assert {PERM_PRODUCTO_LEER, PERM_PRODUCTO_EDITAR} <= PERMISOS_POR_ROL[ROL_DUENO]


def test_todo_permiso_asignado_a_un_rol_esta_en_el_catalogo():
    """Candado de ADR-023: `PERMISOS_POR_ROL` no puede prometer un permiso
    que la siembra no crea como rol de realm."""
    declarados = {p[0] for p in PERMISSION_CATALOG}
    for rol, permisos in PERMISOS_POR_ROL.items():
        assert permisos <= declarados, f"el rol {rol} tiene permisos fuera del catálogo: {permisos - declarados}"
```

  c) Añadir al import de `vendi_core.auth.policies` los nombres `PERM_PRODUCTO_LEER` y `PERM_PRODUCTO_EDITAR`.

  d) En `test_el_grupo_de_un_rol_mapea_el_rol_y_sus_permisos`, reemplazar el comentario y la aserción final (que afirmaba que cajero no tiene permisos) por:

```python
    # Cajero ya tiene su primer permiso (ADR-023): el grupo mapea el rol Y
    # producto:leer, en orden estable.
    assert roles_de_realm_del_grupo(ROL_CAJERO) == sorted({ROL_CAJERO, PERM_PRODUCTO_LEER})
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_auth_policies.py -q
```

Esperado: fallos con `ImportError: cannot import name 'PERM_PRODUCTO_LEER'`.

- [ ] **Paso 2: implementar en `policies.py`.** En `backend/libs/vendi-core/src/vendi_core/auth/policies.py`:

  a) Tras `PERM_AUDIT_READ`, añadir:

```python
# Catálogo de productos (ADR-019/ADR-023)
PERM_PRODUCTO_LEER = "producto:leer"
PERM_PRODUCTO_EDITAR = "producto:editar"
```

  b) Ampliar `PERMISSION_CATALOG`:

```python
PERMISSION_CATALOG: tuple[tuple[str, str], ...] = (
    (PERM_TENANT_READ, "tenant"),
    (PERM_TENANT_CREATE, "tenant"),
    (PERM_TENANT_UPDATE, "tenant"),
    (PERM_TENANT_DELETE, "tenant"),
    (PERM_PLATFORM_ADMIN, "platform"),
    (PERM_AUDIT_READ, "audit"),
    (PERM_PRODUCTO_LEER, "producto"),
    (PERM_PRODUCTO_EDITAR, "producto"),
)
```

  c) Ampliar `_PERMISOS_DUENO` con los dos permisos nuevos, y reemplazar el bloque de cajero/almacenista vacíos por:

```python
# El reparto de ADR-023 para el catálogo: el cajero consulta el catálogo para
# vender pero NO lo edita; el almacenista es quien lo mantiene. El resto de
# permisos de cada rol llega con su módulo (ventas, caja, inventario...).
_PERMISOS_CAJERO: frozenset[str] = frozenset({PERM_PRODUCTO_LEER})
_PERMISOS_ALMACENISTA: frozenset[str] = frozenset({PERM_PRODUCTO_LEER, PERM_PRODUCTO_EDITAR})
```

  d) Actualizar el comentario que decía «Cajero y almacenista quedan declarados y VACÍOS a propósito» por el párrafo de arriba, y el docstring de cabecera: donde dice que `_PERMISOS_CAJERO` y `_PERMISOS_ALMACENISTA` están vacíos «a propósito», sustituir por una referencia a ADR-023 («los llena ADR-023 módulo a módulo; el catálogo es el primero»).

- [ ] **Paso 3: verificar y resembrar el realm de desarrollo.**

```bash
cd backend && uv run pytest tests/test_auth_policies.py tests/test_auth_dependencies.py -q
# Esperado: todos passed
bash scripts/seed.sh
# Esperado: permisos_sembrados cuantos=8; los grupos quedan con el diff aplicado
```

La resiembra es idempotente: `ensure_realm_role` crea los dos roles de realm nuevos y `set_group_realm_roles` hace diff en los tres grupos (ADR-023: «los realms ya aprovisionados se resiembran o se editan a mano»).

- [ ] **Paso 4: commit**

```bash
git add backend/libs/vendi-core/src/vendi_core/auth/policies.py backend/tests/test_auth_policies.py
git commit -m "Permisos de catálogo en el catálogo de Vendi: producto:leer y producto:editar repartidos según ADR-023"
```

**Criterios de aceptación:** `test_auth_policies.py` verde con el reparto nuevo; el candado «todo permiso asignado está en el catálogo» existe y pasa; `bash scripts/seed.sh` siembra los dos roles de realm nuevos sin error.

---

## Tarea 5: Servicio del catálogo (`CatalogoService`)

**Files:**
- Create: `backend/tests/test_catalogo_servicio.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/catalogo/service.py`

**Interfaces:**
- Consume: `sesion` de tenant (RLS activo: el servicio NUNCA filtra por `tenant_id` a mano; la policy lo hace), `DomainEventService.emit` (outbox transaccional), errores de `vendi_core.errors.domain`.
- Produce: CRUD + búsqueda por EAN + listado paginado + límite por tier + idempotencia por UUID de cliente + eventos `producto.creado/actualizado/eliminado`.

- [ ] **Paso 1: escribir los tests que fallan.** Crear `backend/tests/test_catalogo_servicio.py`:

```python
"""`CatalogoService` contra el PostgreSQL real, con el rol `vendi_app`.

`integration` porque la base NO se dobla: la RLS, el índice único parcial del
EAN y la policy de INSERT del outbox solo existen en PostgreSQL. La sesión es
la misma fábrica que usa la API, con el tenant en el ContextVar — el mismo
camino por el que pasarán los handlers.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from datos_de_prueba import T1, T2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.catalogo.schemas import ProductoActualizar, ProductoCrear
from app.modules.catalogo.service import CatalogoService
from vendi_core.db.engine import create_engine
from vendi_core.db.session import create_session_factory
from vendi_core.errors.domain import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from vendi_core.tenant.context import current_tenant_id

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def limpiar_productos(pg_platform_url: str):
    engine = create_async_engine(pg_platform_url)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM productos WHERE tenant_id = ANY(:ids)"), {"ids": [T1, T2]})
        await conn.execute(
            text("DELETE FROM outbox_messages WHERE routing_key LIKE 'producto.%' OR routing_key LIKE '%.producto.%'")
        )
    try:
        yield
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM productos WHERE tenant_id = ANY(:ids)"), {"ids": [T1, T2]})
        await engine.dispose()


@pytest_asyncio.fixture
async def servicio(pg_app_url: str, limpiar_productos):
    """Servicio del negocio T1 con tier 'pro' (sin límite)."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            yield CatalogoService(session=s, tenant_id=T1, tier="pro")
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def _contar(session, **filtros) -> int:
    from sqlalchemy import func, select

    from app.modules.catalogo.models import Producto

    consulta = select(func.count()).select_from(Producto)
    for campo, valor in filtros.items():
        consulta = consulta.where(getattr(Producto, campo) == valor)
    return (await session.execute(consulta)).scalar_one()


async def test_crear_y_obtener(servicio):
    creado = await servicio.crear(ProductoCrear(nombre="Arroz 500g", precio_venta=2500, iva_pct=Decimal("5")))
    assert creado.id is not None
    assert creado.tenant_id == T1
    assert creado.stock_actual == Decimal("0")

    obtenido = await servicio.obtener(creado.id)
    assert obtenido.nombre == "Arroz 500g"
    assert obtenido.iva_pct == Decimal("5")


async def test_crear_con_id_de_cliente_es_idempotente(servicio, pg_platform_url):
    """ADR-017: reenviar la misma creación es un no-op porque la fila ya
    existe con la PK que le puso el cliente — no porque nadie recuerde qué se
    procesó."""
    el_id = uuid.uuid4()
    datos = ProductoCrear(id=el_id, nombre="Huevo und", precio_venta=600)
    primero = await servicio.crear(datos)
    await servicio._session.commit()
    segundo = await servicio.crear(datos)

    assert segundo.id == primero.id == el_id
    assert await _contar(servicio._session, nombre="Huevo und") == 1

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            eventos = (
                await conn.execute(
                    text("SELECT count(*) FROM outbox_messages WHERE routing_key = :k"),
                    {"k": f"{T1}.producto.creado"},
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert eventos == 1, "el reintento NO re-emite el evento (ADR-017: una sola vez por operación aceptada)"


async def test_un_id_ya_usado_por_un_producto_dado_de_baja_se_rechaza(servicio):
    datos = ProductoCrear(id=uuid.uuid4(), nombre="Temporal", precio_venta=100)
    creado = await servicio.crear(datos)
    await servicio.eliminar(creado.id)
    with pytest.raises(ConflictError) as exc:
        await servicio.crear(datos)
    assert exc.value.code == "producto_id_duplicado"


async def test_el_ean_duplicado_en_el_mismo_tenant_da_409_tipado(servicio):
    await servicio.crear(ProductoCrear(nombre="A", precio_venta=100, codigo_barras="770123"))
    with pytest.raises(ConflictError) as exc:
        await servicio.crear(ProductoCrear(nombre="B", precio_venta=100, codigo_barras="770123"))
    assert exc.value.code == "codigo_barras_duplicado"
    await servicio._session.rollback()


async def test_buscar_por_codigo(servicio):
    await servicio.crear(ProductoCrear(nombre="Gaseosa 400ml", precio_venta=2500, codigo_barras="770400"))
    encontrado = await servicio.buscar_por_codigo("770400")
    assert encontrado.nombre == "Gaseosa 400ml"
    with pytest.raises(NotFoundError) as exc:
        await servicio.buscar_por_codigo("000000")
    assert exc.value.code == "producto_no_encontrado"


async def test_listar_pagina_filtra_por_nombre_y_categoria(servicio):
    await servicio.crear(ProductoCrear(nombre="Arroz 500g", precio_venta=2500, categoria="Granos"))
    await servicio.crear(ProductoCrear(nombre="Arroz integral", precio_venta=4000, categoria="Granos"))
    await servicio.crear(ProductoCrear(nombre="Detergente", precio_venta=9000, categoria="Aseo"))

    filas, total = await servicio.listar(q="arroz")
    assert total == 2 and [f.nombre for f in filas] == ["Arroz 500g", "Arroz integral"]

    filas, total = await servicio.listar(categoria="Aseo")
    assert total == 1 and filas[0].nombre == "Detergente"

    filas, total = await servicio.listar(skip=1, limit=1)
    assert total == 3 and len(filas) == 1

    # Los comodines de LIKE en la búsqueda son texto, no patrón:
    filas, total = await servicio.listar(q="100%")
    assert total == 0


async def test_actualizar_emite_evento_con_los_cambios(servicio, pg_platform_url):
    creado = await servicio.crear(ProductoCrear(nombre="Leche", precio_venta=3200))
    await servicio._session.commit()

    actualizado = await servicio.actualizar(creado.id, ProductoActualizar(precio_venta=3500))
    assert actualizado.precio_venta == 3500
    await servicio._session.commit()

    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            fila = (
                await conn.execute(
                    text("SELECT payload FROM outbox_messages WHERE routing_key = :k"),
                    {"k": f"{T1}.producto.actualizado"},
                )
            ).first()
    finally:
        await engine.dispose()
    assert fila is not None
    assert fila.payload["data"]["cambios"]["precio_venta"] == {"antes": "3200", "despues": "3500"}


async def test_actualizar_sin_cambios_no_emite_evento(servicio, pg_platform_url):
    creado = await servicio.crear(ProductoCrear(nombre="Sal", precio_venta=1500))
    await servicio._session.commit()
    mismo = await servicio.actualizar(creado.id, ProductoActualizar(precio_venta=1500))
    assert mismo.precio_venta == 1500
    await servicio._session.commit()
    assert await _contar_outbox(pg_platform_url, f"{T1}.producto.actualizado") == 0


async def _contar_outbox(pg_platform_url: str, routing_key: str) -> int:
    """El outbox se lee con el rol de PLATAFORMA: `vendi_app` solo tiene
    INSERT sobre `outbox_messages` (migración 0001) y un SELECT con la sesión
    de tenant fallaría con `permission denied`."""
    engine = create_async_engine(pg_platform_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT count(*) FROM outbox_messages WHERE routing_key = :k"),
                    {"k": routing_key},
                )
            ).scalar_one()
    finally:
        await engine.dispose()


async def test_eliminar_es_borrado_logico_libera_el_ean_y_emite_evento(servicio, pg_platform_url):
    creado = await servicio.crear(ProductoCrear(nombre="Panela", precio_venta=4200, codigo_barras="770999"))
    await servicio.eliminar(creado.id)
    await servicio._session.commit()

    with pytest.raises(NotFoundError):
        await servicio.obtener(creado.id)
    _, total = await servicio.listar()
    assert total == 0

    # El EAN quedó libre en el mismo tenant (decisión 3 del plan):
    otro = await servicio.crear(ProductoCrear(nombre="Panela nueva", precio_venta=4300, codigo_barras="770999"))
    assert otro.id != creado.id
    assert await _contar_outbox(pg_platform_url, f"{T1}.producto.eliminado") == 1


async def test_el_limite_del_tier_se_verifica_contra_las_filas_vivas(pg_app_url, limpiar_productos):
    """ADR-010/ADR-019: el límite se verifica en la aplicación contra las
    filas VIVAS del negocio; no es una constraint de base."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s:
            gratis = CatalogoService(session=s, tenant_id=T1, tier="gratis")
            for i in range(100):
                await gratis.crear(ProductoCrear(nombre=f"Producto {i:03d}", precio_venta=100))
            with pytest.raises(PermissionDeniedError) as exc:
                await gratis.crear(ProductoCrear(nombre="El 101", precio_venta=100))
            assert exc.value.code == "limite_de_productos_alcanzado"
            assert exc.value.details == {"tier": "gratis", "limite": 100}
            await s.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()


async def test_el_padre_debe_existir_en_el_propio_tenant(pg_app_url, limpiar_productos):
    """Postgres NO aplica RLS al verificar la FK de `padre_id`: sin este
    chequeo, una variante podría colgar del producto de OTRO negocio."""
    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T2)
    try:
        async with factory() as s2:
            ajeno = await CatalogoService(session=s2, tenant_id=T2, tier="pro").crear(
                ProductoCrear(nombre="Base ajena", precio_venta=100)
            )
            await s2.commit()
            id_ajeno = ajeno.id
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()

    engine = create_engine(pg_app_url)
    factory = create_session_factory(engine)
    marca = current_tenant_id.set(T1)
    try:
        async with factory() as s1:
            servicio_t1 = CatalogoService(session=s1, tenant_id=T1, tier="pro")
            with pytest.raises(ValidationError) as exc:
                await servicio_t1.crear(ProductoCrear(nombre="Hija", precio_venta=100, padre_id=id_ajeno))
            assert exc.value.code == "padre_no_encontrado"
            with pytest.raises(ValidationError):
                await servicio_t1.crear(ProductoCrear(nombre="Hija", precio_venta=100, padre_id=uuid.uuid4()))
            await s1.rollback()
    finally:
        current_tenant_id.reset(marca)
        await engine.dispose()
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/test_catalogo_servicio.py -q
```

Esperado: error de colección `ModuleNotFoundError: No module named 'app.modules.catalogo.service'`.

- [ ] **Paso 2: implementar el servicio.** Crear `backend/services/api/app/modules/catalogo/service.py`:

```python
"""Servicio del catálogo: CRUD de productos sobre la sesión de tenant.

## RLS hace el aislamiento; el servicio NO filtra por `tenant_id` a mano

Toda consulta de este servicio corre en la sesión de tenant (`vendi_app` +
GUC `vendi.tenant_id`), así que la policy `tenant_isolation` es la que acota
lecturas y escrituras. Escribir `WHERE tenant_id = ...` a mano sería
redundante y —peor— daría la falsa sensación de que el aislamiento depende
del código de negocio. Lo que sí se filtra aquí es `deleted_at IS NULL`: eso
es semántica de negocio (borrado lógico), no aislamiento.

## Los eventos viajan en la transacción del llamante

`DomainEventService.emit` encola en `outbox_messages` dentro de la sesión
recibida. El servicio hace `flush` pero NUNCA `commit`: el commit lo hace la
dependencia `sesion_de_tenant` al final del request (o el test), y con él el
evento y la escritura de negocio confirman o revierten juntos — esa es toda
la garantía del patrón outbox. La policy `outbox_encolado_del_tenant`
exige que el `tenant_id` del evento sea el del GUC, así que los eventos del
catálogo SIEMPRE llevan el tenant del contexto, nunca uno del payload.

## El límite de productos por tier (ADR-010)

`LIMITES_PRODUCTOS_POR_TIER` fija 100 / 500 / sin límite (plan maestro §5).
Se verifica en la aplicación contando las filas VIVAS del negocio (la RLS
acota el `count` al tenant del GUC), como firma ADR-019: no es una
constraint de base. El tier llega por constructor; quién lo resuelve hoy es
la dependencia `tier_del_negocio` (decisión 2 del plan).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalogo.models import Producto
from app.modules.catalogo.schemas import ProductoActualizar, ProductoCrear
from vendi_core.errors.domain import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from vendi_core.events.service import DomainEventService

logger = structlog.get_logger()

#: Límite de productos por tier (plan maestro §5, ADR-010). `None` = sin
#: límite. Los límites de IA y empleados viven en sus módulos, no aquí.
LIMITES_PRODUCTOS_POR_TIER: dict[str, int | None] = {
    "gratis": 100,
    "light": 500,
    "pro": None,
}

#: Tier que la dependencia `tier_del_negocio` asigna mientras no exista el
#: módulo de suscripciones: el trial de Pro del plan maestro §5 (1 mes, sin
#: tarjeta) aplica a todo negocio registrado durante el piloto.
TIER_DEL_PILOTO = "pro"

#: Campos que un PATCH puede tocar. Ni `stock_actual` ni `ultimo_costo` están
#: aquí: los mueven inventario y compras (ADR-020).
_CAMPOS_EDITABLES = (
    "nombre",
    "codigo_barras",
    "categoria",
    "unidad_medida",
    "precio_venta",
    "iva_pct",
    "stock_minimo",
    "padre_id",
)


def _escapar_like(texto: str) -> str:
    """Los comodines de LIKE en la búsqueda del POS son texto, no patrón."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class CatalogoService:
    """Operaciones del catálogo de UN negocio: el del GUC de la sesión."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, tier: str = TIER_DEL_PILOTO):
        if tier not in LIMITES_PRODUCTOS_POR_TIER:
            raise ValueError(f"Tier desconocido: {tier!r}. Los válidos son {list(LIMITES_PRODUCTOS_POR_TIER)}.")
        self._session = session
        self._tenant_id = tenant_id
        self._tier = tier

    # --- Lectura -----------------------------------------------------------

    async def obtener(self, producto_id: uuid.UUID) -> Producto:
        producto = await self._session.get(Producto, producto_id)
        if producto is None or producto.deleted_at is not None:
            # Un id de otro negocio da el mismo 404 que uno inexistente: la
            # RLS lo hace invisible y no hay nada que filtrar.
            raise NotFoundError("El producto no existe.", code="producto_no_encontrado")
        return producto

    async def buscar_por_codigo(self, codigo: str) -> Producto:
        """El camino del escáner (ADR-024): un EAN resuelve a UN producto."""
        consulta = select(Producto).where(
            Producto.codigo_barras == codigo,
            Producto.deleted_at.is_(None),
        )
        producto = (await self._session.execute(consulta)).scalar_one_or_none()
        if producto is None:
            raise NotFoundError("Ningún producto tiene ese código de barras.", code="producto_no_encontrado")
        return producto

    async def listar(
        self,
        *,
        skip: int = 0,
        limit: int = 25,
        q: str | None = None,
        categoria: str | None = None,
    ) -> tuple[list[Producto], int]:
        base = select(Producto).where(Producto.deleted_at.is_(None))
        conteo = select(func.count()).select_from(Producto).where(Producto.deleted_at.is_(None))
        if q:
            patron = f"%{_escapar_like(q)}%"
            base = base.where(Producto.nombre.ilike(patron, escape="\\"))
            conteo = conteo.where(Producto.nombre.ilike(patron, escape="\\"))
        if categoria:
            base = base.where(Producto.categoria == categoria)
            conteo = conteo.where(Producto.categoria == categoria)
        total = (await self._session.execute(conteo)).scalar_one()
        filas = (
            (await self._session.execute(base.order_by(Producto.nombre, Producto.id).offset(skip).limit(limit)))
            .scalars()
            .all()
        )
        return list(filas), int(total)

    # --- Escritura ---------------------------------------------------------

    async def crear(self, datos: ProductoCrear) -> Producto:
        """Alta de producto. Idempotente por el UUID del cliente (ADR-017).

        Si el `id` ya existe y el producto está vivo, se devuelve tal cual:
        reenviar la misma creación es un no-op. Si existe pero está dado de
        baja, se rechaza: un UUID de cliente no se reutiliza jamás.
        """
        if datos.id is not None:
            existente = await self._session.get(Producto, datos.id)
            if existente is not None:
                if existente.deleted_at is None:
                    logger.info("producto_creado_idempotente", producto_id=str(existente.id))
                    return existente
                raise ConflictError(
                    "Ese id ya se usó para un producto dado de baja. Genera uno nuevo.",
                    code="producto_id_duplicado",
                )
        if datos.padre_id is not None:
            await self._exigir_padre(datos.padre_id)
        await self._exigir_cupo()

        producto = Producto(
            tenant_id=self._tenant_id,
            padre_id=datos.padre_id,
            nombre=datos.nombre,
            codigo_barras=datos.codigo_barras,
            categoria=datos.categoria,
            unidad_medida=datos.unidad_medida,
            precio_venta=datos.precio_venta,
            iva_pct=datos.iva_pct,
            stock_minimo=datos.stock_minimo,
        )
        if datos.id is not None:
            producto.id = datos.id
        self._session.add(producto)
        await self._flush_traduciendo_integridad()
        await self._emitir(
            "producto.creado",
            producto,
            data={
                "producto_id": str(producto.id),
                "nombre": producto.nombre,
                "codigo_barras": producto.codigo_barras,
                "precio_venta": producto.precio_venta,
                "iva_pct": str(producto.iva_pct),
            },
        )
        logger.info("producto_creado", producto_id=str(producto.id))
        return producto

    async def actualizar(self, producto_id: uuid.UUID, datos: ProductoActualizar) -> Producto:
        producto = await self.obtener(producto_id)
        if datos.padre_id is not None:
            if datos.padre_id == producto.id:
                raise ValidationError("Un producto no puede ser su propio padre.", code="padre_es_el_mismo")
            await self._exigir_padre(datos.padre_id)

        cambios: dict[str, dict[str, str]] = {}
        for campo in _CAMPOS_EDITABLES:
            nuevo = getattr(datos, campo)
            if nuevo is None:
                continue
            viejo = getattr(producto, campo)
            if nuevo != viejo:
                cambios[campo] = {"antes": str(viejo), "despues": str(nuevo)}
                setattr(producto, campo, nuevo)
        if not cambios:
            return producto

        await self._flush_traduciendo_integridad()
        await self._emitir("producto.actualizado", producto, data={"producto_id": str(producto.id), "cambios": cambios})
        logger.info("producto_actualizado", producto_id=str(producto.id), cambios=list(cambios))
        return producto

    async def eliminar(self, producto_id: uuid.UUID) -> None:
        """Borrado lógico. Anula el EAN para liberarlo: el índice único
        parcial de ADR-019 NO excluye filas borradas, y sin esto volver a
        crear el producto chocaría contra el índice para siempre. El EAN
        original viaja en el payload del evento."""
        producto = await self.obtener(producto_id)
        ean = producto.codigo_barras
        producto.deleted_at = datetime.now(UTC)
        producto.codigo_barras = None
        await self._session.flush()
        await self._emitir(
            "producto.eliminado",
            producto,
            data={"producto_id": str(producto.id), "nombre": producto.nombre, "codigo_barras": ean},
        )
        logger.info("producto_eliminado", producto_id=str(producto.id))

    # --- Internas ----------------------------------------------------------

    async def _exigir_padre(self, padre_id: uuid.UUID) -> None:
        """Postgres NO aplica RLS al verificar llaves foráneas: sin este
        chequeo, una variante podría colgar del producto de OTRO negocio."""
        padre = await self._session.get(Producto, padre_id)
        if padre is None or padre.deleted_at is not None:
            raise ValidationError("El producto padre no existe en tu negocio.", code="padre_no_encontrado")

    async def _exigir_cupo(self) -> None:
        """El límite del tier contra las filas VIVAS (ADR-019: en la
        aplicación, no en una constraint). La RLS acota el count al negocio."""
        limite = LIMITES_PRODUCTOS_POR_TIER[self._tier]
        if limite is None:
            return
        cuantos = (
            await self._session.execute(select(func.count()).select_from(Producto).where(Producto.deleted_at.is_(None)))
        ).scalar_one()
        if cuantos >= limite:
            raise PermissionDeniedError(
                f"Tu plan permite hasta {limite} productos. Amplía tu plan para seguir creando.",
                code="limite_de_productos_alcanzado",
                details={"tier": self._tier, "limite": limite},
            )

    async def _flush_traduciendo_integridad(self) -> None:
        """El índice único del EAN y la PK son las constraints de verdad; el
        servicio traduce su violación al sobre de errores de la API. Tras un
        `IntegrityError` la transacción queda abortada: quien llama (la
        dependencia o el test) hace rollback al propagar."""
        try:
            await self._session.flush()
        except IntegrityError as exc:
            detalle = str(exc)
            if "ux_productos_ean" in detalle:
                raise ConflictError(
                    "Ya existe un producto con ese código de barras en tu negocio.",
                    code="codigo_barras_duplicado",
                ) from exc
            if "productos_pkey" in detalle:
                # El id venía del cliente y choca con una fila que la RLS no
                # le deja ver (de otro negocio) o con una carrera de dos altas.
                raise ConflictError("Ese id de producto ya existe.", code="producto_id_duplicado") from exc
            raise

    async def _emitir(self, evento: str, producto: Producto, *, data: dict) -> None:
        await DomainEventService.emit(
            self._session,
            tenant_id=self._tenant_id,
            event_name=evento,
            resource_type="producto",
            resource_id=str(producto.id),
            data=data,
        )
```

- [ ] **Paso 3: verificar.**

```bash
cd backend && uv run pytest tests/test_catalogo_servicio.py -q
# Esperado: 11 passed
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 4: commit**

```bash
git add backend/services/api/app/modules/catalogo/service.py backend/tests/test_catalogo_servicio.py
git commit -m "Servicio del catálogo: CRUD con idempotencia por UUID de cliente, límite por tier y eventos de outbox"
```

**Criterios de aceptación:** los 11 tests pasan contra PostgreSQL real, 0 SKIPPED; el reintento de creación no duplica fila ni evento; el límite de tier corta en el producto 101 con `limite_de_productos_alcanzado`; el padre de otro tenant se rechaza.

---

## Tarea 6: Dependencias, router y montaje en la app

**Files:**
- Create: `backend/tests/api/test_catalogo_productos.py` (primero: el test que falla)
- Create: `backend/services/api/app/modules/catalogo/dependencies.py`
- Create: `backend/services/api/app/modules/catalogo/router.py`
- Modify: `backend/services/api/app/factory.py` (montar el router; actualizar la descripción)
- Modify: `backend/tests/api/ayudas.py` (helper `usuario_con_rol`)
- Modify: `backend/tests/api/conftest.py` (la limpieza borra también `productos` de los tenants de prueba)

**Interfaces:**
- Consume: `sesion_de_tenant`, `contexto_de_tenant` (`app.dependencies`), `exigir_negocio_activo` (`app.modules.tenants.dependencies`), `get_current_user` (`vendi_core.auth.dependencies`), `PagedList` (`vendi_core.models.pagination`).
- Produce: `/api/v1/productos` con CRUD completo, búsqueda por EAN y listado paginado, protegido por `producto:leer`/`producto:editar`.

- [ ] **Paso 1: preparar los apoyos de test (helpers y limpieza).**

  a) En `backend/tests/api/ayudas.py`, añadir tras `usuario_de_negocio`:

```python
def usuario_con_rol(rol: str, *tenant_ids: uuid.UUID) -> UserContext:
    """Un usuario con un rol de negocio concreto (cajero, almacenista...).

    `roles` lleva el rol y sus permisos, que es lo que `realm_access.roles`
    trae de un token real desde que el grupo mapea las dos cosas
    (`roles_de_realm_del_grupo`). Sirve para probar los 200/403 por rol sin
    inventar claims que el realm jamás emitiría.
    """
    return UserContext(
        user_id=f"{rol}-prueba",
        username=f"{rol}@demo.vendi.co",
        email=f"{rol}@demo.vendi.co",
        roles=frozenset(roles_de_realm_del_grupo(rol)),
        realm="vendi-co",
        organizations={str(t): f"org-{t}" for t in tenant_ids},
    )
```

  b) En `backend/tests/api/conftest.py`, dentro de `_borrar()` del fixture `limpiar_tenants_de_prueba`, añadir **antes** del `DELETE FROM tenants`:

```python
                await conn.execute(
                    text("DELETE FROM productos WHERE tenant_id = ANY(:ids)"),
                    {"ids": list(ids)},
                )
```

(sin esto, los productos de los tenants de prueba se acumulan entre corridas y los EAN de los tests acabarían chocando consigo mismos: la suite tiene que ser re-entrante).

- [ ] **Paso 2: escribir los tests de API que fallan.** Crear `backend/tests/api/test_catalogo_productos.py`:

```python
"""El router `/api/v1/productos` contra el PostgreSQL real.

Misma regla que `test_tenants_crud.py`: la base no se dobla. Cada test crea
su negocio por el camino real (alta de plataforma) y opera con tokens de
roles distintos, porque lo que se mide aquí es quién puede hacer qué — y un
403 que aparece cuando NO debe es tan grave como un 200 que aparece cuando
no debe.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from ayudas import PREFIJO_PRUEBA, usuario_con_rol, usuario_de_plataforma
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vendi_core.auth.policies import ROL_ALMACENISTA, ROL_CAJERO, ROL_DUENO

pytestmark = pytest.mark.integration


def _dec(valor) -> Decimal:
    return Decimal(str(valor))


def _admin(cliente, validador, token: str = "tok-admin") -> dict:
    validador.registrar(token, usuario_de_plataforma())
    return {"Authorization": f"Bearer {token}"}


def _crear_negocio(cliente, validador, nombre: str) -> str:
    respuesta = cliente.post(
        "/api/v1/platform/tenants", json={"nombre": PREFIJO_PRUEBA + nombre}, headers=_admin(cliente, validador)
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _cabeceras_de(validador, rol: str, tenant_id: str, token: str) -> dict:
    validador.registrar(token, usuario_con_rol(rol, uuid.UUID(tenant_id)))
    return {"Authorization": f"Bearer {token}"}


def _alta(cliente, cabeceras, **campos) -> dict:
    cuerpo = {"nombre": "Arroz 500g", "precio_venta": 2500, **campos}
    respuesta = cliente.post("/api/v1/productos", json=cuerpo, headers=cabeceras)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# --- Alta y permisos ----------------------------------------------------------


def test_crear_producto_devuelve_201_con_sus_campos(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 1")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d1")

    cuerpo = _alta(cliente, dueno, codigo_barras="770100000001", iva_pct=5, categoria="Granos")

    assert uuid.UUID(cuerpo["id"])
    assert cuerpo["nombre"] == "Arroz 500g"
    assert cuerpo["precio_venta"] == 2500
    assert _dec(cuerpo["iva_pct"]) == Decimal("5")
    assert _dec(cuerpo["stock_actual"]) == Decimal("0")


def test_crear_requiere_producto_editar_y_el_cajero_no_lo_tiene(app_con_base):
    """El cajero vende con el catálogo pero no lo mantiene (ADR-023). El 403
    es la respuesta correcta y esperada, con sobre estándar y código."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 2")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c2")

    respuesta = cliente.post("/api/v1/productos", json={"nombre": "X", "precio_venta": 100}, headers=cajero)

    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "permiso_ausente"
    assert respuesta.json()["success"] is False


def test_el_cajero_si_puede_leer(app_con_base):
    """La pareja del anterior: distingue «deniega porque no lo tiene» de
    «deniega siempre» (el patrón de `test_un_rol_ausente_deniega_de_verdad`)."""
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 3")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d3")
    cajero = _cabeceras_de(validador, ROL_CAJERO, negocio, "tok-c3")
    creado = _alta(cliente, dueno)

    assert cliente.get("/api/v1/productos", headers=cajero).status_code == 200
    assert cliente.get(f"/api/v1/productos/{creado['id']}", headers=cajero).status_code == 200


def test_el_almacenista_crea_y_edita_pero_no_borra(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 4")
    almacenista = _cabeceras_de(validador, ROL_ALMACENISTA, negocio, "tok-a4")

    creado = _alta(cliente, almacenista)
    respuesta = cliente.patch(
        f"/api/v1/productos/{creado['id']}", json={"precio_venta": 3000}, headers=almacenista
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["precio_venta"] == 3000
    # ADR-023 reparte producto:editar al almacenista, y el borrado lógico es
    # una edición (un UPDATE de deleted_at), así que también puede:
    assert cliente.delete(f"/api/v1/productos/{creado['id']}", headers=almacenista).status_code == 204


def test_sin_token_da_401(app_sin_base):
    cliente, _, _ = app_sin_base
    assert cliente.get("/api/v1/productos").status_code == 401


# --- Lectura, búsqueda y listado ----------------------------------------------


def test_get_por_id_y_404_tipado(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 5")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d5")
    creado = _alta(cliente, dueno)

    assert cliente.get(f"/api/v1/productos/{creado['id']}", headers=dueno).json()["id"] == creado["id"]
    respuesta = cliente.get(f"/api/v1/productos/{uuid.uuid4()}", headers=dueno)
    assert respuesta.status_code == 404
    assert respuesta.json()["code"] == "producto_no_encontrado"


def test_un_producto_de_otro_negocio_es_un_404_no_una_fuga(app_con_base):
    """El id es válido y existe — pero en otro tenant. La RLS lo hace
    invisible y el 404 no revela ni que existe."""
    cliente, validador, _ = app_con_base
    negocio_a = _crear_negocio(cliente, validador, "Catálogo 6A")
    negocio_b = _crear_negocio(cliente, validador, "Catálogo 6B")
    dueno_a = _cabeceras_de(validador, ROL_DUENO, negocio_a, "tok-d6a")
    dueno_b = _cabeceras_de(validador, ROL_DUENO, negocio_b, "tok-d6b")
    creado = _alta(cliente, dueno_a)

    assert cliente.get(f"/api/v1/productos/{creado['id']}", headers=dueno_b).status_code == 404
    assert cliente.get("/api/v1/productos", headers=dueno_b).json()["total"] == 0


def test_buscar_por_codigo_de_barras(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 7")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d7")
    _alta(cliente, dueno, codigo_barras="770400000004")

    respuesta = cliente.get("/api/v1/productos/por-codigo/770400000004", headers=dueno)
    assert respuesta.status_code == 200
    assert respuesta.json()["nombre"] == "Arroz 500g"
    assert cliente.get("/api/v1/productos/por-codigo/000", headers=dueno).status_code == 404


def test_listado_paginado_con_filtro_de_nombre(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 8")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d8")
    for nombre in ("Arroz 500g", "Arroz integral", "Detergente"):
        _alta(cliente, dueno, nombre=nombre)

    respuesta = cliente.get("/api/v1/productos?q=arroz&skip=0&limit=1", headers=dueno)
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 2
    assert len(cuerpo["items"]) == 1
    assert cliente.get("/api/v1/productos?limit=0", headers=dueno).status_code == 422


# --- Integridad, idempotencia y borrado ---------------------------------------


def test_el_ean_duplicado_da_409_y_en_otro_tenant_no(app_con_base):
    cliente, validador, _ = app_con_base
    negocio_a = _crear_negocio(cliente, validador, "Catálogo 9A")
    negocio_b = _crear_negocio(cliente, validador, "Catálogo 9B")
    dueno_a = _cabeceras_de(validador, ROL_DUENO, negocio_a, "tok-d9a")
    dueno_b = _cabeceras_de(validador, ROL_DUENO, negocio_b, "tok-d9b")
    _alta(cliente, dueno_a, codigo_barras="770900000009")

    duplicado = cliente.post(
        "/api/v1/productos",
        json={"nombre": "Otro", "precio_venta": 100, "codigo_barras": "770900000009"},
        headers=dueno_a,
    )
    assert duplicado.status_code == 409
    assert duplicado.json()["code"] == "codigo_barras_duplicado"

    # El mismo EAN en OTRO negocio es válido (índice único por tenant):
    respuesta = cliente.post(
        "/api/v1/productos",
        json={"nombre": "Suyo", "precio_venta": 100, "codigo_barras": "770900000009"},
        headers=dueno_b,
    )
    assert respuesta.status_code == 201


def test_post_con_uuid_de_cliente_es_idempotente(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 10")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d10")
    el_id = str(uuid.uuid4())
    cuerpo = {"id": el_id, "nombre": "Huevo und", "precio_venta": 600}

    assert cliente.post("/api/v1/productos", json=cuerpo, headers=dueno).status_code == 201
    reintento = cliente.post("/api/v1/productos", json=cuerpo, headers=dueno)

    assert reintento.status_code == 201
    assert reintento.json()["id"] == el_id
    assert cliente.get("/api/v1/productos", headers=dueno).json()["total"] == 1


def test_eliminar_es_borrado_logico_y_libera_el_ean(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 11")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d11")
    creado = _alta(cliente, dueno, codigo_barras="771100000011")

    assert cliente.delete(f"/api/v1/productos/{creado['id']}", headers=dueno).status_code == 204
    assert cliente.get(f"/api/v1/productos/{creado['id']}", headers=dueno).status_code == 404
    assert cliente.get("/api/v1/productos", headers=dueno).json()["total"] == 0
    # El EAN queda libre para un alta nueva:
    assert (
        cliente.post(
            "/api/v1/productos",
            json={"nombre": "Re alta", "precio_venta": 100, "codigo_barras": "771100000011"},
            headers=dueno,
        ).status_code
        == 201
    )


def test_la_validacion_da_422(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 12")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d12")

    assert cliente.post("/api/v1/productos", json={"nombre": "X", "precio_venta": -5}, headers=dueno).status_code == 422
    assert (
        cliente.post(
            "/api/v1/productos", json={"nombre": "X", "precio_venta": 5, "iva_pct": 8}, headers=dueno
        ).status_code
        == 422
    )


def test_el_limite_del_tier_da_403(app_con_base, pg_platform_url):
    """El límite se fuerza sembrando 100 filas en SQL (100 altas por HTTP
    harían el test lento sin probar nada nuevo) y anulando el tier con
    `dependency_overrides`: el camino del check es el real."""
    from app.modules.catalogo.dependencies import tier_del_negocio

    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 13")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d13")

    valores = ", ".join(f"('{negocio}', 'Producto {i:03d}', 100)" for i in range(100))
    engine = create_async_engine(pg_platform_url)

    async def _sembrar():
        async with engine.begin() as conn:
            await conn.execute(
                text(f"INSERT INTO productos (tenant_id, nombre, precio_venta) VALUES {valores}")
            )
        await engine.dispose()

    import asyncio

    asyncio.run(_sembrar())

    cliente.app.dependency_overrides[tier_del_negocio] = lambda: "gratis"
    try:
        respuesta = cliente.post("/api/v1/productos", json={"nombre": "El 101", "precio_venta": 100}, headers=dueno)
        assert respuesta.status_code == 403
        assert respuesta.json()["code"] == "limite_de_productos_alcanzado"
        # Y con el tier del piloto (pro, sin límite) el mismo alta entra:
        cliente.app.dependency_overrides[tier_del_negocio] = lambda: "pro"
        assert (
            cliente.post("/api/v1/productos", json={"nombre": "El 101", "precio_venta": 100}, headers=dueno).status_code
            == 201
        )
    finally:
        cliente.app.dependency_overrides.clear()


def test_un_negocio_suspendido_no_opera_su_catalogo(app_con_base):
    cliente, validador, _ = app_con_base
    negocio = _crear_negocio(cliente, validador, "Catálogo 14")
    dueno = _cabeceras_de(validador, ROL_DUENO, negocio, "tok-d14")
    cliente.patch(
        f"/api/v1/platform/tenants/{negocio}", json={"estado": "suspendido"}, headers=_admin(cliente, validador)
    )

    respuesta = cliente.get("/api/v1/productos", headers=dueno)
    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "tenant_suspendido"
```

Ejecutar y comprobar el fallo:

```bash
cd backend && uv run pytest tests/api/test_catalogo_productos.py -q
```

Esperado: 14-15 fallos con `404` en todo (`/api/v1/productos` no existe aún) y errores de import de `app.modules.catalogo.dependencies`.

- [ ] **Paso 3: implementar las dependencias.** Crear `backend/services/api/app/modules/catalogo/dependencies.py`:

```python
"""Dependencias del módulo `catalogo`.

El guard de permisos es una fábrica propia y NO `require_permission` de
`vendi-core`, por el mismo motivo por el que existe
`app.dependencies.exigir_admin_de_plataforma`: aquella lanza `HTTPException`
(cuerpo `{"detail": ...}`) y toda la API contesta con el sobre
`{"success": false, "message": ..., "code": ...}`. Dos formatos de error en la
misma API son dos caminos de parseo en el frontend.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import contexto_de_tenant, sesion_de_tenant
from app.modules.catalogo.service import TIER_DEL_PILOTO, CatalogoService
from app.modules.tenants.dependencies import exigir_negocio_activo
from vendi_core.auth.context import UserContext
from vendi_core.auth.dependencies import get_current_user
from vendi_core.auth.policies import PERM_PRODUCTO_EDITAR, PERM_PRODUCTO_LEER, has_permission
from vendi_core.errors.domain import PermissionDeniedError
from vendi_core.tenant.context import TenantContext


def exigir_permiso(permiso: str) -> Callable:
    """Fábrica de guards: exige un permiso del token, con sobre estándar.

    La autorización lee SOLO el token (`realm_access.roles`), sin consulta a
    base de datos en la ruta caliente (ADR-015/ADR-023). El 403 es la
    respuesta correcta y esperada cuando falta el permiso.
    """

    async def _comprobar(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not has_permission(user, permiso):
            raise PermissionDeniedError(
                f"Esta operación requiere el permiso {permiso}.",
                code="permiso_ausente",
                details={"permiso": permiso},
            )
        return user

    return _comprobar


exigir_producto_leer = exigir_permiso(PERM_PRODUCTO_LEER)
exigir_producto_editar = exigir_permiso(PERM_PRODUCTO_EDITAR)


async def tier_del_negocio(tenant: TenantContext = Depends(contexto_de_tenant)) -> str:
    """El tier del negocio en sesión. Hoy: `pro` para todos.

    Decisión 2 del plan del módulo: en Fase 1 no existe módulo de
    suscripciones ni columna de tier en `tenants`, y el plan maestro §5
    registra a todo negocio nuevo en el trial de Pro. El límite ya se
    verifica de verdad en `CatalogoService` (testeado con los tres tiers vía
    `dependency_overrides`); esta función es el ÚNICO punto de cambio cuando
    llegue la suscripción.
    """
    return TIER_DEL_PILOTO


async def servicio_de_catalogo(
    tenant: TenantContext = Depends(exigir_negocio_activo),
    session: AsyncSession = Depends(sesion_de_tenant),
    tier: str = Depends(tier_del_negocio),
) -> CatalogoService:
    """El servicio del negocio del token, con la sesión que la RLS acota.

    `exigir_negocio_activo` va primero: un negocio suspendido corta con 403
    `tenant_suspendido` antes de tocar el catálogo (la suspensión es
    app-level; el token sigue siendo criptográficamente válido).
    """
    return CatalogoService(session=session, tenant_id=tenant.tenant_id, tier=tier)


__all__ = [
    "exigir_permiso",
    "exigir_producto_editar",
    "exigir_producto_leer",
    "servicio_de_catalogo",
    "tier_del_negocio",
]
```

- [ ] **Paso 4: implementar el router.** Crear `backend/services/api/app/modules/catalogo/router.py`:

```python
"""Catálogo: `/api/v1/productos/*`.

Primer router de dominio de Fase 1. Todo lo que hay aquí trabaja con la
sesión de TENANT (rol `vendi_app`, RLS activo): ningún handler recibe un
`tenant_id` por URL, cuerpo o cabecera — el único que interviene es el que
`TenantMiddleware` sacó del claim `organization`, y la policy hace el resto.

Los permisos (ADR-023): lectura con `producto:leer` (los tres roles),
escritura con `producto:editar` (dueño y almacenista; el cajero recibe 403
`permiso_ausente`, que es la respuesta correcta y esperada).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.modules.catalogo.dependencies import (
    exigir_producto_editar,
    exigir_producto_leer,
    servicio_de_catalogo,
)
from app.modules.catalogo.schemas import ProductoActualizar, ProductoCrear, ProductoSalida
from app.modules.catalogo.service import CatalogoService
from vendi_core.auth.context import UserContext
from vendi_core.models.pagination import PagedList
from vendi_core.models.responses import ErrorResponse

router = APIRouter(prefix="/productos", tags=["catalogo"])

_RESPUESTAS_COMUNES = {
    401: {"model": ErrorResponse, "description": "Falta el token o no es válido"},
    403: {"model": ErrorResponse, "description": "Falta el permiso o el negocio está suspendido"},
    404: {"model": ErrorResponse, "description": "El producto no existe"},
}


@router.post(
    "",
    response_model=ProductoSalida,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un producto",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "EAN duplicado o id ya usado"},
    },
)
async def crear_producto(
    datos: ProductoCrear,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_editar),
) -> ProductoSalida:
    """Acepta el `id` que traiga el cliente (ADR-017): reenviar la misma
    creación devuelve el producto ya creado, sin duplicar fila ni evento."""
    return ProductoSalida.model_validate(await servicio.crear(datos))


@router.get(
    "",
    response_model=PagedList[ProductoSalida],
    summary="Listar productos",
    responses={k: v for k, v in _RESPUESTAS_COMUNES.items() if k != 404},
)
async def listar_productos(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    q: str | None = Query(default=None, description="Texto a buscar en el nombre"),
    categoria: str | None = Query(default=None),
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_leer),
) -> PagedList[ProductoSalida]:
    filas, total = await servicio.listar(skip=skip, limit=limit, q=q, categoria=categoria)
    return PagedList[ProductoSalida](
        items=[ProductoSalida.model_validate(f) for f in filas],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/por-codigo/{codigo}",
    response_model=ProductoSalida,
    summary="Buscar un producto por código de barras",
    responses=_RESPUESTAS_COMUNES,
)
async def buscar_por_codigo(
    codigo: str,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_leer),
) -> ProductoSalida:
    """El camino del escáner (ADR-024): un EAN resuelve a exactamente un
    producto, gracias al índice único parcial."""
    return ProductoSalida.model_validate(await servicio.buscar_por_codigo(codigo))


@router.get(
    "/{producto_id}",
    response_model=ProductoSalida,
    summary="Ver un producto",
    responses=_RESPUESTAS_COMUNES,
)
async def ver_producto(
    producto_id: uuid.UUID,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_leer),
) -> ProductoSalida:
    return ProductoSalida.model_validate(await servicio.obtener(producto_id))


@router.patch(
    "/{producto_id}",
    response_model=ProductoSalida,
    summary="Actualizar un producto",
    responses={
        **_RESPUESTAS_COMUNES,
        409: {"model": ErrorResponse, "description": "EAN duplicado"},
    },
)
async def actualizar_producto(
    producto_id: uuid.UUID,
    datos: ProductoActualizar,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_editar),
) -> ProductoSalida:
    """No acepta `stock_actual` ni `ultimo_costo`: el stock lo mueven los
    movimientos de inventario y el costo las compras (ADR-020)."""
    return ProductoSalida.model_validate(await servicio.actualizar(producto_id, datos))


@router.delete(
    "/{producto_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dar de baja un producto (borrado lógico)",
    responses=_RESPUESTAS_COMUNES,
)
async def eliminar_producto(
    producto_id: uuid.UUID,
    servicio: CatalogoService = Depends(servicio_de_catalogo),
    _actor: UserContext = Depends(exigir_producto_editar),
) -> Response:
    """Marca `deleted_at` y libera el EAN. La fila sobrevive: el historial de
    ventas la referencia (ADR-019)."""
    await servicio.eliminar(producto_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Paso 5: montar el router en la app.** En `backend/services/api/app/factory.py`:

  a) Añadir el import junto a los de los otros routers:

```python
from app.modules.catalogo.router import router as router_catalogo
```

  b) Montarlo tras `router_tenants`:

```python
    app.include_router(router_tenants, prefix="/api/v1")
    app.include_router(router_catalogo, prefix="/api/v1")
```

  c) Actualizar la línea de `DESCRIPCION` que dice `API regional de Vendi. Fase 0: fundación.` por:

```python
API regional de Vendi. Fase 1: fundación + catálogo de productos.
```

- [ ] **Paso 6: verificar.**

```bash
cd backend && uv run pytest tests/api/test_catalogo_productos.py -q
# Esperado: 15 passed
uv run pytest tests/api -q
# Esperado: toda la carpeta verde (los tests de tenants no se tocan)
uv run ruff check .
# Esperado: All checks passed!
```

- [ ] **Paso 7: commit**

```bash
git add backend/services/api/app/modules/catalogo/dependencies.py backend/services/api/app/modules/catalogo/router.py backend/services/api/app/factory.py backend/tests/api/test_catalogo_productos.py backend/tests/api/ayudas.py backend/tests/api/conftest.py
git commit -m "Router del catálogo con permisos por rol, búsqueda por EAN y listado paginado"
```

**Criterios de aceptación:** los 15 tests del router pasan contra el stack real, 0 SKIPPED; cajero 403 en escritura y 200 en lectura; un id de otro negocio es 404; `tests/api` completo verde; `ruff` limpio.

---

## Tarea 7: Extender el check 23 de `verify-setup.sh` (candado de ADR-023)

**Files:**
- Modify: `scripts/verify-setup.sh` (bloque del check 23, ~líneas 699-748)

**Interfaces:**
- Consume: el generador de tokens de ejemplo de la Admin API que el check 23 ya usa para inspeccionar `realm_access.roles` del token del dueño demo.
- Produce: el check falla si el token del dueño no trae `producto:leer` y `producto:editar` — «un permiso que nadie tiene en el token del dueño es un bug de siembra, no de autorización» (ADR-023).

- [ ] **Paso 1: extender el bloque Python del check 23.** En `scripts/verify-setup.sh`, dentro del heredoc `python3 - <<'PY'` del check 23, sustituir el bloque de `problemas`:

```python
problemas = []
if aud_esperada not in aud:
    problemas.append(f"aud={aud or '(ninguna)'}, esperaba {aud_esperada}")
if "dueno" not in roles:
    problemas.append("realm_access.roles no trae 'dueno' (deuda D-08: has_role() sería inerte)")
for permiso in ("producto:leer", "producto:editar"):
    if permiso not in roles:
        problemas.append(
            f"realm_access.roles no trae '{permiso}' (ADR-023: el grupo dueno debe mapearlo; "
            "un permiso ausente del token del dueno es un bug de siembra, ejecuta scripts/seed.sh)"
        )
print("OK" if not problemas else " · ".join(problemas))
```

y el mensaje del `ok`:

```bash
        ok "aud=${KEYCLOAK_AUDIENCE:-vendi-backend}, rol de negocio y permisos de catálogo en el token del dueño"
```

- [ ] **Paso 2: verificar contra el stack.**

```bash
bash scripts/seed.sh && bash scripts/verify-setup.sh 2>&1 | grep -E "^\[(OK|FALLO|OMITIDO)\].*23"
# Esperado: [OK] 23 ... permisos de catálogo en el token del dueño
```

Prueba negativa (obligatoria): quitar temporalmente `producto:editar` del mapeo del grupo `dueno` en la consola de Keycloak (`https://accounts.vendi.co`, con `--resolve accounts.vendi.co:443:127.0.0.1`), re-ejecutar el check y verlo fallar con el mensaje de siembra; restaurar con `bash scripts/seed.sh` y ver el OK.

- [ ] **Paso 3: commit**

```bash
git add scripts/verify-setup.sh
git commit -m "El check 23 exige los permisos de catálogo en el token del dueño (ADR-023)"
```

**Criterios de aceptación:** el check 23 pasa con la siembra al día y falla —con mensaje accionable— si falta cualquiera de los dos permisos.

---

## Tarea 8: Congelar el OpenAPI y regenerar el cliente TypeScript

**Files:**
- Modify: `docs/api/openapi-fase0.json` (regenerado, mismo archivo — decisión 5 del plan)
- Modify: `docs/api/README.md` (título y tabla de rutas)
- Modify: `frontend/projects/libs/data-access/src/lib/api-client/openapi.json` e `index.ts` (salida del codegen)

**Interfaces:**
- Consume: la API viva con `DOCS_PUBLICOS=true` (el stack de desarrollo ya lo trae) y `scripts/codegen-api-client.sh` en modo congelado.
- Produce: el contrato con las 6 rutas del catálogo; el cliente TS regenerado sin deriva (`codegen + git diff --exit-code` en 0).

- [ ] **Paso 1: regenerar el contrato congelado desde la API viva.** Con el stack levantado y la migración aplicada:

```bash
curl -sS --resolve api.vendi.co:443:127.0.0.1 https://api.vendi.co/openapi.json \
  | python3 -c 'import json,sys; json.dump(json.load(sys.stdin), open("docs/api/openapi-fase0.json","w"), indent=2, ensure_ascii=False, sort_keys=True)'
python3 -c 'import json; d=json.load(open("docs/api/openapi-fase0.json")); print(sorted(p for p in d["paths"] if "productos" in p))'
# Esperado: ['/api/v1/productos', '/api/v1/productos/por-codigo/{codigo}', '/api/v1/productos/{producto_id}']
```

`sort_keys=True` e `indent=2` no son cosméticos: sin orden estable, cada regeneración produce un diff ilegible (lo dice el propio README del contrato).

- [ ] **Paso 2: actualizar `docs/api/README.md`.** Cambiar el título `# Contrato de la API — Fase 0` por `# Contrato de la API — esquema congelado`, ajustar la primera línea («`openapi-fase0.json` es el esquema **congelado** de la API. Se llama así por historia —nació en la Fase 0— pero contiene el contrato vigente completo; es la fuente única del codegen y del job `frontend-contratos` del CI.») y añadir a la tabla de rutas:

```markdown
| `POST /api/v1/productos` | `producto:editar` | alta; acepta `id` del cliente (idempotente, ADR-017); 409 por EAN duplicado; 403 por límite del tier |
| `GET /api/v1/productos` | `producto:leer` | listado paginado (`PagedList`) con `q` (nombre) y `categoria` |
| `GET /api/v1/productos/por-codigo/{codigo}` | `producto:leer` | el camino del escáner: un EAN → un producto |
| `GET/PATCH/DELETE /api/v1/productos/{id}` | `producto:leer` / `producto:editar` | ver, editar (sin `stock_actual` ni `ultimo_costo`), borrado lógico |
```

y a la lista de `code` estables: `producto_no_encontrado`, `codigo_barras_duplicado`, `producto_id_duplicado`, `padre_no_encontrado`, `padre_es_el_mismo`, `limite_de_productos_alcanzado`, `permiso_ausente`.

- [ ] **Paso 3: regenerar el cliente y demostrar que no hay deriva.**

```bash
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh
cd frontend && npm run build:libs && npx ng build vendi-admin
# Esperado: build de libs y de vendi-admin en verde (contrato.ts sigue compilando)
git add docs/api frontend/projects/libs/data-access/src/lib/api-client
git diff --cached --stat
```

- [ ] **Paso 4: commit**

```bash
git commit -m "Contrato OpenAPI con las rutas del catálogo y cliente TypeScript regenerado"
```

**Criterios de aceptación:** el OpenAPI congelado contiene las rutas de `productos` con sus schemas; el job `frontend-contratos` del CI (codegen contra el congelado + `git diff --exit-code`) queda en verde; `vendi-admin` compila contra el cliente regenerado.

---

## Tarea 9: Cierre del módulo — gate de la Etapa 1.2 y `docs/estado.md`

**Files:**
- Modify: `docs/estado.md` (sección nueva del módulo catálogo, con fecha de corte y evidencia comando+salida)
- Modify: `docs/deuda-tecnica.md` (solo si quedó deuda nueva; si no, no se toca)

- [x] **Paso 1: ejecutar el gate completo del módulo** (idéntico al de cualquier módulo de la Etapa 1.2):

```bash
bash scripts/migrate.sh
cd backend && uv run pytest -q
# Esperado: toda la suite verde; los tests nuevos integration corren (0 SKIPPED)
uv run pytest -q -m integration
# Esperado: verde, 0 SKIPPED
uv run ruff check .
# Esperado: All checks passed!
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git diff --exit-code
# Esperado: salida 0 (sin deriva de contrato)
```

Gate por módulo (del plan maestro de Fase 1), verificado ítem a ítem:
- [x] Migración con RLS + índice + grants, revisada por el agente de seguridad.
- [x] Tests de integración con aislamiento cross-tenant nuevo por tabla (`test_aislamiento_productos.py`), 0 SKIPPED.
- [x] OpenAPI congelado actualizado + codegen + `contrato.ts` sigue compilando.
- [x] Eventos de outbox emitidos según ADR-019 (`producto.creado/actualizado/eliminado`, clave `<tenant_id>.producto.*`); `pytest -m integration` verde; `ruff` verde.

- [x] **Paso 2: actualizar `docs/estado.md`.** Añadir una sección «Módulo catálogo (Fase 1, Etapa 1.2)» con: fecha de corte, qué se entregó (tabla, endpoints, permisos, eventos), y **al lado de cada afirmación el comando que la demuestra** con su salida pegada (regla del documento: no promete nada que un comando no demuestre). Si quedó deuda (p. ej. «el tier se resuelve como `pro` hasta que exista el módulo de suscripciones»), registrarla en `docs/deuda-tecnica.md` con vencimiento.

- [x] **Paso 3: commit de cierre**

```bash
git add docs/estado.md docs/deuda-tecnica.md
git commit -m "Módulo catálogo cerrado: gate de la Etapa 1.2 verificado y estado actualizado"
```

---

## Superficie de ataque para QA — módulo catálogo

Para el agente de QA adversarial de la Etapa 1.4 (agente distinto del implementador; su KPI son hallazgos):

- **Aislamiento:** con dos negocios semilla, intentar leer/editar/borrar el producto del vecino por id (debe ser 404, no 403 ni 200), por EAN (ídem), y por listado con `q` que solo matchea productos del vecino (`total` debe ser 0). Intentar crear una variante con `padre_id` del vecino (debe ser 422 `padre_no_encontrado`, y la fila NO debe quedar insertada — la FK de Postgres no aplica RLS).
- **Idempotencia:** el mismo POST con `id` de cliente tres veces (una fila, un evento `producto.creado`); el mismo `id` con cuerpo distinto (hoy devuelve el existente — decisión 4 del plan, verificar que queda documentada); dos altas concurrentes con el mismo `id` (una debe ganar y la otra recibir 201 con la ganadora o 409, nunca dos filas).
- **EAN:** dos productos con el mismo EAN en el mismo tenant (409), el mismo EAN en dos tenants (201/201), re-alta con el EAN de un producto dado de baja (201 — el EAN se liberó), PATCH que pone un EAN ya usado por OTRO producto del mismo tenant (409 `codigo_barras_duplicado`, y el producto queda como estaba).
- **Límite de tier:** con override a `gratis` y 100 filas sembradas, el alta 101 da 403 con `details.limite == 100`; dar de baja uno y reintentar (debe entrar: el límite cuenta filas VIVAS). Verificar que un negocio con override a `light` se detiene en 500.
- **Permisos:** cajero → 200 en GET, 403 en POST/PATCH/DELETE con `code=permiso_ausente`; almacenista → 200/201/200/204; token sin el claim `organization` → 401/403 del middleware, no un 500; negocio suspendido a media sesión → 403 `tenant_suspendido` en el siguiente request (≤ TTL del cache de estado, 60 s).
- **Validación y bordes:** `precio_venta` enorme (int32 de Postgres: ¿422, 409 o 500? — lo que salga que no sea 500 o se registra como deuda), `nombre` de 160 y 161 caracteres, `q` con `%` y `_` (comodines escapados), `skip` más allá del total (lista vacía, no error), `limit=0` y `limit=100000` (422).
- **Stock intocable:** PATCH con `stock_actual` en el cuerpo (debe ignorarse o 422, jamás aplicarse — la invariante del libro de ADR-020 depende de ello).
- **Ciclos de variantes:** `padre_id` apuntando a sí mismo (422 `padre_es_el_mismo`); ciclo indirecto A→B→A (hoy NO se detecta: si se considera hallazgo, va a `deuda-tecnica.md` con vencimiento).

---

## Self-Review

- **Cobertura del spec:** ADR-019 (tabla, EAN único parcial, NUMERIC para cantidades, centavos para dinero, `iva_pct`, borrado lógico, categoría texto, eventos, límite en aplicación) → Tareas 1, 2, 3, 5. ADR-017 (UUID de cliente como PK, idempotencia) → Tareas 3, 5, 6. ADR-020 (stock como proyección, el catálogo no lo mueve) → Tareas 2, 3, 5 (columnas declaradas, schemas sin `stock_actual`, QA lo ataca). ADR-023 (`producto:leer`/`producto:editar`, reparto por rol, candados) → Tareas 4, 6, 7. ADR-010 (límite por tier) → Tarea 5 + decisión 2. Gate de la Etapa 1.2 → Tarea 9. Item 5 del encargo (OpenAPI/codegen/estado.md) → Tareas 8 y 9.
- **Placeholders:** ninguno. Todo paso lleva código completo, comando exacto y salida esperada. Las únicas cantidades que el ejecutor puede tener que ajustar son los conteos de tests si añade casos (los comandos de verificación son de suite, no de conteo, salvo donde se indica).
- **Consistencia de tipos/contratos:** los nombres de columnas, índices, checks y constraints coinciden entre migración (Tarea 1), modelo (Tarea 2) y tests de metadata; los `code` de error coinciden entre servicio, router, tests y la tabla de `docs/api/README.md`; los eventos usan la firma real de `DomainEventService.emit` y el formato de clave `<tenant_id>.producto.*` que ADR-019 firma y `test_tenants_crud.py` ya ejemplifica.
- **Riesgos conocidos y declarados:** (1) el tier resuelto como `pro` es una decisión fuera de ADR — queda justificada en la sección de decisiones y como candidata a entrada de deuda con vencimiento; (2) los ciclos indirectos de variantes no se detectan — queda en la superficie de QA; (3) `stock_actual` se declara pero ningún consumidor lo lee todavía — es lo firmado (ADR-020 lo proyecta en el módulo de inventario).
