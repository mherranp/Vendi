import { Routes } from '@angular/router';
import { authGuard, tenantGuard } from 'auth';
import { NotFoundComponent } from 'ui-kit';
import { ShellComponent } from './layout/shell.component';

/**
 * Rutas de la consola web del negocio.
 *
 * `/elegir-negocio` cuelga del shell pero **no** lleva `tenantGuard`: es
 * justamente donde `tenantGuard` manda a quien todavía no ha elegido negocio, y
 * protegerla con él sería un bucle de redirección infinito.
 */
export const routes: Routes = [
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'mi-negocio' },
      {
        path: 'mi-negocio',
        canActivate: [tenantGuard],
        loadComponent: () =>
          import('./features/mi-negocio/mi-negocio.component').then((m) => m.MiNegocioComponent),
      },
      {
        path: 'elegir-negocio',
        loadComponent: () =>
          import('./features/elegir-negocio/elegir-negocio.component').then(
            (m) => m.ElegirNegocioComponent,
          ),
      },
      { path: '**', component: NotFoundComponent },
    ],
  },
];
