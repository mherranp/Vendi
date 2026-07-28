/*
 * Public API Surface of ui-kit/confirm-dialog
 *
 * Punto de entrada **secundario**: el diálogo de confirmación, aparte del
 * barril principal por la misma razón que `ui-kit/data-table` (ver su
 * `public-api.ts`): el fesm del barril es un solo módulo que el shell carga
 * en el inicial, y sus imports estáticos de módulos de Material arrastran al
 * inicial cualquier dependencia que una feature perezosa use — ConfirmDialog
 * importa `@angular/material/dialog`, y eso condenaba mat-dialog y cdk-dialog
 * (~27 kB minificados) al arranque en cuanto una pantalla perezosa abriera
 * cualquier diálogo. Por eso el barril principal ya NO lo exporta: este es
 * su único hogar público.
 */

export { ConfirmDialogComponent } from './lib/confirm-dialog.component';
export type { ConfirmDialogData } from './lib/confirm-dialog.component';
