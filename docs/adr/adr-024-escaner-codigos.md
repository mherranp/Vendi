# ADR-024 — Escáner de códigos: cámara nativa, lookup local y alta rápida

**Fecha:** 2026-07-27 · **Estado:** Firmada (Fase 1)
**Origen:** `docs/plan-maestro.md` §3 (POS: «escáner de código»), §4.2 (pipeline de
escaneo en 3 capas) y §7 (Fase 1). Complementa ADR-001 y ADR-011.

## Contexto

El plan maestro adopta del socio un pipeline de escaneo en 3 capas (§4.2):
código de barras on-device, VLM estándar para recibos impresos y productos sin
código, y VLM avanzado para manuscritos. Lo que el plan no dice es qué de eso
es del POS del MVP, dónde corre cada capa y —la pregunta que decide si el
escáner se usa o se abandona— qué pasa cuando el código escaneado **no existe**
en el catálogo de la tienda. En una tienda de barrio colombiana eso es lo
normal al principio: el catálogo nace vacío y se construye vendiendo.

## Decisión

**Capa 1 es la única capa del POS, y corre entera en el dispositivo.** Las
capas 2 y 3 (VLM) no son del POS: las consumen catálogo y compras
(ADR-019/ADR-020) y se ejecutan **en el backend** a través de `AIProvider`
(ADR-007/ADR-026), porque la API key del proveedor no puede vivir en la app.

Tres piezas concretas:

- **Cámara:** plugin de barcode de Capacitor (ML Kit en Android, AVFoundation
  en iOS), envuelto en la librería `native` — el único punto del workspace
  autorizado a importar `@capacitor/*` (ADR-011). Sin red, latencia <100 ms.
- **Base local de códigos:** el lookup se hace contra el catálogo local en
  IndexedDB, que es la fuente de verdad local del POS offline (ADR-017).
  Nunca contra la API durante una venta: una consulta de red por ítem rompe
  el «cobro en <5s» y mata el escáner en los sótanos sin señal donde opera
  media tienda de barrio.
- **Código desconocido → alta rápida en el POS:** escanear un código que no
  está en el catálogo abre un formulario mínimo —nombre y precio, con el
  código ya capturado— **dentro del flujo de venta**. Al confirmar, el
  producto queda creado y el ítem añadido a la venta en curso. Sin conexión,
  el alta entra en la cola de sincronización como cualquier escritura offline
  (ADR-017). Consecuencia para el catálogo: ADR-019 tiene que aceptar la
  creación de un producto con solo nombre, precio y código — el resto de
  campos no puede ser obligatorio.

La entrada manual del código por teclado existe siempre (cámara rota, gama
baja, luz mala), y una pistola de códigos USB/Bluetooth funciona como teclado
HID sin escribir una línea adicional.

## Alternativas descartadas

- **VLM en el dispositivo (capas 2-3 locales).** Exigiría distribuir la API
  key con la app —un secreto en 50–100 celulares ajenos— o embarcar un modelo
  local pesado en gama baja. ADR-007 ya decidió centralizar los proveedores;
  la foto sube comprimida (800 px, §4.2) y la extracción vuelve estructurada.
- **Catálogo global precargado de códigos (tipo Open Food Facts).** Su
  cobertura para productos de barrio colombianos —marcas locales, granel,
  empaques sin EAN— es justo la que falta. La alta rápida resuelve el mismo
  problema sin depender de un tercero, y cada alta construye el catálogo del
  tenant, que es el dato que luego vale como switching cost (plan maestro §6).
- **Escáner web por `getUserMedia` (PWA sin plugin nativo).** Es el camino
  que ADR-001 ya descartó al firmar Capacitor: decodificación lenta y sin
  autofoco continuo en los Android de gama baja del segmento.

## Consecuencias

- El plugin de escaneo se añade a `native` con su fachada; ninguna otra capa
  lo importa, y el candado `no-restricted-imports` de ADR-011 lo vigila sin
  regla nueva.
- Vender un producto recién creado por alta rápida es una operación normal del
  POS: el modelo de producto y sus validaciones (ADR-019) nacen con esta
  presión, no pueden descubrirla después.
- Las capas 2-3 heredan el coste y el fallback del proveedor de IA: sin API
  key o sin red, la carga por foto no existe pero el POS y la capa 1 siguen
  intactos. El porqué de que el VLM no sea del POS es este: una tienda no
  puede dejar de cobrar porque Gemini esté caído.

## Tablas, eventos y candado

- **Tablas nuevas:** ninguna. El producto y su código viven en el modelo de
  catálogo (ADR-019); la copia local en IndexedDB la define ADR-017.
- **Eventos de outbox:** ninguno propio. La alta rápida es una escritura de
  catálogo normal y emite lo que ADR-019 declare para creación de producto.
- **Candado:** spec de `vendi-app` con el plugin mockeado que verifica las dos
  rutas decisivas sin red: (a) código conocido → ítem en la venta sin tocar
  la API; (b) código desconocido → alta rápida con el código precargado y
  venta que continúa. Más el test de integración de API de que la creación
  mínima de producto (nombre + precio + código) es aceptada (ADR-019).
