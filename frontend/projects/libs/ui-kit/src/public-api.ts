/*
 * Public API Surface of ui-kit
 *
 * Presentación pura: componentes, directivas, pipes y tokens de diseño.
 * Sin HTTP, sin persistencia, sin plataforma nativa.
 * Recibe datos por inputs, emite eventos por outputs.
 */

// --- Componentes ----------------------------------------------------------
export { ConfirmDialogComponent } from './lib/components/confirm-dialog/confirm-dialog.component';
export type { ConfirmDialogData } from './lib/components/confirm-dialog/confirm-dialog.component';
export { AvisosComponent } from './lib/avisos/avisos.component';
export type { AvisoEnPantalla } from './lib/avisos/avisos.component';
export { DataTableComponent } from './lib/components/data-table/data-table.component';
export type { ColumnaTabla } from './lib/components/data-table/data-table.component';
export { EmptyStateComponent } from './lib/components/empty-state/empty-state.component';
export { FileUploadComponent } from './lib/components/file-upload/file-upload.component';
export { LoadingSpinnerComponent } from './lib/components/loading-spinner/loading-spinner.component';
export { NotFoundComponent } from './lib/components/not-found/not-found.component';
export { PageHeaderComponent } from './lib/components/page-header/page-header.component';
export { StatusBadgeComponent } from './lib/components/status-badge/status-badge.component';
export type { VarianteEstado } from './lib/components/status-badge/status-badge.component';

// --- Formularios declarativos ---------------------------------------------
export { FormRendererComponent } from './lib/forms/form-renderer.component';
export { claveDelPrimerError, construirValidadores } from './lib/forms/validadores';
export type {
  CampoDeFormulario,
  ConfiguracionFormulario,
  DisposicionFormulario,
  OpcionDeCampo,
  TipoDeCampo,
  ValidadorDeCampo,
} from './lib/forms/form.models';

// --- Shell y bandas -------------------------------------------------------
export { FullLayoutComponent } from './lib/layout/full-layout/full-layout.component';
export type { ElementoDeNavegacion } from './lib/layout/full-layout/full-layout.component';
export { ImpersonationBannerComponent } from './lib/impersonation/impersonation-banner.component';
export { NotificationsBadgeComponent } from './lib/notifications/notifications-badge.component';
export type { NotificacionEnPantalla } from './lib/notifications/notifications-badge.component';
