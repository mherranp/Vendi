import { AbstractControl, ValidationErrors, ValidatorFn, Validators } from '@angular/forms';
import { ValidadorDeCampo } from './form.models';

/**
 * Traduce la especificación declarativa de validadores a `ValidatorFn` de
 * Angular. Cosechado de `ui-dataforms/src/lib/validators/validators.ts`.
 */
export function construirValidadores(spec: ValidadorDeCampo[] | undefined): ValidatorFn[] {
  if (!spec?.length) return [];
  const resultado: ValidatorFn[] = [];
  for (const v of spec) {
    switch (v.tipo) {
      case 'required':
        resultado.push(Validators.required);
        break;
      case 'min':
        if (typeof v.valor === 'number') resultado.push(Validators.min(v.valor));
        break;
      case 'max':
        if (typeof v.valor === 'number') resultado.push(Validators.max(v.valor));
        break;
      case 'minLength':
        if (typeof v.valor === 'number') resultado.push(Validators.minLength(v.valor));
        break;
      case 'maxLength':
        if (typeof v.valor === 'number') resultado.push(Validators.maxLength(v.valor));
        break;
      case 'pattern':
        if (typeof v.valor === 'string') resultado.push(Validators.pattern(v.valor));
        break;
      case 'email':
        resultado.push(Validators.email);
        break;
    }
  }
  return resultado;
}

/**
 * Claves de traducción de los mensajes genéricos, por tipo de error de Angular.
 *
 * Ojo con las mayúsculas: Angular emite `minlength`/`maxlength` en minúsculas,
 * mientras que la especificación declarativa usa `minLength`/`maxLength`. El
 * mapa va indexado por lo que emite Angular, que es lo que se recibe.
 */
const CLAVES_POR_ERROR: Record<string, string> = {
  required: 'ui.validacion.requerido',
  email: 'ui.validacion.correo',
  min: 'ui.validacion.minimo',
  max: 'ui.validacion.maximo',
  minlength: 'ui.validacion.muy_corto',
  maxlength: 'ui.validacion.muy_largo',
  pattern: 'ui.validacion.formato',
};

/**
 * Clave de traducción del primer error del control, o cadena vacía si es
 * válido. Si la especificación del campo trae un `mensaje` propio, gana ése.
 */
export function claveDelPrimerError(
  control: AbstractControl | null,
  spec: ValidadorDeCampo[] | undefined,
): string {
  if (!control?.errors) return '';
  const errores = control.errors as ValidationErrors;
  const primero = Object.keys(errores)[0];
  if (!primero) return '';

  const propio = spec?.find((v) => v.tipo.toLowerCase() === primero.toLowerCase())?.mensaje;
  if (propio) return propio;

  return CLAVES_POR_ERROR[primero] ?? 'ui.validacion.invalido';
}
