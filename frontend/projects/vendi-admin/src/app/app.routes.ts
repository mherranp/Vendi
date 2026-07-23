import { Routes } from '@angular/router';
import { authGuard } from 'auth';
import { NotFoundComponent } from 'ui-kit';
import { ShellComponent } from './layout/shell.component';
import { guardPlataforma } from './nucleo/plataforma.guard';

/**
 * Rutas de la consola de plataforma.
 *
 * Todo cuelga del shell, que a su vez exige sesión (`authGuard`). Dentro,
 * `/negocios` exige además el permiso de plataforma; `/sin-acceso` no, porque
 * es precisamente donde aterriza quien no lo tiene: protegerla con el mismo
 * guard sería un bucle de redirección.
 *
 * Las páginas se cargan con `loadComponent` para que la consola no arrastre el
 * `FormRenderer` ni la tabla en el bundle inicial. La frontera de ADR-011 sigue
 * cubierta: el lint de esta app aplica la restricción también a los imports
 * dinámicos (ver `eslint.fronteras.js`).
 */
export const routes: Routes = [
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'negocios' },
      {
        path: 'negocios',
        canActivate: [guardPlataforma],
        loadComponent: () =>
          import('./features/tenants/tenants.component').then((m) => m.TenantsComponent),
      },
      {
        path: 'sin-acceso',
        loadComponent: () =>
          import('./features/sin-acceso/sin-acceso.component').then((m) => m.SinAccesoComponent),
      },
      { path: '**', component: NotFoundComponent },
    ],
  },
];
