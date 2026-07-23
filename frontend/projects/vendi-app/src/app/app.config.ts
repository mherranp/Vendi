import {
  ApplicationConfig,
  inject,
  isDevMode,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideServiceWorker } from '@angular/service-worker';
import { TranslateService, provideTranslateService } from '@ngx-translate/core';
import { provideTranslateHttpLoader } from '@ngx-translate/http-loader';
import { firstValueFrom } from 'rxjs';

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
    provideTranslateService({
      // `fallbackLang`/`lang` sustituyen a `defaultLanguage`, deprecado en
      // @ngx-translate/core 17. El idioma se fija a español y NO se negocia con
      // el navegador: Vendi en Fase 0 es solo Colombia, y dejar que un navegador
      // en inglés pidiera `en.json` (que no existe) pintaría las claves crudas.
      fallbackLang: 'es',
      lang: 'es',
      loader: provideTranslateHttpLoader({
        prefix: '/i18n/',
        suffix: '.json',
        // En desarrollo se añade un parámetro anti-caché para que al editar
        // `public/i18n/es.json` no haya que vaciar la caché del navegador; en
        // producción el catálogo se cachea como cualquier otro asset.
        enforceLoading: !environment.production,
      }),
    }),
    // Se espera al catálogo antes de arrancar: sin esto el primer render pinta
    // literalmente `app.titulo` hasta que llega el JSON.
    provideAppInitializer(() => firstValueFrom(inject(TranslateService).use('es'))),
    provideServiceWorker('ngsw-worker.js', {
      // El SW no debe correr dentro del WebView de Capacitor: serviría HTML
      // cacheado tras actualizar el binario nativo. La fuente de verdad
      // offline es IndexedDB (data-access), no el service worker.
      enabled: environment.production && !isDevMode() && !esPlataformaNativa(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
