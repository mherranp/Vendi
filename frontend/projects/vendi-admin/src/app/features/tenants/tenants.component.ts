import { Component, TemplateRef, computed, inject, signal, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { PageEvent } from '@angular/material/paginator';
import { TranslateModule } from '@ngx-translate/core';
import { TenantDeApi } from 'domain';
import {
  ColumnaTabla,
  ConfirmDialogComponent,
  ConfirmDialogData,
  DataTableComponent,
  PageHeaderComponent,
  StatusBadgeComponent,
} from 'ui-kit';
import { etiquetaDeEstado, varianteDeEstado } from './estados';
import {
  DatosFormularioTenant,
  ResultadoFormularioTenant,
  TenantFormularioComponent,
} from './tenant-formulario.component';
import { TenantsService } from './tenants.service';

const TAMANO_PAGINA_INICIAL = 10;

/**
 * Fila de la tabla: el tenant más una clave técnica para la columna de acciones.
 *
 * `ColumnaTabla<T>.clave` está tipada como `keyof T` —lo correcto: evita
 * columnas que apunten a campos inexistentes— y la columna de botones no
 * corresponde a ningún campo. En vez de ensanchar el tipo de la librería o de
 * reutilizar un campo real como hueco (que dejaría a alguien creyendo que ahí
 * se pinta ese dato), se declara aquí un campo fantasma: `never` opcional no
 * puede tomar ningún valor, así que nadie va a intentar leerlo.
 */
export interface FilaTenant extends TenantDeApi {
  acciones?: never;
}

/**
 * Listado y CRUD de negocios de la plataforma.
 *
 * Es la pantalla que demuestra el criterio 3 de Fase 0. Todo lo que hace pasa
 * por `TenantsService`; aquí solo vive el estado de la vista (página vigente,
 * cargando, filas) y la coreografía de los diálogos.
 */
@Component({
  selector: 'vd-tenants',
  imports: [
    TranslateModule,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatSlideToggleModule,
    PageHeaderComponent,
    DataTableComponent,
    StatusBadgeComponent,
  ],
  templateUrl: './tenants.component.html',
  styleUrl: './tenants.component.scss',
})
export class TenantsComponent {
  private readonly servicio = inject(TenantsService);
  private readonly dialogos = inject(MatDialog);

  readonly filas = signal<FilaTenant[]>([]);
  readonly total = signal(0);
  readonly cargando = signal(false);
  /** `true` si la última carga falló: la pantalla ofrece reintentar. */
  readonly fallo = signal(false);
  readonly indicePagina = signal(0);
  readonly tamanoPagina = signal(TAMANO_PAGINA_INICIAL);

  /**
   * ¿Se listan también los negocios dados de baja?
   *
   * Por defecto no —una baja lógica no debe ensuciar la operación diaria—, pero
   * tiene que ser alcanzable: sin esto, un negocio eliminado desaparece de la
   * consola y no hay forma de auditar qué pasó con él, ni de comprobar que al
   * recrear uno con el mismo nombre no colisionó con la organización anterior.
   */
  readonly incluirEliminados = signal(false);

  /**
   * Candado del diálogo de alta.
   *
   * Sin él, dos clics rápidos en "Nuevo negocio" abren dos diálogos apilados y
   * el usuario puede enviar los dos: dos negocios creados con una sola
   * intención. Es el primer ataque de la lista de QA de la etapa.
   */
  private readonly dialogoAbierto = signal(false);

  private readonly plantillaEstado =
    viewChild<TemplateRef<{ $implicit: FilaTenant }>>('celdaEstado');
  private readonly plantillaAcciones =
    viewChild<TemplateRef<{ $implicit: FilaTenant }>>('celdaAcciones');

  // Las plantillas son consultas de vista: la primera pasada de detección de
  // cambios las ve todavía como `undefined`. No es un problema —`ColumnaTabla`
  // declara `plantilla` opcional y la tabla cae a pintar el valor crudo—, y en
  // cuanto la consulta se resuelve, la señal notifica, el `computed` se
  // recalcula y la celda pasa a su plantilla. Por eso `viewChild()` y no
  // `viewChild.required()`, que lanzaría en esa primera lectura.
  readonly columnas = computed<ColumnaTabla<FilaTenant>[]>(() => [
    { clave: 'nombre', etiqueta: 'tenants.columna.nombre' },
    { clave: 'estado', etiqueta: 'tenants.columna.estado', plantilla: this.plantillaEstado() },
    { clave: 'id', etiqueta: 'tenants.columna.id' },
    {
      clave: 'acciones',
      etiqueta: 'tenants.columna.acciones',
      plantilla: this.plantillaAcciones(),
      ancho: '9rem',
    },
  ]);

  readonly varianteDeEstado = varianteDeEstado;
  readonly etiquetaDeEstado = etiquetaDeEstado;

  constructor() {
    this.recargar();
  }

  recargar(): void {
    this.cargando.set(true);
    this.fallo.set(false);
    const skip = this.indicePagina() * this.tamanoPagina();
    this.servicio.listar(skip, this.tamanoPagina(), this.incluirEliminados()).subscribe({
      next: (pagina) => {
        this.filas.set(pagina.items);
        this.total.set(pagina.total);
        this.cargando.set(false);
      },
      error: () => {
        // El aviso traducido ya lo emitió `errorInterceptor`. Aquí solo se
        // apaga el indicador y se deja la pantalla en un estado del que se
        // pueda salir: sin esto queda un spinner eterno, que es el modo de
        // fallo que la lista de QA de la etapa busca.
        this.cargando.set(false);
        this.fallo.set(true);
      },
    });
  }

  alternarEliminados(incluir: boolean): void {
    this.incluirEliminados.set(incluir);
    // Vuelta a la primera página: el conjunto cambia de tamaño y quedarse en la
    // página 7 de un listado que ahora tiene 3 enseñaría una tabla vacía que
    // parecería un error.
    this.indicePagina.set(0);
    this.recargar();
  }

  alPaginar(evento: PageEvent): void {
    this.indicePagina.set(evento.pageIndex);
    this.tamanoPagina.set(evento.pageSize);
    this.recargar();
  }

  crear(): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const datos: DatosFormularioTenant = {};
    this.dialogos
      .open<
        TenantFormularioComponent,
        DatosFormularioTenant,
        ResultadoFormularioTenant | undefined
      >(TenantFormularioComponent, { data: datos, width: '32rem' })
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado) {
          return;
        }
        this.cargando.set(true);
        this.servicio.crear(resultado.nombre).subscribe({
          // Se recarga en vez de insertar la fila en memoria: el alta puede
          // haber cambiado la página (orden del servidor) y el `total` del
          // paginador es del servidor, no de lo que tengamos cargado.
          next: () => this.recargar(),
          error: () => this.cargando.set(false),
        });
      });
  }

  renombrar(tenant: FilaTenant): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    const datos: DatosFormularioTenant = { tenant };
    this.dialogos
      .open<
        TenantFormularioComponent,
        DatosFormularioTenant,
        ResultadoFormularioTenant | undefined
      >(TenantFormularioComponent, { data: datos, width: '32rem' })
      .afterClosed()
      .subscribe((resultado) => {
        this.dialogoAbierto.set(false);
        if (!resultado || resultado.nombre === tenant.nombre) {
          return;
        }
        this.cargando.set(true);
        this.servicio.actualizar(tenant.id, { nombre: resultado.nombre }).subscribe({
          next: () => this.recargar(),
          error: () => this.cargando.set(false),
        });
      });
  }

  suspender(tenant: FilaTenant): void {
    this.confirmarYAplicar(
      {
        titulo: 'tenants.confirmar.suspender_titulo',
        mensaje: 'tenants.confirmar.suspender_mensaje',
        textoConfirmar: 'tenants.accion.suspender',
      },
      () =>
        this.servicio.actualizar(tenant.id, { estado: 'suspendido' }).subscribe(this.observador()),
    );
  }

  reactivar(tenant: FilaTenant): void {
    this.confirmarYAplicar(
      {
        titulo: 'tenants.confirmar.reactivar_titulo',
        mensaje: 'tenants.confirmar.reactivar_mensaje',
        textoConfirmar: 'tenants.accion.reactivar',
      },
      () => this.servicio.actualizar(tenant.id, { estado: 'activo' }).subscribe(this.observador()),
    );
  }

  eliminar(tenant: FilaTenant): void {
    this.confirmarYAplicar(
      {
        titulo: 'tenants.confirmar.eliminar_titulo',
        mensaje: 'tenants.confirmar.eliminar_mensaje',
        textoConfirmar: 'comun.eliminar',
        peligroso: true,
      },
      () => this.servicio.eliminar(tenant.id).subscribe(this.observador()),
    );
  }

  /** ¿Este negocio admite la acción de suspender (o ya no está operando)? */
  puedeSuspender(tenant: FilaTenant): boolean {
    return tenant.estado === 'activo';
  }

  /** ¿Se puede devolver a la operación? */
  puedeReactivar(tenant: FilaTenant): boolean {
    return tenant.estado === 'suspendido';
  }

  /** Un negocio ya dado de baja no se vuelve a borrar. */
  puedeEliminar(tenant: FilaTenant): boolean {
    return tenant.estado !== 'eliminado';
  }

  private confirmarYAplicar(datos: ConfirmDialogData, accion: () => void): void {
    if (this.dialogoAbierto()) {
      return;
    }
    this.dialogoAbierto.set(true);
    this.dialogos
      .open<ConfirmDialogComponent, ConfirmDialogData, boolean>(ConfirmDialogComponent, {
        data: datos,
      })
      .afterClosed()
      .subscribe((confirmado) => {
        this.dialogoAbierto.set(false);
        if (confirmado) {
          this.cargando.set(true);
          accion();
        }
      });
  }

  /** Observador común de las mutaciones: recargar si va bien, soltar el spinner si no. */
  private observador(): { next: () => void; error: () => void } {
    return {
      next: () => this.recargar(),
      error: () => this.cargando.set(false),
    };
  }
}
