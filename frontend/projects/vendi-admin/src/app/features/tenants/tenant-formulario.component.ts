import { Component, inject, signal } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { TranslateModule } from '@ngx-translate/core';
import { TenantDeApi } from 'domain';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit/form-renderer';
import { MAXIMO_NOMBRE } from './tenants.service';

/** Datos con los que se abre el diálogo. Sin `tenant` es un alta. */
export interface DatosFormularioTenant {
  tenant?: TenantDeApi;
}

/** Resultado del diálogo. `undefined` si el usuario canceló. */
export interface ResultadoFormularioTenant {
  nombre: string;
}

/**
 * Alta y renombrado de un negocio.
 *
 * Es un formulario tonto: recoge el nombre y lo devuelve. Quien llama a la API
 * es la página, que es la que sabe si toca `POST` o `PATCH` y la que tiene que
 * recargar el listado después.
 */
@Component({
  selector: 'vd-tenant-formulario',
  imports: [MatDialogModule, TranslateModule, FormRendererComponent],
  templateUrl: './tenant-formulario.component.html',
})
export class TenantFormularioComponent {
  private readonly fb = inject(FormBuilder);
  readonly ref =
    inject<MatDialogRef<TenantFormularioComponent, ResultadoFormularioTenant | undefined>>(
      MatDialogRef,
    );
  readonly datos = inject<DatosFormularioTenant>(MAT_DIALOG_DATA, { optional: true }) ?? {};

  readonly esEdicion = !!this.datos.tenant;

  readonly configuracion: ConfiguracionFormulario = {
    campos: [
      {
        clave: 'nombre',
        etiqueta: 'tenants.campo.nombre',
        tipo: 'text',
        marcador: 'tenants.campo.nombre_marcador',
        ayuda: 'tenants.campo.nombre_ayuda',
        valorPorDefecto: this.datos.tenant?.nombre ?? '',
        validadores: [
          { tipo: 'required' },
          { tipo: 'minLength', valor: 2 },
          // Ver `MAXIMO_NOMBRE`: por debajo del varchar(255) de Keycloak, para
          // que el límite lo aplique un mensaje en español y no un 500 de JDBC
          // en mitad del aprovisionamiento.
          { tipo: 'maxLength', valor: MAXIMO_NOMBRE },
        ],
      },
    ],
  };

  readonly formulario: FormGroup = FormRendererComponent.construirFormulario(
    this.fb,
    this.configuracion,
  );

  /**
   * Candado de doble envío.
   *
   * `MatDialogRef.close()` no cierra el diálogo de forma síncrona: hay una
   * animación de salida por medio. Un doble clic rápido sobre "Guardar" —el
   * ataque que la sección de QA de la etapa pide probar— emite dos veces el
   * `enviado` del `FormRenderer` antes de que el diálogo desaparezca, y la
   * página crearía dos negocios con el mismo nombre. Este flag lo corta en el
   * primer clic.
   */
  private readonly enviando = signal(false);

  alEnviar(valores: Record<string, unknown>): void {
    if (this.enviando()) {
      return;
    }
    const nombre = String(valores['nombre'] ?? '').trim();
    if (nombre.length === 0) {
      return;
    }
    this.enviando.set(true);
    this.ref.close({ nombre });
  }

  cancelar(): void {
    this.ref.close(undefined);
  }
}
