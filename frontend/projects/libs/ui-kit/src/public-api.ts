/*
 * Public API Surface of ui-kit
 *
 * Presentación pura: componentes, directivas, pipes y tokens de diseño.
 * Sin HTTP, sin persistencia, sin plataforma nativa.
 * Recibe datos por inputs, emite eventos por outputs.
 *
 * `DataTableComponent`, `FormRendererComponent` y `ConfirmDialogComponent` NO
 * viven aquí: este fesm es un solo módulo y los shells lo cargan en el chunk
 * inicial (FullLayout, avisos), así que sus imports estáticos de Material
 * arrastran al inicial cualquier dependencia que una feature perezosa use
 * (~500 kB entre tabla, paginador, campos de formulario y diálogo). Viven en
 * los puntos de entrada secundarios `ui-kit/data-table`,
 * `ui-kit/form-renderer` y `ui-kit/confirm-dialog`, que viajan en el chunk
 * perezoso de la feature que los usa.
 */

// --- Componentes ----------------------------------------------------------
export { AvisosComponent } from './lib/avisos/avisos.component';
export type { AvisoEnPantalla } from './lib/avisos/avisos.component';
export { EmptyStateComponent } from './lib/components/empty-state/empty-state.component';
export { FileUploadComponent } from './lib/components/file-upload/file-upload.component';
export { LoadingSpinnerComponent } from './lib/components/loading-spinner/loading-spinner.component';
export { NotFoundComponent } from './lib/components/not-found/not-found.component';
export { PageHeaderComponent } from './lib/components/page-header/page-header.component';
export { StatusBadgeComponent } from './lib/components/status-badge/status-badge.component';
export type { VarianteEstado } from './lib/components/status-badge/status-badge.component';

// --- Shell y bandas -------------------------------------------------------
export { FullLayoutComponent } from './lib/layout/full-layout/full-layout.component';
export type { ElementoDeNavegacion } from './lib/layout/full-layout/full-layout.component';
export { ImpersonationBannerComponent } from './lib/impersonation/impersonation-banner.component';
export { NotificationsBadgeComponent } from './lib/notifications/notifications-badge.component';
export type { NotificacionEnPantalla } from './lib/notifications/notifications-badge.component';
