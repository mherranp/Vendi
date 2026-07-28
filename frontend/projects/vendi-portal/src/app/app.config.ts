import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';

import { API_BASE_URL, CATALOGO_MINIMO_ES, fusionarCatalogos, proveerI18nVendi } from 'data-access';

import catalogoPortal from '../../public/i18n/es.json';
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
