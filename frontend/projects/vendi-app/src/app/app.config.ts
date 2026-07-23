import { ApplicationConfig, isDevMode, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideServiceWorker } from '@angular/service-worker';

import { API_BASE_URL, proveerI18nVendi } from 'data-access';

// La detección de plataforma va por la fachada de `native`: ADR-011 reserva los
// imports de @capacitor/* a esa librería y el lint de esta app lo hace cumplir.
import { esPlataformaNativa } from 'native';

import { routes } from './app.routes';
import { environment } from '../environments/environment';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // HttpClient es prerrequisito del cargador de traducciones.
    provideHttpClient(),
    // Base de la API para `ApiService`. Los interceptores de sesión y de error
    // se cablean en la Etapa 4, cuando estas apps empiecen a llamar endpoints.
    { provide: API_BASE_URL, useValue: environment.apiUrl },
    // i18n resiliente (ver `proveerI18nVendi` en data-access): español fijo,
    // catálogo por HTTP con **respaldo empotrado**. El bloque anterior era
    // fail-hard —si `/i18n/es.json` no se podía descargar, el inicializador
    // rechazaba y Angular abortaba el bootstrap: pantalla en blanco—. Para un
    // POS que promete funcionar sin conexión eso no es aceptable.
    ...proveerI18nVendi(),
    provideServiceWorker('ngsw-worker.js', {
      // El SW no debe correr dentro del WebView de Capacitor: serviría HTML
      // cacheado tras actualizar el binario nativo. La fuente de verdad
      // offline es IndexedDB (data-access), no el service worker.
      enabled: environment.production && !isDevMode() && !esPlataformaNativa(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
