# ADR-019 — Catálogo: productos vendibles, variantes como filas, IVA como dato

**Fecha:** 2026-07-27 · **Estado:** Firmada
**Origen:** `docs/plan-maestro.md` §3 (Ventas/POS e Inventario) y §7 (Fase 1);
límite de catálogo por tier en §5 (100 / 500 / ilimitado productos).

## Contexto

Todo lo de Fase 1 cuelga del catálogo: el POS cobra productos, el inventario los
descuenta, las compras los reabastecen y el P&L (ADR-006) los costea. Había que
decidir la forma del modelo antes de escribir el primer módulo de negocio, y la
presión concreta es la tienda de barrio colombiana real: productos con código de
barras y sin él, la misma gaseosa en dos presentaciones, fruver y carnes que se
venden por peso, y precios que incluyen IVA a tarifas distintas (0 %, 5 %,
19 %) según el producto.

## Decisión

**Una sola tabla `productos` donde cada fila es un ítem vendible**, con estas
reglas:

- **La variante es una fila más.** `padre_id UUID NULL` autorreferencia al
  producto base; las hojas (padre e hijas) son lo vendible: cada una lleva su
  código de barras, su precio y su stock. La gaseosa de 400 ml y la de 1,5 l ya
  tienen códigos de barras distintos en el mundo real; modelarlas como dos
  filas es más fiel que una jerarquía de atributos.
- **Código de barras opcional y único por negocio.** `codigo_barras TEXT NULL`
  con índice único parcial `(tenant_id, codigo_barras) WHERE codigo_barras IS
  NOT NULL`. Opcional porque gran parte del surtido de barrio no tiene EAN
  (bolsa de arroz a granel, huevo por unidad); único porque el escáner (ADR-024)
  necesita que un código resuelva a exactamente un producto.
- **Cantidades decimales, dinero en enteros.** `unidad_medida` (`unidad`,
  `kg`, `g`, `lt`, `ml`) y stock en `NUMERIC`: el fruver se vende a 0,350 kg.
  Un stock entero obligaría a modelar el granel como productos ficticios
  («250 g de lenteja»), que es como el tendero NO piensa su tienda. Los
  precios, en cambio, son enteros en centavos (criterio unificado con
  ADR-018): el dinero nunca se representa en flotante ni en `NUMERIC` con
  decimales.
- **IVA como dato del producto, no como módulo fiscal.** `iva_pct NUMERIC(5,2)`
  por fila (0, 5 u 19 hoy en Colombia). La facturación electrónica DIAN es
  Fase 2 (add-on, ADR-010); para el MVP el IVA solo alimenta el desglose del
  ticket y el P&L, y un número por producto basta.
- **Un solo precio de venta y un último costo.** `precio_venta` y
  `ultimo_costo` (lo actualiza cada compra registrada, ADR-020) son lo que el
  P&L simple de ADR-006 necesita. No hay listas de precios ni precio por
  cliente en el MVP.
- **Borrado lógico** (`deleted_at`), como en `tenants`: el historial de ventas
  referencia productos que ya no se venden, y borrar la fila rompería el
  cuaderno.
- **Categoría como texto libre** (`categoria TEXT NULL`), no tabla. La
  clasificación ABC del plan maestro §3 es un cálculo sobre ventas, no una
  taxonomía que mantener.

El límite de productos por tier (ADR-010) se verifica en la aplicación contra
las filas vivas del negocio; no es una constraint de base.

## Alternativas descartadas

- **Producto + tabla `variantes` separada (modelo e-commerce).** Obliga a crear
  dos filas y entender una jerarquía para el caso del 90 %: un producto, un
  precio, un código. La complejidad se paga en cada alta y en cada consulta del
  POS, y la pantalla táctil del POS quiere una lista plana de vendibles.
- **Tabla de impuestos configurable.** Colombia tiene tres tarifas de IVA
  vigentes y la tienda no configura impuestos: los hereda del producto. Una
  tabla de impuestos es diseño para el contador que no usa la app (ADR-006:
  fuera de scope la contabilidad formal).
- **Código de barras obligatorio.** Excluiría de entrada el granel y el
  «traído de la plaza», que son el corazón del margen de la tienda de barrio.
- **Una tabla `categorias` con su CRUD.** Sin reportes que la consuman en el
  MVP es una entidad sin consumidor — el error que ADR-016 lista para los
  módulos de backlog: escribir contra un consumidor imaginado.

## Consecuencias

- El POS y el catálogo local offline (ADR-017) cachean filas planas de
  vendibles; la sincronización de catálogo es «estas filas cambiaron», sin
  árboles que fusionar.
- El stock negativo y los decimales de peso se propagan a todo lo que toca
  cantidades: movimientos de inventario, ítems de venta e ítems de compra son
  `NUMERIC`, nunca `INTEGER`.
- Cuando llegue la DIAN (Fase 2) habrá que añadir lo fiscal de verdad
  (unidades de medida estándar, códigos UNSPSC); se hará como ampliación, no
  como reescritura: `iva_pct` ya está en el sitio correcto.
- Los índices del catálogo parten de `tenant_id` (regla de ADR-013); la
  búsqueda por nombre para el POS usa un índice adicional sobre
  `(tenant_id, nombre)`.

## Tablas nuevas

- **`productos`** — `tenant_id` + RLS (`enable_rls`), índice por `tenant_id`,
  índice único parcial de código de barras, índice `(tenant_id, nombre)`,
  FK `padre_id` a sí misma.

## Eventos de outbox que emite

- `producto.creado`, `producto.actualizado`, `producto.eliminado` — con
  `tenant_id` del negocio (clave de enrutado `<tenant_id>.producto.*`, patrón
  de `vendi_core.events`). Su consumidor es la invalidación del catálogo local
  de los dispositivos offline y, más adelante, el cálculo ABC.

## Candado verificable

- Test de aislamiento cross-tenant sobre `productos` con la plantilla
  `backend/tests/integration/test_cross_tenant_isolation.py` (PostgreSQL real,
  falla —no se omite— si falta el servicio).
- Test de integración de la unicidad del código de barras: mismo EAN en dos
  tenants distintos se acepta; duplicado dentro del mismo tenant se rechaza.
- `test_rls_coverage.py` ya delata cualquier tabla nueva sin `enable_rls` en su
  migración.
