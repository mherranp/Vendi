import { Component, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TranslateModule } from '@ngx-translate/core';

/**
 * Zona de arrastrar y soltar archivos.
 *
 * Cosechado de `ui-components/file-upload`. Solo selecciona archivos y los
 * emite: la subida es HTTP y por tanto vive fuera de `ui-kit`.
 */
@Component({
  selector: 'vd-file-upload',
  imports: [MatButtonModule, MatIconModule, TranslateModule],
  templateUrl: './file-upload.component.html',
  styleUrls: ['./file-upload.component.scss'],
})
export class FileUploadComponent {
  readonly acepta = input<string>('*/*');
  readonly multiple = input<boolean>(false);
  readonly ayuda = input<string>('');
  readonly archivosElegidos = output<File[]>();

  private readonly _arrastrando = signal(false);
  readonly arrastrando = this._arrastrando.asReadonly();

  alArrastrarEncima(e: DragEvent): void {
    e.preventDefault();
    this._arrastrando.set(true);
  }

  alSalirDelArrastre(e: DragEvent): void {
    e.preventDefault();
    this._arrastrando.set(false);
  }

  alSoltar(e: DragEvent): void {
    e.preventDefault();
    this._arrastrando.set(false);
    this.alElegir(e.dataTransfer?.files ?? null);
  }

  alElegir(lista: FileList | null): void {
    if (!lista || lista.length === 0) return;
    this.archivosElegidos.emit(Array.from(lista));
  }
}
