import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { PageEvent } from '@angular/material/paginator';
import { Sort } from '@angular/material/sort';
import { provideRouter } from '@angular/router';

import { proveerTraduccionDePrueba } from '../testing/i18n-de-prueba';
import { ConfirmDialogComponent } from 'ui-kit/confirm-dialog';
import { ColumnaTabla, DataTableComponent } from 'ui-kit/data-table';
import { EmptyStateComponent } from './empty-state/empty-state.component';
import { FileUploadComponent } from './file-upload/file-upload.component';
import { LoadingSpinnerComponent } from './loading-spinner/loading-spinner.component';
import { NotFoundComponent } from './not-found/not-found.component';
import { PageHeaderComponent } from './page-header/page-header.component';
import { StatusBadgeComponent } from './status-badge/status-badge.component';

function preparar(extra: unknown[] = []): void {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [provideRouter([]), ...proveerTraduccionDePrueba(), ...extra],
  });
}

function texto(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

// --- StatusBadge -------------------------------------------------------------

describe('StatusBadgeComponent', () => {
  it('pinta la etiqueta traducida y la clase de la variante', () => {
    preparar();
    const fixture = TestBed.createComponent(StatusBadgeComponent);
    fixture.componentRef.setInput('etiqueta', 'Activo');
    fixture.componentRef.setInput('variante', 'exito');
    fixture.detectChanges();

    const span = fixture.nativeElement.querySelector('span');
    expect(span.textContent.trim()).toBe('Activo');
    expect(span.className).toContain('vd-insignia--exito');
  });

  it('la variante por defecto es neutro', () => {
    preparar();
    const fixture = TestBed.createComponent(StatusBadgeComponent);
    fixture.componentRef.setInput('etiqueta', 'x');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('span').className).toContain('vd-insignia--neutro');
  });
});

// --- EmptyState --------------------------------------------------------------

describe('EmptyStateComponent', () => {
  it('traduce el título por defecto en vez de pintar la clave', () => {
    preparar();
    const fixture = TestBed.createComponent(EmptyStateComponent);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('Nada por aquí todavía');
    expect(texto(fixture)).not.toContain('ui.vacio');
  });

  it('no pinta el botón si no hay texto de acción', () => {
    preparar();
    const fixture = TestBed.createComponent(EmptyStateComponent);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('button')).toBeNull();
  });

  it('emite la acción cuando se pulsa el botón', () => {
    preparar();
    const fixture = TestBed.createComponent(EmptyStateComponent);
    fixture.componentRef.setInput('textoAccion', 'comun.guardar');
    fixture.detectChanges();
    let emitido = false;
    fixture.componentInstance.accion.subscribe(() => (emitido = true));
    fixture.nativeElement.querySelector('button').click();
    expect(emitido).toBe(true);
  });
});

// --- PageHeader --------------------------------------------------------------

describe('PageHeaderComponent', () => {
  it('pinta título y subtítulo', () => {
    preparar();
    const fixture = TestBed.createComponent(PageHeaderComponent);
    fixture.componentRef.setInput('titulo', 'Negocios');
    fixture.componentRef.setInput('subtitulo', 'Todos los tenants');
    fixture.detectChanges();
    expect(texto(fixture)).toContain('Negocios');
    expect(texto(fixture)).toContain('Todos los tenants');
  });

  it('omite el subtítulo si viene vacío', () => {
    preparar();
    const fixture = TestBed.createComponent(PageHeaderComponent);
    fixture.componentRef.setInput('titulo', 'Negocios');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.vd-cabecera__subtitulo')).toBeNull();
  });
});

// --- LoadingSpinner ----------------------------------------------------------

describe('LoadingSpinnerComponent', () => {
  it('anuncia el estado a los lectores de pantalla', () => {
    preparar();
    const fixture = TestBed.createComponent(LoadingSpinnerComponent);
    fixture.detectChanges();
    const contenedor = fixture.nativeElement.querySelector('.vd-cargando');
    expect(contenedor.getAttribute('role')).toBe('status');
    expect(contenedor.getAttribute('aria-live')).toBe('polite');
  });

  it('pinta la etiqueta solo si se pasa', () => {
    preparar();
    const fixture = TestBed.createComponent(LoadingSpinnerComponent);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.vd-cargando__etiqueta')).toBeNull();

    fixture.componentRef.setInput('etiqueta', 'layout.cargando');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.vd-cargando__etiqueta')).not.toBeNull();
  });
});

// --- NotFound ----------------------------------------------------------------

describe('NotFoundComponent', () => {
  it('pinta el 404 con textos traducidos y enlace al inicio', () => {
    preparar();
    const fixture = TestBed.createComponent(NotFoundComponent);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('404');
    expect(texto(fixture)).toContain('No encontramos esta página');
    expect(texto(fixture)).not.toContain('ui.404');
    expect(fixture.nativeElement.querySelector('a').getAttribute('href')).toBe('/');
  });
});

// --- FileUpload --------------------------------------------------------------

describe('FileUploadComponent', () => {
  it('emite los archivos soltados y desactiva el resaltado', () => {
    preparar();
    const fixture = TestBed.createComponent(FileUploadComponent);
    fixture.detectChanges();
    let recibidos: File[] = [];
    fixture.componentInstance.archivosElegidos.subscribe((f) => (recibidos = f));

    const archivo = new File(['x'], 'ticket.png', { type: 'image/png' });
    // jsdom no implementa `DragEvent`; el componente solo usa
    // `preventDefault()` y `dataTransfer`, así que basta con un Event normal.
    const eventoSoltar = new Event('drop') as DragEvent;
    Object.defineProperty(eventoSoltar, 'dataTransfer', {
      value: { files: { 0: archivo, length: 1, item: () => archivo } as unknown as FileList },
    });

    fixture.componentInstance.alArrastrarEncima(new Event('dragover') as DragEvent);
    expect(fixture.componentInstance.arrastrando()).toBe(true);

    fixture.componentInstance.alSoltar(eventoSoltar);
    expect(fixture.componentInstance.arrastrando()).toBe(false);
    expect(recibidos.length).toBe(1);
    expect(recibidos[0].name).toBe('ticket.png');
  });

  it('no emite nada si la selección viene vacía', () => {
    preparar();
    const fixture = TestBed.createComponent(FileUploadComponent);
    fixture.detectChanges();
    let veces = 0;
    fixture.componentInstance.archivosElegidos.subscribe(() => veces++);
    fixture.componentInstance.alElegir(null);
    fixture.componentInstance.alElegir({ length: 0 } as FileList);
    expect(veces).toBe(0);
  });
});

// --- ConfirmDialog -----------------------------------------------------------

describe('ConfirmDialogComponent', () => {
  it('cierra con true al confirmar y con false al cancelar', () => {
    const cerrado: (boolean | undefined)[] = [];
    preparar([
      { provide: MatDialogRef, useValue: { close: (v?: boolean) => cerrado.push(v) } },
      {
        provide: MAT_DIALOG_DATA,
        useValue: { titulo: 'Eliminar negocio', mensaje: '¿Seguro?', peligroso: true },
      },
    ]);
    const fixture = TestBed.createComponent(ConfirmDialogComponent);
    fixture.detectChanges();

    const botones = fixture.nativeElement.querySelectorAll('button');
    expect(botones[0].textContent.trim()).toBe('Cancelar');
    expect(botones[1].textContent.trim()).toBe('Aceptar');
    expect(botones[1].className).toContain('vd-accion-peligrosa');

    botones[0].click();
    botones[1].click();
    expect(cerrado).toEqual([false, true]);
  });
});

// --- DataTable ---------------------------------------------------------------

interface Negocio {
  id: string;
  nombre: string;
}

@Component({
  imports: [DataTableComponent],
  template: `
    <vd-data-table
      [columnas]="columnas"
      [filas]="filas()"
      [total]="filas().length"
      [cargando]="cargando()"
      (paginaCambia)="pagina = $event"
      (ordenCambia)="orden = $event"
    />
  `,
})
class AnfitrionTabla {
  readonly columnas: ColumnaTabla<Negocio>[] = [
    { clave: 'nombre', etiqueta: 'Nombre', ordenable: true },
  ];
  readonly filas = signal<Negocio[]>([]);
  readonly cargando = signal(false);
  pagina: PageEvent | null = null;
  orden: Sort | null = null;
}

describe('DataTableComponent', () => {
  it('sin filas y sin carga muestra el estado vacío traducido', () => {
    preparar();
    const fixture = TestBed.createComponent(AnfitrionTabla);
    fixture.detectChanges();
    expect(texto(fixture)).toContain('Sin registros');
    expect(fixture.nativeElement.querySelector('table')).toBeNull();
  });

  it('con filas pinta la tabla y el encabezado traducido', () => {
    preparar();
    const fixture = TestBed.createComponent(AnfitrionTabla);
    fixture.componentInstance.filas.set([
      { id: '1', nombre: 'Tienda Don Carlos' },
      { id: '2', nombre: 'Minimercado Andrea' },
    ]);
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('table')).not.toBeNull();
    expect(texto(fixture)).toContain('Tienda Don Carlos');
    expect(texto(fixture)).toContain('Minimercado Andrea');
  });

  it('mientras carga muestra la barra de progreso y no el estado vacío', () => {
    preparar();
    const fixture = TestBed.createComponent(AnfitrionTabla);
    fixture.componentInstance.cargando.set(true);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('mat-progress-bar')).not.toBeNull();
    expect(texto(fixture)).not.toContain('Sin registros');
  });

  it('reemite paginación y ordenación al anfitrión', () => {
    preparar();
    const fixture = TestBed.createComponent(AnfitrionTabla);
    fixture.componentInstance.filas.set([{ id: '1', nombre: 'A' }]);
    fixture.detectChanges();

    const tabla = fixture.debugElement.children[0].componentInstance as DataTableComponent<Negocio>;
    tabla.alPaginar({ pageIndex: 2, pageSize: 25, length: 100 });
    tabla.alOrdenar({ active: 'nombre', direction: 'desc' });
    fixture.detectChanges();

    expect(fixture.componentInstance.pagina?.pageIndex).toBe(2);
    expect(fixture.componentInstance.orden?.direction).toBe('desc');
  });
});
