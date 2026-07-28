import { Routes } from '@angular/router';
import { authGuard, tenantGuard } from 'auth';

/**
 * Rutas del POS (Etapa 1.3): la pantalla de venta ES la app.
 *
 * `authGuard` y `tenantGuard` llegan con este subproyecto: el spec-candado
 * que los prohibía se retiró en la Tarea 9 y su inverso (`app.spec.ts`)
 * ahora exige que sigan aquí. El flujo de login es el web: en el navegador
 * y en la PWA instalada funciona el passkey; la auth nativa es la deuda D-29.
 *
 * `/elegir-negocio` NO lleva `tenantGuard`: es adonde `tenantGuard` manda a
 * quien no ha elegido, y protegerla con él sería un bucle de redirección
 * (mismo criterio que en vendi-tenant).
 */
export const routes: Routes = [
  {
    path: '',
    canActivate: [authGuard, tenantGuard],
    loadComponent: () => import('./features/pos/pos.component').then((m) => m.PosComponent),
  },
  {
    path: 'elegir-negocio',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/elegir-negocio/elegir-negocio.component').then(
        (m) => m.ElegirNegocioComponent,
      ),
  },
  { path: '**', redirectTo: '' },
];
