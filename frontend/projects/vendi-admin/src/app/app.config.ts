import {
  ApplicationConfig,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { TranslateService, provideTranslateService } from '@ngx-translate/core';
import { provideTranslateHttpLoader } from '@ngx-translate/http-loader';
import { firstValueFrom } from 'rxjs';

import { routes } from './app.routes';
import { environment } from '../environments/environment';

/** Configuración de arranque de la consola de plataforma. */
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
  ],
};
