import { Component } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';

/**
 * Pantalla única de `vendi-app` en Fase 0.
 *
 * ## Por qué NO hay login aquí
 *
 * No es un olvido ni una tarea pendiente de esta etapa: es una decisión del
 * alcance. La autenticación móvil es el **subproyecto 2**, y hacerla bien
 * exige cosas que Fase 0 no construye:
 *
 *  - El login **no puede abrirse dentro del WebView** de Capacitor: los
 *    passkeys (WebAuthn) no funcionan ahí, y el realm `vendi-co` está
 *    configurado como passwordless (`browserFlow: browser-passwordless`). Tiene
 *    que salir al navegador del sistema vía la fachada de `native`
 *    (`@capacitor/browser`), y volver por el esquema `co.vendi.app://`, que ya
 *    está registrado como redirect URI del cliente `vendi-web`.
 *  - Y exige decidir dónde vive la sesión cuando la app está offline, que es
 *    parte del diseño offline-first (subproyecto 3), no de la fundación.
 *
 * Poner aquí un login "provisional" dentro del WebView sería escribir código
 * que hay que borrar entero y, peor, dejar en el repositorio un ejemplo de
 * cómo NO se hace.
 *
 * Lo que esta app SÍ demuestra en Fase 0 es el criterio 4: que el pipeline
 * produce un AAB instalable (`ng build vendi-app && npx cap sync android &&
 * ./gradlew bundleDebug`).
 *
 * Ancla para el subproyecto 2: cuando exista su spec, esta pantalla se
 * reemplaza por el flujo real de login. Ver `docs/plan-maestro.md` §
 * subproyectos y ADR-004 (frontera de plataforma nativa).
 */
@Component({
  selector: 'vd-proximamente',
  imports: [TranslateModule],
  templateUrl: './proximamente.component.html',
  styleUrl: './proximamente.component.scss',
})
export class ProximamenteComponent {}
