import { Component, inject, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormBuilder, FormGroup } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import { CATALOGO_MINIMO_ES, textoDeRespaldo } from 'data-access';

import { ConfirmDialogComponent } from 'ui-kit/confirm-dialog';
import { ColumnaTabla, DataTableComponent } from 'ui-kit/data-table';
import { ConfiguracionFormulario, FormRendererComponent } from 'ui-kit/form-renderer';
import { EmptyStateComponent } from '../components/empty-state/empty-state.component';
import { FileUploadComponent } from '../components/file-upload/file-upload.component';
import { NotFoundComponent } from '../components/not-found/not-found.component';
import { ImpersonationBannerComponent } from '../impersonation/impersonation-banner.component';
import { FullLayoutComponent } from '../layout/full-layout/full-layout.component';
import { NotificationsBadgeComponent } from '../notifications/notifications-badge.component';
import { CATALOGO_DE_PRUEBA, proveerTraduccionDePrueba } from './i18n-de-prueba';

/*
 * Regresión de la deuda 11: la app degradada no puede pintar claves crudas.
 *
 * El escenario es el que motiva `CATALOGO_MINIMO_ES`: el catálogo remoto
 * (`/i18n/es.json`) no se puede descargar —PWA instalada sin red, service worker
 * sin la entrada en caché, 404 tras un despliegue a medias— y
 * `CargadorDeTraduccionesResiliente` cae a la copia empotrada en el bundle.
 *
 * Hasta esta ronda ese respaldo solo traía `app`/`comun`/`layout`/`errores`,
 * mientras `ui-kit` renderiza además `ui.*`, `notificaciones.*` y
 * `suplantacion.*` con el pipe `| translate` directo —que devuelve la clave
 * cuando no la encuentra, sin pasar por `traducir()`—. La app arrancaba, sí,
 * pero con `ui.404.titulo` y un `ui.validacion.requerido` bajo cada campo
 * obligatorio.
 *
 * Este spec monta los componentes que traducen usando **el catálogo de
 * producción** (`proveerTraduccionDePrueba()` sirve `CATALOGO_MINIMO_ES`, no una
 * copia parcial) y barre el DOM en busca de cualquier identificador con forma de
 * clave.
 */

/** Espacios de nombres del catálogo. Una clave cruda siempre empieza por uno. */
const PREFIJOS = ['app', 'comun', 'layout', 'errores', 'ui', 'notificaciones', 'suplantacion'];

/**
 * Detecta un identificador con notación de punto que haya llegado al DOM.
 * `ui.404.titulo` incluye dígitos, de ahí el `[a-z0-9_]`.
 */
const CLAVE_CRUDA = new RegExp(`\\b(${PREFIJOS.join('|')})(\\.[a-z0-9_]+)+\\b`, 'g');

function preparar(extra: unknown[] = []): void {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [provideRouter([]), ...proveerTraduccionDePrueba(), ...extra],
  });
}

function texto(fixture: ComponentFixture<unknown>): string {
  const raiz = fixture.nativeElement as HTMLElement;
  // Se incluyen los atributos que también son visibles para el usuario o para
  // un lector de pantalla: un `aria-label` con la clave cruda es el mismo
  // defecto, solo que invisible.
  const atributos = Array.from(raiz.querySelectorAll<HTMLElement>('*'))
    .flatMap((el) => ['aria-label', 'title', 'placeholder'].map((a) => el.getAttribute(a) ?? ''))
    .join(' ');
  return `${raiz.textContent ?? ''} ${atributos}`.replace(/\s+/g, ' ').trim();
}

function sinClavesCrudas(fixture: ComponentFixture<unknown>): void {
  const encontradas = texto(fixture).match(CLAVE_CRUDA);
  expect(encontradas ?? []).toEqual([]);
}

// --- El catálogo de los specs ES el de producción ----------------------------

describe('catálogo de respaldo', () => {
  it('los specs de ui-kit se ejecutan contra el catálogo empotrado de producción', () => {
    // Si alguien vuelve a bifurcar los catálogos, toda la garantía de este
    // archivo se evapora: los specs pasarían con textos que el bundle no lleva.
    expect(CATALOGO_DE_PRUEBA).toBe(CATALOGO_MINIMO_ES);
  });

  it('cubre todas las claves que renderiza ui-kit', () => {
    // Inventario obtenido de las plantillas (`| translate`), de los valores por
    // defecto de los inputs y de `CLAVES_POR_ERROR` en forms/validadores.ts:
    //
    //   grep -rhoE "'[a-z_.0-9]+'[[:space:]]*\|[[:space:]]*translate" \
    //     projects/libs/ui-kit/src/lib --include='*.html'
    const claves = [
      'comun.aceptar',
      'comun.cancelar',
      'comun.guardar',
      'layout.menu',
      'layout.cuenta',
      'layout.cerrar_sesion',
      'layout.cargando',
      'notificaciones.titulo',
      'notificaciones.marcar_leidas',
      'notificaciones.vacio',
      'suplantacion.titulo',
      'suplantacion.expira_en',
      'suplantacion.detener',
      'ui.vacio.titulo',
      'ui.tabla.vacia',
      'ui.archivos.suelta_aqui',
      'ui.archivos.buscar',
      'ui.404.titulo',
      'ui.404.descripcion',
      'ui.404.volver',
      'ui.validacion.requerido',
      'ui.validacion.correo',
      'ui.validacion.minimo',
      'ui.validacion.maximo',
      'ui.validacion.muy_corto',
      'ui.validacion.muy_largo',
      'ui.validacion.formato',
      'ui.validacion.invalido',
    ];
    const sinRespaldo = claves.filter((clave) => textoDeRespaldo(clave) === null);
    expect(sinRespaldo).toEqual([]);
  });
});

// --- Barrido del DOM con el catálogo degradado -------------------------------

describe('la app degradada no pinta claves crudas', () => {
  it('NotFoundComponent', () => {
    preparar();
    const fixture = TestBed.createComponent(NotFoundComponent);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('No encontramos esta página');
    sinClavesCrudas(fixture);
  });

  it('EmptyStateComponent', () => {
    preparar();
    const fixture = TestBed.createComponent(EmptyStateComponent);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('Nada por aquí todavía');
    sinClavesCrudas(fixture);
  });

  it('FileUploadComponent', () => {
    preparar();
    const fixture = TestBed.createComponent(FileUploadComponent);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('Suelta los archivos aquí');
    sinClavesCrudas(fixture);
  });

  it('ConfirmDialogComponent', () => {
    preparar([
      { provide: MatDialogRef, useValue: { close: () => undefined } },
      { provide: MAT_DIALOG_DATA, useValue: { titulo: 'Eliminar', mensaje: '¿Seguro?' } },
    ]);
    const fixture = TestBed.createComponent(ConfirmDialogComponent);
    fixture.detectChanges();
    sinClavesCrudas(fixture);
  });

  it('ImpersonationBannerComponent', () => {
    preparar();
    const fixture = TestBed.createComponent(ImpersonationBannerComponent);
    fixture.componentRef.setInput('actor', 'ana@vendi.co');
    fixture.componentRef.setInput('expiraEnSegundos', 120);
    fixture.detectChanges();
    sinClavesCrudas(fixture);
  });

  it('NotificationsBadgeComponent', () => {
    preparar();
    const fixture = TestBed.createComponent(NotificationsBadgeComponent);
    fixture.detectChanges();
    sinClavesCrudas(fixture);
  });

  it('FullLayoutComponent', () => {
    preparar();
    const fixture = TestBed.createComponent(FullLayoutComponent);
    fixture.componentRef.setInput('marca', 'Vendi');
    fixture.componentRef.setInput('nombreUsuario', 'Ana Gómez');
    fixture.componentRef.setInput('rutaCuenta', '/cuenta');
    fixture.detectChanges();
    // `layout.cuenta` y `layout.cerrar_sesion` viven dentro de un `mat-menu`,
    // que no se instancia hasta abrirlo; `layout.menu` sí está en el DOM
    // inicial. La cobertura de las tres la da el test de claves de arriba.
    expect(texto(fixture)).toContain('Menú');
    sinClavesCrudas(fixture);
  });

  it('DataTableComponent vacía', () => {
    preparar();
    const fixture = TestBed.createComponent(AnfitrionTablaVacia);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('Sin registros');
    sinClavesCrudas(fixture);
  });

  it('FormRendererComponent con un campo obligatorio tocado', () => {
    preparar();
    const fixture = TestBed.createComponent(AnfitrionFormulario);
    fixture.detectChanges();
    fixture.componentInstance.formulario.markAllAsTouched();
    fixture.detectChanges();
    expect(texto(fixture)).toContain('Este campo es obligatorio');
    sinClavesCrudas(fixture);
  });
});

// --- Anfitriones -------------------------------------------------------------

interface Fila {
  id: string;
  nombre: string;
}

@Component({
  imports: [DataTableComponent],
  template: `<vd-data-table [columnas]="columnas" [filas]="[]" [total]="0" />`,
})
class AnfitrionTablaVacia {
  readonly columnas: ColumnaTabla<Fila>[] = [{ clave: 'nombre', etiqueta: 'Nombre' }];
}

const CONFIG_OBLIGATORIA: ConfiguracionFormulario = {
  campos: [
    { clave: 'nombre', etiqueta: 'Nombre', tipo: 'text', validadores: [{ tipo: 'required' }] },
  ],
};

@Component({
  imports: [FormRendererComponent],
  template: `<vd-form-renderer [configuracion]="configuracion()" [formulario]="formulario" />`,
})
class AnfitrionFormulario {
  private readonly fb = inject(FormBuilder);
  readonly configuracion = signal(CONFIG_OBLIGATORIA);
  readonly formulario: FormGroup = FormRendererComponent.construirFormulario(
    this.fb,
    CONFIG_OBLIGATORIA,
  );
}
