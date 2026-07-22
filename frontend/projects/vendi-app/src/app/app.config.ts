import { ApplicationConfig, provideBrowserGlobalErrorListeners, isDevMode } from '@angular/core';
import { provideRouter } from '@angular/router';

import { routes } from './app.routes';
import { provideServiceWorker } from '@angular/service-worker';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    provideServiceWorker('ngsw-worker.js', {
      // TODO(paso 12): añadir `&& !Capacitor.isNativePlatform()` al instalar Capacitor.
      // Dentro del WebView el SW sirve HTML cacheado tras actualizar el binario.
      // La fuente de verdad offline es IndexedDB, no el service worker.
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
