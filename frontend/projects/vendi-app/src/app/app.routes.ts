import { Routes } from '@angular/router';
import { ProximamenteComponent } from './features/proximamente/proximamente.component';

/**
 * Rutas de la app móvil en Fase 0: una sola pantalla y **sin guard de sesión**.
 *
 * Deliberado. Ver el comentario largo de `ProximamenteComponent`: la auth móvil
 * es el subproyecto 2 porque el login tiene que salir al navegador del sistema
 * (los passkeys no funcionan dentro del WebView), y eso no se improvisa aquí.
 *
 * No se usa `loadComponent`: con una sola pantalla, el lazy loading solo añade
 * una petición más al arranque de una app que puede estar sin red.
 */
export const routes: Routes = [
  { path: '', component: ProximamenteComponent },
  { path: '**', redirectTo: '' },
];
