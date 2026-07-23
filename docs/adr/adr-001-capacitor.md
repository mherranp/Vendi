# ADR-001 — Capacitor como empaquetado nativo desde el inicio

**Fecha:** 2026-07-20 · **Estado:** Firmada
**Origen:** `docs/plan-tecnico.md` §3, migrado a archivo en la Etapa 5 de Fase 0.

## Contexto

Vendi tiene que estar en Play Store desde el piloto. El camino corto era una TWA
(Trusted Web Activity, vía Bubblewrap): empaqueta la PWA en un APK sin escribir
código nativo, y se migra a Capacitor «cuando haga falta».

## Decisión

**Capacitor es el empaquetado único desde el MVP**, para Play Store y App Store.
No hay etapa TWA.

## Alternativas descartadas

- **TWA primero, Capacitor después.** El «después» es una migración completa del
  pipeline de binarios, de la firma, de la ficha de la tienda y de las pruebas,
  hecha en el peor momento posible: cuando ya hay usuarios instalados. Y la
  necesidad de nativo no es hipotética ni lejana — impresora Bluetooth de
  tickets, escáner de códigos, push y biometría son requisitos del MVP, y TWA no
  da ninguno.
- **Nativo puro (Kotlin/Swift).** Dos bases de código para un equipo que no las
  puede mantener, y sin reutilizar nada del frontend web.

## Consecuencias

- Un solo camino de binarios: `ng build` → `cap sync` → Gradle/Xcode.
- En Fase 0, `vendi-app` **solo compila y produce un AAB**; no tiene login (la
  autenticación móvil es un subproyecto posterior). El AAB de prueba es el
  criterio 4 de cierre de Fase 0 y lo produce `.github/workflows/android.yml`.
- iOS entra por TestFlight en Fase 1 y a la App Store en Fase 2: el coste de
  Capacitor ya está pagado cuando llegue.
