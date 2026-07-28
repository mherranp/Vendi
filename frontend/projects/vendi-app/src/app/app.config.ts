import { ApplicationConfig, isDevMode, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideServiceWorker } from '@angular/service-worker';

import { authInterceptor } from 'auth';
import {
  API_BASE_URL,
  correlationIdInterceptor,
  errorInterceptor,
  proveerI18nVendi,
} from 'data-access';

// La detección de plataforma va por la fachada de `native`: ADR-011 reserva los
// imports de @capacitor/* a esa librería y el lint de esta app lo hace cumplir.
import { esPlataformaNativa } from 'native';

import { routes } from './app.routes';
import { environment } from '../environments/environment';
import { proveerSesion } from './nucleo/sesion';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // Mismo orden que vendi-tenant: errorInterceptor envuelve al resto.
    provideHttpClient(
      withInterceptors([errorInterceptor, correlationIdInterceptor, authInterceptor]),
    ),
    { provide: API_BASE_URL, useValue: environment.apiUrl },
    // i18n resiliente (ver `proveerI18nVendi` en data-access): español fijo,
    // catálogo por HTTP con **respaldo empotrado**. El bloque anterior era
    // fail-hard —si `/i18n/es.json` no se podía descargar, el inicializador
    // rechazaba y Angular abortaba el bootstrap: pantalla en blanco—. Para un
    // POS que promete funcionar sin conexión eso no es aceptable.
    ...proveerI18nVendi(),
    // Sesión de Keycloak con el flujo WEB (passkey en el navegador). La auth
    // nativa por navegador del sistema es la deuda D-29; el canal del piloto
    // es la PWA instalada (decisión 1 del plan).
    proveerSesion({
      url: environment.keycloakUrl,
      realm: environment.realm,
      clientId: environment.clientId,
    }),
    provideServiceWorker('ngsw-worker.js', {
      // El SW no debe correr dentro del WebView de Capacitor: serviría HTML
      // cacheado tras actualizar el binario nativo. La fuente de verdad
      // offline es IndexedDB (data-access), no el service worker.
      enabled: environment.production && !isDevMode() && !esPlataformaNativa(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
