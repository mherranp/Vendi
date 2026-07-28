# `vendi-portal` comercial — landing pública con propuesta de valor, precios de ADR-010 y captación por WhatsApp (Fase 1, Etapa 1.3, pista comercial) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir `vendi-portal` —hoy una página de Fase 0 con un párrafo y un enlace— en la landing comercial del MVP: hero con la propuesta de valor «del cuaderno al celular» (POS que vende sin internet, fiado sin cuaderno con recordatorios, inventario al día, caja al peso), la tabla de precios de ADR-010 con los precios reales en pesos (Gratis $0, Light $19.500/mes, Pro $40.000/mes —borde inferior del rango firmado—, el trial de 1 mes de Pro sin tarjeta como sello estrella y el add-on DIAN marcado «Próximamente — Fase 2», sin precio), la captación honesta de Fase 1 (CTA de WhatsApp `wa.me` con mensaje prearmado, SIN endpoint de backend — decisión 1 con sus cinco razones—, y sin promesa de auto-registro porque el realm no lo tiene abierto — decisión 2), la sección de confianza (offline-first, datos aislados por negocio, hecho para la tienda de barrio colombiana), SEO/compartir básico en el HTML estático (título, meta description, Open Graph mínimo sin `og:image` — no hay asset de marca), accesibilidad WCAG (solo pares de color medidos, objetivo táctil de 48px, landmarks y `h1` único), el respaldo i18n propio del portal (si `/i18n/es.json` falla, la superficie pública NUNCA pinta claves crudas) y el retiro del contenido provisional de Fase 0. El backend, el contrato OpenAPI, `nginx-spa.conf` y el `Dockerfile` NO se tocan.

**Architecture:** `vendi-portal` sigue siendo la app pública y anónima del workspace (ADR-012): sin Keycloak, sin sesión, sin llamadas de negocio. Todo lo nuevo vive dentro del feature `inicio`: `planes.ts` + `moneda.ts` (TS puro, los datos comerciales y el formato — presentación, no dominio compartido: no van a `domain` ni a `data-access`), tres componentes de sección (`hero`, `precios`, `confianza`) que compone `InicioComponent`, y un `InjectionToken` (`WHATSAPP_COMERCIAL`) que lee el número del `environment`. Los estilos usan exclusivamente los tokens `--vd-*` del tema de `ui-kit` (Material 3 con `light-dark()`); el i18n usa el cargador resiliente de `data-access`, ahora con el propio catálogo del portal como respaldo empotrado (`proveerI18nVendi(respaldo)` ya acepta el parámetro). De `ui-kit` solo se consume `StatusBadgeComponent` para los sellos («1 mes de Pro gratis», «Próximamente»).

**Tech Stack:** Angular 21 (standalone, signals, control flow `@if`/`@for`) · TypeScript 5.9 · Vitest sobre jsdom (`@angular/build:unit-test`) · ngx-translate 17 · `ui-kit` (componentes + tema) · `data-access` (i18n resiliente). Sin dependencias nuevas.

**Spec fuente:**
- `docs/adr/adr-010-tiers-y-precios.md` (Gratis / Light ~$19.500 / Pro ~$40.000–$60.000 + add-on DIAN aparte; trial de 1 mes de Pro sin tarjeta; los precios son hipótesis a validar en el piloto)
- `docs/adr/adr-004-cobro-web-first.md` (la suscripción se cobra SOLO en el portal web, Fase 2; el portal existe para la conversión; dentro de la app no hay CTAs de compra)
- `docs/adr/adr-009-fiado-y-clientes.md` (el fiado ES el cuaderno; el argumento comercial es «del cuaderno al celular»)
- `docs/adr/adr-012-cuatro-apps-angular.md` (`vendi-portal` = `vendi.co`/`www.vendi.co`, público anónimo, sin autenticación)
- `docs/monetizacion-web.md` §2 (la tabla de límites por tier: 100/500/ilimitado productos, 1/2/3 usuarios, fiado desde Light, IA 5/mes y 30/día) y §3 (los precios se anclan por día; los métodos de pago y el checkout son Fase 2)
- `docs/plan-maestro.md` §5 (tiers y precios como hipótesis etiquetadas), §6 (la venta es por agentes de barrio y WhatsApp: guion §6 de monetizacion-web) y §7 (piloto 50–100 tiendas reclutadas desde listas CCB — no por tráfico orgánico)
- `docs/superpowers/plans/2026-07-27-fase1-mvp-colombia-plan.md` §Etapa 1.3 («Comercial: `vendi-portal` con captación y precios (ADR-010)»; gate: 9 proyectos verdes, budgets sin relajar)
- Hechos verificados del código que condicionan el diseño: `infra/keycloak/realm-vendi-co.json` (sin `registrationEnabled`: NO hay auto-registro público — ADR-027 lo describe como riesgo y el alta de tienda es por `provisioner`/agentes); `frontend/projects/libs/data-access/src/lib/i18n/i18n.provider.ts:140` (`proveerI18nVendi` acepta respaldo alternativo); `frontend/projects/libs/ui-kit/src/lib/components/status-badge/status-badge.component.ts` (inputs `etiqueta` requerido y `variante`); `frontend/projects/vendi-portal/eslint.config.js` (el grupo prohibido es `['@capacitor/*', 'dexie', 'native']`: `ui-kit`, `domain`, `auth` y `data-access` permitidos)
- Plantillas a imitar: `docs/superpowers/plans/2026-07-29-pos-offline-vendi-app-plan.md` (formato de este plan), `frontend/projects/vendi-portal/src/app/app.spec.ts` (cargador i18n de prueba con `fusionarCatalogos`), `frontend/projects/vendi-portal/src/app/features/inicio/` (el feature actual que este plan reescribe)

## Global Constraints

- Todo artefacto en español riguroso (código, docstrings, commits, claves i18n, mensajes). Sin tildes ni eñes en identificadores técnicos que viajen en tokens, URLs, JSON o claves de traducción. El copy visible sí lleva sus tildes.
- TDD en cada tarea: primero el test que falla (con la salida del fallo esperada), luego la implementación completa, luego el test en verde, luego el commit. Prohibido «similar a», «agregar validación», TODO o código elidido.
- El backend NO se toca: ni un endpoint, ni una migración, ni `docs/api/openapi-fase0.json`. La captación de Fase 1 no necesita servidor (decisión 1). El codegen no debe derivar.
- Toda cadena visible va por `translate` con las claves nuevas en `frontend/projects/vendi-portal/public/i18n/es.json`; ninguna cadena cruda en plantillas (el candado de i18n del repo ya existe en Fase 0). La única excepción histórica —las cifras literales `100`, `500`, `1`, `2`, `3` de la comparativa— son números, no texto.
- Ningún color nuevo sin medir. Solo se usan: los tokens `--vd-*` (los pares de insignias y textos están medidos y candados por `npm run verificar:contraste`, que corre en CI) y el par `#047857` (`--vd-marca-700`) sobre `#ffffff` para el CTA, medido a mano con la fórmula WCAG 2.1 al escribir este plan: **5.49:1** (AA para texto normal). Quien «ajuste» ese par tiene que volver a medir y decirlo.
- Dinero de mentira no: los precios se muestran en pesos colombianos con separador de miles de punto (`$19.500`), sin decimales, con el formateador propio de la Tarea 1 (nada de `Intl` con ICU variable entre entornos: la salida tiene que ser idéntica en CI, en el navegador y en el aserto del test).
- El ancla «por día» NUNCA promete de menos: se redondea estrictamente al alza al múltiplo de $50 siguiente (decisión 5).
- Accesibilidad como requisito, no como barniz: `h1` único, landmarks (`header`/`nav`/`main`/`footer`), objetivo táctil mínimo de 48px (`--vd-objetivo-tactil`) en todo enlace, «Incluido/No incluido» como texto (nunca ✓/✗ mudas para un lector de pantalla), `lang="es-CO"` ya fijado.
- Los budgets del portal (`500kB`/`1MB` inicial, `4kB`/`8kB` por estilo de componente) NO se relajan. `frontend/nginx-spa.conf` y `frontend/Dockerfile` quedan byte a byte iguales.
- El portal sigue anónimo y estático: sin Keycloak, sin guards, sin rutas nuevas (una sola página con anclas `#precios`/`#confianza`).
- Los commits son por tarea, mensajes en español estilo oración. Nunca `git push` sin confirmación humana.
- Un ADR no se edita para cambiar de opinión: lo que este plan decide más allá de los ADRs queda listado en la sección siguiente, con su justificación.

## Decisiones de diseño tomadas en este plan (más allá de los ADRs)

1. **Captación SIN endpoint de backend: el CTA es WhatsApp (`wa.me`), y se descarta el formulario nombre+whatsapp por YAGNI justificado.** Un endpoint `POST /interesados` es «una pieza pequeña pero real»: tabla, migración, router público sin tenant (rompe el patrón de la API, todo lo demás cuelga de `X-Tenant-Id`), rate-limit que no existe en el stack, y cambio del contrato OpenAPI. Y sobre todo no tiene consumidor: la infraestructura de notificación (workers `notify.jobs`, dunning por WhatsApp) es **Fase 2** (`docs/monetizacion-web.md` §9, tarea 4), así que los leads se pudrirían en una tabla que nadie lee durante el piloto. Además, almacenar nombre+celular de anónimos exige la autorización de tratamiento de datos de la Ley 1581 (Habeas Data) que hoy el portal no tiene. Mientras tanto, el canal de venta real ya existe y es WhatsApp: los agentes de barrio trabajan con guion por WhatsApp (`docs/monetizacion-web.md` §6) y el producto ya usa `wa.me` prearmado para los recordatorios del fiado (ADR-022). Un `wa.me` con mensaje prearmado pone al interesado directamente en el canal donde se cierra la venta, con cero backend y cero PII almacenada. El endpoint de leads se reevalúa en Fase 2, cuando exista `notify.jobs` y el portal `/pro`.
2. **El CTA NO apunta a la app porque no hay auto-registro: prometerlo sería mentira.** Verificado en `infra/keycloak/realm-vendi-co.json`: el realm no tiene `registrationEnabled`, y ADR-027 explica que abrir el auto-registro público es parte del riesgo que se mitigó — el alta de tienda es por `provisioner`, es decir, asistida por agentes (el piloto se recluta desde listas CCB, plan-maestro §7). Un botón «Empieza gratis» hacia `app.vendi.co` estrellaría al visitante nuevo contra una pantalla de login sin opción de registro. Por eso el CTA principal es «Quiero probarlo gratis» → WhatsApp (el agente da de alta y el trial aplica igual: «todo registro nuevo recibe 1 mes de Pro», monetizacion-web §2), y el enlace a `app.vendi.co` queda como «Ya tengo cuenta: entrar a mi negocio», que es lo único cierto hoy. Si en el futuro se abre el auto-registro, cambiar el destino del CTA es una línea.
3. **El número comercial es configuración de entorno, y mientras no exista, el CTA no se pinta.** En el repo no hay ningún número oficial de WhatsApp (verificado: solo usos de `wa.me` por cliente del fiado). Inventar uno en el código sería un placeholder prohibido; ocultar el mecanismo sería no entregar la captación. La salida honesta: `environment.whatsappComercial` (cadena vacía hoy) leído por el token `WHATSAPP_COMERCIAL`; con cadena vacía el CTA no se renderiza (spec firmado), con número sale el `wa.me` con el mensaje codificado (spec firmado), y un tercer spec bloquea el formato (solo dígitos: el `#` clásico de `wa.me` es el `+57` con el `+`). Cuando operaciones tenga el número es UNA línea en `environment.ts` y rebuild de la imagen — el portal se sirve estático, no hay configuración en caliente, y eso se dice así.
4. **Pro se publica a $40.000/mes: el borde inferior del rango firmado.** ADR-010 firma «~$40.000–$60.000» y etiqueta los precios como hipótesis de piloto. La landing no puede mostrar un rango («desde» sería engañoso si luego sale a $60.000), así que se fija el piso del rango: es coherente con la sensibilidad de precio del segmento y con el escalón Light «precio de un café» ($19.500). El spec de la Tarea 1 bloquea los tres precios: cambiarlos es una decisión de negocio que rompe un test a propósito, no un retoque de CSS.
5. **El ancla por día redondea estrictamente al alza.** `docs/monetizacion-web.md` ancla Pro en «menos de $1.300 al día», que era matemáticamente falso incluso para $39.000 (39.000/30 = 1.300 exactos: no es «menos de»). Regla de este plan: `pesosPorDia` devuelve el múltiplo de $50 estrictamente superior a `precio/30`, y el copy es «menos de {{valor}} al día». Resultados: Light → «menos de $700 al día», Pro → «menos de $1.350 al día». Ambos verdaderos. Gratis no tiene ancla.
6. **El respaldo i18n del portal es su propio catálogo.** El cargador resiliente cae a `CATALOGO_MINIMO_ES` cuando `/i18n/es.json` falla — y el mínimo no tiene ni una clave `portal.*`: la superficie pública y anónima pintaría claves crudas ante el primer visitante. `proveerI18nVendi(respaldo)` ya acepta el catálogo alternativo (`i18n.provider.ts:140`); el portal pasa el suyo fusionado sobre el mínimo. Coste: ~6 kB empotrados en el bundle inicial de una landing pública — nada. Con esto, si el JSON falla, la página pinta exactamente lo mismo.
7. **SEO/compartir en el HTML estático, sin SSR ni prerender.** Las tarjetas de WhatsApp/Facebook no ejecutan JavaScript: título, meta description y Open Graph mínimo van en `index.html` a mano. Sin `og:image`: no hay asset de marca (la rampa de color es «provisional: no hay manual de identidad», dice `_tokens.scss`), y una tarjeta sin imagen es fea pero honesta — un `og:image` inventado es peor. SSR/prerender queda fuera por YAGNI de Fase 1: Google ejecuta JS e indexa la SPA; los scrapers sociales solo leen las metas estáticas, que están. Se declara en la superficie de QA.
8. **Una sola página con anclas, sin rutas nuevas.** `/precios` como ruta propia llegará con el `/pro` transaccional de Fase 2 (monetizacion-web §3); hoy la tabla es una sección con `id="precios"` y enlaces de ancla en la barra. Menos superficie, menos tests de router, mismo resultado para el visitante.
9. **Los datos comerciales viven en el feature, no en libs.** `planes.ts` y `moneda.ts` son presentación de ESTA landing: nadie más los consume (la app no muestra precios — ADR-004 prohíbe el steering—, la consola aún no). Moverlos a `domain` sería especular con un consumidor que no existe; cuando `/pro` los necesite en Fase 2, se promueven con su decisión.
10. **El contenido provisional de Fase 0 se retira en bloque.** Las claves `portal.lema`, `portal.descripcion` y `portal.entrar` y el layout centrado de una columna desaparecen con la landing nueva; el spec viejo del portal («pinta el lema traducido») se reemplaza por specs de la página real. No hay candado que invertir aquí — el spec viejo no protegía un riesgo, solo describía el placeholder.

---

## Tarea 1: El modelo comercial y el formato de pesos (candado de ADR-010)

**Files:**
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/planes.ts`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/planes.spec.ts` (primero: el test que falla)
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/moneda.ts`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/moneda.spec.ts` (primero: el test que falla)

**Interfaces:**
- Consume: ADR-010 (precios y trial) y `docs/monetizacion-web.md` §2 (límites).
- Produce: `TIERS`/`TierComercial` y las constantes de precio que renderiza `PreciosComponent` (Tarea 3); `formatearPesos` y `pesosPorDia` para todo el feature.

- [ ] **Paso 1: el spec de `moneda.ts`.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/moneda.spec.ts`:

```ts
import { formatearPesos, pesosPorDia } from './moneda';

describe('formatearPesos', () => {
  it('el cero se muestra sin separadores', () => {
    expect(formatearPesos(0)).toBe('$0');
  });

  it('menos de mil no lleva separador', () => {
    expect(formatearPesos(999)).toBe('$999');
  });

  it('los miles llevan punto, a la colombiana', () => {
    expect(formatearPesos(1_300)).toBe('$1.300');
  });

  it('los dos precios firmados en ADR-010', () => {
    expect(formatearPesos(19_500)).toBe('$19.500');
    expect(formatearPesos(40_000)).toBe('$40.000');
  });

  it('millones con todos los separadores', () => {
    expect(formatearPesos(1_000_000)).toBe('$1.000.000');
  });

  it('rechaza lo que no es un entero en pesos', () => {
    expect(() => formatearPesos(-1)).toThrow();
    expect(() => formatearPesos(19.5)).toThrow();
    expect(() => formatearPesos(Number.NaN)).toThrow();
  });
});

describe('pesosPorDia', () => {
  it('el plan gratis no tiene ancla por día', () => {
    expect(pesosPorDia(0)).toBe(0);
  });

  it('redondea estrictamente AL ALZA al múltiplo de 50: nunca prometer de menos', () => {
    // 19.500/30 = 650 exactos: «menos de $650» sería FALSO. Sube a 700.
    expect(pesosPorDia(19_500)).toBe(700);
    // 40.000/30 = 1.333,33…: sube a 1.350.
    expect(pesosPorDia(40_000)).toBe(1_350);
  });
});
```

```bash
cd frontend && npx ng test vendi-portal --watch=false
# Esperado: FAIL — Cannot find module './moneda' (todavía no existe)
```

- [ ] **Paso 2: `moneda.ts`.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/moneda.ts`:

```ts
/**
 * Formato de dinero de la landing, en pesos colombianos.
 *
 * No usa `Intl.NumberFormat`: la salida de ICU varía entre versiones de Node
 * y navegadores (espacio duro, símbolo con o sin separación), y el precio de
 * la página pública tiene que verse IDÉNTICO en el test, en CI y en el
 * celular del tendero. Los precios son enteros de pesos —Colombia no usa
 * centavos en el habla— así que el formateador es una agrupación de miles.
 */

/**
 * `$` + miles con punto: 19_500 → `$19.500`.
 *
 * @throws si el valor no es un entero no negativo: un precio con decimales o
 *   negativo en la landing es un error de datos, no algo que maquillar.
 */
export function formatearPesos(valor: number): string {
  if (!Number.isInteger(valor) || valor < 0) {
    throw new Error(`formatearPesos espera un entero de pesos no negativo; recibió: ${valor}`);
  }
  return '$' + String(valor).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

/**
 * El ancla «menos de X al día», redondeada estrictamente AL ALZA al múltiplo
 * de $50 siguiente.
 *
 * «Menos de» es una promesa: si el cociente exacto cae en un múltiplo de 50
 * (19.500/30 = 650), decir «menos de $650» es falso — es exactamente $650—.
 * Por eso el redondeo es `floor + 50`, no `ceil`. El plan gratis no tiene
 * ancla: devuelve 0 y la plantilla no la pinta.
 */
export function pesosPorDia(precioMensual: number): number {
  if (precioMensual <= 0) {
    return 0;
  }
  return Math.floor(precioMensual / 30 / 50) * 50 + 50;
}
```

- [ ] **Paso 3: el spec de `planes.ts`.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/planes.spec.ts`:

```ts
import { PRECIO_LIGHT_PESOS_MES, PRECIO_PRO_PESOS_MES, TIERS } from './planes';

// Este spec es un CANDADO, no un detalle: ADR-010 firma los precios y los
// etiqueta como hipótesis de piloto. Cambiarlos es una decisión de negocio,
// y esta suite es donde esa decisión tiene que pasar y explicarse.
describe('TIERS (ADR-010)', () => {
  it('son tres, en orden Gratis → Light → Pro, con los precios firmados', () => {
    expect(TIERS.map((t) => t.id)).toEqual(['gratis', 'light', 'pro']);
    expect(TIERS.map((t) => t.precioMensualPesos)).toEqual([0, 19_500, 40_000]);
  });

  it('Pro es el tier destacado, y solo él', () => {
    expect(TIERS.filter((t) => t.destacado).map((t) => t.id)).toEqual(['pro']);
  });

  it('los precios son enteros de pesos (nunca centavos ni flotantes)', () => {
    expect(Number.isInteger(PRECIO_LIGHT_PESOS_MES)).toBe(true);
    expect(Number.isInteger(PRECIO_PRO_PESOS_MES)).toBe(true);
    for (const tier of TIERS) {
      expect(Number.isInteger(tier.precioMensualPesos)).toBe(true);
      expect(tier.precioMensualPesos).toBeGreaterThanOrEqual(0);
    }
  });
});
```

```bash
cd frontend && npx ng test vendi-portal --watch=false
# Esperado: FAIL — Cannot find module './planes' (todavía no existe)
```

- [ ] **Paso 4: `planes.ts`.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/planes.ts`:

```ts
/**
 * Los datos comerciales de la landing, fijados por ADR-010.
 *
 * Los precios son una hipótesis firmada (el propio ADR los etiqueta como
 * supuestos a validar en el piloto): cambiarlos es una decisión de negocio,
 * no un retoque, y por eso `planes.spec.ts` los bloquea — quien mueva un
 * número rompe el test y tiene que decirlo.
 *
 * Pro se publica en $40.000, el borde inferior del rango firmado
 * ($40.000–$60.000): una landing no puede mostrar un rango sin mentir, y el
 * piso es el coherente con la sensibilidad de precio del segmento y con el
 * escalón Light «precio de un café». Subirlo después es decisión de negocio
 * protegida por el spec.
 */

/** Precio mensual del tier Light, en pesos colombianos (ADR-010). */
export const PRECIO_LIGHT_PESOS_MES = 19_500;

/** Precio mensual del tier Pro, en pesos colombianos (ADR-010, borde inferior del rango). */
export const PRECIO_PRO_PESOS_MES = 40_000;

export interface TierComercial {
  readonly id: 'gratis' | 'light' | 'pro';
  readonly precioMensualPesos: number;
  /**
   * Pro es la recomendación visual: es el tier que el trial deja probar un
   * mes y al que se degrada después — la comparación honesta ya la vivió el
   * tendero.
   */
  readonly destacado: boolean;
}

/** Los tres tiers de ADR-010, en el orden en que se muestran. */
export const TIERS: readonly TierComercial[] = [
  { id: 'gratis', precioMensualPesos: 0, destacado: false },
  { id: 'light', precioMensualPesos: PRECIO_LIGHT_PESOS_MES, destacado: false },
  { id: 'pro', precioMensualPesos: PRECIO_PRO_PESOS_MES, destacado: true },
];
```

- [ ] **Paso 5: verificar en verde.**

```bash
cd frontend && npx ng test vendi-portal --watch=false
# Esperado: verde — 8 specs nuevos de moneda + 3 de planes (más los 2 viejos del portal)
npx ng lint vendi-portal
# Esperado: sin errores
```

- [ ] **Paso 6: commit**

```bash
git add frontend/projects/vendi-portal/src/app/features/inicio
git commit -m "Modelo comercial de la landing: tiers de ADR-010 con candado de precios y formato de pesos colombianos"
```

**Criterios de aceptación:** los 11 specs nuevos pasan; `formatearPesos(19_500)` es exactamente `$19.500`; `pesosPorDia` nunca devuelve un valor menor o igual al cociente real cuando éste es múltiplo de 50; los tres precios quedan bloqueados por spec.

---

## Tarea 2: Captación — token de WhatsApp, environments, helper de pruebas y el Hero

**Files:**
- Create: `frontend/projects/vendi-portal/src/app/testing/i18n-prueba.ts`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/whatsapp-comercial.token.ts`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/hero/hero.component.ts`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/hero/hero.component.html`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/hero/hero.component.scss`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/hero/hero.component.spec.ts` (primero: el test que falla)
- Modify: `frontend/projects/vendi-portal/src/environments/environment.ts` (gana `whatsappComercial`)
- Modify: `frontend/projects/vendi-portal/src/environments/environment.development.ts` (ídem)
- Modify: `frontend/projects/vendi-portal/public/i18n/es.json` (gana el sub-bloque `portal.hero`; las claves viejas se conservan hasta la Tarea 5 — ver la nota del Paso 6)

**Interfaces:**
- Consume: `fusionarCatalogos`/`CATALOGO_MINIMO_ES` de `data-access` (el patrón del spec viejo, ahora compartido); `environment.whatsappComercial`.
- Produce: el helper `prepararPruebaI18n` que usan TODOS los specs del portal (incluido el `app.spec.ts` reescrito de la Tarea 5); el token `WHATSAPP_COMERCIAL`; el hero con la propuesta de valor y el CTA de captación.

- [ ] **Paso 1: el helper de pruebas compartido.** Crear `frontend/projects/vendi-portal/src/app/testing/i18n-prueba.ts`:

```ts
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Provider } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import {
  TranslateLoader,
  TranslateService,
  TranslationObject,
  provideTranslateService,
} from '@ngx-translate/core';
import { CATALOGO_MINIMO_ES, fusionarCatalogos } from 'data-access';
import { Observable, of } from 'rxjs';

import catalogoApp from '../../public/i18n/es.json';

/**
 * El catálogo de la app fusionado sobre el mínimo, exactamente como hace el
 * cargador resiliente en producción: si un spec ve una clave cruda
 * (`portal.algo`), es que la clave no existe en `es.json` — el aserto
 * `not.toContain('portal.')` de la página la caza.
 */
class CargadorDePrueba extends TranslateLoader {
  override getTranslation(): Observable<TranslationObject> {
    return of(
      fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoApp as never) as unknown as TranslationObject,
    );
  }
}

/**
 * TestBed base de los specs del portal: i18n real con el catálogo de la app,
 * más los providers extra que pida el spec (p. ej. el número comercial de
 * WhatsApp). `TestBed.resetTestingModule()` primero: cada spec arranca limpio.
 */
export function prepararPruebaI18n(proveedoresExtra: Provider[] = []): void {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      ...provideTranslateService({
        lang: 'es',
        fallbackLang: 'es',
        loader: { provide: TranslateLoader, useClass: CargadorDePrueba },
      }),
      ...proveedoresExtra,
    ],
  });
  TestBed.inject(TranslateService).use('es');
}
```

- [ ] **Paso 2: el token.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/whatsapp-comercial.token.ts`:

```ts
import { InjectionToken } from '@angular/core';

import { environment } from '../../../environments/environment';

/**
 * Número comercial de WhatsApp en formato `wa.me`: solo dígitos, con código
 * de país y SIN '+' (p. ej. '573001234567'). El spec del hero bloquea ese
 * formato: un '+' o un espacio rompe el enlace silenciosamente.
 *
 * La cadena vacía significa «todavía no hay número oficial»: el CTA de
 * captación no se pinta (decisión 3 del plan). Cuando operaciones tenga el
 * número es UNA línea en `environment.ts` y rebuild — el portal es estático
 * y no hay configuración en caliente.
 */
export const WHATSAPP_COMERCIAL = new InjectionToken<string>('WHATSAPP_COMERCIAL', {
  providedIn: 'root',
  factory: () => environment.whatsappComercial,
});
```

- [ ] **Paso 3: los environments.** Reemplazar `frontend/projects/vendi-portal/src/environments/environment.ts`:

```ts
/**
 * Entorno de PRODUCCIÓN de `vendi-portal` (sitio público: producto y planes).
 *
 * Se sirve en `https://vendi.co` y `https://www.vendi.co`
 * (ver `infra/traefik/templates/dynamic.yml.tpl`).
 *
 * **No lleva configuración de Keycloak a propósito** (Tarea 2.4, Paso 1: "el
 * portal no usa Keycloak"). El portal es contenido público sin sesión;
 * declarar aquí un `clientId` sugeriría un flujo de login que no existe.
 * Cuando llegue `/cuenta` (subproyecto de monetización, Fase 2) se añadirá
 * entonces, con su redirect URI registrado en el realm.
 *
 * `whatsappComercial`: número oficial de ventas en formato `wa.me` (solo
 * dígitos, con código de país, sin '+'). Vacío = aún no existe: el CTA de
 * captación no se pinta (decisión 3 del plan comercial, Etapa 1.3). Cuando
 * operaciones lo tenga, es esta línea y rebuild de la imagen.
 */
export const environment = {
  production: true,
  apiUrl: 'https://api.vendi.co/api/v1',
  whatsappComercial: '',
};
```

Y `frontend/projects/vendi-portal/src/environments/environment.development.ts`:

```ts
/**
 * Entorno de DESARROLLO de `vendi-portal`.
 *
 * Apunta al stack local de `infra/` (`*.vendi.co` vía Traefik + dnsmasq).
 * Sin Keycloak, igual que en producción: el portal es público.
 *
 * Para probar el CTA de WhatsApp en local, pon aquí un número de prueba en
 * formato `wa.me` (solo dígitos); en producción el CTA nace oculto hasta que
 * exista el número oficial.
 */
export const environment = {
  production: false,
  apiUrl: 'https://api.vendi.co/api/v1',
  whatsappComercial: '',
};
```

- [ ] **Paso 4: el spec del hero.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/hero/hero.component.spec.ts`:

```ts
import { TestBed } from '@angular/core/testing';

import { environment } from '../../../../environments/environment';
import { prepararPruebaI18n } from '../../../testing/i18n-prueba';
import { WHATSAPP_COMERCIAL } from '../whatsapp-comercial.token';
import { HeroComponent } from './hero.component';

describe('HeroComponent', () => {
  it('pinta la propuesta de valor y el enlace absoluto a la consola', () => {
    prepararPruebaI18n();
    const fixture = TestBed.createComponent(HeroComponent);
    fixture.detectChanges();
    const raiz = fixture.nativeElement as HTMLElement;
    expect(raiz.textContent).toContain('Del cuaderno al celular');
    expect(raiz.textContent).toContain('funciona sin internet');
    expect(raiz.textContent).toContain('fiado');
    // La consola es otro origen: href absoluto, nunca routerLink.
    const entrar = raiz.querySelector<HTMLAnchorElement>('a.hero__secundario');
    expect(entrar?.getAttribute('href')).toBe('https://app.vendi.co');
  });

  it('sin número comercial configurado NO pinta el CTA de WhatsApp', () => {
    prepararPruebaI18n([{ provide: WHATSAPP_COMERCIAL, useValue: '' }]);
    const fixture = TestBed.createComponent(HeroComponent);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('a.hero__cta')).toBeNull();
  });

  it('con número configurado pinta el wa.me con el mensaje prearmado codificado', () => {
    prepararPruebaI18n([{ provide: WHATSAPP_COMERCIAL, useValue: '573001234567' }]);
    const fixture = TestBed.createComponent(HeroComponent);
    fixture.detectChanges();
    const cta = (fixture.nativeElement as HTMLElement).querySelector<HTMLAnchorElement>(
      'a.hero__cta',
    );
    expect(cta?.getAttribute('href')).toBe(
      `https://wa.me/573001234567?text=${encodeURIComponent('Hola, quiero probar Vendi en mi tienda')}`,
    );
    expect(cta?.getAttribute('target')).toBe('_blank');
    expect(cta?.getAttribute('rel')).toContain('noopener');
  });

  it('el número del entorno, si existe, es apto para wa.me (solo dígitos)', () => {
    // Candado de formato: un '+' o un espacio rompe el enlace silenciosamente.
    expect(environment.whatsappComercial).toMatch(/^\d*$/);
  });
});
```

```bash
cd frontend && npx ng test vendi-portal --watch=false
# Esperado: FAIL — Cannot find module './hero.component' (todavía no existe)
```

- [ ] **Paso 5: el hero.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/hero/hero.component.ts`:

```ts
import { Component, inject } from '@angular/core';
import { TranslateModule, TranslateService } from '@ngx-translate/core';

import { WHATSAPP_COMERCIAL } from '../whatsapp-comercial.token';

/**
 * Hero de la landing: la propuesta de valor («del cuaderno al celular») y los
 * dos caminos del visitante.
 *
 * Captación de Fase 1, alcance honesto (decisiones 1 y 2 del plan): NO hay
 * formulario de interés con backend —la infra de notificación es Fase 2 y una
 * tabla de leads sin consumidor es peor que no tenerla— y NO hay
 * auto-registro —el realm no lo tiene abierto, así que un «empieza gratis»
 * hacia la app sería mentira—. El canal de captación es el que ya usa la
 * venta: WhatsApp con mensaje prearmado. Mientras no haya número oficial
 * configurado, el CTA no se pinta.
 */
@Component({
  selector: 'vd-hero',
  imports: [TranslateModule],
  templateUrl: './hero.component.html',
  styleUrl: './hero.component.scss',
})
export class HeroComponent {
  /**
   * Consola web del negocio. URL absoluta fija a propósito: `app.vendi.co` es
   * OTRA aplicación servida en otro origen; un `routerLink` no llegaría allí.
   */
  readonly urlDeLaConsola = 'https://app.vendi.co';

  /**
   * Enlace `wa.me` con el mensaje prearmado, o `null` cuando no hay número
   * configurado: la plantilla no pinta el CTA con `null`.
   */
  readonly enlaceWhatsapp: string | null;

  constructor() {
    const numero = inject(WHATSAPP_COMERCIAL);
    const traductor = inject(TranslateService);
    this.enlaceWhatsapp = numero
      ? `https://wa.me/${numero}?text=${encodeURIComponent(traductor.instant('portal.hero.whatsapp_mensaje'))}`
      : null;
  }
}
```

`frontend/projects/vendi-portal/src/app/features/inicio/hero/hero.component.html`:

```html
<section class="hero" aria-labelledby="hero-titulo">
  <h1 id="hero-titulo" class="hero__titulo">{{ 'portal.hero.titulo' | translate }}</h1>
  <p class="hero__subtitulo">{{ 'portal.hero.subtitulo' | translate }}</p>

  <ul class="hero__beneficios">
    @for (beneficio of ['beneficio_1', 'beneficio_2', 'beneficio_3', 'beneficio_4']; track beneficio) {
      <li>{{ 'portal.hero.' + beneficio | translate }}</li>
    }
  </ul>

  <div class="hero__acciones">
    @if (enlaceWhatsapp) {
      <a class="hero__cta" [href]="enlaceWhatsapp" target="_blank" rel="noopener noreferrer">
        {{ 'portal.hero.cta_probar' | translate }}
      </a>
    }
    <a class="hero__secundario" [href]="urlDeLaConsola">
      {{ 'portal.hero.cta_entrar' | translate }}
    </a>
  </div>

  <p class="hero__nota">{{ 'portal.hero.nota_prueba' | translate }}</p>
</section>
```

`frontend/projects/vendi-portal/src/app/features/inicio/hero/hero.component.scss`:

```scss
.hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--vd-espacio-6);
  padding: var(--vd-espacio-12) var(--vd-espacio-4);
  text-align: center;

  &__titulo {
    margin: 0;
    font-size: var(--vd-texto-4xl);
    line-height: 1.15;
    color: var(--vd-texto-marca);
  }

  &__subtitulo {
    margin: 0;
    max-width: 40rem;
    font-size: var(--vd-texto-lg);
    color: var(--vd-texto-secundario);
  }

  &__beneficios {
    display: grid;
    gap: var(--vd-espacio-3);
    margin: 0;
    padding: 0;
    list-style: none;
    text-align: start;
  }

  &__acciones {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: var(--vd-espacio-4);
  }

  &__cta,
  &__secundario {
    display: inline-flex;
    align-items: center;
    min-height: var(--vd-objetivo-tactil);
    padding: 0 var(--vd-espacio-6);
    border-radius: var(--vd-radio-completo);
    font-weight: 600;
    text-decoration: none;
  }

  // Par medido a mano con la fórmula WCAG 2.1 al escribirlo: #047857 sobre
  // #ffffff = 5.49:1 (AA para texto normal). El candado automático
  // (`npm run verificar:contraste`) solo cubre los pares de `_tokens.scss`;
  // éste NO — quien lo «ajuste» tiene que volver a medir y decirlo.
  &__cta {
    background: var(--vd-marca-700);
    color: #ffffff;
  }

  &__secundario {
    border: 1px solid var(--vd-borde-fuerte);
    color: var(--vd-texto-primario);
  }

  &__nota {
    margin: 0;
    font-size: var(--vd-texto-sm);
    color: var(--vd-texto-secundario);
  }
}
```

- [ ] **Paso 6: las claves i18n del hero.** En `frontend/projects/vendi-portal/public/i18n/es.json`, DENTRO del bloque `"portal"` existente, añadir el sub-bloque `"hero"`. Las tres claves viejas (`lema`/`descripcion`/`entrar`) SE CONSERVAN en esta tarea: la página de Fase 0 las usa hasta que la Tarea 5 la reemplaza — quitarlas aquí dejaría la página actual pintando claves crudas y rompería su spec. El bloque `"portal"` queda con las tres claves viejas más:

```json
    "hero": {
      "titulo": "Del cuaderno al celular",
      "subtitulo": "Vendi es el punto de venta hecho para las tiendas de barrio de Colombia: vende, fía y cierra la caja desde tu celular, aunque se vaya el internet.",
      "beneficio_1": "Vende siempre: el punto de venta funciona sin internet",
      "beneficio_2": "El fiado sin cuaderno: saldo por cliente y recordatorios por WhatsApp",
      "beneficio_3": "Tu inventario al día: sabes qué tienes y qué se está acabando",
      "beneficio_4": "La caja cuadra al peso, todos los días",
      "cta_probar": "Quiero probarlo gratis",
      "cta_entrar": "Ya tengo cuenta: entrar a mi negocio",
      "nota_prueba": "Al darte de alta tienes 1 mes de Pro completo. Sin tarjeta, sin letra pequeña.",
      "whatsapp_mensaje": "Hola, quiero probar Vendi en mi tienda"
    },
```

Verificar que el JSON sigue siendo válido:

```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/projects/vendi-portal/public/i18n/es.json','utf8')); console.log('JSON válido')"
# Esperado: JSON válido
```

- [ ] **Paso 7: verificar en verde.**

```bash
cd frontend && npx ng test vendi-portal --watch=false
# Esperado: verde — los 4 specs del hero pasan (los 2 specs viejos de app.spec siguen
# usando su propio cargador inline; se migran al helper en la Tarea 5)
npx ng lint vendi-portal
# Esperado: sin errores
```

- [ ] **Paso 8: commit**

```bash
git add frontend/projects/vendi-portal
git commit -m "Hero de la landing con captación por WhatsApp: token de número comercial, environments y helper i18n de pruebas"
```

**Criterios de aceptación:** el CTA de WhatsApp no existe con número vacío y es un `wa.me` bien formado con número; el formato del número queda candado por spec; el enlace a la consola sigue siendo absoluto; las claves viejas (`portal.lema`/`descripcion`/`entrar`) siguen vivas —la página de Fase 0 y su spec las usan hasta la Tarea 5—; el JSON valida.

---

## Tarea 3: Precios — la tabla de tiers con los precios reales y el trial

**Files:**
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/precios/precios.component.ts`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/precios/precios.component.html`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/precios/precios.component.scss`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/precios/precios.component.spec.ts` (después de las claves i18n: el test que falla)
- Modify: `frontend/projects/vendi-portal/public/i18n/es.json` (gana el sub-bloque `portal.precios`)

**Interfaces:**
- Consume: `TIERS`/`TierComercial` y `formatearPesos`/`pesosPorDia` (Tarea 1); `StatusBadgeComponent` de `ui-kit` (inputs `etiqueta` requerido y `variante`); las claves `portal.precios.*` (Paso 1 de esta tarea).
- Produce: la sección `#precios` de la landing.

- [ ] **Paso 1: las claves i18n de la sección.** En `frontend/projects/vendi-portal/public/i18n/es.json`, dentro del bloque `"portal"`, añadir el sub-bloque `"precios"`:

```json
    "precios": {
      "titulo": "Precios claros, en pesos",
      "subtitulo": "Empieza gratis y crece cuando lo necesites. Sin contratos ni permanencia.",
      "por_mes": "al mes",
      "gratis": "Gratis",
      "light": "Light",
      "pro": "Pro",
      "gratis_para": "Para arrancar",
      "light_para": "Para la tienda que crece",
      "pro_para": "Para sacarle todo el jugo",
      "gratis_precio_nota": "para siempre",
      "por_dia": "menos de {{valor}} al día",
      "prueba_badge": "1 mes de Pro gratis al darte de alta, sin tarjeta",
      "fila_productos": "Productos",
      "fila_usuarios": "Usuarios",
      "fila_fiado": "Fiado y clientes",
      "fila_asistente": "Asistente con IA",
      "fila_reportes": "Reportes con IA",
      "ilimitado": "Ilimitado",
      "si": "Incluido",
      "no": "No incluido",
      "asistente_5_mes": "5 consultas al mes",
      "asistente_30_dia": "30 consultas al día",
      "reportes_briefing": "Briefing diario",
      "reportes_completos": "Completos",
      "dian_titulo": "Facturación electrónica DIAN",
      "dian_badge": "Próximamente",
      "dian_descripcion": "Factura electrónica y POS electrónico como add-on. Llega con la Fase 2."
    },
```

```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/projects/vendi-portal/public/i18n/es.json','utf8')); console.log('JSON válido')"
# Esperado: JSON válido
```

- [ ] **Paso 2: el spec.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/precios/precios.component.spec.ts`:

```ts
import { TestBed } from '@angular/core/testing';

import { prepararPruebaI18n } from '../../../testing/i18n-prueba';
import { PreciosComponent } from './precios.component';

describe('PreciosComponent', () => {
  function crear(): HTMLElement {
    prepararPruebaI18n();
    const fixture = TestBed.createComponent(PreciosComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('muestra los tres tiers con los precios reales de ADR-010', () => {
    const raiz = crear();
    expect(raiz.textContent).toContain('Gratis');
    expect(raiz.textContent).toContain('Light');
    expect(raiz.textContent).toContain('Pro');
    expect(raiz.textContent).toContain('$0');
    expect(raiz.textContent).toContain('$19.500');
    expect(raiz.textContent).toContain('$40.000');
  });

  it('ancla el precio al día sin prometer de menos (redondeo estricto al alza)', () => {
    const raiz = crear();
    // 19.500/30 = 650 exactos: «menos de $650» sería falso; la regla sube a 700.
    expect(raiz.textContent).toContain('menos de $700 al día');
    // 40.000/30 = 1.333,33…: sube a 1.350.
    expect(raiz.textContent).toContain('menos de $1.350 al día');
  });

  it('el trial es el sello estrella: 1 mes de Pro, sin tarjeta', () => {
    const raiz = crear();
    expect(raiz.textContent).toContain('1 mes de Pro gratis');
    expect(raiz.textContent).toContain('sin tarjeta');
  });

  it('el add-on DIAN está marcado como próximamente y SIN precio', () => {
    const raiz = crear();
    expect(raiz.textContent).toContain('Facturación electrónica DIAN');
    expect(raiz.textContent).toContain('Próximamente');
    const dian = raiz.querySelector('.precios__dian');
    expect(dian?.textContent).not.toContain('$');
  });

  it('los límites de ADR-010 están en la comparativa, como texto legible', () => {
    const raiz = crear();
    for (const esperado of ['100', '500', 'Ilimitado', 'Incluido', '30 consultas al día']) {
      expect(raiz.textContent).toContain(esperado);
    }
    // Nada de ✓/✗ mudas: un lector de pantalla tiene que poder leer la tabla.
    expect(raiz.textContent).toContain('No incluido');
  });
});
```

```bash
cd frontend && npx ng test vendi-portal --watch=false
# Esperado: FAIL — Cannot find module './precios.component' (todavía no existe)
```

- [ ] **Paso 3: el componente.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/precios/precios.component.ts`:

```ts
import { Component, inject } from '@angular/core';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { StatusBadgeComponent } from 'ui-kit';

import { formatearPesos, pesosPorDia } from '../moneda';
import { TIERS, TierComercial } from '../planes';

interface FilaComparativa {
  readonly clave: string;
  /**
   * Un valor por tier, en el orden de `TIERS`. Las cifras literales (`'100'`)
   * se pintan tal cual; el resto son claves bajo `portal.precios`.
   */
  readonly valores: readonly string[];
}

/**
 * La tabla de precios de ADR-010.
 *
 * Los números que no deben derivar NUNCA (los tres precios) vienen del modelo
 * candado de `planes.ts`; los límites y descripciones vienen del catálogo
 * i18n y los vigila el spec de esta sección. El add-on DIAN se anuncia sin
 * precio: es Fase 2 y prometerle precio hoy sería inventarlo.
 */
@Component({
  selector: 'vd-precios',
  imports: [TranslateModule, StatusBadgeComponent],
  templateUrl: './precios.component.html',
  styleUrl: './precios.component.scss',
})
export class PreciosComponent {
  private readonly traductor = inject(TranslateService);

  readonly tiers = TIERS;

  /** Las filas de la comparativa, en el orden de `TIERS`. */
  readonly filas: readonly FilaComparativa[] = [
    { clave: 'portal.precios.fila_productos', valores: ['100', '500', 'ilimitado'] },
    { clave: 'portal.precios.fila_usuarios', valores: ['1', '2', '3'] },
    { clave: 'portal.precios.fila_fiado', valores: ['no', 'si', 'si'] },
    {
      clave: 'portal.precios.fila_asistente',
      valores: ['asistente_5_mes', 'asistente_30_dia', 'ilimitado'],
    },
    {
      clave: 'portal.precios.fila_reportes',
      valores: ['no', 'reportes_briefing', 'reportes_completos'],
    },
  ];

  precioDe(tier: TierComercial): string {
    return formatearPesos(tier.precioMensualPesos);
  }

  /** El ancla por día, redondeada al alza (nunca prometer de menos). Gratis no tiene. */
  porDiaDe(tier: TierComercial): string | null {
    if (tier.precioMensualPesos === 0) {
      return null;
    }
    return formatearPesos(pesosPorDia(tier.precioMensualPesos));
  }

  /** Cifra literal o traducción bajo `portal.precios`, según la celda. */
  textoDeCelda(celda: string): string {
    return /^\d+$/.test(celda) ? celda : this.traductor.instant(`portal.precios.${celda}`);
  }
}
```

`frontend/projects/vendi-portal/src/app/features/inicio/precios/precios.component.html`:

```html
<section class="precios" id="precios" aria-labelledby="precios-titulo">
  <h2 id="precios-titulo" class="precios__titulo">{{ 'portal.precios.titulo' | translate }}</h2>
  <p class="precios__subtitulo">{{ 'portal.precios.subtitulo' | translate }}</p>
  <p class="precios__prueba">
    <vd-status-badge variante="exito" [etiqueta]="'portal.precios.prueba_badge' | translate" />
  </p>

  <div class="precios__tiers">
    @for (tier of tiers; track tier.id; let indice = $index) {
      <article class="precios__tier" [class.precios__tier--destacado]="tier.destacado">
        <h3>{{ 'portal.precios.' + tier.id | translate }}</h3>
        <p class="precios__para">{{ 'portal.precios.' + tier.id + '_para' | translate }}</p>
        <p class="precios__precio">
          {{ precioDe(tier) }}
          <span class="precios__periodo">
            {{
              (tier.precioMensualPesos === 0
                ? 'portal.precios.gratis_precio_nota'
                : 'portal.precios.por_mes'
              ) | translate
            }}
          </span>
        </p>
        @if (porDiaDe(tier); as porDia) {
          <p class="precios__dia">{{ 'portal.precios.por_dia' | translate: { valor: porDia } }}</p>
        }
        <ul>
          @for (fila of filas; track fila.clave) {
            <li>
              <strong>{{ fila.clave | translate }}:</strong>
              {{ textoDeCelda(fila.valores[indice]) }}
            </li>
          }
        </ul>
      </article>
    }
  </div>

  <article class="precios__dian" aria-labelledby="dian-titulo">
    <h3 id="dian-titulo">
      {{ 'portal.precios.dian_titulo' | translate }}
      <vd-status-badge variante="info" [etiqueta]="'portal.precios.dian_badge' | translate" />
    </h3>
    <p>{{ 'portal.precios.dian_descripcion' | translate }}</p>
  </article>
</section>
```

`frontend/projects/vendi-portal/src/app/features/inicio/precios/precios.component.scss`:

```scss
.precios {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--vd-espacio-6);
  padding: var(--vd-espacio-12) var(--vd-espacio-4);
  text-align: center;

  &__titulo {
    margin: 0;
    font-size: var(--vd-texto-3xl);
  }

  &__subtitulo {
    margin: 0;
    max-width: 36rem;
    color: var(--vd-texto-secundario);
  }

  &__prueba {
    margin: 0;
  }

  &__tiers {
    display: grid;
    gap: var(--vd-espacio-4);
    width: 100%;
    max-width: 60rem;

    @media (min-width: 48rem) {
      grid-template-columns: repeat(3, 1fr);
      align-items: stretch;
    }
  }

  &__tier {
    display: flex;
    flex-direction: column;
    gap: var(--vd-espacio-3);
    padding: var(--vd-espacio-6);
    border: 1px solid var(--vd-borde-normal);
    border-radius: var(--vd-radio-lg);
    background: var(--vd-superficie-1);
    text-align: start;

    h3 {
      margin: 0;
      font-size: var(--vd-texto-xl);
    }

    &--destacado {
      border-color: var(--vd-marca-500);
      box-shadow: var(--vd-sombra-md);
    }

    ul {
      display: grid;
      gap: var(--vd-espacio-2);
      margin: 0;
      padding: 0;
      list-style: none;
      font-size: var(--vd-texto-sm);
    }
  }

  &__para {
    margin: 0;
    color: var(--vd-texto-secundario);
    font-size: var(--vd-texto-sm);
  }

  &__precio {
    margin: 0;
    font-size: var(--vd-texto-3xl);
    font-weight: 700;
  }

  &__periodo {
    font-size: var(--vd-texto-sm);
    font-weight: 400;
    color: var(--vd-texto-secundario);
  }

  &__dia {
    margin: 0;
    font-size: var(--vd-texto-sm);
    color: var(--vd-texto-secundario);
  }

  &__dian {
    width: 100%;
    max-width: 60rem;
    padding: var(--vd-espacio-6);
    border: 1px dashed var(--vd-borde-normal);
    border-radius: var(--vd-radio-lg);
    text-align: start;

    h3 {
      margin: 0 0 var(--vd-espacio-2);
      font-size: var(--vd-texto-lg);
    }

    p {
      margin: 0;
      color: var(--vd-texto-secundario);
    }
  }
}
```

- [ ] **Paso 4: verificar en verde.**

```bash
cd frontend && npx ng test vendi-portal --watch=false
# Esperado: verde — 5 specs nuevos de precios
npx ng lint vendi-portal
# Esperado: sin errores
```

- [ ] **Paso 5: commit**

```bash
git add frontend/projects/vendi-portal/src/app/features/inicio/precios frontend/projects/vendi-portal/public/i18n/es.json
git commit -m "Sección de precios de la landing: tiers de ADR-010 con ancla por día honesta, trial sin tarjeta y DIAN como próximamente"
```

**Criterios de aceptación:** los tres precios reales aparecen formateados a la colombiana; las anclas por día son estrictamente mayores que el cociente real; el trial aparece como sello; DIAN no muestra ni un `$`; la comparativa se lee en voz alta («Incluido»/«No incluido»).

---

## Tarea 4: Confianza — offline-first, datos del negocio y hecho para la tienda

**Files:**
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/confianza/confianza.component.ts`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/confianza/confianza.component.html`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/confianza/confianza.component.scss`
- Create: `frontend/projects/vendi-portal/src/app/features/inicio/confianza/confianza.component.spec.ts` (después de las claves i18n: el test que falla)
- Modify: `frontend/projects/vendi-portal/public/i18n/es.json` (gana el sub-bloque `portal.confianza`)

**Interfaces:**
- Consume: las claves `portal.confianza.*` (Paso 1 de esta tarea). Cada afirmación es cierta del producto de Fase 1: offline-first (ADR-017, ya entregado en la pista móvil), aislamiento por negocio (RLS, ADR-013), lenguaje del mostrador (granel de 3 decimales, fiado por persona — ADR-009/ADR-018).
- Produce: la sección `#confianza` de la landing.

- [ ] **Paso 1: las claves i18n de la sección.** En `frontend/projects/vendi-portal/public/i18n/es.json`, dentro del bloque `"portal"`, añadir el sub-bloque `"confianza"`:

```json
    "confianza": {
      "titulo": "Hecho para la tienda de barrio",
      "punto_1_titulo": "Funciona sin internet",
      "punto_1_texto": "La venta nunca se para: registras en el mostrador y, cuando vuelve la conexión, todo se sincroniza solo.",
      "punto_2_titulo": "Tus datos son de tu negocio",
      "punto_2_texto": "Cada tienda ve solo lo suyo: tus ventas, tu fiado y tu caja no los ve nadie más.",
      "punto_3_titulo": "Habla como se habla en el mostrador",
      "punto_3_texto": "Pesos colombianos, granel por kilos y libras, y el fiado como se fía aquí: por persona y con confianza."
    },
```

```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/projects/vendi-portal/public/i18n/es.json','utf8')); console.log('JSON válido')"
# Esperado: JSON válido
```

- [ ] **Paso 2: el spec.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/confianza/confianza.component.spec.ts`:

```ts
import { TestBed } from '@angular/core/testing';

import { prepararPruebaI18n } from '../../../testing/i18n-prueba';
import { ConfianzaComponent } from './confianza.component';

describe('ConfianzaComponent', () => {
  it('pinta las tres pruebas de confianza', () => {
    prepararPruebaI18n();
    const fixture = TestBed.createComponent(ConfianzaComponent);
    fixture.detectChanges();
    const raiz = fixture.nativeElement as HTMLElement;
    expect(raiz.textContent).toContain('Hecho para la tienda de barrio');
    expect(raiz.textContent).toContain('Funciona sin internet');
    expect(raiz.textContent).toContain('Tus datos son de tu negocio');
    expect(raiz.textContent).toContain('mostrador');
  });

  it('tiene su propio ancla para la barra de navegación', () => {
    prepararPruebaI18n();
    const fixture = TestBed.createComponent(ConfianzaComponent);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('#confianza')).not.toBeNull();
  });
});
```

```bash
cd frontend && npx ng test vendi-portal --watch=false
# Esperado: FAIL — Cannot find module './confianza.component' (todavía no existe)
```

- [ ] **Paso 3: el componente.** Crear `frontend/projects/vendi-portal/src/app/features/inicio/confianza/confianza.component.ts`:

```ts
import { Component } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';

/**
 * Las tres pruebas de confianza de la landing.
 *
 * Cada afirmación es cierta del producto de Fase 1 — no es copy inflado:
 * «funciona sin internet» es ADR-017 ya entregado, «cada tienda ve solo lo
 * suyo» es la RLS de ADR-013, y «habla como se habla en el mostrador» es el
 * granel por kilos y el fiado por persona. Si una deja de ser cierta, el copy
 * se corrige el mismo día: la confianza es la moneda del segmento.
 */
@Component({
  selector: 'vd-confianza',
  imports: [TranslateModule],
  templateUrl: './confianza.component.html',
  styleUrl: './confianza.component.scss',
})
export class ConfianzaComponent {
  readonly puntos = ['punto_1', 'punto_2', 'punto_3'] as const;
}
```

`frontend/projects/vendi-portal/src/app/features/inicio/confianza/confianza.component.html`:

```html
<section class="confianza" id="confianza" aria-labelledby="confianza-titulo">
  <h2 id="confianza-titulo" class="confianza__titulo">{{ 'portal.confianza.titulo' | translate }}</h2>
  <div class="confianza__puntos">
    @for (punto of puntos; track punto) {
      <article class="confianza__punto">
        <h3>{{ 'portal.confianza.' + punto + '_titulo' | translate }}</h3>
        <p>{{ 'portal.confianza.' + punto + '_texto' | translate }}</p>
      </article>
    }
  </div>
</section>
```

`frontend/projects/vendi-portal/src/app/features/inicio/confianza/confianza.component.scss`:

```scss
.confianza {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--vd-espacio-6);
  padding: var(--vd-espacio-12) var(--vd-espacio-4);
  text-align: center;

  &__titulo {
    margin: 0;
    font-size: var(--vd-texto-3xl);
  }

  &__puntos {
    display: grid;
    gap: var(--vd-espacio-4);
    width: 100%;
    max-width: 60rem;

    @media (min-width: 48rem) {
      grid-template-columns: repeat(3, 1fr);
    }
  }

  &__punto {
    padding: var(--vd-espacio-6);
    border-radius: var(--vd-radio-lg);
    background: var(--vd-superficie-2);
    text-align: start;

    h3 {
      margin: 0 0 var(--vd-espacio-2);
      font-size: var(--vd-texto-lg);
    }

    p {
      margin: 0;
      color: var(--vd-texto-secundario);
    }
  }
}
```

- [ ] **Paso 4: verificar en verde.**

```bash
cd frontend && npx ng test vendi-portal --watch=false
# Esperado: verde — 2 specs nuevos de confianza
npx ng lint vendi-portal
# Esperado: sin errores
```

- [ ] **Paso 5: commit**

```bash
git add frontend/projects/vendi-portal/src/app/features/inicio/confianza frontend/projects/vendi-portal/public/i18n/es.json
git commit -m "Sección de confianza de la landing: offline-first, datos aislados por negocio y lenguaje de mostrador"
```

**Criterios de aceptación:** las tres afirmaciones se pintan con ancla propia; ninguna promete nada que el producto de Fase 1 no haga ya.

---

## Tarea 5: La página ensamblada — InicioComponent, respaldo i18n propio, SEO/OG y el spec de la página

**Files:**
- Modify: `frontend/projects/vendi-portal/src/app/features/inicio/inicio.component.ts` (reescrito: compone las secciones)
- Modify: `frontend/projects/vendi-portal/src/app/features/inicio/inicio.component.html` (reescrito: barra + secciones + pie)
- Modify: `frontend/projects/vendi-portal/src/app/features/inicio/inicio.component.scss` (reescrito)
- Modify: `frontend/projects/vendi-portal/src/app/app.config.ts` (respaldo i18n propio del portal — decisión 6)
- Modify: `frontend/projects/vendi-portal/public/i18n/es.json` (gana `portal.nav` y `portal.footer`; mueren las tres claves de Fase 0 — decisión 10)
- Modify: `frontend/projects/vendi-portal/src/index.html` (título, meta description, Open Graph mínimo — decisión 7)
- Modify: `frontend/projects/vendi-portal/src/app/app.spec.ts` (reescrito: specs de la página real + candado del respaldo)

**Interfaces:**
- Consume: las tres secciones (Tareas 2-4), `proveerI18nVendi(respaldo)` de `data-access` (firma verificada en `i18n.provider.ts:140`), `CATALOGO_DE_RESPALDO` (exportado por `data-access`), el helper `prepararPruebaI18n` (Tarea 2).
- Produce: la landing completa servida en `/`; las metas sociales estáticas.

- [ ] **Paso 1: el spec de la página (reescribe `app.spec.ts`).** Reemplazar `frontend/projects/vendi-portal/src/app/app.spec.ts`:

```ts
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { CATALOGO_DE_RESPALDO } from 'data-access';

import { App } from './app';
import { appConfig } from './app.config';
import { routes } from './app.routes';
import { prepararPruebaI18n } from './testing/i18n-prueba';

describe('App', () => {
  it('debería crearse', () => {
    prepararPruebaI18n();
    expect(TestBed.createComponent(App).componentInstance).toBeTruthy();
  });
});

describe('la landing pública', () => {
  async function pintar(): Promise<HTMLElement> {
    prepararPruebaI18n();
    TestBed.configureTestingModule({ providers: [provideRouter(routes)] });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    return harness.fixture.nativeElement as HTMLElement;
  }

  it('pinta hero, precios y confianza, con los precios de ADR-010 y sin claves crudas', async () => {
    const raiz = await pintar();
    expect(raiz.textContent).toContain('Del cuaderno al celular');
    expect(raiz.textContent).toContain('$19.500');
    expect(raiz.textContent).toContain('$40.000');
    expect(raiz.textContent).toContain('Hecho para la tienda de barrio');
    // El catálogo de prueba es el real: una clave cruda aquí es una clave que
    // falta en es.json.
    expect(raiz.textContent).not.toContain('portal.');
  });

  it('sin número comercial no hay CTA de WhatsApp, y la consola sigue a un clic', async () => {
    const raiz = await pintar();
    expect(raiz.querySelector('a[href*="wa.me"]')).toBeNull();
    // Otro origen: href absoluto, nunca routerLink.
    expect(raiz.querySelector('a[href="https://app.vendi.co"]')).not.toBeNull();
  });

  it('cualquier ruta desconocida cae en la landing, no en blanco', () => {
    const comodin = routes.find((r) => r.path === '**');
    expect(comodin?.redirectTo).toBe('');
  });
});

describe('el respaldo i18n del portal', () => {
  it('es el propio catálogo de la landing: si /i18n/es.json falla, nada pinta claves crudas', () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ providers: appConfig.providers });
    const respaldo = TestBed.inject(CATALOGO_DE_RESPALDO);
    expect(typeof respaldo['portal']).toBe('object');
    expect(JSON.stringify(respaldo['portal'])).toContain('Del cuaderno al celular');
  });
});
```

```bash
cd frontend && npx ng test vendi-portal --watch=false
# Esperado: FAIL — la página actual no pinta «Del cuaderno al celular» ni precios,
# y el respaldo actual es CATALOGO_MINIMO_ES (sin `portal`)
```

- [ ] **Paso 2: `InicioComponent` reensamblado.** Reemplazar `frontend/projects/vendi-portal/src/app/features/inicio/inicio.component.ts`:

```ts
import { Component } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';

import { ConfianzaComponent } from './confianza/confianza.component';
import { HeroComponent } from './hero/hero.component';
import { PreciosComponent } from './precios/precios.component';

/**
 * La landing pública de Vendi (Fase 1, Etapa 1.3, pista comercial).
 *
 * Una sola página con anclas: hero (propuesta de valor y captación por
 * WhatsApp), precios (ADR-010) y confianza. Sin rutas nuevas: `/precios`
 * como ruta llegará con el `/pro` transaccional de Fase 2.
 *
 * El enlace a la consola se escribe como URL absoluta y no como ruta de
 * Angular porque `app.vendi.co` es **otra aplicación**, servida por otro
 * origen; un `routerLink` no llegaría allí.
 */
@Component({
  selector: 'vd-inicio',
  imports: [TranslateModule, HeroComponent, PreciosComponent, ConfianzaComponent],
  templateUrl: './inicio.component.html',
  styleUrl: './inicio.component.scss',
})
export class InicioComponent {
  readonly urlDeLaConsola = 'https://app.vendi.co';
}
```

`frontend/projects/vendi-portal/src/app/features/inicio/inicio.component.html`:

```html
<header class="barra">
  <span class="barra__marca">{{ 'app.titulo' | translate }}</span>
  <nav class="barra__nav">
    <a href="#precios">{{ 'portal.nav.precios' | translate }}</a>
    <a href="#confianza">{{ 'portal.nav.confianza' | translate }}</a>
    <a class="barra__entrar" [href]="urlDeLaConsola">{{ 'portal.nav.entrar' | translate }}</a>
  </nav>
</header>

<main>
  <vd-hero />
  <vd-precios />
  <vd-confianza />
</main>

<footer class="pie">
  <p>{{ 'portal.footer.lema' | translate }}</p>
  <p>{{ 'portal.footer.hecho' | translate }}</p>
</footer>
```

`frontend/projects/vendi-portal/src/app/features/inicio/inicio.component.scss`:

```scss
.barra {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vd-espacio-4);
  padding: var(--vd-espacio-3) var(--vd-espacio-4);
  border-bottom: 1px solid var(--vd-borde-sutil);

  &__marca {
    font-size: var(--vd-texto-xl);
    font-weight: 600;
    color: var(--vd-texto-marca);
  }

  &__nav {
    display: flex;
    align-items: center;
    gap: var(--vd-espacio-4);

    a {
      display: inline-flex;
      align-items: center;
      min-height: var(--vd-objetivo-tactil);
      color: var(--vd-texto-primario);
      text-decoration: none;
    }
  }

  &__entrar {
    font-weight: 600;
  }
}

.pie {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--vd-espacio-2);
  padding: var(--vd-espacio-8) var(--vd-espacio-4);
  border-top: 1px solid var(--vd-borde-sutil);
  color: var(--vd-texto-secundario);
  font-size: var(--vd-texto-sm);
  text-align: center;

  p {
    margin: 0;
  }
}
```

- [ ] **Paso 3: el respaldo i18n propio en `app.config.ts`.** Reemplazar `frontend/projects/vendi-portal/src/app/app.config.ts`:

```ts
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';

import {
  API_BASE_URL,
  CATALOGO_MINIMO_ES,
  fusionarCatalogos,
  proveerI18nVendi,
} from 'data-access';

import catalogoPortal from '../public/i18n/es.json';
import { routes } from './app.routes';
import { environment } from '../environments/environment';

/** Configuración de arranque del portal público. */
export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // HttpClient es prerrequisito del cargador de traducciones.
    provideHttpClient(),
    // Base de la API para `ApiService`. El portal de Fase 1 no llama a la API
    // (la captación es por WhatsApp, decisión 1 del plan comercial); el
    // provider queda porque lo exige el contrato del workspace.
    { provide: API_BASE_URL, useValue: environment.apiUrl },
    // i18n resiliente con el respaldo PROPIO del portal: el mínimo empotrado
    // compartido no tiene ni una clave `portal.*`, y esta es la superficie
    // pública y anónima — si `/i18n/es.json` no se puede descargar, la
    // landing tiene que pintar exactamente lo mismo, no claves crudas ante
    // el primer visitante. El coste es ~6 kB empotrados: nada.
    ...proveerI18nVendi(fusionarCatalogos(CATALOGO_MINIMO_ES, catalogoPortal as never)),
  ],
};
```

- [ ] **Paso 4: las claves i18n de la barra y el pie, y el retiro de las de Fase 0.** En `frontend/projects/vendi-portal/public/i18n/es.json`: (a) QUITAR las tres claves viejas del bloque `"portal"` —`"lema"`, `"descripcion"` y `"entrar"`— que solo usaba la página provisional que el Paso 2 acaba de reemplazar (decisión 10); (b) añadir los sub-bloques `"nav"` y `"footer"`:

```json
    "nav": {
      "precios": "Precios",
      "confianza": "Por qué Vendi",
      "entrar": "Entrar a mi negocio"
    },
    "footer": {
      "lema": "El punto de venta para las tiendas de barrio de Colombia",
      "hecho": "Hecho en Colombia"
    },
```

Verificar que el JSON sigue siendo válido y que ninguna clave vieja sobrevive:

```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/projects/vendi-portal/public/i18n/es.json','utf8')); console.log('JSON válido')"
# Esperado: JSON válido
grep -n "\"lema\": \"El punto de venta para las tiendas de barrio\"" frontend/projects/vendi-portal/public/i18n/es.json
# Esperado: UNA sola coincidencia — la de portal.footer.lema; la vieja portal.lema murió
grep -rn "portal.lema\|portal.descripcion\|portal.entrar" frontend/projects/vendi-portal/src || echo "ninguna plantilla usa las claves retiradas"
# Esperado: ninguna plantilla usa las claves retiradas
```

- [ ] **Paso 5: SEO y Open Graph en `index.html`.** Reemplazar `frontend/projects/vendi-portal/src/index.html`:

```html
<!doctype html>
<html lang="es-CO">
  <head>
    <meta charset="utf-8" />
    <title>Vendi — Del cuaderno al celular: punto de venta para tiendas de barrio</title>
    <base href="/" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta
      name="description"
      content="Vendi es el punto de venta para las tiendas de barrio de Colombia: vende sin internet, lleva el fiado sin cuaderno, tu inventario al día y la caja al peso. Empieza con 1 mes de Pro gratis, sin tarjeta."
    />
    <!--
      Open Graph mínimo. Las tarjetas de WhatsApp/Facebook NO ejecutan
      JavaScript: estas etiquetas tienen que vivir en el HTML estático, no
      inyectadas por Angular. Sin `og:image` todavía: no hay asset de marca
      (la rampa de color es provisional, dice `_tokens.scss`), y una tarjeta
      sin imagen es fea pero honesta — uno inventado es peor.
    -->
    <meta property="og:type" content="website" />
    <meta property="og:locale" content="es_CO" />
    <meta property="og:url" content="https://vendi.co/" />
    <meta property="og:site_name" content="Vendi" />
    <meta property="og:title" content="Vendi — Del cuaderno al celular" />
    <meta
      property="og:description"
      content="El punto de venta para las tiendas de barrio de Colombia: vende sin internet, lleva el fiado sin cuaderno y cierra la caja al peso. 1 mes de Pro gratis, sin tarjeta."
    />
    <link rel="icon" type="image/x-icon" href="favicon.ico" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500&display=swap"
      rel="stylesheet"
    />
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet" />
  </head>
  <body>
    <vd-root></vd-root>
    <noscript>Para usar Vendi necesitas activar JavaScript en tu navegador.</noscript>
  </body>
</html>
```

- [ ] **Paso 6: verificar en verde y revisar las metas en el build.**

```bash
cd frontend && npm run build:libs && npx ng test vendi-portal --watch=false
# Esperado: verde — 5 specs en app.spec.ts (1 de App + 3 de la landing + 1 del respaldo)
npx ng lint vendi-portal
# Esperado: sin errores
npx ng build vendi-portal
# Esperado: build de desarrollo verde
grep -c 'property="og:' dist/vendi-portal/browser/index.html
# Esperado: 6 (type, locale, url, site_name, title, description)
grep -c 'name="description"' dist/vendi-portal/browser/index.html
# Esperado: 1
```

- [ ] **Paso 7: commit**

```bash
git add frontend/projects/vendi-portal
git commit -m "Landing comercial completa: página ensamblada, respaldo i18n propio del portal y metas SEO/Open Graph estáticas"
```

**Criterios de aceptación:** la página pinta las tres secciones sin claves crudas; el respaldo empotrado contiene el catálogo del portal (spec firmado — el modo de fallo de claves crudas en la superficie pública queda cerrado); las 6 metas OG y la description están en el `index.html` del build; sin número comercial no hay `wa.me` en la página.

---

## Tarea 6: Cierre — gate de la pista comercial y `docs/estado.md`

**Files:**
- Modify: `docs/estado.md` (sección nueva de la landing comercial, con fecha de corte y evidencia comando+salida)

**NO se toca:** `backend/` entero, `docs/api/openapi-fase0.json`, `frontend/nginx-spa.conf`, `frontend/Dockerfile`, `.github/workflows/`.

- [ ] **Paso 1: ejecutar el gate completo de la pista comercial:**

```bash
cd frontend
npm ci --no-audit --no-fund
npm run build:libs
npx ng test --watch=false
# Esperado: verde en los 9 proyectos; vendi-portal corre 27 specs
# (3 de planes + 8 de moneda + 4 de hero + 5 de precios + 2 de confianza + 5 de app)
npx ng lint
# Esperado: sin errores en los 9 proyectos (fronteras incluidas)
npm run format:check
# Esperado: sin diferencias (si prettier marca los archivos nuevos: npm run format)
npm run verificar:contraste
# Esperado: los 12 pares verificados, todos ≥ 4.5:1 (los tokens no se tocaron:
# es la verificación de que esta pista no degradó la accesibilidad medida)
npx ng build vendi-portal --configuration production
# Esperado: build de producción verde, dentro de los budgets (500kB/1MB inicial)
grep -rE "localhost:[0-9]{4}|environment\.development" dist/vendi-portal/browser || echo "sin URLs de desarrollo"
# Esperado: sin URLs de desarrollo
grep -c 'property="og:' dist/vendi-portal/browser/index.html
# Esperado: 6
cd ..
git diff --exit-code -- frontend/nginx-spa.conf frontend/Dockerfile docs/api/openapi-fase0.json
# Esperado: salida 0 — ni el servidor estático, ni la imagen, ni el contrato se tocaron
CODEGEN_SCHEMA_FILE=docs/api/openapi-fase0.json bash scripts/codegen-api-client.sh && git diff --exit-code
# Esperado: salida 0 — el contrato no se tocó y el cliente generado no deriva
git status --porcelain -- backend/ | wc -l
# Esperado: 0 — el backend no existe para esta pista
```

Gate de la pista (del plan maestro §Etapa 1.3), a verificar ítem a ítem:
- [ ] `ng test` verde en los 9 proyectos con los specs nuevos de la landing (27 en `vendi-portal`).
- [ ] Captación y precios entregados: precios reales de ADR-010 con candado, trial visible, DIAN como «próximamente», CTA de WhatsApp con su mecanismo probado (y su estado honesto: oculto hasta que exista número oficial).
- [ ] Budgets de bundle no relajados; `nginx-spa.conf` y `Dockerfile` intactos; el backend y el OpenAPI sin un byte de diferencia.
- [ ] `verificar:contraste` verde en CI (ningún par medido se degradó; el único par nuevo —`marca-700`+blanco, 5.49:1— está medido a mano y documentado en el SCSS).

- [ ] **Paso 2: actualizar `docs/estado.md`.** Añadir una sección «Landing comercial de `vendi-portal` (Fase 1, Etapa 1.3, pista comercial)» siguiendo el formato de las secciones hermanas («POS offline-first en `vendi-app`…»): fecha de corte, enlace a este plan, qué se entregó (hero con «del cuaderno al celular»; precios de ADR-010 con candado —$0 / $19.500 / $40.000— y ancla por día con redondeo estricto al alza; trial de 1 mes de Pro sin tarjeta como sello; DIAN «próximamente» sin precio; captación por `wa.me` con token de entorno; confianza; respaldo i18n propio; metas SEO/OG estáticas), el alcance honesto con las decisiones que el lector necesita sin abrir el plan (SIN endpoint de leads —YAGNI: sin `notify.jobs` hasta Fase 2, Habeas Data, el piloto se recluta por agentes—; SIN auto-registro —el realm no lo tiene abierto y el CTA no miente—; el CTA de WhatsApp nace OCULTO hasta que operaciones configure `environment.whatsappComercial` —pendiente operativo, una línea + rebuild—; sin `og:image` por falta de asset de marca; Pro publicado en el piso del rango firmado), y **al lado de cada afirmación el comando que la demuestra** con su salida pegada (regla del documento: no promete nada que un comando no demuestre).

- [ ] **Paso 3: commit de cierre**

```bash
git add docs/estado.md
git commit -m "Pista comercial de la Etapa 1.3 cerrada: landing de vendi-portal con precios de ADR-010 y captación por WhatsApp"
```

---

## Superficie de ataque para QA — landing pública (captación, precios, i18n, metas)

Para el agente de QA adversarial de la Etapa 1.4 (agente distinto del implementador; su KPI son hallazgos). Los escenarios marcados (firmado) ya tienen test que los fija: verificarlos, no «redescubrirlos»; el hallazgo sería que el test miente.

- **La captación:** el CTA de WhatsApp ausente con número vacío (firmado); el `wa.me` bien formado con número y mensaje codificado (firmado — provocar de verdad un click en staging con un número de prueba y verificar que WhatsApp abre con el texto prearmado); el formato del número candado (firmado — intentar colar `'57 300 123 4567'` o `'+573001234567'` en `environment.ts` y ver el spec romperse); número configurado pero inválido para WhatsApp (dígitos que no son una línea real: `wa.me` responde «número inválido» — el mecanismo no puede saberlo; verificar en el despliegue real que el número contesta); el CTA abre en pestaña nueva con `noopener` (firmado); la página NO promete auto-registro en ninguna parte (recorrer el copy: «al darte de alta» es el único camino mencionado y es cierto — si alguien añade «regístrate gratis» apuntando a `app.vendi.co`, es un hallazgo: el realm no tiene registro abierto).
- **Los precios:** los tres precios y su orden (firmado); la deriva del copy vs ADR-010 (los asertos de texto del spec de precios cubren los límites como cadenas — el hallazgo sería que alguien cambia «500» en el JSON y el aserto también); la ancla por día nunca menor ni igual al cociente real cuando éste es múltiplo de 50 (firmado para 19.500 y 40.000; provocar con un precio nuevo, p. ej. $60.000 → `pesosPorDia` da 2.050 y 60.000/30 = 2.000: «menos de $2.050» es cierto ✓); DIAN sin un solo `$` (firmado); `formatearPesos` rechaza no-enteros (firmado); el tier Gratis no muestra ancla por día (verificar visualmente que dice «para siempre», no «al mes»).
- **El i18n:** tumbar `/i18n/es.json` (devolver 404 desde el dev-server o el proxy) y recargar: la landing debe pintar EXACTAMENTE igual por el respaldo propio (el mecanismo está firmado por el spec del token; la verificación end-to-end es manual — si pinta `portal.hero.titulo`, el respaldo no es el que dice el spec); JSON servido corrupto (el cargador cae al respaldo: misma verificación); catálogo lento >5 s (timeout del cargador → respaldo; portal cautivo simulado con throttling); la fusión no contamina el mínimo compartido entre apps (las otras tres apps no heredan claves `portal.*`: verificar que `vendi-tenant` sigue sin conocer `portal.hero.titulo` — su respaldo sigue siendo el mínimo).
- **Contraste y tema:** `verificar:contraste` cubre SOLO los pares de `_tokens.scss`; el par del CTA (`marca-700`+blanco, medido a mano 5.49:1) NO está candado por script — es el punto débil declarado: medirlo de nuevo con cualquier herramienta y, si la rampa de marca cambia (es «provisional»), exigir la re-medición; recorrer la landing en modo oscuro del sistema (los tokens conmutan con `light-dark()`; el CTA no conmuta — verificar que sigue siendo legible, y que el borde del tier destacado `marca-500` no desaparece sobre la superficie oscura); zoom al 200 % sin pérdida de contenido; la insignia del trial usa el par `insignia-exito` medido (firmado por el script).
- **Accesibilidad real:** `h1` único por página (verificar que solo el hero lo tiene); landmarks `header`/`nav`/`main`/`footer` presentes; todos los enlaces con objetivo táctil ≥48px (medir el de la barra, el CTA y el secundario); la comparativa legible por lector de pantalla («Incluido»/«No incluido» texto, firmado — recorrerla con VoiceOver); los anclas `#precios`/`#confianza` mueven el foco visual sin romper el flujo (sin `scroll-behavior` exótico: no se añadió ninguno).
- **SEO y compartir:** `view-source:` sin ejecutar JS muestra título, description y las 6 OG (las tarjetas sociales no ejecutan JS — por eso son estáticas; verificar el HTML servido, no el DOM); compartir la URL en WhatsApp real muestra título y descripción SIN imagen (og:image ausente — declarado, no es un bug; cuando haya manual de marca, añadirlo es la mejora); Google indexa la SPA pero los scrapers sociales no ven el contenido dinámico (límite de Fase 1 declarado en decisión 7: si el piloto exige más SEO, la respuesta es prerender, no parches); `robots.txt` no existe — indexable por defecto, que es lo deseado para una landing pública (declarado).
- **Build y despliegue:** budgets sin relajar (el build de producción es la prueba); `dist` sin URLs de desarrollo (gate); `nginx-spa.conf` y `Dockerfile` byte a byte iguales (gate con `git diff`); el portal sigue sin arrastrar Keycloak ni cliente de API al bundle (revisar los chunks: si aparece `keycloak-js` en el bundle del portal, algo se importó mal — el portal no lo usa); la página en 320px de ancho apila las tarjetas y no desborda horizontalmente (verificar con devtools).

---

## Self-Review

- **Cobertura del spec:** ADR-010 (tiers, precios, trial sin tarjeta, add-on DIAN aparte) → Tarea 1 (modelo + candado) y Tarea 3 (tabla, trial como sello, DIAN «próximamente» sin precio). ADR-004 (el portal capta, no cobra; la venta es web-first Fase 2) → decisión 1 (sin endpoint, sin checkout, sin métodos de pago) + CTA de captación en Tarea 2. ADR-009 (el fiado ES el cuaderno; «del cuaderno al celular») → hero (Tarea 2) y confianza (Tarea 4). ADR-012 (portal público anónimo en `vendi.co`) → constraints (sin Keycloak, sin rutas nuevas) + Tarea 5. monetizacion-web §2 (límites por tier) → comparativa de la Tarea 3; §3 (ancla por día) → `pesosPorDia` con redondeo honesto (decisión 5); §6 (la venta es por WhatsApp) → el CTA de la Tarea 2. plan-maestro §Etapa 1.3 pista comercial («captación y precios») → Tareas 1-6; su gate (9 proyectos verdes, budgets sin relajar) → Tarea 6. El encargo (hero, precios, captación, confianza, SEO/accesibilidad, tests) → Tareas 2, 3, 2+decisiones 1-3, 4, 5 y todas respectivamente.
- **Placeholders:** ninguno. Todo paso lleva código completo, comando exacto y salida esperada; los dos archivos que se «reemplazan» (`environment*.ts`, `index.html`, `app.config.ts`, `app.spec.ts`, `inicio.component.*`) se dan enteros; el bloque i18n se da completo de una vez. El número de WhatsApp NO es un placeholder de código: es configuración declarada vacía con el comportamiento firmado por spec (decisión 3).
- **Consistencia de tipos/contratos:** `proveerI18nVendi(respaldo?: CatalogoTraducciones)` verificado en `i18n.provider.ts:140` y `fusionarCatalogos`/`CATALOGO_MINIMO_ES`/`CATALOGO_DE_RESPALDO` exportados por `data-access` (verificado en `public-api.ts`); `StatusBadgeComponent` consume `etiqueta` (requerido) y `variante` (`'exito' | 'info' | 'aviso' | 'peligro' | 'neutro'` — verificado en el fuente: las dos usadas, `exito` e `info`, existen); el alias `ui-kit` es el que usa `vendi-tenant` (verificado); la frontera ESLint del portal permite `ui-kit` y `data-access` (verificado en su `eslint.config.js`); las claves i18n de las plantillas se verificaron una a una contra los sub-bloques que añaden la Tarea 2 (Paso 6: `hero.*`), la Tarea 3 (Paso 1: `precios.*` incluidas `si`/`no`/`ilimitado`/`asistente_*`/`reportes_*`), la Tarea 4 (Paso 1: `confianza.punto_{1..3}_{titulo,texto}`) y la Tarea 5 (Paso 4: `nav.*` y `footer.*`, y el retiro de las tres de Fase 0 EN la misma tarea que reemplaza la página que las usaba — ninguna tarea deja la app pintando claves crudas); los asertos de los specs usan las cadenas exactas de esos bloques; `encodeURIComponent('Hola, quiero probar Vendi en mi tienda')` del aserto corresponde al valor de `portal.hero.whatsapp_mensaje`.
- **Riesgos conocidos y declarados:** (1) la captación depende de un número que no existe — el CTA nace oculto por diseño y el pendiente es operativo, declarado en decisión 3 y en `estado.md`; (2) el trial que publicita la landing («1 mes de Pro al darte de alta») es la promesa de ADR-010/monetizacion-web, pero el alta es asistida por agentes y el trial automático en backend es Fase 2 — la promesa es cierta para todo alta, el mecanismo que la honra se construye después: tensión declarada, el copy no promete automatismo; (3) el par de color del CTA no está cubierto por el candado automático — medido a mano (5.49:1) y declarado en la superficie de QA; (4) sin `og:image` ni SSR — la tarjeta social sale sin imagen y los scrapers no ven el contenido dinámico (decisión 7); (5) Pro publicado en el piso del rango firmado — si el piloto valida $60.000, el cambio es una línea que rompe el candado a propósito; (6) los límites por tier viven en el copy i18n vigilado por asertos de texto, no en el modelo — aceptado a propósito (son descripción, no dato operativo; los precios, que sí son críticos, están en el modelo candado).
