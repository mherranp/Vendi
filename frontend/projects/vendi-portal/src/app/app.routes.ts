import { Routes } from '@angular/router';
import { InicioComponent } from './features/inicio/inicio.component';

/** El portal público de Fase 0 tiene una sola página. */
export const routes: Routes = [
  { path: '', component: InicioComponent },
  { path: '**', redirectTo: '' },
];
