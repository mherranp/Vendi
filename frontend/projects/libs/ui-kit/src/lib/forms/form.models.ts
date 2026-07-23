/*
 * Modelos del renderizador de formularios.
 *
 * Cosechado de `ui-dataforms/src/lib/models/form.models.ts` de BaseSaaS. Se
 * quitan dos tipos de control que Fase 0 no puede sostener: `lookup` (requería
 * un endpoint de búsqueda remota, es decir HTTP dentro de ui-kit) y `color`
 * (era para el branding por tenant, que Vendi no tiene).
 */

export type TipoDeCampo =
  | 'text'
  | 'textarea'
  | 'number'
  | 'email'
  | 'password'
  | 'url'
  | 'tel'
  | 'select'
  | 'multiselect'
  | 'radio'
  | 'checkbox'
  | 'date'
  | 'datetime'
  | 'time'
  | 'file';

export interface OpcionDeCampo {
  /** Clave de traducción o texto ya resuelto. */
  etiqueta: string;
  valor: string | number | boolean;
}

export interface ValidadorDeCampo {
  tipo: 'required' | 'min' | 'max' | 'minLength' | 'maxLength' | 'pattern' | 'email';
  valor?: string | number | boolean;
  /** Clave de traducción del mensaje. Si falta, se usa el genérico del tipo. */
  mensaje?: string;
}

export interface CampoDeFormulario {
  clave: string;
  etiqueta: string;
  tipo: TipoDeCampo;
  marcador?: string;
  ayuda?: string;
  valorPorDefecto?: unknown;
  deshabilitado?: boolean;
  soloLectura?: boolean;
  validadores?: ValidadorDeCampo[];
  opciones?: OpcionDeCampo[];
  columnas?: 1 | 2 | 3 | 4;
  acepta?: string;
  multiple?: boolean;
}

export type DisposicionFormulario = 'una-columna' | 'dos-columnas' | 'rejilla';

export interface ConfiguracionFormulario {
  campos: CampoDeFormulario[];
  disposicion?: DisposicionFormulario;
  columnas?: number;
}
