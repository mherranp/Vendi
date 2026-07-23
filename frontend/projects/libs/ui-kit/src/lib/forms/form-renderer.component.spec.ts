import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { TestBed } from '@angular/core/testing';

import { proveerTraduccionDePrueba } from '../testing/i18n-de-prueba';
import { ConfiguracionFormulario } from './form.models';
import { FormRendererComponent } from './form-renderer.component';
import { claveDelPrimerError, construirValidadores } from './validadores';

const CONFIG: ConfiguracionFormulario = {
  disposicion: 'dos-columnas',
  campos: [
    {
      clave: 'nombre',
      etiqueta: 'Nombre del negocio',
      tipo: 'text',
      validadores: [{ tipo: 'required' }, { tipo: 'minLength', valor: 3 }],
    },
    {
      clave: 'correo',
      etiqueta: 'Correo',
      tipo: 'email',
      validadores: [{ tipo: 'email' }],
    },
    { clave: 'activo', etiqueta: 'Activo', tipo: 'checkbox' },
  ],
};

@Component({
  imports: [FormRendererComponent],
  template: `
    <vd-form-renderer
      [configuracion]="config()"
      [formulario]="formulario"
      (enviado)="enviado = $event"
      (cancelado)="cancelaciones = cancelaciones + 1"
    />
  `,
})
class AnfitrionFormulario {
  private readonly fb = inject(FormBuilder);
  readonly config = signal(CONFIG);
  readonly formulario: FormGroup = FormRendererComponent.construirFormulario(this.fb, CONFIG);
  enviado: Record<string, unknown> | null = null;
  cancelaciones = 0;
}

function montar() {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({ providers: [...proveerTraduccionDePrueba()] });
  const fixture = TestBed.createComponent(AnfitrionFormulario);
  fixture.detectChanges();
  return fixture;
}

describe('construirValidadores', () => {
  it('traduce la especificación declarativa a validadores de Angular', () => {
    expect(construirValidadores([{ tipo: 'required' }]).length).toBe(1);
    expect(construirValidadores([{ tipo: 'min', valor: 3 }]).length).toBe(1);
    expect(construirValidadores(undefined).length).toBe(0);
    expect(construirValidadores([]).length).toBe(0);
  });

  it('ignora un validador numérico cuyo valor no es número', () => {
    // Configuración venida de la API mal formada: mejor sin validador que
    // reventando al construir el formulario.
    expect(construirValidadores([{ tipo: 'min', valor: 'tres' }]).length).toBe(0);
  });
});

describe('claveDelPrimerError', () => {
  it('devuelve cadena vacía si el control es válido o no existe', () => {
    expect(claveDelPrimerError(null, [])).toBe('');
  });

  it('mapea el error de Angular a su clave, respetando el mensaje propio', () => {
    const control = { errors: { required: true } } as never;
    expect(claveDelPrimerError(control, undefined)).toBe('ui.validacion.requerido');
    expect(claveDelPrimerError(control, [{ tipo: 'required', mensaje: 'errores.mio' }])).toBe(
      'errores.mio',
    );
  });

  it('empareja minlength (Angular) con minLength (especificación)', () => {
    // Angular emite la clave en minúsculas; la especificación usa camelCase.
    const control = { errors: { minlength: {} } } as never;
    expect(
      claveDelPrimerError(control, [{ tipo: 'minLength', valor: 3, mensaje: 'errores.corto' }]),
    ).toBe('errores.corto');
    expect(claveDelPrimerError(control, undefined)).toBe('ui.validacion.muy_corto');
  });

  it('cae a la clave genérica ante un error desconocido', () => {
    const control = { errors: { loQueSea: true } } as never;
    expect(claveDelPrimerError(control, undefined)).toBe('ui.validacion.invalido');
  });
});

describe('FormRendererComponent', () => {
  it('construye el formulario con los validadores de la configuración', () => {
    const fixture = montar();
    const form = fixture.componentInstance.formulario;
    expect(form.get('nombre')?.valid).toBe(false); // required
    expect(form.get('activo')?.value).toBe(false); // checkbox → false, no null
    form.get('nombre')?.setValue('Tienda Don Carlos');
    expect(form.get('nombre')?.valid).toBe(true);
  });

  it('no emite si el formulario es inválido y marca todo como tocado', () => {
    const fixture = montar();
    const renderer = fixture.debugElement.children[0].componentInstance as FormRendererComponent;
    renderer.alEnviar();
    expect(fixture.componentInstance.enviado).toBeNull();
    expect(fixture.componentInstance.formulario.get('nombre')?.touched).toBe(true);
  });

  it('emite los valores en bruto cuando el formulario es válido', () => {
    const fixture = montar();
    fixture.componentInstance.formulario.patchValue({
      nombre: 'Tienda Don Carlos',
      correo: 'ana@vendi.local',
      activo: true,
    });
    const renderer = fixture.debugElement.children[0].componentInstance as FormRendererComponent;
    renderer.alEnviar();
    expect(fixture.componentInstance.enviado).toEqual({
      nombre: 'Tienda Don Carlos',
      correo: 'ana@vendi.local',
      activo: true,
    });
  });

  it('pinta el error traducido cuando el control está tocado', () => {
    const fixture = montar();
    const control = fixture.componentInstance.formulario.get('nombre');
    control?.markAsTouched();
    fixture.detectChanges();

    const texto = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(texto).toContain('Este campo es obligatorio');
    expect(texto).not.toContain('ui.validacion');
  });

  it('calcula la plantilla de rejilla según la disposición', () => {
    const fixture = montar();
    const renderer = fixture.debugElement.children[0].componentInstance as FormRendererComponent;
    expect(renderer.plantillaRejilla()).toBe('repeat(2, minmax(0, 1fr))');
  });

  it('mapea los tipos de campo al type del input', () => {
    const fixture = montar();
    const renderer = fixture.debugElement.children[0].componentInstance as FormRendererComponent;
    expect(renderer.tipoDeInput('datetime')).toBe('datetime-local');
    expect(renderer.tipoDeInput('email')).toBe('email');
    expect(renderer.tipoDeInput('text')).toBe('text');
    expect(renderer.tipoDeInput('loQueSea')).toBe('text');
  });

  it('emite la cancelación', () => {
    const fixture = montar();
    const botones = fixture.nativeElement.querySelectorAll('button');
    botones[0].click();
    expect(fixture.componentInstance.cancelaciones).toBe(1);
  });
});
