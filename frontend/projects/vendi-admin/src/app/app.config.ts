import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';

import { authInterceptor } from 'auth';
import {
  API_BASE_URL,
  correlationIdInterceptor,
  errorInterceptor,
  proveerI18nVendi,
} from 'data-access';

import { environment } from '../environments/environment';
import { routes } from './app.routes';
import { proveerSesion } from './nucleo/sesion';

/** Configuración de arranque de la consola de plataforma. */
export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // Sin `provideAnimationsAsync()`: el paquete `@angular/animations` no está
    // en las dependencias del workspace y Angular Material 21 ya no lo
    // necesita —usa animaciones CSS—. Añadirlo solo para esto engordaría el
    // bundle de las cuatro apps a cambio de nada.
    // El orden de la lista es el de la petición saliente, de fuera hacia
    // dentro. `errorInterceptor` va primero a propósito: al envolver al resto,
    // su `catchError` ve también los fallos que produzcan los interceptores de
    // dentro, no solo los de la red.
    provideHttpClient(
      withInterceptors([errorInterceptor, correlationIdInterceptor, authInterceptor]),
    ),
    // Base de la API para `ApiService`.
    { provide: API_BASE_URL, useValue: environment.apiUrl },
    // i18n resiliente (ver `proveerI18nVendi` en data-access): español fijo,
    // catálogo por HTTP con **respaldo empotrado**. El bloque anterior era
    // fail-hard —si `/i18n/es.json` no se podía descargar, el inicializador
    // rechazaba y Angular abortaba el bootstrap: pantalla en blanco—. Para un
    // POS que promete funcionar sin conexión eso no es aceptable.
    ...proveerI18nVendi(),
    // Sesión de Keycloak. Ver `proveerSesion` para por qué es `check-sso` y no
    // `login-required`.
    proveerSesion({
      url: environment.keycloakUrl,
      realm: environment.realm,
      clientId: environment.clientId,
    }),
  ],
};
