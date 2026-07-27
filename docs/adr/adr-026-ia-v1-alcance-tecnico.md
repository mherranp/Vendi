# ADR-026 — IA v1: alcance técnico sobre `AIProvider`

**Fecha:** 2026-07-27 · **Estado:** Firmada (Fase 1)
**Origen:** `docs/plan-maestro.md` §1 (regla de oro de IA), §3 («Asistente IA»)
y §4.1. Acota ADR-007, que firma la capa `AIProvider` pero no su alcance.

## Contexto

El plan maestro promete para Fase 1 «consultas en lenguaje natural,
recomendaciones diarias (reglas + narración LLM), registro por voz y briefing
matutino push», con una regla de oro ya consensuada: **las recomendaciones
nacen de reglas deterministas sobre los datos; el LLM solo las narra**
(§1 — «el código decide, la IA conversa»). ADR-007 dejó el proveedor
enchufable pero no definió qué puede preguntar el tendero, qué datos salen del
tenant hacia el proveedor, ni qué pasa sin red o sin API key (bloqueante B-3).

## Decisión

IA v1 son **tres capacidades** sobre `AIProvider`, ninguna más:

1. **Consultas en lenguaje natural — cerradas a cinco**, implementadas con
   function calling: el LLM elige la función y extrae el período; la función
   consulta la base **con la sesión de `vendi_app` y el GUC del tenant**
   (ADR-013) y devuelve el dato; el LLM narra la respuesta. Nunca SQL libre.
   Las cinco: (a) ¿cuánto vendí hoy / esta semana / este mes?; (b) ¿cuánto
   gané este mes? (P&L simple, ADR-006); (c) ¿qué productos se están agotando
   / qué me toca pedir?; (d) ¿quién me debe y cuánto? (fiado, ADR-009);
   (e) ¿cuáles son mis productos más vendidos?
2. **Recomendaciones diarias y briefing matutino.** Reglas deterministas —
   bajo stock, fiados vencidos, forecast de caja negativo (ADR-006)— generan
   hechos; el LLM solo los narra en lenguaje simple. Se entrega por push
   (`notificacion.enviar`, ADR-025) y en la app. Sin LLM disponible, **las
   mismas reglas se muestran como tarjetas sin narración**: el briefing no
   desaparece, pierde la prosa.
3. **Registro por voz.** Audio → Gemini multimodal → extracción estructurada
   por function calling → **pantalla de confirmación**. Nada se persiste sin
   el toque del tendero: un error de transcripción confirmado es culpa del
   tendero; uno persistido sin confirmar es culpa nuestra. Solo tier Pro
   (ADR-010).

**Privacidad — qué sale del tenant hacia el proveedor:** la pregunta del
tendero, la salida ya agregada de la función invocada (cifras y, solo si la
función los devuelve, nombres de producto o de cliente del fiado), y el audio
en la voz. **No sale:** `tenant_id`, ids internos, volcados de tablas, ni
nada de otro tenant — no por disciplina sino por construcción: las funciones
corren bajo RLS y físicamente no pueden leer fuera del GUC. El audio no se
almacena; se transcribe y se descarta.

**Fallback.** Sin conexión: el asistente responde «sin conexión» y el POS
sigue intacto — la IA es acelerador, nunca requisito para cobrar. Sin API key
(B-3): el módulo arranca **deshabilitado, no ausente**: `/ia/*` responde 503
con mensaje claro, las tarjetas de reglas sin narración siguen saliendo, y el
arranque de la API no falla. La regla «secretos sin default» no puede
convertirse en «sin Gemini no hay POS». Las cuotas por tier (5 consultas/mes
Gratis, 30/día Light, Pro ilimitada) se aplican en Redis (ADR-002) **antes**
de llamar al proveedor.

## Alternativas descartadas

- **Text-to-SQL libre.** El riesgo «alucinaciones del LLM» del plan maestro
  §10 se mitiga con «reglas deterministas deciden; LLM narra». Un SQL
  inventado sobre datos de dinero es exactamente la alucinación que esa regla
  prohíbe; cinco funciones fijas cubren las preguntas reales del piloto.
- **RAG/embeddings sobre el catálogo.** Ninguna de las cinco consultas lo
  necesita; añade un índice vectorial, otra superficie de privacidad y costo
  para responder preguntas que nadie ha hecho todavía.
- **Narración on-device (modelo local).** Inconsistente con ADR-007 (un solo
  punto de proveedor) e inviable en la gama baja del segmento.

## Consecuencias

- Añadir una sexta consulta es añadir una función determinista testeada, no
  entrenar ni ajustar prompts: la frontera «el código decide» se mantiene
  sola si toda respuesta de dinero sale de una función.
- `AIProvider` necesita function calling y entrada de audio en su interfaz
  mínima — los dos usos exclusivos de Gemini que se adoptan; si el fallback
  GPT-5 mini no los soporta igual, degrada a texto limpio (consecuencia ya
  firmada en ADR-007).
- La métrica del piloto «costo IA por negocio < $0,20 USD/mes» (§11) se mide
  con la tabla de uso de abajo; sin ella esa cifra sería una suposición más.

## Tablas, eventos y candado

- **Tablas nuevas:** `ai_requests` (`tenant_id` + RLS, usuario, tipo de
  consulta, tokens de entrada/salida, costo estimado, `creado_en`) — con
  `enable_rls(op, 'ai_requests')`. Es medición de costo y uso, no telemetría
  de producto: ADR-005 sigue abierta y este ADR no la resuelve.
- **Eventos de outbox que emite:** `notificacion.enviar` (definido en
  ADR-025) para el briefing matutino. Ninguno más.
- **Candado:** (a) test de privacidad que construye el payload hacia el
  proveedor y falla si contiene `tenant_id` o cualquier campo fuera de la
  lista blanca; (b) test de arranque sin API key: la API levanta y `/ia/*`
  responde 503; (c) test de integración con dos tenants que verifica que la
  función «¿quién me debe?» solo ve los fiados del GUC activo; (d) test de
  cuota con Redis. Las evals con casos reales del piloto (riesgo §10) son el
  gate del módulo `modulo-ia-v1`, no de este ADR.
