/*
 * Public API Surface of ui-kit/form-renderer
 *
 * Punto de entrada **secundario**: el renderizador declarativo de
 * formularios, aparte del barril principal por la misma razón que
 * `ui-kit/data-table` (ver su `public-api.ts`): el fesm del barril es un solo
 * módulo que el shell carga en el inicial, y FormRenderer arrastra los
 * módulos de Material de todos los tipos de campo que soporta —form-field,
 * input, select, checkbox, radio y datepicker suman ~400 kB crudos—. Usado
 * desde aquí, ese peso viaja en el chunk perezoso de la feature que lo abre
 * (diálogos de la consola), no en el arranque de la app. Por eso el barril
 * principal ya NO lo exporta: este es su único hogar público.
 */

export { FormRendererComponent } from './lib/form-renderer.component';
export { claveDelPrimerError, construirValidadores } from './lib/validadores';
export type {
  CampoDeFormulario,
  ConfiguracionFormulario,
  DisposicionFormulario,
  OpcionDeCampo,
  TipoDeCampo,
  ValidadorDeCampo,
} from './lib/form.models';
