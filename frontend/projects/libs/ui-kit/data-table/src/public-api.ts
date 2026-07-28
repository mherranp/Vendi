/*
 * Public API Surface of ui-kit/data-table
 *
 * Punto de entrada **secundario**: la tabla con paginación delegada al
 * servidor, aparte del barril principal por una razón de peso, no de gusto.
 *
 * El fesm del barril `ui-kit` es un solo módulo y el shell de cada app lo
 * carga en el chunk inicial (FullLayout, avisos). Todo símbolo que una
 * feature perezosa use DE ESE MISMO módulo queda retenido en el inicial —con
 * sus dependencias de Material— aunque la feature cargue con `loadComponent`.
 * DataTable arrastra mat-table, mat-paginator y mat-sort (~100 kB crudos):
 * importada desde aquí vive en el chunk perezoso de la feature, que es donde
 * se usa. Por eso el barril principal ya NO la exporta: este es su único
 * hogar público.
 */

export { DataTableComponent } from './lib/data-table.component';
export type { ColumnaTabla } from './lib/data-table.component';
