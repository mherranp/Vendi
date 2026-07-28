import { Component, computed, input, output } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatNativeDateModule } from '@angular/material/core';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatRadioModule } from '@angular/material/radio';
import { MatSelectModule } from '@angular/material/select';
import { TranslateModule } from '@ngx-translate/core';
import { CampoDeFormulario, ConfiguracionFormulario } from './form.models';
import { claveDelPrimerError, construirValidadores } from './validadores';

/**
 * Renderiza un formulario a partir de una configuración declarativa.
 *
 * Cosechado de `ui-dataforms/form-renderer`. El `FormGroup` lo construye y lo
 * posee quien lo usa (con `FormRendererComponent.construirFormulario`), no el
 * componente: así la página puede reaccionar a cambios de valor sin pelearse
 * con un formulario que vive dentro de un hijo.
 */
@Component({
  selector: 'vd-form-renderer',
  imports: [
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatRadioModule,
    MatDatepickerModule,
    MatNativeDateModule,
    MatButtonModule,
    TranslateModule,
  ],
  templateUrl: './form-renderer.component.html',
  styleUrls: ['./form-renderer.component.scss'],
})
export class FormRendererComponent {
  readonly configuracion = input.required<ConfiguracionFormulario>();
  readonly formulario = input.required<FormGroup>();
  readonly textoEnviar = input<string>('comun.guardar');
  readonly textoCancelar = input<string>('comun.cancelar');
  readonly mostrarCancelar = input<boolean>(true);

  readonly enviado = output<Record<string, unknown>>();
  readonly cancelado = output<void>();

  readonly plantillaRejilla = computed(() => {
    const config = this.configuracion();
    const columnas = config.columnas ?? (config.disposicion === 'dos-columnas' ? 2 : 1);
    return `repeat(${columnas}, minmax(0, 1fr))`;
  });

  /** Construye el `FormGroup` que corresponde a una configuración. */
  static construirFormulario(fb: FormBuilder, config: ConfiguracionFormulario): FormGroup {
    const grupo: Record<string, unknown> = {};
    for (const campo of config.campos) {
      grupo[campo.clave] = [
        {
          value: campo.valorPorDefecto ?? (campo.tipo === 'checkbox' ? false : null),
          disabled: !!campo.deshabilitado,
        },
        construirValidadores(campo.validadores),
      ];
    }
    return fb.group(grupo);
  }

  tipoDeInput(tipo: string): string {
    if (tipo === 'datetime') return 'datetime-local';
    if (['email', 'password', 'url', 'tel', 'number', 'time'].includes(tipo)) return tipo;
    return 'text';
  }

  claveDeError(campo: CampoDeFormulario): string {
    const control = this.formulario().get(campo.clave);
    if (!control?.touched) return '';
    return claveDelPrimerError(control, campo.validadores);
  }

  alElegirArchivo(clave: string, evento: Event): void {
    const entrada = evento.target as HTMLInputElement;
    const archivos = entrada.files ? Array.from(entrada.files) : [];
    this.formulario().get(clave)?.setValue(archivos);
  }

  alEnviar(): void {
    if (this.formulario().invalid) {
      this.formulario().markAllAsTouched();
      return;
    }
    this.enviado.emit(this.formulario().getRawValue());
  }
}
